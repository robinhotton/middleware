"""Composants partages entre les packages auth et api."""

from .base import BaseRepository
from .common import HealthResponse, MessageResponse, PaginatedResponse

__all__ = [
    "BaseRepository",
    "PaginatedResponse",
    "MessageResponse",
    "HealthResponse",
]
