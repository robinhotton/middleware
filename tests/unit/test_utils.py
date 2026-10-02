"""Tests unitaires pour les utilitaires."""

import time
from datetime import UTC, datetime

from src.conf.utils import utcnow


def test_utcnow_returns_naive_datetime():
    """Verifie que utcnow() retourne un datetime naif (tzinfo=None)."""
    result = utcnow()
    assert isinstance(result, datetime)
    assert result.tzinfo is None


def test_utcnow_is_approximately_utc():
    """Verifie que la valeur est coherente avec l'heure UTC."""
    before = datetime.now(UTC).replace(tzinfo=None)
    time.sleep(0.001)
    result = utcnow()
    time.sleep(0.001)
    after = datetime.now(UTC).replace(tzinfo=None)
    assert before <= result <= after
