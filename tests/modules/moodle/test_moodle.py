"""Tests pour le module Moodle (GET /moodle/health et GET /moodle/learner/{id})."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.modules.moodle.models.schemas import (
    LearnerProfile,
    MoodleAssignment,
    MoodleCompletion,
    MoodleCourse,
    MoodleCourseGrade,
    MoodleGradeItem,
    MoodleQuizAttempt,
)
from src.modules.moodle.repositories.moodle_repository import MoodleAPIException
from src.modules.moodle.routes.moodle_routes import get_moodle_service
from tests.conftest import API_PREFIX

# ============================================================================
# Helpers
# ============================================================================


def _make_learner_profile(moodle_userid: int = 7) -> LearnerProfile:
    """Cree un LearnerProfile complet pour les tests."""
    course = MoodleCourse(
        id=101,
        fullname="Introduction a Python",
        shortname="PY101",
        progress=75.0,
        lastaccess=1700000000,
    )
    return LearnerProfile(
        moodle_userid=moodle_userid,
        username="alice",
        fullname="Alice Martin",
        email="alice@example.com",
        courses=[course],
        overview_grades=[
            MoodleCompletion(cmid=1, modname="assign", state=1)
            if False  # factice — utilise la vraie liste vide
            else MoodleCourseGrade(courseid=101, grade="15.00 / 20", rawgrade=15.0)
        ],
        grades_by_course={
            101: [
                MoodleGradeItem(
                    itemname="Devoir 1",
                    itemmodule="assign",
                    graderaw=14.0,
                    grademax=20.0,
                    gradeformatted="14.00",
                )
            ]
        },
        completion_by_course={
            101: [MoodleCompletion(cmid=1, modname="assign", state=1)]
        },
        quiz_attempts=[
            MoodleQuizAttempt(
                quizid=5,
                attempt_number=1,
                state="finished",
                sumgrades=8.5,
            )
        ],
        assignments=[
            MoodleAssignment(
                assignid=10,
                name="Devoir final",
                status="submitted",
                gradingstatus="graded",
                grade=14.0,
            )
        ],
    )


def _make_mock_moodle_svc(
    profile: LearnerProfile | None = None,
    site_info: dict | None = None,
) -> MagicMock:
    """Cree un MoodleService factice."""
    svc = MagicMock()
    svc.get_learner_profile = AsyncMock(return_value=profile or _make_learner_profile())
    svc.get_site_info = AsyncMock(
        return_value=site_info
        or {
            "release": "4.3+ (Build: 20231110)",
            "siteurl": "https://moodle.example.com",
            "username": "wsuser",
        }
    )
    return svc


@pytest.fixture(name="moodle_client")
def moodle_client_fixture(client: TestClient):
    """TestClient avec MoodleService moque."""
    mock_svc = _make_mock_moodle_svc()
    app.dependency_overrides[get_moodle_service] = lambda: mock_svc
    yield client, mock_svc
    # La fixture parent 'client' vide dependency_overrides en teardown


# ============================================================================
# GET /moodle/health — admin uniquement
# ============================================================================


async def test_moodle_health_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    resp = client.get("/moodle/health")
    assert resp.status_code == 401


async def test_moodle_health_forbidden_not_admin(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie le 403 pour un user sans role admin."""
    _, headers = user_and_headers
    resp = client.get("/moodle/health", headers=headers)
    assert resp.status_code == 403


