"""Couche de logique metier pour le domaine proactivite."""

import logging
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis

from ....conf import get_settings, utcnow
from ....exceptions import MoodleAPIException
from ...llm.repositories import LLMLogRepository, LLMRepository
from ...moodle.services import MoodleService
from ..models.schemas import ProactivityEvent, ProactivitySettings
from ..repositories.proactivity_repository import (
    ProactivityEventRepository,
    ProactivityHttpRepository,
)

logger = logging.getLogger(__name__)

_SETTINGS_CACHE_KEY = "proactivity:settings"

_SUGGESTION_SYSTEM_PROMPT = (
    "Tu es un assistant pedagogique. L'apprenant vient de terminer le module {module}. "
    "Propose-lui en 2-3 phrases une activite ou ressource complementaire pertinente. "
    "Sois concis et encourageant."
)

_REMINDER_SUBJECT = "Reprenez votre formation !"
_REMINDER_MESSAGE = (
    "Bonjour, vous n'avez pas utilise votre assistant pedagogique depuis un moment. "
    "Reconnectez-vous pour reprendre votre apprentissage la ou vous l'avez laissé."
)
_SUGGESTION_SUBJECT = "Activite complementaire a decouvrir"

# Fenetre anti-doublon reminder : on ne renvoie pas si deja envoye dans les
# (reminder_delay_hours + 24) heures (evite les doubles sur executions proches)
_REMINDER_WINDOW_EXTRA_HOURS = 24


