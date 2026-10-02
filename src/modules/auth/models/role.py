"""Modele et schemas de donnees pour les roles."""

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from .user_role_link import UserRoleLink

if TYPE_CHECKING:
    from .user import User, UserReadMinimal


class RoleName(StrEnum):
    """Roles predefinis crees au seed — source de verite pour les noms de roles."""

    ADMIN = "admin"
    USER = "user"


class Role(SQLModel, table=True):
    """Modele de table Role en base de donnees."""

    id: int | None = SQLField(default=None, primary_key=True)
    # str en colonne : SQLite/asyncpg ne gere pas StrEnum comme type natif
    name: str = SQLField(unique=True, description="Nom du role")
    description: str | None = SQLField(default=None, max_length=255)

    users: list["User"] = Relationship(
        back_populates="roles",
        link_model=UserRoleLink,
        sa_relationship_kwargs={"lazy": "raise"},
    )


class RoleReadMinimal(BaseModel):
    """Schema de reponse API minimal (pour imbrication dans UserRead)."""

    id: int = Field(description="Identifiant unique du role", examples=[1])
    name: RoleName = Field(description="Nom du role", examples=[RoleName.ADMIN])


class RoleRead(BaseModel):
    """Schema de reponse API complet."""

    id: int
    name: RoleName
    description: str | None = None
    users: list["UserReadMinimal"] = []
