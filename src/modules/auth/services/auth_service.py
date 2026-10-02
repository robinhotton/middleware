"""Couche de logique metier pour l'authentification."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from ....conf import (
    DUMMY_HASH,
    async_hash_password,
    async_verify_password,
    create_access_token,
    get_settings,
    utcnow,
)
from ....exceptions import (
    BadRequestException,
    ConflictException,
    IntegrityError,
    NotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
)
from ...shared.common import MessageResponse
from ..models import (
    EmailVerificationToken,
    PasswordResetToken,
    RoleName,
    TokenResponse,
    User,
    UserPost,
)
from ..repositories import (
    EmailVerificationTokenRepository,
    ResetTokenRepository,
    RevokedTokenRepository,
    RoleRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Service metier pour l'authentification par JWT."""

    def __init__(
        self,
        repository: UserRepository,
        role_repository: RoleRepository,
        reset_token_repository: ResetTokenRepository,
        email_verification_token_repository: EmailVerificationTokenRepository,
        revoked_token_repository: RevokedTokenRepository,
    ):
        self.repository = repository
        self.role_repository = role_repository
        self.reset_token_repository = reset_token_repository
        self.email_verification_token_repository = email_verification_token_repository
        self.revoked_token_repository = revoked_token_repository

    async def login(self, email: str, password: str) -> TokenResponse:
        """Authentifie un utilisateur et retourne un token JWT.

        Blocage progressif anti brute-force (seuil/paliers dans Settings) :
          FAILED_LOGIN_THRESHOLD echecs consecutifs declenchent un cycle.
          La duree augmente a chaque cycle selon LOCKOUT_DURATIONS_MINUTES.
          Au-dela du dernier palier : blocage definitif.
        Tous les compteurs se reinitalisent apres une connexion reussie.

        Args:
            email: Adresse email du compte.
            password: Mot de passe en clair.

        Returns:
            TokenResponse avec access_token et token_type.

        Raises:
            UnauthorizedException: Identifiants invalides ou compte desactive.
            TooManyRequestsException: Compte temporairement ou definitivement bloque.
        """
        settings = get_settings()
        lockout_durations = [
            timedelta(minutes=m) for m in settings.LOCKOUT_DURATIONS_MINUTES
        ]

        user = await self.repository.get_by_email(email)
        if not user:
            # Appel factice pour egaliser le temps de reponse (CWE-208 timing attack)
            await async_verify_password(password, DUMMY_HASH)
            raise UnauthorizedException("Invalid email or password")

        now = utcnow()

        if not user.is_active:
            logger.warning("Login refuse — compte desactive : user_id=%s", user.id)
            raise UnauthorizedException("Invalid email or password")

        # Blocage definitif : le nombre de cycles depasse les paliers temporaires
        if user.lockout_count > len(lockout_durations):
            logger.warning(
                "Login refuse — compte definitivement bloque : user_id=%s", user.id
            )
            raise TooManyRequestsException(
                "Compte bloque definitivement. "
                "Contactez l'administrateur ou reinitializez votre mot de passe."
            )

        # Blocage temporaire en cours
        if user.locked_until and user.locked_until > now:
            minutes_left = max(
                1, int((user.locked_until - now).total_seconds() / 60) + 1
            )
            logger.warning(
                "Login refuse — compte bloque : user_id=%s (%s min restantes)",
                user.id,
                minutes_left,
            )
            raise TooManyRequestsException(
                f"Compte bloque suite a trop de tentatives. "
                f"Reessayez dans {minutes_left} minute(s)."
            )

        # Mot de passe incorrect → incrementer le compteur
        if not await async_verify_password(password, user.password_hash):
            # Verrou precedent expire : on repart de 0 sur failed_login_attempts
            base = (
                0
                if (user.locked_until and user.locked_until <= now)
                else user.failed_login_attempts
            )
            attempts = base + 1
            update: dict = {"failed_login_attempts": attempts, "locked_until": None}
            if attempts >= settings.FAILED_LOGIN_THRESHOLD:
                new_lockout_count = user.lockout_count + 1
                update["lockout_count"] = new_lockout_count
                update["failed_login_attempts"] = 0
                if new_lockout_count <= len(lockout_durations):
                    duration = lockout_durations[new_lockout_count - 1]
                    update["locked_until"] = now + duration
                    logger.warning(
                        "Compte bloque — user_id=%s cycle=%s duree=%smin",
                        user.id,
                        new_lockout_count,
                        int(duration.total_seconds() // 60),
                    )
                else:
                    logger.warning(
                        "Compte bloque definitivement — user_id=%s cycles=%s",
                        user.id,
                        new_lockout_count,
                    )
            else:
                logger.warning(
                    "Echec de connexion — user_id=%s tentative=%s/%s",
                    user.id,
                    attempts,
                    settings.FAILED_LOGIN_THRESHOLD,
                )
            await self.repository.update(user, update)
            raise UnauthorizedException("Invalid email or password")

        # Succes : reinitialiser tous les compteurs
        if (
            user.failed_login_attempts > 0
            or user.locked_until
            or user.lockout_count > 0
        ):
            await self.repository.update(
                user,
                {
                    "failed_login_attempts": 0,
                    "locked_until": None,
                    "lockout_count": 0,
                },
            )

        logger.info("Login reussi — user_id=%s", user.id)
        token = create_access_token({"sub": str(user.id)})
        return TokenResponse(access_token=token, token_type="bearer")  # nosec B106

    async def register(self, user_data: UserPost) -> tuple[User, str]:
        """Inscrit un nouvel utilisateur (inactif jusqu'a verification de l'email).

        Args:
            user_data: Schema de creation (email, mot de passe).

        Returns:
            Tuple (user, token_str) avec l'utilisateur cree et le token de verification.

        Raises:
            ConflictException: Un utilisateur avec cet email existe deja.
        """
        settings = get_settings()
        user = User(
            email=user_data.email,
            password_hash=await async_hash_password(user_data.password),
            pseudo=user_data.pseudo,
            is_active=False,
        )
        try:
            user = await self.repository.create(user)
        except IntegrityError as exc:
            raise ConflictException("A user with this email already exists") from exc
        default_role = await self.role_repository.get_by_name(RoleName.USER)
        if default_role:
            await self.repository.add_role(user, default_role)
        token_str = secrets.token_urlsafe(settings.TOKEN_BYTES)
        # UTC naif : coherence SQLite/PostgreSQL (cf. utcnow())
        expires_at = utcnow() + timedelta(
            minutes=settings.EMAIL_VERIFICATION_EXPIRY_MINUTES
        )
        verification_token = EmailVerificationToken(
            user_id=user.id,
            token=token_str,
            expires_at=expires_at,
        )
        await self.email_verification_token_repository.create(verification_token)
        logger.info("Inscription — user_id=%s", user.id)
        return user, token_str

    async def verify_email(self, token_str: str) -> MessageResponse:
        """Valide le token et active le compte utilisateur.

        Args:
            token_str: Token de verification recu par email.

        Returns:
            MessageResponse confirmant la verification.

        Raises:
            NotFoundException: Token introuvable.
            BadRequestException: Token invalide ou expire.
        """
        token = await self.email_verification_token_repository.get_by_token(token_str)
        if not token:
            raise NotFoundException("Token de verification introuvable")
        now = utcnow()
        if token.used or token.expires_at < now:
            raise BadRequestException("Token invalide ou expire")
        user = await self.repository.get_by_id(token.user_id)
        if not user:
            raise NotFoundException("User not found")
        await self.repository.update(user, {"is_active": True})
        await self.email_verification_token_repository.mark_used(token)
        return MessageResponse(message="Email verified successfully.")

    async def reset_password(self, email: str) -> tuple[User | None, str | None]:
        """Genere un token de reinitialisation et retourne (user, token).

        Retourne (None, None) si l'email est inconnu — ne pas exposer cette information
        a l'appelant pour eviter l'enumeration d'emails.

        Args:
            email: Adresse email du compte a reinitialiser.

        Returns:
            Tuple (user, token_str) ou (None, None) si l'email est inconnu.
        """
        settings = get_settings()
        user = await self.repository.get_by_email(email)
        if not user:
            return None, None
        await self.reset_token_repository.invalidate_for_user(user.id)
        token_str = secrets.token_urlsafe(settings.TOKEN_BYTES)
        expires_at = utcnow() + timedelta(
            minutes=settings.RESET_TOKEN_EXPIRY_MINUTES
        )
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token_str,
            expires_at=expires_at,
        )
        await self.reset_token_repository.create(reset_token)
        return user, token_str

    async def confirm_reset(self, token_str: str, new_password: str) -> MessageResponse:
        """Valide le token et applique le nouveau mot de passe.

        Args:
            token_str: Token de reinitialisation recu par email.
            new_password: Nouveau mot de passe en clair.

        Returns:
            MessageResponse confirmant la reinitialisation.

        Raises:
            NotFoundException: Token introuvable.
            BadRequestException: Token invalide ou expire.
        """
        reset_token = await self.reset_token_repository.get_by_token(token_str)
        if not reset_token:
            raise NotFoundException("Token de reinitialisation introuvable")
        now = utcnow()
        if reset_token.used or reset_token.expires_at < now:
            raise BadRequestException("Token invalide ou expire")
        user = await self.repository.get_by_id(reset_token.user_id)
        if not user:
            raise NotFoundException("User not found")
        if not user.is_active:
            raise BadRequestException("Account is deactivated")
        await self.repository.update(
            user,
            {
                "password_hash": await async_hash_password(new_password),
                "failed_login_attempts": 0,
                "locked_until": None,
                "lockout_count": 0,
            },
        )
        await self.reset_token_repository.mark_used(reset_token)
        logger.info("Mot de passe reinitialise — user_id=%s", user.id)
        return MessageResponse(message="Password reset successfully.")

    async def logout(self, payload: dict[str, Any]) -> MessageResponse:
        """Revoque le JTI du token courant dans la blocklist.

        Args:
            payload: Payload JWT decode contenant 'jti' et 'exp'.

        Returns:
            MessageResponse confirmant la deconnexion.
        """
        jti = payload.get("jti")
        if jti:
            expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC).replace(
                tzinfo=None
            )
            await self.revoked_token_repository.revoke(jti, expires_at)
        return MessageResponse(message="Logged out successfully.")
