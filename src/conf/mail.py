"""Factory FastMail configuree depuis les settings de l'application."""

from functools import lru_cache

from fastapi_mail import ConnectionConfig, FastMail

from .settings import get_settings


@lru_cache
def get_fastmail() -> FastMail:
    """Instancie FastMail a partir de la configuration SMTP des settings (singleton)."""
    s = get_settings()
    config = ConnectionConfig(
        MAIL_USERNAME=s.MAIL_USERNAME,
        MAIL_PASSWORD=s.MAIL_PASSWORD,
        MAIL_FROM=s.MAIL_FROM,
        MAIL_FROM_NAME=s.MAIL_FROM_NAME,
        MAIL_PORT=s.MAIL_PORT,
        MAIL_SERVER=s.MAIL_SERVER,
        MAIL_STARTTLS=s.MAIL_STARTTLS,
        MAIL_SSL_TLS=s.MAIL_SSL_TLS,
        SUPPRESS_SEND=s.MAIL_SUPPRESS_SEND,
        USE_CREDENTIALS=bool(s.MAIL_USERNAME),
    )
    return FastMail(config)
