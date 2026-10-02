"""Routes du domaine proactivite."""

from fastapi import APIRouter

from .proactivity_routes import router

proactivity_router = APIRouter()
proactivity_router.include_router(router, prefix="/proactivity", tags=["proactivity"])

__all__ = ["proactivity_router"]
