"""Tests pour le module LLM (POST /llm/chat et GET /llm/learner/{id})."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.modules.auth import get_current_user, verify_moodle_webhook
from src.modules.auth.models.user import User
from src.modules.llm.dependencies import get_llm_service
from src.modules.llm.models.schemas import LearnerAnalysis, MoodleChatResponse
from src.modules.moodle.dependencies import get_moodle_service
from src.modules.moodle.models.schemas import LearnerProfile, MoodleUserRole
from tests.conftest import API_PREFIX

# ============================================================================
# Helpers / fixtures locaux
# ============================================================================


def _make_learner_profile(moodle_userid: int = 42) -> LearnerProfile:
    """Cree un LearnerProfile minimal pour les tests."""
    return LearnerProfile(
        moodle_userid=moodle_userid,
        username="jdoe",
        fullname="John Doe",
        email="jdoe@example.com",
    )


def _make_mock_moodle_svc(profile: LearnerProfile | None = None) -> MagicMock:
    """Cree un MoodleService factice."""
    svc = MagicMock()
    svc.get_learner_profile = AsyncMock(return_value=profile or _make_learner_profile())
    svc.get_chat_profiles = AsyncMock(return_value=[profile or _make_learner_profile()])
    svc.get_related_profiles = AsyncMock(return_value=None)
    svc.get_user_role = AsyncMock(return_value=MoodleUserRole.STUDENT)
    return svc


def _make_mock_llm_svc(
    chat_resp: MoodleChatResponse | None = None,
    analysis: LearnerAnalysis | None = None,
) -> MagicMock:
    """Cree un LLMService factice."""
    svc = MagicMock()
    svc.chat = AsyncMock(
        return_value=chat_resp
        or MoodleChatResponse(
            response="Reponse LLM factice."
        )
    )
    svc.analyse_learner = AsyncMock(
        return_value=analysis
        or LearnerAnalysis(
            moodle_userid=42,
            fullname="John Doe",
            model_used="mistral-small-latest",
            analysis="Bilan pedagogique factice.",
        )
    )
    return svc


def _mock_user() -> User:
    """Cree un User factice pour l'override get_current_user."""
    return User(email="llm@test.com", pseudo="LLMUser", is_active=True)


@pytest.fixture(name="llm_client")
def llm_client_fixture(client: TestClient):
    """TestClient avec webhook auth bypasse et services LLM/Moodle moques."""
    mock_moodle = _make_mock_moodle_svc()
    mock_llm = _make_mock_llm_svc()
    # /llm/chat utilise verify_moodle_webhook (pas JWT) — on bypasse pour les tests
    app.dependency_overrides[verify_moodle_webhook] = lambda: None
    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_moodle_service] = lambda: mock_moodle
    app.dependency_overrides[get_llm_service] = lambda: mock_llm
    yield client, mock_moodle, mock_llm
    # La fixture parent 'client' vide dependency_overrides en teardown


# ============================================================================
# POST /llm/chat — authentification JWT
# ============================================================================


async def test_chat_no_auth_returns_401(client: TestClient):
    """Verifie le 401 quand aucun token JWT n'est fourni."""
    resp = client.post(
        f"{API_PREFIX}/llm/chat",
        json={"message": "Bonjour"},
    )
    assert resp.status_code == 401


async def test_chat_invalid_token_returns_401(client: TestClient):
    """Verifie le 401 quand le token JWT est invalide."""
    resp = client.post(
        f"{API_PREFIX}/llm/chat",
        json={"message": "Bonjour"},
        headers={"Authorization": "Bearer token-invalide"},
    )
    assert resp.status_code == 401


# ============================================================================
# POST /llm/chat — reponse normale
# ============================================================================


