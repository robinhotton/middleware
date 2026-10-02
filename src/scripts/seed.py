"""Donnees initiales idempotentes (roles par defaut + administrateur)."""

from sqlmodel import select

from ..conf import async_hash_password, async_session_factory, get_settings
from ..modules.auth.models import Role, RoleName, User


async def seed_database() -> None:
    """Cree les roles par defaut et l'utilisateur admin s'ils n'existent pas."""
    settings = get_settings()

    async with async_session_factory() as session:
        async with session.begin():
            # Creer les roles par defaut
            for role_name in RoleName:
                result = await session.execute(
                    select(Role).where(Role.name == role_name)
                )
                existing = result.scalar_one_or_none()
                if not existing:
                    session.add(Role(name=role_name))
            await session.flush()

            # Recuperer le role admin
            result = await session.execute(
                select(Role).where(Role.name == RoleName.ADMIN)
            )
            admin_role = result.scalar_one_or_none()

            # Creer ou recuperer l'utilisateur admin par defaut
            result = await session.execute(
                select(User).where(User.email == settings.ADMIN_EMAIL)
            )
            admin_user = result.scalar_one_or_none()

            if not admin_user:
                # Nouvel utilisateur : assigner le role avant session.add pour eviter
                # le chargement implicite de la relation sur un objet persistant.
                admin_user = User(
                    email=settings.ADMIN_EMAIL,
                    password_hash=await async_hash_password(
                        settings.ADMIN_PASSWORD
                    ),
                    pseudo=settings.ADMIN_PSEUDO,
                )
                if admin_role:
                    admin_user.roles.append(admin_role)
                session.add(admin_user)
            else:
                # Utilisateur existant : roles charges via selectin lors du SELECT.
                if admin_role and admin_role not in admin_user.roles:
                    admin_user.roles.append(admin_role)
