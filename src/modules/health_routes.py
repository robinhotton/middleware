"""Endpoints de diagnostic — health global et sous-systemes."""

from fastapi import APIRouter, Depends, Request

from ..conf import limiter
from .auth.dependencies import require_role
from .auth.models.role import RoleName
from .auth.models.user import User
from .moodle.dependencies import get_moodle_service
from .moodle.models.schemas import MoodleHealthResponse
from .moodle.services.moodle_service import MoodleService
from .shared.common import HealthResponse

health_router = APIRouter(tags=["health"])

@health_router.get(
    "/health",
    summary="Sonde de sante",
    response_model=HealthResponse,
    responses={200: {"description": "API operationnelle"}},
)
async def health_check() -> HealthResponse:
    """Verifie que l'API est operationnelle."""
    return HealthResponse(status="ok")


@health_router.get(
    "/moodle/health",
    summary="Verifie la connexion Moodle",
    response_model=MoodleHealthResponse,
    responses={
        502: {"description": "Moodle inaccessible ou token invalide"},
        403: {"description": "Acces admin requis"},
    },
)
@limiter.limit("10/minute")
async def moodle_health(
    request: Request,
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
    service: MoodleService = Depends(get_moodle_service),
) -> MoodleHealthResponse:
    """Appelle core_webservice_get_site_info et retourne la version Moodle.

    Requiert le role admin.
    """
    info = await service.get_site_info()
    return MoodleHealthResponse(
        status="ok",
        moodle_version=info.get("release", info.get("version", "inconnu")),
        site_url=info.get("siteurl", ""),
        username=info.get("username", ""),
    )
