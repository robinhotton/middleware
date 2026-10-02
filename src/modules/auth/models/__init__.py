"""Modeles et schemas d'authentification."""

from .email import EmailVerificationToken, LoginRequest, ResetPasswordRequest
from .revoked_token import RevokedToken
from .role import Role, RoleName, RoleRead, RoleReadMinimal
from .token import ConfirmResetRequest, PasswordResetToken, TokenRequest, TokenResponse
from .user import (
    User,
    UserAdminPatch,
    UserPost,
    UserRead,
    UserReadMinimal,
    UserSelfPatch,
)
from .user_role_link import UserRoleLink

# Reconstruction des modeles pour resoudre les references circulaires
UserRead.model_rebuild()
RoleRead.model_rebuild()

__all__ = [
    "UserRoleLink",
    "User",
    "UserPost",
    "UserSelfPatch",
    "UserAdminPatch",
    "UserRead",
    "UserReadMinimal",
    "Role",
    "RoleName",
    "RoleRead",
    "RoleReadMinimal",
    "EmailVerificationToken",
    "PasswordResetToken",
    "RevokedToken",
    "LoginRequest",
    "TokenResponse",
    "ResetPasswordRequest",
    "ConfirmResetRequest",
    "TokenRequest",
]
