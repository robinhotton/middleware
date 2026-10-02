"""Aggregation des routes du package auth."""

from fastapi import APIRouter

from .auth_routes import router as _auth
from .role_routes import router as _roles
from .user_routes import router as _users

auth_router = APIRouter()
auth_router.include_router(_auth, prefix="/auth", tags=["auth"])
auth_router.include_router(_users, prefix="/users", tags=["users"])
auth_router.include_router(_roles, prefix="/roles", tags=["roles"])

__all__ = ["auth_router"]
