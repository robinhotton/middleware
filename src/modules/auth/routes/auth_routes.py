"""Endpoints REST pour l'authentification."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ....conf import limiter
from ...shared import MessageResponse
from ..dependencies import (
    get_auth_service,
    get_current_user,
    get_email_service,
    get_token_payload,
)
from ..models import (
    ConfirmResetRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenResponse,
    User,
    UserPost,
    UserRead,
)
from ..services import AuthService, EmailService
from ._responses import R400, R401, R404, R409, R422, R429

# --- Auth endpoints ---

router = APIRouter()


@router.post(
    "/login",
    summary="Se connecter",
    response_model=TokenResponse,
    responses={**R401, **R422, **R429},
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    credentials: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Authentifie un utilisateur et retourne un token JWT."""
    return await service.login(credentials.email, credentials.password)


@router.post(
    "/register",
    summary="S'inscrire",
    response_model=UserRead,
    status_code=201,
    responses={**R409, **R422, **R429},
)
@limiter.limit("10/minute")
async def register(
    request: Request,
    new_user: UserPost,
    background_tasks: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
    email_service: EmailService = Depends(get_email_service),
) -> UserRead:
    """Inscrit un nouvel utilisateur et envoie un email de verification."""
    user, token = await service.register(new_user)
    background_tasks.add_task(
        email_service.send_verification_link, user.email, token
    )
    return user


@router.get(
    "/verify-email",
    summary="Verifier l'email",
    response_model=MessageResponse,
    responses={**R400, **R404, **R429},
)
@limiter.limit("10/minute")
async def verify_email_get(
    request: Request,
    token: str,
    service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Valide le token depuis un lien email (GET). Active le compte utilisateur."""
    return await service.verify_email(token)


@router.post(
    "/reset-password",
    summary="Demander une reinitialisation de mot de passe",
    response_model=MessageResponse,
    responses={**R422, **R429},
)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    reset_data: ResetPasswordRequest,
    background_tasks: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
    email_service: EmailService = Depends(get_email_service),
) -> MessageResponse:
    """Genere un token de reinitialisation et envoie un email de confirmation. Public.

    Retourne toujours 200 meme si l'email est inconnu (evite l'enumeration d'emails).
    """
    user, token = await service.reset_password(reset_data.email)
    if user and token:
        background_tasks.add_task(
            email_service.send_reset_link, user.email, token
        )
    return MessageResponse(message="A confirmation email has been sent.")


@router.post(
    "/confirm-reset",
    summary="Confirmer la reinitialisation de mot de passe",
    response_model=MessageResponse,
    responses={**R400, **R404, **R422, **R429},
)
@limiter.limit("10/minute")
async def confirm_reset(
    request: Request,
    payload: ConfirmResetRequest,
    service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Valide le token et applique le nouveau mot de passe. Public."""
    return await service.confirm_reset(payload.token, payload.new_password)


@router.post(
    "/logout",
    summary="Se deconnecter",
    response_model=MessageResponse,
    responses={**R401},
)
async def logout(
    _current_user: User = Depends(get_current_user),
    payload: dict[str, Any] = Depends(get_token_payload),
    service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Revoque le token JWT courant (JTI blocklist). Requiert un token valide."""
    return await service.logout(payload)
