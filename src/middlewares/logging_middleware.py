"""Middleware de logging des requetes HTTP."""

import logging
import time
from collections.abc import Awaitable, Callable

import jwt
from fastapi import Request, Response

from ..conf.security import decode_access_token

logger = logging.getLogger(__name__)


def _anonymise_ip(ip: str | None) -> str:
    """Anonymise l'adresse IP pour conformite RGPD.

    IPv4 : masque le dernier octet (192.168.1.42 → 192.168.1.0)
    IPv6 : conserve les 4 premiers groupes (64 bits reseau)
    """
    if not ip:
        return "inconnu"
    if ":" in ip:
        groupes = ip.split(":")
        return ":".join(groupes[:4]) + "::"
    parties = ip.split(".")
    if len(parties) == 4:
        return f"{parties[0]}.{parties[1]}.{parties[2]}.0"
    return ip


def _get_client_ip(request: Request) -> str:
    """Retourne l'IP anonymisee du client (X-Forwarded-For ou request.client)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    elif request.client:
        ip = request.client.host
    else:
        ip = None
    return _anonymise_ip(ip)


def _get_user_id(request: Request) -> str:
    """Extrait l'identifiant utilisateur du token JWT si present et valide."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return "non connecte"
    try:
        payload = decode_access_token(auth[7:])
        return str(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return "non connecte"


_SILENT_PATHS = {"/health"}


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Logue methode, path, status, duree, utilisateur et IP de chaque requete.

    Les chemins dans _SILENT_PATHS (ex. /health) sont ignores pour eviter le bruit
    des sondes Docker/orchestrateurs.
    """
    if request.url.path in _SILENT_PATHS:
        return await call_next(request)
    start = time.perf_counter()
    user_id = _get_user_id(request)
    ip = _get_client_ip(request)
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "%s %s — %s (%dms) | user=%s | ip=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        user_id,
        ip,
    )
    return response