async def test_moodle_health_success(client: TestClient, admin_headers: dict):
    """Verifie la reponse 200 avec les informations du site Moodle."""
    mock_svc = _make_mock_moodle_svc()
    app.dependency_overrides[get_moodle_service] = lambda: mock_svc

    resp = client.get("/moodle/health", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["moodle_version"] == "4.3+ (Build: 20231110)"
    assert data["site_url"] == "https://moodle.example.com"
    assert data["username"] == "wsuser"


async def test_moodle_health_service_error(client: TestClient, admin_headers: dict):
    """Verifie le 502 quand Moodle est inaccessible."""
    mock_svc = MagicMock()
    mock_svc.get_site_info = AsyncMock(
        side_effect=MoodleAPIException("Impossible de joindre Moodle")
    )
    app.dependency_overrides[get_moodle_service] = lambda: mock_svc

    resp = client.get("/moodle/health", headers=admin_headers)

    assert resp.status_code == 502
    assert "Impossible de joindre Moodle" in resp.json()["detail"]


async def test_moodle_health_version_fallback(client: TestClient, admin_headers: dict):
    """Verifie que 'version' est utilise si 'release' est absent."""
    mock_svc = _make_mock_moodle_svc(
        site_info={"version": "2023110800", "siteurl": "https://moodle.example.com"}
    )
    app.dependency_overrides[get_moodle_service] = lambda: mock_svc

    resp = client.get("/moodle/health", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["moodle_version"] == "2023110800"


# ============================================================================
# GET /moodle/learner/{moodle_userid} — admin uniquement
# ============================================================================


async def test_get_learner_profile_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    resp = client.get(f"{API_PREFIX}/moodle/learner/7")
    assert resp.status_code == 401


async def test_get_learner_profile_forbidden_not_admin(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie le 403 pour un user sans role admin."""
    _, headers = user_and_headers
    resp = client.get(f"{API_PREFIX}/moodle/learner/7", headers=headers)
    assert resp.status_code == 403


async def test_get_learner_profile_success(client: TestClient, admin_headers: dict):
    """Verifie la reponse 200 du profil apprenant agrege."""
    mock_svc = _make_mock_moodle_svc()
    app.dependency_overrides[get_moodle_service] = lambda: mock_svc

    resp = client.get(f"{API_PREFIX}/moodle/learner/7", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["moodle_userid"] == 7
    assert data["username"] == "alice"
    assert data["fullname"] == "Alice Martin"
    assert data["email"] == "alice@example.com"
    assert len(data["courses"]) == 1
    assert data["courses"][0]["shortname"] == "PY101"
    assert data["courses"][0]["progress"] == 75.0
    mock_svc.get_learner_profile.assert_awaited_once_with(7)


async def test_get_learner_profile_moodle_error(
    client: TestClient, admin_headers: dict
):
    """Verifie le 502 quand Moodle retourne une erreur."""
    mock_svc = MagicMock()
    mock_svc.get_learner_profile = AsyncMock(
        side_effect=MoodleAPIException("Utilisateur Moodle introuvable (userid=999)")
    )
    app.dependency_overrides[get_moodle_service] = lambda: mock_svc

    resp = client.get(f"{API_PREFIX}/moodle/learner/999", headers=admin_headers)

    assert resp.status_code == 502
    assert "Utilisateur Moodle introuvable" in resp.json()["detail"]


async def test_get_learner_profile_complete_data(
    client: TestClient, admin_headers: dict
):
    """Verifie que toutes les sections du profil sont presentes dans la reponse."""
    mock_svc = _make_mock_moodle_svc()
    app.dependency_overrides[get_moodle_service] = lambda: mock_svc

    resp = client.get(f"{API_PREFIX}/moodle/learner/7", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    # Notes globales
    assert len(data["overview_grades"]) == 1
    assert data["overview_grades"][0]["grade"] == "15.00 / 20"
    # Notes par activite
    assert "101" in data["grades_by_course"]
    assert data["grades_by_course"]["101"][0]["itemname"] == "Devoir 1"
    # Completion
    assert "101" in data["completion_by_course"]
    # Tentatives quiz
    assert len(data["quiz_attempts"]) == 1
    assert data["quiz_attempts"][0]["quizid"] == 5
    assert data["quiz_attempts"][0]["sumgrades"] == 8.5
    # Devoirs
    assert len(data["assignments"]) == 1
    assert data["assignments"][0]["name"] == "Devoir final"
    assert data["assignments"][0]["grade"] == 14.0
