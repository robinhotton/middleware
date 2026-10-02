"""Couche d'acces aux donnees pour les utilisateurs."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ...shared import BaseRepository
from ..models import Role, User


class UserRepository(BaseRepository[User]):
    """Repository pour les operations CRUD sur la table User."""

    model = User

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_all(self, skip: int = 0, limit: int = 20) -> list[User]:  # type: ignore[override]
        """Recupere une page d'utilisateurs."""
        result = await self.session.execute(select(User).offset(skip).limit(limit))
        return result.scalars().all()

    async def get_by_email(self, email: str) -> User | None:
        """Recupere un utilisateur par son email."""
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        """Cree un utilisateur en base de donnees."""
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update(self, entity: User, update_data: dict) -> User:  # type: ignore[override]
        """Met a jour les champs fournis d'un utilisateur."""
        for key, value in update_data.items():
            setattr(entity, key, value)
        self.session.add(entity)
        await self.session.commit()
        return entity

    async def add_role(self, user: User, role: Role) -> User:
        """Ajoute un role a un utilisateur."""
        user.roles.append(role)
        self.session.add(user)
        await self.session.commit()
        return user

    async def remove_role(self, user: User, role: Role) -> User:
        """Retire un role d'un utilisateur."""
        user.roles.remove(role)
        self.session.add(user)
        await self.session.commit()
        return user
