"""Couche de logique metier : construction du prompt et analyse LLM."""

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, time

import redis.asyncio as aioredis

from ....exceptions import NotFoundException, TooManyRequestsException
from ...moodle.models import LearnerLevel, LearnerProfile, MoodleUserRole
from ..models import LearnerAnalysis, LLMLog, MoodleChatResponse
from ..models.chat_session import ChatSession, ChatTurn
from ..prompts import get_system_prompt
from ..repositories import (
    ChatSessionRepository,
    LLMLogRepository,
    LLMRepository,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Tu es un assistant pedagogique expert. "
    "On te fournit le profil d'un apprenant Moodle. "
    "Redige un bilan pedagogique CONCIS en francais (150-200 mots max), "
)

_MAX_PER_CATEGORY = 2
_MAX_ACTIVITY_EVENTS = 3
_MAX_RESOURCES_PER_COURSE = 3
_MAX_BADGES = 3
_MAX_CALENDAR_EVENTS = 5
_MAX_FORUM_POSTS = 3

_LEVEL_LABELS: dict[LearnerLevel, str] = {
    LearnerLevel.BEGINNER: "debutant",
    LearnerLevel.INTERMEDIATE: "intermediaire",
    LearnerLevel.ADVANCED: "avance",
    LearnerLevel.UNKNOWN: "indetermine",
}

_CACHE_TTL = 3600  # 1 heure
_LIGHT_MODEL_MAX_WORDS = 25  # seuil : question courte sans profil → modele leger
_TOKEN_CHARS = 4  # approximation : 1 token ~ 4 caracteres
_PROFILE_SUMMARY_CACHE_PREFIX = "llm:profile_summary:"
_MAX_RECENT_TURNS = 4  # tours user/assistant gardes bruts dans le prompt
_COMPACT_AFTER_TURNS = 6  # seuil de declenchement du compact

_PROFILE_SUMMARY_PROMPT = (
    "Tu es un assistant pedagogique. On te fournit le dossier Moodle complet "
    "d'un apprenant. Resume-le en francais en 6 a 10 lignes maximum, en gardant "
    "uniquement : identite, cours suivis avec progression, points forts, "
    "points d'attention, ressources cles. Ne rajoute aucune analyse, juste un "
    "resume factuel et compact qui pourra etre injecte dans un chat ulterieur."
)
_SESSION_COMPACT_PROMPT = (
    "Tu vas recevoir une serie d'echanges entre un utilisateur et un assistant "
    "pedagogique. Resume cette conversation en francais en 5 a 8 phrases, en "
    "gardant : sujets abordes, decisions ou conseils donnes, points en suspens. "
    "Ne reformule pas tour par tour, fournis un resume synthetique."
)