class ProactivityService:
    """Orchestre les jobs de proactivite M1-008 (reminder) et M1-009 (suggestion)."""

    def __init__(
        self,
        event_repo: ProactivityEventRepository,
        llm_log_repo: LLMLogRepository,
        http_repo: ProactivityHttpRepository,
        moodle_svc: MoodleService,
        llm_repo: LLMRepository,
        redis: aioredis.Redis | None = None,
    ) -> None:
        self._event_repo = event_repo
        self._llm_log_repo = llm_log_repo
        self._http_repo = http_repo
        self._moodle_svc = moodle_svc
        self._llm_repo = llm_repo
        self._redis = redis
        self._settings = get_settings()

    # -------------------------------------------------------------------------
    # Configuration Moodle (cachee Redis)
    # -------------------------------------------------------------------------

    async def get_proactivity_settings(self) -> ProactivitySettings:
        """Retourne la config proactivite — Redis TTL PROACTIVITY_SETTINGS_CACHE_TTL.

        En cas d'erreur Moodle : leve MoodleAPIException (propagee a l'appelant).
        """
        ttl = self._settings.PROACTIVITY_SETTINGS_CACHE_TTL

        if self._redis is not None and ttl > 0:
            cached = await self._redis.get(_SETTINGS_CACHE_KEY)
            if cached:
                return ProactivitySettings.model_validate_json(cached)

        raw = await self._http_repo.get_settings()
        settings = ProactivitySettings.model_validate(raw)

        if self._redis is not None and ttl > 0:
            await self._redis.set(
                _SETTINGS_CACHE_KEY,
                settings.model_dump_json(),
                ex=ttl,
            )

        return settings

    # -------------------------------------------------------------------------
    # M1-008 — Rappel apres inactivite
    # -------------------------------------------------------------------------

    async def run_reminder_job(self) -> int:
        """Envoie des rappels aux apprenants inactifs depuis reminder_delay_hours.

        Cible tous les inscrits Moodle qui n'ont pas utilise le chat recemment,
        y compris ceux qui ne l'ont jamais utilise.

        Retourne le nombre de notifications envoyees.
        Idempotent : skip si un reminder a deja ete envoye dans la fenetre.
        """
        try:
            proactivity_settings = await self.get_proactivity_settings()
        except MoodleAPIException as exc:
            logger.error("Reminder : impossible de recuperer les settings : %s", exc.detail)
            return 0

        if not proactivity_settings.reminder_enabled:
            logger.info("Reminder : job desactive par configuration Moodle")
            return 0

        now = utcnow()
        cutoff = now - timedelta(hours=proactivity_settings.reminder_delay_hours)
        window_start = now - timedelta(
            hours=proactivity_settings.reminder_delay_hours + _REMINDER_WINDOW_EXTRA_HOURS
        )

        # Apprenants inscrits dans Moodle (formateurs exclus)
        try:
            all_learners = await self._moodle_svc.get_enrolled_learner_ids()
        except MoodleAPIException as exc:
            logger.error("Reminder : impossible de recuperer les apprenants Moodle : %s", exc.detail)
            return 0

        # Utilisateurs ayant utilise le chat recemment → exclus du rappel
        try:
            recently_active = set(await self._llm_log_repo.get_active_userids(cutoff))
        except Exception as exc:
            logger.error("Reminder : erreur requete LLMLog : %s", exc)
            recently_active = set()

        inactive_ids = all_learners - recently_active
        logger.info(
            "Reminder : %d apprenant(s), %d actif(s) recemment, %d inactif(s) a traiter",
            len(all_learners), len(recently_active), len(inactive_ids),
        )

        sent = 0
        for userid in inactive_ids:
            try:
                sent += await self._process_reminder(
                    userid, proactivity_settings, window_start
                )
            except Exception as exc:
                logger.warning("Reminder userid=%d : erreur inattendue : %s", userid, exc)

        logger.info("Reminder : %d notification(s) envoyee(s)", sent)
        return sent

    async def _process_reminder(
        self,
        userid: int,
        proactivity_settings: ProactivitySettings,
        window_start: datetime,
    ) -> int:
        """Traite un utilisateur pour le job reminder. Retourne 0 ou 1."""
        # Anti-doublon
        if await self._event_repo.has_event_in_window(userid, "reminder", window_start):
            return 0

        # Envoi notification
        try:
            await self._http_repo.push_notification(
                type_="reminder",
                moodle_userid=userid,
                subject=_REMINDER_SUBJECT,
                message=_REMINDER_MESSAGE,
                url=proactivity_settings.chat_url,
            )
        except MoodleAPIException as exc:
            logger.warning("Reminder : push_notification userid=%d echoue : %s", userid, exc.detail)
            return 0

        # Enregistrement de l'evenement
        await self._event_repo.save(
            ProactivityEvent(
                moodle_userid=userid,
                event_type="reminder",
            )
        )
        await self._event_repo.session.commit()
        return 1

    # -------------------------------------------------------------------------
    # M1-009 — Suggestion apres completion de module
    # -------------------------------------------------------------------------

    async def run_suggestion_job(self) -> int:
        """Genere des suggestions pour les modules completés depuis le dernier check.

        Cible tous les inscrits Moodle, y compris ceux qui n'ont jamais
        utilise le chat.

        Retourne le nombre de suggestions envoyees.
        """
        try:
            proactivity_settings = await self.get_proactivity_settings()
        except MoodleAPIException as exc:
            logger.error("Suggestion : impossible de recuperer les settings : %s", exc.detail)
            return 0

        if not proactivity_settings.suggestion_enabled:
            logger.info("Suggestion : job desactive par configuration Moodle")
            return 0

        # Apprenants inscrits dans Moodle (formateurs exclus)
        try:
            target_ids = await self._moodle_svc.get_enrolled_learner_ids()
        except MoodleAPIException as exc:
            logger.error(
                "Suggestion : impossible de recuperer les apprenants Moodle : %s", exc.detail
            )
            return 0

        logger.info("Suggestion : %d apprenant(s) a verifier", len(target_ids))

        sent = 0
        for userid in target_ids:
            try:
                sent += await self._process_suggestion(userid, proactivity_settings)
            except Exception as exc:
                logger.warning("Suggestion userid=%d : erreur inattendue : %s", userid, exc)

        logger.info("Suggestion : %d suggestion(s) envoyee(s)", sent)
        return sent

    async def _process_suggestion(
        self,
        userid: int,
        proactivity_settings: ProactivitySettings,
    ) -> int:
        """Traite un utilisateur pour le job suggestion. Retourne le nb de suggestions."""
        # Dernier check pour cet utilisateur
        last_check = await self._event_repo.get_last_event(userid, "suggestion_check")
        last_check_dt: datetime
        if last_check is not None:
            last_check_dt = last_check.created_at
        else:
            last_check_dt = utcnow() - timedelta(days=30)

        # Profil Moodle (avec cache Redis)
        try:
            profile = await self._moodle_svc.get_learner_profile(userid)
        except MoodleAPIException as exc:
            logger.warning("Suggestion userid=%d : profil indisponible : %s", userid, exc.detail)
            return 0

        # Modules completes depuis le dernier check
        newly_completed_cmids: list[int] = []
        for completions in profile.completion_by_course.values():
            for completion in completions:
                if completion.state not in (1, 2):
                    continue
                if not completion.timecompleted:
                    continue
                completed_at = datetime.fromtimestamp(completion.timecompleted, UTC).replace(tzinfo=None)
                if completed_at > last_check_dt:
                    newly_completed_cmids.append(completion.cmid)

        # Exclusion des modules deja suggeres
        already_suggested = await self._event_repo.get_suggestion_module_ids(userid)
        to_suggest = [cmid for cmid in newly_completed_cmids if cmid not in already_suggested]

        # Enregistrement du check AVANT les suggestions (marque l'instant de reference)
        await self._event_repo.save(
            ProactivityEvent(
                moodle_userid=userid,
                event_type="suggestion_check",
            )
        )
        await self._event_repo.session.commit()

        if not to_suggest:
            return 0

        sent = 0
        for cmid in to_suggest:
            try:
                sent += await self._send_suggestion(
                    userid, cmid, profile, proactivity_settings
                )
            except Exception as exc:
                logger.warning(
                    "Suggestion userid=%d cmid=%d : erreur : %s", userid, cmid, exc
                )

        return sent

    async def _send_suggestion(
        self,
        userid: int,
        cmid: int,
        profile,
        proactivity_settings: ProactivitySettings,
    ) -> int:
        """Genere et envoie une suggestion pour un module complete. Retourne 0 ou 1."""
        # Recherche du nom du module dans les ressources
        module_name = _find_module_name(profile, cmid)

        # Appel LLM pour generer la suggestion
        prompt = _SUGGESTION_SYSTEM_PROMPT.format(module=module_name)
        try:
            completion = await self._llm_repo.chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Propose une activite complementaire."},
                ],
            )
        except Exception as exc:
            logger.warning("Suggestion : LLM echoue pour cmid=%d : %s", cmid, exc)
            return 0

        # Envoi notification
        try:
            await self._http_repo.push_notification(
                type_="suggestion",
                moodle_userid=userid,
                subject=_SUGGESTION_SUBJECT,
                message=completion.text,
                url=proactivity_settings.recommendations_url,
            )
        except MoodleAPIException as exc:
            logger.warning(
                "Suggestion : push_notification userid=%d cmid=%d echoue : %s",
                userid, cmid, exc.detail,
            )
            return 0

        # Persistance de l'evenement
        await self._event_repo.save(
            ProactivityEvent(
                moodle_userid=userid,
                event_type="suggestion",
                payload={"module_id": cmid, "module_name": module_name},
            )
        )
        await self._event_repo.session.commit()
        return 1


def _find_module_name(profile, cmid: int) -> str:
    """Recherche le nom d'un module par son cmid dans le profil apprenant."""
    for resources in profile.resources_by_course.values():
        for resource in resources:
            if resource.cmid == cmid:
                return resource.name
    return f"module {cmid}"
