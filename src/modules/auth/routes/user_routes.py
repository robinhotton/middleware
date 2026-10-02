"""Endpoints REST pour la gestion des utilisateurs."""

from fastapi import APIRouter, Depends, Query

from ...shared import MessageResponse, PaginatedResponse
from ..dependencies import (
    get_user_service,
    require_role,
)
from ..models import RoleName, User, UserAdminPatch, UserRead, UserSelfPatch
from ..services import UserService
from ._responses import R401, R403, R404, R409, R422

# --- Users endpoints ---

router = APIRouter()


@router.get(
    "/",
    summary="Lister les utilisateurs",
    response_model=PaginatedResponse[UserRead],
    responses={**R401, **R403},
)
async def get_all_users(
    skip: int = Query(0, ge=0, description="Nombre d'elements a ignorer"),
    limit: int = Query(
        20, ge=1, le=100, description="Nombre maximum d'elements a retourner"
    ),
    service: UserService = Depends(get_user_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
) -> PaginatedResponse[UserRead]:
    """Recupere une page d'utilisateurs. Requiert le role admin."""
    total = await service.count_users()
    items = await service.get_all_users(skip=skip, limit=limit)
    return PaginatedResponse(total=total, skip=skip, limit=limit, items=items)


@router.get(
    "/{user_id}",
    summary="Recuperer un utilisateur",
    response_model=UserRead,
    responses={**R401, **R403, **R404},
)
async def get_user_by_id(
    user_id: int,
    service: UserService = Depends(get_user_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN, allow_self=True)),
) -> UserRead:
    """Recupere un utilisateur par son identifiant. Requiert self ou admin."""
    return await service.get_user_by_id(user_id)


@router.patch(
    "/{user_id}",
    summary="Mettre a jour son profil",
    response_model=UserRead,
    responses={**R401, **R403, **R404, **R422},
)
async def patch_user(
    user_id: int,
    update_user: UserSelfPatch,
    service: UserService = Depends(get_user_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN, allow_self=True)),
) -> UserRead:
    """Met a jour le pseudo. Requiert self ou admin."""
    return await service.patch_user(user_id, update_user)


@router.patch(
    "/{user_id}/admin",
    summary="Mettre a jour le statut d'un utilisateur",
    response_model=UserRead,
    responses={**R401, **R403, **R404, **R422},
)
async def patch_user_admin(
    user_id: int,
    update_user: UserAdminPatch,
    service: UserService = Depends(get_user_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
) -> UserRead:
    """Met a jour le statut du compte. Admin only."""
    return await service.patch_user_admin(user_id, update_user)


@router.delete(
    "/{user_id}",
    summary="Desactiver un utilisateur",
    response_model=MessageResponse,
    responses={**R401, **R403, **R404},
)
async def delete_user_by_id(
    user_id: int,
    service: UserService = Depends(get_user_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN, allow_self=True)),
) -> MessageResponse:
    """Desactive un utilisateur (soft delete). Requiert self ou admin."""
    return await service.delete_user_by_id(user_id)


# --- User-role assignment ---


@router.post(
    "/{user_id}/roles/{role_id}",
    summary="Assigner un role a un utilisateur",
    response_model=UserRead,
    responses={**R401, **R403, **R404, **R409},
)
async def assign_role_to_user(
    user_id: int,
    role_id: int,
    service: UserService = Depends(get_user_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
) -> UserRead:
    """Assigne un role a un utilisateur. Requiert le role admin."""
    return await service.assign_role_to_user(user_id, role_id)


@router.delete(
    "/{user_id}/roles/{role_id}",
    summary="Retirer un role d'un utilisateur",
    response_model=UserRead,
    responses={**R401, **R403, **R404},
)
async def remove_role_from_user(
    user_id: int,
    role_id: int,
    service: UserService = Depends(get_user_service),
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
) -> UserRead:
    """Retire un role d'un utilisateur. Requiert le role admin."""
    return await service.remove_role_from_user(user_id, role_id)