async def test_chat_success(llm_client):
    """Verifie la reponse 200 avec un message simple."""
    client, _, mock_llm = llm_client
    resp = client.post(
        f"{API_PREFIX}/llm/chat",
        json={"message": "Explique les closures en Python."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Reponse LLM factice."
    mock_llm.chat.assert_awaited_once()


async def test_chat_with_context(llm_client):
    """Verifie que le contexte est prepend au message transmis au service LLM."""
    client, _, mock_llm = llm_client
    resp = client.post(
        f"{API_PREFIX}/llm/chat",
        json={
            "message": "Donne un exemple.",
            "context": "Cours Python avance, module 3",
        },
    )
    assert resp.status_code == 200
    # Le contexte est fusionne dans le message
    call_kwargs = mock_llm.chat.call_args
    message = call_kwargs.kwargs.get("message") or ""
    assert "Cours Python avance, module 3" in message


async def test_chat_with_moodle_userid(llm_client):
    """Verifie que moodle_userid recupere le profil et le passe au service LLM."""
    client, mock_moodle, mock_llm = llm_client
    resp = client.post(
        f"{API_PREFIX}/llm/chat",
        json={"message": "Quel est mon niveau ?", "moodle_userid": 42},
    )
    assert resp.status_code == 200
    # Les profils apprenants ont ete recuperes
    mock_moodle.get_chat_profiles.assert_awaited_once_with(42)
    # Les profils sont passes directement au service LLM
    call_kwargs = mock_llm.chat.call_args
    profiles = call_kwargs.kwargs.get("profiles")
    assert profiles is not None
    assert len(profiles) == 1
    assert profiles[0].fullname == "John Doe"


async def test_chat_without_moodle_userid(llm_client):
    """Verifie que sans moodle_userid, get_learner_profile n'est pas appele."""
    client, mock_moodle, _ = llm_client
    client.post(
        f"{API_PREFIX}/llm/chat",
        json={"message": "Question sans profil."},
    )
    mock_moodle.get_chat_profiles.assert_not_awaited()


async def test_chat_trainer_without_related_learners(llm_client):
    """Un formateur sans apprenants lies ne doit pas avoir son propre profil construit."""
    client, mock_moodle, mock_llm = llm_client
    mock_moodle.get_user_role = AsyncMock(return_value=MoodleUserRole.TRAINER)
    mock_moodle.get_related_profiles = AsyncMock(return_value=None)

    resp = client.post(
        f"{API_PREFIX}/llm/chat",
        json={"message": "Bonjour", "moodle_userid": 99},
    )
    assert resp.status_code == 200
    # get_related_profiles est appele a la place de get_chat_profiles
    mock_moodle.get_related_profiles.assert_awaited_once_with(99)
    mock_moodle.get_chat_profiles.assert_not_awaited()
    # Pas de profil injecte dans le chat
    call_kwargs = mock_llm.chat.call_args
    assert call_kwargs.kwargs.get("profiles") is None


async def test_chat_trainer_with_related_learners(llm_client):
    """Un formateur avec des apprenants lies recoit leurs profils."""
    client, mock_moodle, mock_llm = llm_client
    child_profile = _make_learner_profile(moodle_userid=10)
    mock_moodle.get_user_role = AsyncMock(return_value=MoodleUserRole.TRAINER)
    mock_moodle.get_related_profiles = AsyncMock(return_value=[child_profile])

    resp = client.post(
        f"{API_PREFIX}/llm/chat",
        json={"message": "Rapport de mon eleve", "moodle_userid": 99},
    )
    assert resp.status_code == 200
    mock_moodle.get_related_profiles.assert_awaited_once_with(99)
    call_kwargs = mock_llm.chat.call_args
    profiles = call_kwargs.kwargs.get("profiles")
    assert profiles is not None
    assert len(profiles) == 1
    assert profiles[0].moodle_userid == 10


# ============================================================================
# GET /llm/learner/{moodle_userid} — admin uniquement
# ============================================================================


async def test_analyse_learner_forbidden_no_auth(client: TestClient):
    """Verifie le 401 sans token."""
    resp = client.get(f"{API_PREFIX}/llm/learner/42")
    assert resp.status_code == 401


async def test_analyse_learner_forbidden_not_admin(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie le 403 pour un user sans role admin."""
    _, headers = user_and_headers
    resp = client.get(f"{API_PREFIX}/llm/learner/42", headers=headers)
    assert resp.status_code == 403


async def test_analyse_learner_success(client: TestClient, admin_headers: dict):
    """Verifie la reponse 200 de l'analyse pedagogique pour un admin."""
    mock_moodle = _make_mock_moodle_svc()
    mock_llm = _make_mock_llm_svc()
    app.dependency_overrides[get_moodle_service] = lambda: mock_moodle
    app.dependency_overrides[get_llm_service] = lambda: mock_llm

    resp = client.get(f"{API_PREFIX}/llm/learner/42", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["moodle_userid"] == 42
    assert data["fullname"] == "John Doe"
    assert data["model_used"] == "mistral-small-latest"
    assert "Bilan" in data["analysis"]
    mock_moodle.get_learner_profile.assert_awaited_once_with(42)
    mock_llm.analyse_learner.assert_awaited_once()
