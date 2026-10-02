"""Modele et schemas lies au reset de mot de passe."""

from datetime import datetime

from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from ._example_data import _EXAMPLE_PASSWORD, _EXAMPLE_TOKEN
from .user import PasswordStr


class PasswordResetToken(SQLModel, table=True):
    """Token a usage unique pour la reinitialisation du mot de passe."""

    __tablename__ = "password_reset_token"
    id: int | None = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(foreign_key="user.id")
    token: str = SQLField(index=True, unique=True)
    expires_at: datetime
    used: bool = SQLField(default=False)


class TokenResponse(BaseModel):
    """Schema de reponse contenant le token JWT."""

    access_token: str = Field(
        description="Token JWT Bearer a inclure dans le header Authorization",
        examples=[_EXAMPLE_TOKEN],
    )
    token_type: str = Field(
        description="Type de token (toujours 'bearer')",
        examples=["bearer"],
    )


class TokenRequest(BaseModel):
    """Schema de requete contenant un token recu par email."""

    token: str = Field(
        description="Token recu par email",
        examples=[_EXAMPLE_TOKEN],
    )


class ConfirmResetRequest(TokenRequest):
    """Schema de requete pour la confirmation de reinitialisation du mot de passe."""

    new_password: PasswordStr = Field(
        description="Nouveau mot de passe (min 12 cars, maj+min+chiffre+special)",
        examples=[_EXAMPLE_PASSWORD],
    )