class LLMService:
    """Orchestre la construction du prompt et l'appel au LLM."""

    def __init__(
        self,
        repository: LLMRepository,
        log_repository: LLMLogRepository,
        cache: aioredis.Redis | None = None,
        model_light: str | None = None,
        daily_token_limit: int = 0,
        max_prompt_tokens: int = 0,
        chat_session_repository: ChatSessionRepository | None = None,
        profile_summary_ttl: int = 300,
    ) -> None:
        self.repository = repository
        self.log_repository = log_repository
        self._cache = cache
        self._model_light = model_light or repository._model
        self._daily_token_limit = daily_token_limit
        self._max_prompt_tokens = max_prompt_tokens
        self._chat_session_repository = chat_session_repository
        self._profile_summary_ttl = profile_summary_ttl

    async def chat(
        self,
        message: str,
        profiles: list[LearnerProfile] | None = None,
        moodle_userid: int | None = None,
        role: MoodleUserRole = MoodleUserRole.STUDENT,
        prompt_id: str | None = None,
        session_id: int | None = None,
    ) -> MoodleChatResponse:
        """Repond a un message avec le prompt systeme adapte au role.

        Mode session (recommande) : quand `chat_session_repository` est cable et
        qu'un `moodle_userid` est fourni, on tient un fil conversationnel
        persistant. Le prompt envoye au LLM combine :
        - le system prompt du role,
        - un resume du profil apprenant (genere une fois par session, cache Redis),
        - le resume des tours anciens deja compactes,
        - les `_MAX_RECENT_TURNS` derniers tours bruts,
        - le nouveau message.
        Au-dela de `_COMPACT_AFTER_TURNS` tours non compactes, les plus anciens
        sont fusionnes en `summary` via un appel LLM auxiliaire.

        Mode legacy (retro-compat) : sans repository session ou sans userid, on
        retombe sur le comportement initial (profil injecte tel quel + cache Redis
        de la reponse + garde-fou tokens).
        """
        if self._chat_session_repository is not None and moodle_userid is not None:
            return await self._chat_with_session(
                message=message,
                profiles=profiles,
                moodle_userid=moodle_userid,
                role=role,
                prompt_id=prompt_id,
                session_id=session_id,
            )
        return await self._chat_stateless(
            message=message,
            profiles=profiles,
            moodle_userid=moodle_userid,
            role=role,
            prompt_id=prompt_id,
        )

    async def _chat_stateless(
        self,
        message: str,
        profiles: list[LearnerProfile] | None,
        moodle_userid: int | None,
        role: MoodleUserRole,
        prompt_id: str | None,
    ) -> MoodleChatResponse:
        """Chemin sans session : profil entier injecte + cache reponse Redis."""
        user_content = self._build_user_content(message, profiles)

        cache_key = _make_cache_key(user_content, role, prompt_id)
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached:
                data = json.loads(cached)
                return MoodleChatResponse(**data)

        await self._check_daily_token_limit(moodle_userid)

        model = (
            self._model_light
            if _is_simple_query(message, bool(profiles))
            else self.repository._model
        )

        result = await self.repository.chat_completion(
            [
                {"role": "system", "content": get_system_prompt(role, prompt_id)},
                {"role": "user", "content": user_content},
            ],
            model=model,
        )
        await self._log(
            result.prompt_tokens,
            result.completion_tokens,
            result.duration_ms,
            moodle_userid,
        )
        response = MoodleChatResponse(response=result.text)

        if self._cache is not None:
            await self._cache.set(
                cache_key, json.dumps(response.model_dump()), ex=_CACHE_TTL
            )

        return response

    async def _chat_with_session(
        self,
        message: str,
        profiles: list[LearnerProfile] | None,
        moodle_userid: int,
        role: MoodleUserRole,
        prompt_id: str | None,
        session_id: int | None,
    ) -> MoodleChatResponse:
        """Chemin conversationnel : session persistante + profile_summary + compact."""
        repo = self._chat_session_repository
        assert repo is not None  # garde-fou statique

        await self._check_daily_token_limit(moodle_userid)

        # --- Ouverture/chargement de la session ---
        if session_id is None:
            profile_summary = await self._get_or_build_profile_summary(profiles)
            chat_session = await repo.create(
                moodle_userid=moodle_userid,
                profile_summary=profile_summary,
            )
        else:
            loaded = await repo.get_for_user(session_id, moodle_userid)
            if loaded is None:
                raise NotFoundException(
                    f"Session {session_id} introuvable pour cet utilisateur"
                )
            chat_session = loaded

        # --- Construction des messages ---
        recent_turns = await repo.get_active_turns(chat_session.id)
        messages = _build_chat_messages(
            role=role,
            prompt_id=prompt_id,
            chat_session=chat_session,
            recent_turns=recent_turns[-_MAX_RECENT_TURNS:],
            new_message=message,
        )

        # --- Appel LLM ---
        result = await self.repository.chat_completion(
            messages, model=self.repository._model
        )
        await self._log(
            result.prompt_tokens,
            result.completion_tokens,
            result.duration_ms,
            moodle_userid,
        )

        # --- Persistance du tour ---
        await repo.append_turn(
            session_id=chat_session.id,
            user_message=message,
            assistant_response=result.text,
        )

        # --- Compact eventuel ---
        await self._compact_session_if_needed(chat_session)

        return MoodleChatResponse(response=result.text, session_id=chat_session.id)

    async def analyse_learner(self, profile: LearnerProfile) -> LearnerAnalysis:
        """Genere un bilan pedagogique a partir d'un profil apprenant Moodle."""
        await self._check_daily_token_limit(profile.moodle_userid)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _profile_to_text(profile)},
        ]
        result = await self.repository.chat_completion(messages)
        await self._log(
            result.prompt_tokens,
            result.completion_tokens,
            result.duration_ms,
            profile.moodle_userid,
        )
        return LearnerAnalysis(
            moodle_userid=profile.moodle_userid,
            fullname=profile.fullname,
            model_used=self.repository._model,
            analysis=result.text,
        )

    # ------------------------------------------------------------------
    # Consultation des logs (admin)
    # ------------------------------------------------------------------

    async def get_logs(
        self,
        skip: int = 0,
        limit: int = 20,
        moodle_userid: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[LLMLog]:
        """Recupere les logs LLM filtres et pagines."""
        return list(
            await self.log_repository.get_filtered(
                skip, limit, moodle_userid, date_from, date_to
            )
        )

    async def count_logs(
        self,
        moodle_userid: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """Compte les logs LLM selon les filtres."""
        return await self.log_repository.count_filtered(
            moodle_userid, date_from, date_to
        )

    async def get_stats(
        self,
        moodle_userid: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        """Retourne les statistiques agregees des appels LLM."""
        row = await self.log_repository.get_stats(moodle_userid, date_from, date_to)
        return {
            "total_calls": row["total_calls"],
            "total_prompt_tokens": row["total_prompt"],
            "total_completion_tokens": row["total_completion"],
            "total_tokens": row["total_prompt"] + row["total_completion"],
            "avg_prompt_tokens": float(row["avg_prompt"]),
            "avg_completion_tokens": float(row["avg_completion"]),
            "avg_duration_ms": float(row["avg_duration"]),
        }

    async def _log(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: int,
        moodle_userid: int | None,
    ) -> None:
        """Persiste les metriques de l'appel — echec silencieux."""
        try:
            await self.log_repository.insert(
                LLMLog(
                    moodle_userid=moodle_userid,
                    model_used=self.repository._model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=duration_ms,
                )
            )
        except Exception:
            logger.warning("Echec persistance LLMLog", exc_info=True)

    async def _get_or_build_profile_summary(
        self, profiles: list[LearnerProfile] | None
    ) -> str:
        """Genere (ou recupere depuis Redis) le resume compact du profil apprenant.

        Le resume est partage entre toutes les sessions du meme apprenant : cle
        Redis `llm:profile_summary:<userid>` avec un TTL aligne sur le cache
        Moodle. Si le profil change cote Moodle, le cache Moodle est invalide
        et la prochaine ouverture de session regenerera ce resume.
        """
        if not profiles:
            return ""
        # Pour l'instant on resume le profil principal. Si plusieurs profils
        # rattaches (apprenants enfants), on les resume separement et on les
        # concatene.
        sections: list[str] = []
        for profile in profiles:
            section = await self._profile_summary_for(profile)
            if section:
                sections.append(section)
        return "\n\n".join(sections)

    async def _profile_summary_for(self, profile: LearnerProfile) -> str:
        """Resume un profil unique : cache Redis -> sinon appel LLM auxiliaire."""
        cache_key = f"{_PROFILE_SUMMARY_CACHE_PREFIX}{profile.moodle_userid}"
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached:
                return cached.decode() if isinstance(cached, bytes) else cached

        full_profile_text = _profile_to_text(profile)
        try:
            result = await self.repository.chat_completion(
                [
                    {"role": "system", "content": _PROFILE_SUMMARY_PROMPT},
                    {"role": "user", "content": full_profile_text},
                ],
                model=self.repository._model,
            )
        except Exception:
            logger.warning(
                "Echec generation profile_summary userid=%s — fallback synthese",
                profile.moodle_userid,
                exc_info=True,
            )
            # Fallback : on renvoie la synthese deja calculee (sans appel LLM)
            return _build_learner_context(profile)

        summary = result.text.strip()
        await self._log(
            result.prompt_tokens,
            result.completion_tokens,
            result.duration_ms,
            profile.moodle_userid,
        )
        if self._cache is not None and self._profile_summary_ttl > 0:
            await self._cache.set(cache_key, summary, ex=self._profile_summary_ttl)
        return summary

    async def _compact_session_if_needed(self, chat_session: ChatSession) -> None:
        """Si trop de tours non compactes, fusionne les plus anciens en summary.

        Strategie : on garde les `_MAX_RECENT_TURNS` derniers tours bruts, on
        fusionne tous les autres dans `chat_session.summary` via un appel LLM.
        Idempotent : si moins de `_COMPACT_AFTER_TURNS` tours, no-op.
        """
        repo = self._chat_session_repository
        assert repo is not None
        active = await repo.get_active_turns(chat_session.id)
        if len(active) <= _COMPACT_AFTER_TURNS:
            return

        to_compact = list(active[:-_MAX_RECENT_TURNS])
        if not to_compact:
            return

        transcript = _format_turns_for_compact(to_compact)
        previous_summary = chat_session.summary
        compact_input = (
            f"Resume precedent (a integrer) :\n{previous_summary}\n\n"
            f"Nouveaux echanges a fusionner :\n{transcript}"
            if previous_summary
            else transcript
        )

        try:
            result = await self.repository.chat_completion(
                [
                    {"role": "system", "content": _SESSION_COMPACT_PROMPT},
                    {"role": "user", "content": compact_input},
                ],
                model=self.repository._model,
            )
        except Exception:
            logger.warning(
                "Echec compact session_id=%s — conservation des tours bruts",
                chat_session.id,
                exc_info=True,
            )
            return

        new_summary = result.text.strip()
        await self._log(
            result.prompt_tokens,
            result.completion_tokens,
            result.duration_ms,
            chat_session.moodle_userid,
        )
        await repo.update_summary(chat_session, new_summary)
        await repo.mark_compacted([t.id for t in to_compact if t.id is not None])

    def _build_user_content(
        self,
        message: str,
        profiles: list[LearnerProfile] | None,
    ) -> str:
        """Compose le contenu utilisateur (contexte + message) avec garde-fou tokens.

        Si l'estimation du prompt depasse `max_prompt_tokens`, on retombe sur la
        synthese pedagogique compacte au lieu du dossier Moodle complet.
        """
        if not profiles:
            return message

        learner_ctx = _build_chat_profiles_context(profiles)
        full = "\n\n".join(part for part in (learner_ctx, message) if part)

        if self._max_prompt_tokens <= 0:
            return full

        if _estimate_tokens(full) <= self._max_prompt_tokens:
            return full

        compact_ctx = _build_chat_profiles_context(profiles, compact=True)
        compacted = "\n\n".join(part for part in (compact_ctx, message) if part)
        logger.warning(
            "Contexte LLM trop long (%d > %d tokens) — fallback compact (%d)",
            _estimate_tokens(full),
            self._max_prompt_tokens,
            _estimate_tokens(compacted),
        )
        return compacted

    async def _check_daily_token_limit(self, moodle_userid: int | None) -> None:
        """Leve TooManyRequestsException si l'user a depasse la limite du jour.

        No-op si limite=0 (desactive) ou moodle_userid is None (anonyme).
        """
        if self._daily_token_limit <= 0 or moodle_userid is None:
            return
        used = await self.log_repository.sum_tokens_for_user_since(
            moodle_userid, _today_start_utc()
        )
        if used >= self._daily_token_limit:
            logger.info(
                "Daily token limit hit for moodle_userid=%s (used=%d, limit=%d)",
                moodle_userid,
                used,
                self._daily_token_limit,
            )
            raise TooManyRequestsException(
                f"Quota quotidien LLM atteint pour moodle_userid={moodle_userid} : "
                f"{used} tokens consommes / {self._daily_token_limit} autorises. "
                "Le compteur se reinitialise a 00:00 UTC."
            )


# -------------------------------------------------------------------------
# Helpers cache et routage
# -------------------------------------------------------------------------


def _today_start_utc() -> datetime:
    """Retourne 00:00:00 UTC du jour courant (datetime naif, coherent avec utcnow)."""
    return datetime.combine(datetime.now(UTC).date(), time.min)


def _estimate_tokens(text: str) -> int:
    """Estime grossierement le nombre de tokens d'un texte (~4 caracteres / token)."""
    return len(text) // _TOKEN_CHARS


def _build_chat_messages(
    role: MoodleUserRole,
    prompt_id: str | None,
    chat_session: ChatSession,
    recent_turns: Sequence[ChatTurn],
    new_message: str,
) -> list[dict[str, str]]:
    """Compose la liste de messages pour l'API chat completion (mode session).

    Format : system (role + profil + summary) puis tours alternes user/assistant
    puis nouvelle question.
    """
    system_parts: list[str] = [get_system_prompt(role, prompt_id)]
    if chat_session.profile_summary:
        system_parts.append(
            "=== Profil apprenant (resume) ===\n" + chat_session.profile_summary
        )
    if chat_session.summary:
        system_parts.append(
            "=== Resume de la conversation precedente ===\n" + chat_session.summary
        )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(system_parts)}
    ]
    for turn in recent_turns:
        messages.append({"role": "user", "content": turn.user_message})
        messages.append({"role": "assistant", "content": turn.assistant_response})
    messages.append({"role": "user", "content": new_message})
    return messages


def _format_turns_for_compact(turns: Sequence[ChatTurn]) -> str:
    """Serialise une liste de tours en transcript pour le LLM de compact."""
    lines: list[str] = []
    for turn in turns:
        lines.append(f"[Tour {turn.turn_num}] User : {turn.user_message}")
        lines.append(f"[Tour {turn.turn_num}] Assistant : {turn.assistant_response}")
    return "\n".join(lines)


def _make_cache_key(
    user_content: str,
    role: MoodleUserRole,
    prompt_id: str | None,
) -> str:
    """Cle Redis derivee du contenu, du role et du prompt predefini.

    Role et prompt_id sont inclus pour eviter les collisions entre prompts distincts.
    """
    key_material = f"{role}:{prompt_id or ''}:{user_content}"
    digest = hashlib.sha256(key_material.encode()).hexdigest()[:24]
    return f"llm:chat:{digest}"


def _is_simple_query(message: str, has_profile: bool) -> bool:
    """Retourne True si la question est assez simple pour le modele leger.

    Regle : pas de profil apprenant ET message court (<= 15 mots).
    Avec profil = analyse necessitant raisonnement → modele lourd.
    """
    if has_profile:
        return False
    return len(message.split()) <= _LIGHT_MODEL_MAX_WORDS


# -------------------------------------------------------------------------
# Construction du contexte apprenant (synchrone, testable)
# -------------------------------------------------------------------------


def _build_learner_context(profile: LearnerProfile) -> str:
    """Construit un bloc texte resumant forces, faiblesses, actions et ressources.

    Alimente le prompt du tuteur proactif. Retourne chaine vide si aucun element.
    """
    forces: list[str] = []
    faiblesses: list[str] = []
    actions: list[str] = []

    now_ts = int(datetime.now(UTC).timestamp())
    course_names = {c.id: c.fullname for c in profile.courses}

    # --- Progression par cours ---
    for course in profile.courses:
        if course.progress is not None:
            if course.progress >= 70 and len(forces) < _MAX_PER_CATEGORY:
                forces.append(
                    f"Bonne progression dans '{course.fullname}'"
                    f" ({course.progress:.0f}%)"
                )
            elif course.progress < 30 and len(faiblesses) < _MAX_PER_CATEGORY:
                faiblesses.append(
                    f"Faible progression dans '{course.fullname}'"
                    f" ({course.progress:.0f}%)"
                )
                if len(actions) < _MAX_PER_CATEGORY:
                    actions.append(f"Reprendre le cours '{course.fullname}'")

    # --- Notes par activite ---
    for cid, items in profile.grades_by_course.items():
        course_name = course_names.get(cid, f"cours {cid}")
        for item in items:
            if item.graderaw is None or not item.itemname:
                continue
            if item.grademax and item.grademax > 0:
                ratio = item.graderaw / item.grademax
                if ratio >= 0.60 and len(forces) < _MAX_PER_CATEGORY:
                    forces.append(f"Bonne note en '{item.itemname}' ({course_name})")
                elif ratio < 0.50 and len(faiblesses) < _MAX_PER_CATEGORY:
                    faiblesses.append(
                        f"Note insuffisante en '{item.itemname}' ({course_name})"
                    )

    # --- Quiz abandonnes ---
    for attempt in profile.quiz_attempts:
        if attempt.state == "abandoned" and len(faiblesses) < _MAX_PER_CATEGORY:
            faiblesses.append(f"Quiz {attempt.quizid} abandonne")
            if len(actions) < _MAX_PER_CATEGORY:
                actions.append(f"Terminer quiz {attempt.quizid}")

    # --- Devoirs ---
    for assign in profile.assignments:
        duedate = assign.duedate or 0
        submitted = assign.status == "submitted"
        if duedate > 0 and not submitted:
            if duedate < now_ts and len(faiblesses) < _MAX_PER_CATEGORY:
                faiblesses.append(f"Devoir en retard : '{assign.name}'")
                if len(actions) < _MAX_PER_CATEGORY:
                    actions.append(f"Rendre '{assign.name}' (date depassee)")
            elif duedate > now_ts and len(actions) < _MAX_PER_CATEGORY:
                due_str = datetime.fromtimestamp(duedate, tz=UTC).strftime("%d/%m/%Y")
                actions.append(f"Rendre '{assign.name}' avant le {due_str}")

    # --- Premier cours avec activites incompletes ---
    for cid, completions in profile.completion_by_course.items():
        incomplete = sum(1 for c in completions if c.state == 0)
        if incomplete > 0 and len(actions) < _MAX_PER_CATEGORY:
            course_name = course_names.get(cid, f"cours {cid}")
            actions.append(f"Completer {incomplete} activite(s) dans '{course_name}'")
            break

    # --- Journal comportemental (activity_log) ---
    warning_events = [e for e in profile.activity_log if e.severity == "warning"][
        :_MAX_ACTIVITY_EVENTS
    ]

    # --- Index des ressources disponibles ---
    resource_lines: list[str] = []
    for cid, resources in profile.resources_by_course.items():
        if not resources:
            continue
        course_name = course_names.get(cid, f"cours {cid}")
        top = resources[:_MAX_RESOURCES_PER_COURSE]
        items_str = " | ".join(f"{r.name} [{r.modname}]" for r in top)
        extra = len(resources) - len(top)
        suffix = f" (+{extra})" if extra > 0 else ""
        resource_lines.append(f"'{course_name}' : {items_str}{suffix}")

    # --- Assemblage final ---
    has_level = profile.level != LearnerLevel.UNKNOWN
    has_content = any(
        [forces, faiblesses, actions, warning_events, resource_lines, has_level]
    )
    if not has_content:
        return ""

    lines: list[str] = [f"Profil de l'apprenant : {profile.fullname}"]
    if has_level:
        lines.append(f"Niveau estime : {_LEVEL_LABELS[profile.level]}")
    if forces:
        lines.append("Points forts : " + " | ".join(forces))
    if faiblesses:
        lines.append("Points d'attention : " + " | ".join(faiblesses))
    if actions:
        lines.append("Actions prioritaires : " + " | ".join(actions))
    if warning_events:
        lines.append(
            "Journal d'activite : " + " | ".join(e.description for e in warning_events)
        )
    if resource_lines:
        lines.append("Ressources disponibles :\n" + "\n".join(resource_lines))

    return "\n".join(lines)


def _profile_to_chat_text(profile: LearnerProfile, compact: bool = False) -> str:
    """Construit le dossier apprenant injecte dans le prompt chat.

    Synthese pedagogique en tete + apercu cours compact + sections optionnelles
    (ressources, badges, preferences, calendrier, forum). Le dossier Moodle
    detaille (notes par activite, completion, quiz attempts) n'est pas injecte
    dans le chat : trop volumineux et redondant avec la synthese.

    `compact=True` ne garde que la synthese et l'apercu cours — fallback en cas
    de depassement du budget tokens.
    """
    sections: list[str] = []

    summary = _build_learner_context(profile)
    if summary:
        sections.append("=== Synthese pedagogique ===\n" + summary)

    overview = _profile_to_chat_overview(profile)
    if overview:
        sections.append("=== Apercu cours ===\n" + overview)

    if compact:
        return "\n\n".join(section for section in sections if section.strip())

    if profile.resources_by_course:
        course_names = {c.id: c.fullname for c in profile.courses}
        resource_lines: list[str] = []
        for cid, resources in profile.resources_by_course.items():
            if not resources:
                continue
            course_name = course_names.get(cid, f"cours {cid}")
            top = resources[:_MAX_RESOURCES_PER_COURSE]
            items = " | ".join(f"{r.name} [{r.modname}]" for r in top)
            extra = len(resources) - len(top)
            suffix = f" (+{extra})" if extra > 0 else ""
            resource_lines.append(f"- {course_name} : {items}{suffix}")
        if resource_lines:
            sections.append(
                "=== Ressources disponibles ===\n" + "\n".join(resource_lines)
            )

    if profile.badges:
        badge_lines = [f"- {badge.name}" for badge in profile.badges[:_MAX_BADGES]]
        extra = len(profile.badges) - len(badge_lines)
        if extra > 0:
            badge_lines.append(f"- (+{extra} autres badges)")
        sections.append("=== Badges ===\n" + "\n".join(badge_lines))

    pref_map = {pref.name: pref.value for pref in profile.preferences}
    useful_prefs = []
    if pref_map.get("lang"):
        useful_prefs.append(f"- Langue : {pref_map['lang']}")
    if pref_map.get("timezone"):
        useful_prefs.append(f"- Fuseau horaire : {pref_map['timezone']}")
    if useful_prefs:
        sections.append("=== Preferences apprenant ===\n" + "\n".join(useful_prefs))

    if profile.calendar_events:
        sorted_events = sorted(
            profile.calendar_events, key=lambda event: event.timestart
        )
        event_lines = []
        for event in sorted_events[:_MAX_CALENDAR_EVENTS]:
            date_str = datetime.fromtimestamp(event.timestart, tz=UTC).strftime(
                "%d/%m/%Y"
            )
            course_part = f" (cours {event.courseid})" if event.courseid else ""
            event_lines.append(f"- {date_str} : {event.name}{course_part}")
        sections.append("=== Evenements a venir ===\n" + "\n".join(event_lines))

    if profile.forum_posts:
        sorted_posts = sorted(
            profile.forum_posts, key=lambda post: post.created, reverse=True
        )
        post_lines = []
        for post in sorted_posts[:_MAX_FORUM_POSTS]:
            post_lines.append(f"- {post.subject}")
        sections.append("=== Activite forum recente ===\n" + "\n".join(post_lines))

    return "\n\n".join(section for section in sections if section.strip())


def _build_chat_profiles_context(
    profiles: list[LearnerProfile], compact: bool = False
) -> str:
    """Construit le contexte chat a partir d'un ou plusieurs profils apprenants.

    `compact=True` produit une version reduite (synthese + apercu cours uniquement),
    utilisee comme fallback quand le budget tokens est depasse.
    """
    if not profiles:
        return ""
    if len(profiles) == 1:
        return _profile_to_chat_text(profiles[0], compact=compact)

    sections = []
    for profile in profiles:
        ctx = _profile_to_chat_text(profile, compact=compact)
        if ctx:
            sections.append(ctx)

    if not sections:
        return ""

    return "Profils des apprenants rattaches :\n\n" + "\n\n".join(sections)


def _profile_to_chat_overview(profile: LearnerProfile) -> str:
    """Apercu compact d'un apprenant pour le chat : cours + notes globales.

    Ne contient PAS les notes par activite, la completion detaillee, les
    tentatives de quiz ni les devoirs : ces signaux sont deja captures dans
    la synthese (`_build_learner_context`). Cible : ~30 tokens / cours.
    """
    if not profile.courses and not profile.overview_grades:
        return ""

    course_names = {c.id: c.fullname for c in profile.courses}
    lines: list[str] = []

    if profile.courses:
        lines.append(f"Cours inscrits ({len(profile.courses)}) :")
        for course in profile.courses:
            progress = (
                f"{course.progress:.0f}%" if course.progress is not None else "n/a"
            )
            course_level = profile.level_by_course.get(course.id, LearnerLevel.UNKNOWN)
            level_part = (
                f", niveau {_LEVEL_LABELS[course_level]}"
                if course_level != LearnerLevel.UNKNOWN
                else ""
            )
            lines.append(f"- {course.fullname} : {progress}{level_part}")

    if profile.overview_grades:
        lines.append("")
        lines.append("Notes globales :")
        for grade in profile.overview_grades:
            name = course_names.get(grade.courseid, str(grade.courseid))
            lines.append(f"- {name} : {grade.grade}")

    return "\n".join(lines)


# -------------------------------------------------------------------------
# Construction du prompt utilisateur (analyse complete)
# -------------------------------------------------------------------------


def _profile_to_text(profile: LearnerProfile) -> str:
    """Convertit un LearnerProfile en texte lisible pour le LLM."""
    course_names = {c.id: c.fullname for c in profile.courses}
    lines: list[str] = [
        f"Apprenant : {profile.fullname} ({profile.username})",
        f"Email : {profile.email}",
    ]
    if profile.level != LearnerLevel.UNKNOWN:
        lines.append(f"Niveau estime : {_LEVEL_LABELS[profile.level]}")
    lines += [
        "",
        f"=== Cours inscrits ({len(profile.courses)}) ===",
    ]

    for course in profile.courses:
        progress = (
            f"{course.progress:.0f}%"
            if course.progress is not None
            else "progression non suivie"
        )
        course_level = profile.level_by_course.get(course.id, LearnerLevel.UNKNOWN)
        level_part = (
            f", niveau : {_LEVEL_LABELS[course_level]}"
            if course_level != LearnerLevel.UNKNOWN
            else ""
        )
        lines.append(
            f"- {course.fullname} [{course.shortname}] : {progress}{level_part}"
        )

    if profile.overview_grades:
        lines += ["", "=== Notes globales par cours ==="]
        for grade in profile.overview_grades:
            name = course_names.get(grade.courseid, str(grade.courseid))
            lines.append(f"- {name} : {grade.grade}")

    graded = {
        cid: [i for i in items if i.graderaw is not None and i.itemname]
        for cid, items in profile.grades_by_course.items()
    }
    graded = {cid: items for cid, items in graded.items() if items}
    if graded:
        lines += ["", "=== Notes par activite ==="]
        for cid, items in graded.items():
            lines.append(f"Cours {course_names.get(cid, str(cid))} :")
            for item in items:
                score = item.gradeformatted or str(item.graderaw)
                max_score = f"/{item.grademax}" if item.grademax else ""
                lines.append(
                    f"  - {item.itemname} ({item.itemmodule}) : {score}{max_score}"
                )
                if item.feedback:
                    lines.append(f"    Feedback : {item.feedback}")

    completion_stats = {
        cid: (
            sum(1 for c in completions if c.state >= 1),
            len(completions),
        )
        for cid, completions in profile.completion_by_course.items()
        if completions
    }
    if completion_stats:
        lines += ["", "=== Completion des activites ==="]
        for cid, (done, total) in completion_stats.items():
            name = course_names.get(cid, str(cid))
            lines.append(f"- {name} : {done}/{total} activites completees")

    if profile.quiz_attempts:
        lines += ["", "=== Tentatives de quiz ==="]
        for attempt in profile.quiz_attempts:
            score = (
                f"{attempt.sumgrades} pts"
                if attempt.sumgrades is not None
                else "score non disponible"
            )
            lines.append(
                f"- Quiz {attempt.quizid}, tentative {attempt.attempt_number}"
                f" ({attempt.state}) : {score}"
            )

    if profile.assignments:
        lines += ["", "=== Devoirs ==="]
        for assign in profile.assignments:
            grade_info = f", note : {assign.grade}" if assign.grade is not None else ""
            status = assign.status or "non soumis"
            lines.append(f"- {assign.name} : {status}{grade_info}")

    if profile.activity_log:
        lines += ["", "=== Journal comportemental ==="]
        for event in profile.activity_log:
            lines.append(f"- [{event.severity.upper()}] {event.description}")

    return "\n".join(lines)
