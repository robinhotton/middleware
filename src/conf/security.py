"""Utilitaires de securite : hachage de mots de passe et gestion JWT."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt

from .settings import get_settings


def hash_password(plain: str) -> str:
    """Hache un mot de passe en clair avec bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# Hash pre-calcule une seule fois au demarrage pour les comparaisons factices (CWE-208).
# Permet d'egaliser le temps de reponse entre email inconnu et mot de passe incorrect.
DUMMY_HASH: str = bcrypt.hashpw(b"dummy-timing-parity", bcrypt.gensalt(12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verifie un mot de passe en clair contre son hash bcrypt."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


async def async_hash_password(plain: str) -> str:
    """Hache un mot de passe dans un executor pour ne pas bloquer l'event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, hash_password, plain)


async def async_verify_password(plain: str, hashed: str) -> bool:
    """Verifie un mot de passe dans un executor pour ne pas bloquer l'event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, verify_password, plain, hashed)


def create_access_token(data: dict) -> str:
    """Cree un token JWT signe avec la cle privee RSA/EC."""
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    to_encode.update({"exp": expire, "jti": str(uuid4())})
    return jwt.encode(
        to_encode, settings.JWT_PRIVATE_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    """Decode et valide un token JWT avec la cle publique RSA/EC.

    Leve jwt.PyJWTError en cas d'echec.
    """
    settings = get_settings()
    return jwt.decode(
        token, settings.JWT_PUBLIC_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
