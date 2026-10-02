"""Fixtures pytest pour les tests d'integration."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select

from src.conf.database import get_session
from src.conf.limiter import limiter
from src.conf.security import create_access_token, hash_password
from src.conf.settings import get_settings
from src.main import app
from src.modules.auth.dependencies import get_email_service
from src.modules.auth.models.email import EmailVerificationToken
from src.modules.auth.models.role import Role, RoleName
from src.modules.auth.models.user import User
from src.modules.auth.models.user_role_link import UserRoleLink

# Desactive le rate limiting pour les tests (les appels repetitifs declencheraient le limiteur)
limiter.enabled = False

API_PREFIX: str = get_settings().API_PREFIX

engine_test = create_async_engine(
    "sqlite+aiosqlite://",
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(engine_test, expire_on_commit=False)


class NullEmailService:
    """Service email factice : avale tous les envois sans contacter de serveur SMTP."""

    send_verification_link: AsyncMock
    send_reset_link: AsyncMock

    def __init__(self):
        self.send_verification_link = AsyncMock()
        self.send_reset_link = AsyncMock()


@pytest.fixture(name="null_email_service")
def null_email_service_fixture() -> NullEmailService:
    """Fournit le service email factice partage pour inspection dans les tests."""
    return NullEmailService()


@pytest.fixture(name="client")
async def client_fixture(null_email_service: NullEmailService):
    """Fournit un TestClient avec une base SQLite in-memory isolee."""
    async with engine_test.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async def get_session_override():
        async with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_email_service] = lambda: null_email_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    async with engine_test.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture(name="admin_headers")
async def admin_headers_fixture(client: TestClient) -> dict:
    """Cree un admin directement en base et retourne les headers Authorization."""
    async with AsyncSession(engine_test, expire_on_commit=False) as session:
        # Creer le role user (assigne automatiquement au register)
        user_role = Role(name=RoleName.USER, description="Utilisateur")
        session.add(user_role)
        admin_role = Role(name=RoleName.ADMIN, description="Administrateur")
        session.add(admin_role)
        await session.commit()
        await session.refresh(admin_role)

        # Creer l'utilisateur admin (actif directement, bypass verification email)
        admin_user = User(
            email="admin@test.com",
            password_hash=hash_password("adminpass123"),
            is_active=True,
        )
        session.add(admin_user)
        await session.commit()
        await session.refresh(admin_user)

        # Assigner le role admin
        link = UserRoleLink(user_id=admin_user.id, role_id=admin_role.id)
        session.add(link)
        await session.commit()

        token = create_access_token({"sub": str(admin_user.id)})

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(name="user_and_headers")
async def user_and_headers_fixture(client: TestClient) -> tuple[dict, dict]:
    """Cree un user standard via l'API, verifie son email, et retourne (user_data, headers)."""
    resp = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            "email": "regular@test.com",
            "password": "Userpassword1!",
        },
    )
    user_data = resp.json()

    # Recupere le token de verification directement en base et active le compte
    async with AsyncSession(engine_test) as session:
        result = await session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user_data["id"]
            )
        )
        verification = result.scalar_one()
    client.get(f"{API_PREFIX}/auth/verify-email", params={"token": verification.token})

    login_resp = client.post(
        f"{API_PREFIX}/auth/login",
        json={
            "email": "regular@test.com",
            "password": "Userpassword1!",
        },
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    return user_data, headers


# ============================================================================
# Helpers partages entre les fichiers de test
# ============================================================================


async def verify_email_for_user(client: TestClient, user_id: int) -> None:
    """Verifie l'email d'un utilisateur en recuperant le token depuis la base."""
    async with AsyncSession(engine_test) as session:
        result = await session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user_id,
                EmailVerificationToken.used == False,  # noqa: E712
            )
        )
        verification = result.scalar_one()
    client.get(f"{API_PREFIX}/auth/verify-email", params={"token": verification.token})


def create_user(
    client: TestClient,
    email: str = "test@example.com",
    password: str = "Testpassword1!",
    **kwargs,
) -> dict:
    """Cree un utilisateur via /auth/register et retourne les donnees."""
    payload = {
        "email": email,
        "password": password,
    }
    resp = client.post(f"{API_PREFIX}/auth/register", json=payload)
    assert resp.status_code == 201, f"create_user echoue: {resp.json()}"
    return resp.json()


