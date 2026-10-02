"""Modele et schemas lies aux emails (verification, login, reset)."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from ._example_data import _EXAMPLE_EMAIL, _EXAMPLE_PASSWORD


class EmailVerificationToken(SQLModel, table=True):
    """Token a usage unique pour la verification de l'adresse email."""

    __tablename__ = "email_verification_token"
    id: int | None = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(foreign_key="user.id")
    token: str = SQLField(index=True, unique=True)
    expires_at: datetime
    used: bool = SQLField(default=False)


class _EmailRequest(BaseModel):
    """Base avec le champ email commun aux requetes d'authentification."""

    email: EmailStr = Field(
        description="Adresse email du compte",
        examples=[_EXAMPLE_EMAIL],
    )


class LoginRequest(_EmailRequest):
    """Schema de requete pour le login."""

    password: str = Field(
        max_length=72,
        description="Mot de passe du compte",
        examples=[_EXAMPLE_PASSWORD],
    )


class ResetPasswordRequest(_EmailRequest):
    """Schema de requete pour la reinitialisation du mot de passe."""
