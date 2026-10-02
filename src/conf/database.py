"""Configuration du moteur de base de donnees et gestion des sessions async."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .settings import get_settings

settings = get_settings()

engine_kwargs = {
    "echo": settings.DB_ECHO,
}

if settings.DB_DRIVER != "sqlite":
    engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW

engine = create_async_engine(settings.database_url, **engine_kwargs)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Fournit une session de base de donnees async via dependency injection."""
    async with async_session_factory() as session:
        yield session
