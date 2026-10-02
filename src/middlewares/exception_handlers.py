"""Gestionnaires d'exceptions pour l'application FastAPI."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from ..exceptions import AppException

logger = logging.getLogger(__name__)

_BODY_LOG_MAX_CHARS = 4000


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Retourne une reponse JSON coherente avec les autres erreurs applicatives."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Trop de requetes. Reessayez plus tard."},
    )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Gere les exceptions applicatives et retourne une reponse JSON."""
    content: dict = {"detail": exc.detail}
    reason = getattr(exc, "reason", None)
    if reason is not None:
        content["reason"] = reason
    return JSONResponse(status_code=exc.status_code, content=content)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Masque le champ 'input' cote client mais logge le body en interne pour diagnostic.

    La reponse cliente reste sans `input` (anti-fuite). Le body brut et les erreurs
    completes (avec `input`, `ctx`) sont logges en WARNING pour diagnostiquer les
    422 qui n'ont pas d'autre trace exploitable.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, (bytes, bytearray)):
        body_preview = body.decode("utf-8", errors="replace")[:_BODY_LOG_MAX_CHARS]
    elif body is None:
        body_preview = "<empty>"
    else:
        body_preview = str(body)[:_BODY_LOG_MAX_CHARS]
    logger.warning(
        "RequestValidationError on %s %s | body=%s | errors=%s",
        request.method,
        request.url.path,
        body_preview,
        exc.errors(),
    )
    errors = [
        {
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


def register_exception_handlers(app: FastAPI) -> None:
    """Enregistre les gestionnaires d'exceptions sur l'application."""
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
