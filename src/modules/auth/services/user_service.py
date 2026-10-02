"""Couche de logique metier pour les utilisateurs."""

from ....exceptions import ConflictException, NotFoundException
from ...shared import MessageResponse
from ..models import User, UserAdminPatch, UserSelfPatch
from ..repositories import RoleRepository, UserRepository


class UserService:
    """Service metier pour les operations sur les utilisateurs."""

    def __init__(self, repository: UserRepository, role_repository: RoleRepository):
        self.repository = repository
        self.role_repository = role_repository

    async def get_all_users(self, skip: int = 0, limit: int = 20) -> list[User]:
        """Recupere une page d'utilisateurs."""
        return await self.repository.get_all(skip=skip, limit=limit)

    async def get_user_by_id(self, user_id: int) -> User:
        """Recupere un utilisateur ou leve NotFoundException."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        return user

    async def patch_user(self, user_id: int, update_data: UserSelfPatch) -> User:
        """Met a jour le pseudo d'un utilisateur ou leve NotFoundException."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        data = update_data.model_dump(exclude_unset=True)
        return await self.repository.update(user, data)

    async def patch_user_admin(self, user_id: int, update_data: UserAdminPatch) -> User:
        """Met a jour le statut d'un utilisateur (admin) ou leve NotFoundException."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        data = update_data.model_dump(exclude_unset=True)
        return await self.repository.update(user, data)

    async def count_users(self) -> int:
        """Retourne le nombre total d'utilisateurs."""
        return await self.repository.count()

    async def delete_user_by_id(self, user_id: int) -> MessageResponse:
        """Desactive un utilisateur (soft delete) ou leve NotFoundException."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        await self.repository.update(user, {"is_active": False})
        return MessageResponse(message="User deactivated successfully")

    async def assign_role_to_user(self, user_id: int, role_id: int) -> User:
        """Assigne un role a un utilisateur."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        role = await self.role_repository.get_by_id(role_id)
        if not role:
            raise NotFoundException(f"Role {role_id} not found")
        if role in user.roles:
            raise ConflictException("User already has this role")
        return await self.repository.add_role(user, role)

    async def remove_role_from_user(self, user_id: int, role_id: int) -> User:
        """Retire un role d'un utilisateur."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        role = await self.role_repository.get_by_id(role_id)
        if not role:
            raise NotFoundException(f"Role {role_id} not found")
        if role not in user.roles:
            raise NotFoundException("User does not have this role")
        return await self.repository.remove_role(user, role)
