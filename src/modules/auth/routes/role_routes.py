"""Endpoints REST pour la consultation des roles."""

from fastapi import APIRouter, Depends, Query

from ...shared.common import PaginatedResponse
from ..dependencies import get_role_service, require_role
from ..models import RoleName, RoleRead, RoleReadMinimal, User
from ..services import RoleService
from ._responses import R401, R403, R404

# --- Role endpoints ---

router = APIRouter()


@router.get(
    "/",
    summary="Lister les roles",
    response_model=PaginatedResponse[RoleReadMinimal],
    responses={**R401, **R403},
)
async def get_all_roles(
    skip: int = Query(0, ge=0, description="Nombre d'elements a ignorer"),
    limit: int = Query(
        20, ge=1, le=100, description="Nombre maximum d'elements a retourner"
    ),
    service: RoleService = Depends(get_role_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
) -> PaginatedResponse[RoleReadMinimal]:
    """Recupere une page de roles. Requiert le role admin."""
    total = await service.count_roles()
    items = await service.get_all_roles(skip=skip, limit=limit)
    return PaginatedResponse(total=total, skip=skip, limit=limit, items=items)


@router.get(
    "/{role_id}",
    summary="Recuperer un role",
    response_model=RoleRead,
    responses={**R401, **R403, **R404},
)
async def get_role_by_id(
    role_id: int,
    service: RoleService = Depends(get_role_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
) -> RoleRead:
    """Recupere un role par son identifiant. Requiert le role admin."""
    return await service.get_role_by_id(role_id)
