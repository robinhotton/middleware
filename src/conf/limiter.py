"""Limiteur de debit (rate limiting) pour les endpoints publics sensibles."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from .settings import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.REDIS_URL if _settings.REDIS_URL else None,
)
