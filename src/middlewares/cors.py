"""Configuration du middleware CORS."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..conf import Settings


def setup_cors(app: FastAPI, settings: Settings) -> None:
    """Enregistre le middleware CORS avec la configuration fournie."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
