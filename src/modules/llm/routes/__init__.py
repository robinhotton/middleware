"""Aggregation des routes du package llm."""

from fastapi import APIRouter

from .llm_routes import router as _llm

llm_router = APIRouter()
llm_router.include_router(_llm, prefix="/llm", tags=["llm"])

__all__ = ["llm_router"]
