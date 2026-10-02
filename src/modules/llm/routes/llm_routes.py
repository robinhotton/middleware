"""Endpoints REST pour l'analyse LLM d'un profil apprenant Moodle."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from ....conf import get_settings, limiter
from ....exceptions import MoodleAPIException
from ...auth import (
    RoleName,
    User,
    require_role,
    verify_moodle_webhook,
)
from ...moodle.dependencies import get_moodle_service
from ...moodle.models import MoodleUserRole
from ...moodle.services import MoodleService
from ...shared.common import PaginatedResponse
from ..dependencies import get_llm_service
from ..models import (
    LearnerAnalysis,
    LLMLogRead,
    LLMStatsResponse,
    MoodleChatRequest,
    MoodleChatResponse,
    PlatformSettingsResponse,
    PromptTemplateRead,
)
from ..prompts import get_prompts_by_role
from ..services import LLMService

logger = logging.getLogger(__name__)

router = APIRouter()

_TRAINER_SHORTNAMES = frozenset(
    {
        "editingteacher",
        "teacher",
        "manager",
        "coursecreator",
        "formateur",
        "enseignant",
        "trainer",
    }
)


def _parse_moodle_role(raw: str | None) -> MoodleUserRole | None:
    """Normalise un shortname Moodle vers MoodleUserRole.

    Retourne None si raw est absent — signale qu'un fallback WS est necessaire.
    """
    if not raw:
        return None
    lower = raw.lower()
    if lower in _TRAINER_SHORTNAMES:
        return MoodleUserRole.TRAINER
    if lower == "student":
        return MoodleUserRole.STUDENT
    return MoodleUserRole.UNKNOWN


@router.get(
    "/learner/{moodle_userid}",
    summary="Analyse pedagogique LLM d'un apprenant Moodle",
    response_model=LearnerAnalysis,
    responses={
        502: {"description": "Erreur Moodle ou LLM"},
        403: {"description": "Acces admin requis"},
    },
)
@limiter.limit("10/minute")
async def analyse_learner(
    request: Request,
    moodle_userid: int,
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
    moodle_svc: MoodleService = Depends(get_moodle_service),
    llm_svc: LLMService = Depends(get_llm_service),
) -> LearnerAnalysis:
    """Recupere le profil Moodle de l'apprenant puis genere un bilan pedagogique.

    Orchestre : MoodleService.get_learner_profile → LLMService.analyse_learner.
    Requiert le role admin (JWT FastAPI).
    """
    profile = await moodle_svc.get_learner_profile(moodle_userid)
    return await llm_svc.analyse_learner(profile)


@router.get(
    "/settings",
    summary="Parametres de la plateforme exposes a Moodle",
    response_model=PlatformSettingsResponse,
    responses={
        200: {"description": "Parametres courants de la plateforme"},
        401: {"description": "Secret webhook manquant ou invalide"},
    },
)
@limiter.limit("60/minute")
async def get_platform_settings(
    request: Request,
    _auth: None = Depends(verify_moodle_webhook),
) -> PlatformSettingsResponse:
    """Retourne les parametres de la plateforme utilisables par le plugin Moodle.

    Authentification : MOODLE_WEBHOOK_SECRET (header Authorization: Bearer <secret>).
    Moodle utilise cet endpoint pour connaitre le nom de l'IA a afficher dans son UI.
    """
    settings = get_settings()
    return PlatformSettingsResponse(ai_name=settings.AI_NAME)


@router.get(
    "/prompts",
    summary="Catalogue des prompts predefinis par role (Moodle)",
    response_model=list[PromptTemplateRead],
    responses={
        200: {"description": "Liste des prompts predefinis"},
        401: {"description": "Secret webhook manquant ou invalide"},
    },
)
@limiter.limit("60/minute")
async def list_prompts(
    request: Request,
    role: str | None = Query(
        default=None,
        description="Filtrer par role : student ou trainer. Retourne tout si absent.",
        examples=["trainer"],
    ),
    _auth: None = Depends(verify_moodle_webhook),
) -> list[PromptTemplateRead]:
    """Retourne le catalogue des prompts predefinis, filtre par role si specifie.

    Authentification : MOODLE_WEBHOOK_SECRET (header Authorization: Bearer <secret>).
    Moodle utilise cet endpoint pour alimenter l'UI de selection d'activite.
    """
    moodle_role: MoodleUserRole | None = None
    if role is not None:
        parsed = _parse_moodle_role(role)
        moodle_role = parsed if parsed is not None else MoodleUserRole.UNKNOWN

    templates = get_prompts_by_role(moodle_role)
    return [
        PromptTemplateRead(
            id=t.id,
            role=t.role,
            name=t.name,
            description=t.description,
            user_message_template=t.user_message_template,
        )
        for t in templates
    ]


@router.post(
    "/chat",
    summary="Chat LLM avec prompt adapte au role de l'utilisateur",
    response_model=MoodleChatResponse,
    responses={
        200: {"description": "Reponse du LLM"},
        401: {"description": "Secret webhook manquant ou invalide"},
        502: {"description": "Erreur Moodle ou LLM"},
    },
)
@limiter.limit("30/minute")
async def moodle_chat(
    request: Request,
    body: MoodleChatRequest,
    _auth: None = Depends(verify_moodle_webhook),
    moodle_svc: MoodleService = Depends(get_moodle_service),
    llm_svc: LLMService = Depends(get_llm_service),
) -> MoodleChatResponse:
    """Recoit un message, detecte le role de l'utilisateur et repond avec le bon prompt.

    Authentification : MOODLE_WEBHOOK_SECRET (header Authorization: Bearer <secret>).

    Detection du role (par priorite) :
    1. moodle_user_role dans le body (shortname Moodle fourni par le plugin)
    2. Appel WS Moodle sur moodle_userid (best-effort, echec silencieux)
    3. Defaut : STUDENT

    Si prompt_id est fourni et correspond au role detecte, le prompt specifique
    de l'activite est utilise comme system prompt.
    """
    # --- Detection du role ---
    role = _parse_moodle_role(body.moodle_user_role)
    if role is None and body.moodle_userid is not None:
        try:
            role = await moodle_svc.get_user_role(body.moodle_userid)
        except Exception as exc:
            logger.warning(
                "Detection role indisponible (userid=%s) — defaut STUDENT : %s",
                body.moodle_userid,
                exc,
            )
    if role is None:
        role = MoodleUserRole.STUDENT

    # --- Recuperation des profils apprenants ---
    # Le niveau n'est pertinent que pour les apprenants. Pour un formateur,
    # on recupere uniquement les profils de ses apprenants lies (enfants) ;
    # s'il n'en a pas, on ne construit pas son propre profil.
    profiles = None
    if body.moodle_userid is not None:
        try:
            if role == MoodleUserRole.TRAINER:
                profiles = await moodle_svc.get_related_profiles(body.moodle_userid)
            else:
                profiles = await moodle_svc.get_chat_profiles(body.moodle_userid)
        except (MoodleAPIException, Exception) as exc:
            logger.warning(
                "Profils apprenants indisponibles (userid=%s) — chat sans profil : %s",
                body.moodle_userid,
                exc,
            )

    message = f"{body.context}\n\n{body.message}" if body.context else body.message

    return await llm_svc.chat(
        message=message,
        profiles=profiles,
        moodle_userid=body.moodle_userid,
        role=role,
        prompt_id=body.prompt_id,
        session_id=body.session_id,
    )


# ------------------------------------------------------------------
# Endpoints admin — consultation des logs LLM
# ------------------------------------------------------------------


@router.get(
    "/logs",
    summary="Lister les logs d'appels LLM (admin)",
    response_model=PaginatedResponse[LLMLogRead],
    responses={
        401: {"description": "Non authentifie"},
        403: {"description": "Acces admin requis"},
    },
)
@limiter.limit("30/minute")
async def get_llm_logs(
    request: Request,
    skip: int = Query(0, ge=0, description="Nombre d'elements a ignorer"),
    limit: int = Query(
        20, ge=1, le=100, description="Nombre maximum d'elements a retourner"
    ),
    moodle_userid: int | None = Query(
        None, description="Filtrer par identifiant Moodle"
    ),
    date_from: datetime | None = Query(None, description="Date de debut (ISO 8601)"),
    date_to: datetime | None = Query(None, description="Date de fin (ISO 8601)"),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
    llm_svc: LLMService = Depends(get_llm_service),
) -> PaginatedResponse[LLMLogRead]:
    """Retourne les logs LLM pagines avec filtres optionnels."""
    total = await llm_svc.count_logs(moodle_userid, date_from, date_to)
    items = await llm_svc.get_logs(skip, limit, moodle_userid, date_from, date_to)
    return PaginatedResponse(total=total, skip=skip, limit=limit, items=items)


@router.get(
    "/logs/stats",
    summary="Statistiques agregees des appels LLM (admin)",
    response_model=LLMStatsResponse,
    responses={
        401: {"description": "Non authentifie"},
        403: {"description": "Acces admin requis"},
    },
)
@limiter.limit("30/minute")
async def get_llm_stats(
    request: Request,
    moodle_userid: int | None = Query(
        None, description="Filtrer par identifiant Moodle"
    ),
    date_from: datetime | None = Query(None, description="Date de debut (ISO 8601)"),
    date_to: datetime | None = Query(None, description="Date de fin (ISO 8601)"),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
    llm_svc: LLMService = Depends(get_llm_service),
) -> LLMStatsResponse:
    """Retourne les statistiques agregees de consommation LLM."""
    stats = await llm_svc.get_stats(moodle_userid, date_from, date_to)
    return LLMStatsResponse(**stats)
