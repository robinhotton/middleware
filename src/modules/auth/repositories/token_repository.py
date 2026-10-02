"""Couche d'acces aux donnees pour les tokens (reset, blocklist JWT)."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ....conf import utcnow
from ...shared import BaseRepository
from ..models import PasswordResetToken, RevokedToken


class ResetTokenRepository(BaseRepository[PasswordResetToken]):
    """Repository pour les operations CRUD sur la table PasswordResetToken."""

    model = PasswordResetToken

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def create(self, token: PasswordResetToken) -> PasswordResetToken:
        """Persiste un token en base de donnees."""
        self.session.add(token)
        await self.session.commit()
        await self.session.refresh(token)
        return token

    async def get_by_token(self, token: str) -> PasswordResetToken | None:
        """Recupere un token par sa valeur."""
        result = await self.session.execute(
            select(PasswordResetToken).where(PasswordResetToken.token == token)
        )
        return result.scalar_one_or_none()

    async def invalidate_for_user(self, user_id: int) -> None:
        """Invalide en masse tous les tokens actifs de l'utilisateur."""
        await self.session.execute(
            sa_update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used.is_(False),
            )
            .values(used=True)
        )
        await self.session.commit()

    async def mark_used(self, token: PasswordResetToken) -> None:
        """Marque un token comme utilise."""
        token.used = True
        self.session.add(token)
        await self.session.commit()


class RevokedTokenRepository(BaseRepository[RevokedToken]):
    """Repository pour la blocklist JWT (JTI revoques)."""

    model = RevokedToken

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def is_revoked(self, jti: str) -> bool:
        """Retourne True si le JTI a ete revoque."""
        result = await self.session.execute(
            select(RevokedToken).where(RevokedToken.jti == jti)
        )
        return result.scalar_one_or_none() is not None

    async def revoke(self, jti: str, expires_at: datetime) -> None:
        """Ajoute un JTI a la blocklist."""
        token = RevokedToken(jti=jti, expires_at=expires_at)
        self.session.add(token)
        await self.session.commit()

    async def cleanup_expired(self) -> None:
        """Supprime les entrees expirees de la blocklist (bulk DELETE)."""
        now = utcnow()
        await self.session.execute(
            delete(RevokedToken).where(RevokedToken.expires_at < now)
        )
        await self.session.commit()
