"""Couche d'acces aux donnees pour les roles (lecture seule)."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from ...shared import BaseRepository
from ..models import Role


class RoleRepository(BaseRepository[Role]):
    """Repository pour les operations de lecture sur la table Role."""

    model = Role

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_all(self, skip: int = 0, limit: int = 20) -> list[Role]:  # type: ignore[override]
        """Recupere une page de roles (sans les utilisateurs)."""
        result = await self.session.execute(select(Role).offset(skip).limit(limit))
        return result.scalars().all()

    async def get_by_id_with_users(self, role_id: int) -> Role | None:
        """Recupere un role par son identifiant avec ses utilisateurs charges."""
        result = await self.session.execute(
            select(Role)
            .where(Role.id == role_id)
            .options(selectinload(Role.users))  # type: ignore[arg-type]
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Role | None:
        """Recupere un role par son nom."""
        result = await self.session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()
