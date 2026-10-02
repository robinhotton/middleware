"""Package auth — API publique du module d'authentification."""

from .dependencies import (
    get_current_user,
    has_role,
    require_role,
    verify_moodle_webhook,
)
from .models import Role, RoleName, User
from .routes import auth_router

__all__ = [
    "User",
    "Role",
    "RoleName",
    "auth_router",
    "get_current_user",
    "require_role",
    "has_role",
    "verify_moodle_webhook",
]
