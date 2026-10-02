"""Aggregation des routes du package moodle."""

from fastapi import APIRouter

from .moodle_routes import router as _moodle

moodle_router = APIRouter()
moodle_router.include_router(_moodle, prefix="/moodle")

__all__ = ["moodle_router"]
