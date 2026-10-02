"""Couche de logique metier pour les roles (lecture seule)."""

from ....exceptions import NotFoundException
from ..models import Role
from ..repositories import RoleRepository


class RoleService:
    """Service metier pour les operations de lecture sur les roles."""

    def __init__(self, repository: RoleRepository):
        self.repository = repository

    async def get_all_roles(self, skip: int = 0, limit: int = 20) -> list[Role]:
        """Recupere une page de roles."""
        return await self.repository.get_all(skip=skip, limit=limit)

    async def get_role_by_id(self, role_id: int) -> Role:
        """Recupere un role avec ses utilisateurs ou leve NotFoundException."""
        role = await self.repository.get_by_id_with_users(role_id)
        if not role:
            raise NotFoundException(f"Role {role_id} not found")
        return role

    async def count_roles(self) -> int:
        """Retourne le nombre total de roles."""
        return await self.repository.count()
