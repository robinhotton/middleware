"""Schemas de reponse generiques de l'application."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

ItemT = TypeVar("ItemT")


class PaginatedResponse(BaseModel, Generic[ItemT]):
    """Schema de reponse paginee generique."""

    total: int = Field(description="Nombre total d'elements", examples=[42])
    skip: int = Field(description="Nombre d'elements ignores", examples=[0])
    limit: int = Field(description="Nombre maximum d'elements retournes", examples=[10])
    items: list[ItemT] = Field(description="Elements de la page courante")


class MessageResponse(BaseModel):
    """Schema de reponse generique contenant un message."""

    message: str = Field(
        description="Message de confirmation",
        examples=["Operation effectuee avec succes."],
    )


class HealthResponse(BaseModel):
    """Schema de reponse pour l'endpoint de sante."""

    status: Literal["ok"] = Field(
        default="ok",
        description="Statut de l'API (toujours 'ok')",
        examples=["ok"],
    )
