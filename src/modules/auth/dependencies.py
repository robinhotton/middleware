"""Dependencies d'authentification et d'autorisation pour FastAPI."""

from collections.abc import Awaitable, Callable
from typing import Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ...conf import (
    Settings,
    decode_access_token,
    get_fastmail,
    get_session,
    get_settings,
)
from ...exceptions import ForbiddenException, UnauthorizedException
from .models import User
from .repositories import (
    EmailVerificationTokenRepository,
    ResetTokenRepository,
    RevokedTokenRepository,
    RoleRepository,
    UserRepository,
)
from .services import AuthService, EmailService, RoleService, UserService

security_scheme = HTTPBearer(auto_error=False)


async def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> dict:
    """Decode le token JWT Bearer et retourne le payload brut.

    Args:
        credentials: Credentials HTTP Bearer (None si header absent).

    Returns:
        Le payload JWT decode.

    Raises:
        UnauthorizedException: Token absent, invalide ou expire.
    """
    if credentials is None:
        raise UnauthorizedException("Authentication required")
    try:
        return decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise UnauthorizedException("Invalid or expired token") from exc


async def get_current_user(
    payload: dict[str, Any] = Depends(get_token_payload),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Retourne l'utilisateur courant a partir du payload JWT.

    Args:
        payload: Payload JWT decode (fourni par get_token_payload).
        session: Session de base de donnees async.

    Returns:
        L'utilisateur authentifie et actif.

    Raises:
        UnauthorizedException: Token invalide, JTI revoque, ou compte desactive.
    """
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise UnauthorizedException("Invalid or expired token") from exc
    jti = payload.get("jti")
    if jti:
        revoked_repo = RevokedTokenRepository(session)
        if await revoked_repo.is_revoked(jti):
            raise UnauthorizedException("Token has been revoked")
    user = await session.get(User, user_id)
    if not user:
        raise UnauthorizedException("User not found")
    if not user.is_active:
        raise UnauthorizedException("User account is deactivated")
    return user


def require_role(
    *role_names: str, allow_self: bool = False
) -> Callable[..., Awaitable[User]]:
    """Factory qui retourne une dependance verifiant les roles de l'utilisateur.

    Leve ForbiddenException si aucune condition n'est satisfaite.

    Args:
        *role_names: Noms des roles acceptes (au moins un suffit).
        allow_self: Si True, l'acces est aussi autorise quand l'utilisateur
            courant correspond au {user_id} du path (self-access).
            La route doit exposer un parametre de path nomme user_id.

    Returns:
        Dependance FastAPI qui retourne l'utilisateur si autorise.
    """

    async def checker(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        if allow_self:
            raw = request.path_params.get("user_id")
            if raw is not None and user.id == int(raw):
                return user
        if role_names and has_role(user, *role_names):
            return user
        raise ForbiddenException(
            f"Role {' or '.join(repr(r) for r in role_names)} required"
        )

    return checker


async def verify_moodle_webhook(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Verifie que le Bearer token correspond au MOODLE_WEBHOOK_SECRET.

    Utilise une comparaison en temps constant pour eviter les attaques timing.

    Raises:
        UnauthorizedException: Token absent ou incorrect.
    """
    import secrets as _secrets

    if credentials is None:
        raise UnauthorizedException("Authentication required")
    if not _secrets.compare_digest(
        credentials.credentials.encode(),
        settings.MOODLE_WEBHOOK_SECRET.encode(),
    ):
        raise UnauthorizedException("Invalid webhook secret")


def has_role(user: User, *role_names: str) -> bool:
    """Retourne True si l'utilisateur a au moins un des roles demandes.

    Args:
        user: L'utilisateur a verifier.
        *role_names: Noms des roles a tester.

    Returns:
        True si l'utilisateur possede au moins un des roles.
    """
    user_roles = {role.name for role in user.roles}
    return any(r in user_roles for r in role_names)


# -------------------------------------------------------------------------
# Factories de services
# -------------------------------------------------------------------------


def get_auth_service(session: AsyncSession = Depends(get_session)) -> AuthService:
    """Cree la chaine d'injection Repository -> AuthService."""
    return AuthService(
        repository=UserRepository(session=session),
        role_repository=RoleRepository(session=session),
        reset_token_repository=ResetTokenRepository(session=session),
        email_verification_token_repository=EmailVerificationTokenRepository(
            session=session
        ),
        revoked_token_repository=RevokedTokenRepository(session=session),
    )


def get_email_service(settings: Settings = Depends(get_settings)) -> EmailService:
    """Cree le service d'envoi de mails depuis la configuration."""
    return EmailService(
        mail=get_fastmail(),
        from_name=settings.MAIL_FROM_NAME,
        base_url=settings.APP_BASE_URL,
        api_prefix=settings.API_PREFIX,
    )


def get_user_service(session: AsyncSession = Depends(get_session)) -> UserService:
    """Cree la chaine d'injection Repository -> UserService."""
    return UserService(
        repository=UserRepository(session=session),
        role_repository=RoleRepository(session=session),
    )


def get_role_service(session: AsyncSession = Depends(get_session)) -> RoleService:
    """Cree la chaine d'injection Repository -> RoleService."""
    return RoleService(repository=RoleRepository(session=session))
