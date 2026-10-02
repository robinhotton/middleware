"""Classe de base generique pour tous les repositories."""

from abc import ABC
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

T = TypeVar("T", bound=SQLModel)


class BaseRepository(ABC, Generic[T]):
    """Repository abstrait generique : CRUD de base partage par tous les repos."""

    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: int) -> T | None:
        """Recupere une entite par son identifiant."""
        return await self.session.get(self.model, entity_id)

    async def get_all(self, skip: int = 0, limit: int = 100) -> Sequence[T]:
        """Recupere une page d'entites."""
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def count(self) -> int:
        """Retourne le nombre total d'entites."""
        result = await self.session.execute(
            select(func.count()).select_from(self.model)
        )
        return result.scalar_one()

    async def save(self, entity: T) -> T:
        """Persiste une entite (add + flush)."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        """Supprime une entite de la base de donnees."""
        await self.session.delete(entity)
        await self.session.commit()

    async def update(self, entity: T, update_data: dict[str, Any]) -> T:
        """Met a jour les champs fournis d'une entite."""
        for key, value in update_data.items():
            setattr(entity, key, value)
        self.session.add(entity)
        await self.session.commit()
        return entity
