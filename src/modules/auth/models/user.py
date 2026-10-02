"""Modele et schemas de donnees pour les utilisateurs."""

import re
from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from .user_role_link import UserRoleLink

if TYPE_CHECKING:
    from .role import Role, RoleReadMinimal


from ._example_data import _EXAMPLE_EMAIL, _EXAMPLE_PASSWORD


def _validate_password_strength(v: str) -> str:
    """Verifie qu'un mot de passe respecte les regles de complexite."""
    errors = []
    if not re.search(r"[A-Z]", v):
        errors.append("une majuscule")
    if not re.search(r"[a-z]", v):
        errors.append("une minuscule")
    if not re.search(r"\d", v):
        errors.append("un chiffre")
    if not re.search(r"[^a-zA-Z0-9]", v):
        errors.append("un caractere special")
    if errors:
        raise ValueError(
            f"Le mot de passe doit contenir au moins : {', '.join(errors)}"
        )
    return v


# 72 chars max : limite bcrypt (les octets au-dela sont silencieusement ignores)
PasswordStr = Annotated[
    str,
    Field(min_length=12, max_length=72),
    AfterValidator(_validate_password_strength),
]


# ---------------------------------------------------------------------------
# Modele de table
# ---------------------------------------------------------------------------


class User(SQLModel, table=True):
    """Modele de table User en base de donnees (champs auth uniquement).

    email est defini en str car SQLAlchemy ne supporte pas EmailStr.
    La validation email se fait au niveau des schemas (UserPost, UserPatch).
    """

    id: int | None = SQLField(default=None, primary_key=True)
    email: str = SQLField(unique=True)
    password_hash: str = SQLField(default="")
    pseudo: str = SQLField(default="")
    is_active: bool = True
    failed_login_attempts: int = SQLField(default=0)
    locked_until: datetime | None = SQLField(default=None)
    lockout_count: int = SQLField(default=0)

    roles: list["Role"] = Relationship(
        back_populates="users",
        link_model=UserRoleLink,
        sa_relationship_kwargs={"lazy": "selectin"},
    )


# ---------------------------------------------------------------------------
# Schemas d'ecriture
# ---------------------------------------------------------------------------


class _UserWriteBase(BaseModel):
    """Champs communs aux schemas d'ecriture utilisateur."""

    email: EmailStr = Field(
        description="Adresse email (unique)",
        examples=[_EXAMPLE_EMAIL],
    )
    pseudo: str = Field(default="", max_length=50, description="Nom d'affichage")


class UserPost(_UserWriteBase):
    """Schema de creation d'un utilisateur."""

    password: PasswordStr = Field(examples=[_EXAMPLE_PASSWORD])


class UserSelfPatch(BaseModel):
    """Schema de mise a jour par l'utilisateur lui-meme."""

    pseudo: str | None = Field(
        default=None, max_length=50, description="Nom d'affichage"
    )


class UserAdminPatch(BaseModel):
    """Schema de mise a jour reservee aux admins (statut du compte)."""

    is_active: bool | None = Field(default=None, description="Desactive le compte")
    locked_until: datetime | None = Field(
        default=None, description="Date de fin de blocage (None = debloquer)"
    )
    lockout_count: int | None = Field(
        default=None, description="Nombre de cycles de blocage (0 = reinitialiser)"
    )


# ---------------------------------------------------------------------------
# Schemas de lecture
# ---------------------------------------------------------------------------


class UserReadMinimal(BaseModel):
    """Schema de reponse API minimal (pour imbrication dans RoleRead)."""

    id: int = Field(description="Identifiant unique", examples=[1])
    email: str = Field(description="Adresse email", examples=[_EXAMPLE_EMAIL])
    pseudo: str = Field(default="", description="Nom d'affichage")


class UserRead(UserReadMinimal):
    """Schema de reponse API utilisateur."""

    is_active: bool = Field(description="Compte actif")
    locked_until: datetime | None = Field(
        default=None, description="Date de fin de blocage (None = non bloque)"
    )
    lockout_count: int = Field(default=0, description="Nombre de cycles de blocage")
    roles: list["RoleReadMinimal"] = Field(
        default=[], description="Roles attribues a l'utilisateur"
    )
