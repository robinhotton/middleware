"""Utilitaires generaux de l'application."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Retourne la date/heure UTC courante en datetime naif (sans tzinfo).

    SQLite stocke les DATETIME sans timezone ; utiliser des datetimes naifs
    partout garantit la coherence des comparaisons entre les deux dialectes.
    """
    return datetime.now(UTC).replace(tzinfo=None)
