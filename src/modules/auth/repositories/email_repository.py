"""Couche d'acces aux donnees pour les tokens de verification d'email."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ...shared import BaseRepository
from ..models import EmailVerificationToken


class EmailVerificationTokenRepository(BaseRepository[EmailVerificationToken]):
    """Repository pour les operations CRUD sur la table EmailVerificationToken."""

    model = EmailVerificationToken

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def create(self, token: EmailVerificationToken) -> EmailVerificationToken:
        """Persiste un token en base de donnees."""
        self.session.add(token)
        await self.session.commit()
        await self.session.refresh(token)
        return token

    async def get_by_token(self, token: str) -> EmailVerificationToken | None:
        """Recupere un token par sa valeur."""
        result = await self.session.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.token == token)
        )
        return result.scalar_one_or_none()

    async def mark_used(self, token: EmailVerificationToken) -> None:
        """Marque un token comme utilise."""
        token.used = True
        self.session.add(token)
        await self.session.commit()
