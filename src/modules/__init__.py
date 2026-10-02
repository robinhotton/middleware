"""Package modules — domaines metier de l'application."""

from fastapi import FastAPI

from .auth.routes import auth_router
from .health_routes import health_router
from .llm.routes import llm_router
from .moodle.routes import moodle_router
from .proactivity.routes import proactivity_router


def register_routers(app: FastAPI, prefix: str) -> None:
    """Enregistre tous les routers sur l'application FastAPI."""
    app.include_router(health_router)
    app.include_router(auth_router, prefix=prefix)
    app.include_router(moodle_router, prefix=prefix)
    app.include_router(llm_router, prefix=prefix)
    app.include_router(proactivity_router, prefix=prefix)
