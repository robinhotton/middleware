"""Tests d'integration pour les routes /proactivity/."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.modules.proactivity.dependencies import get_proactivity_service
from tests.conftest import API_PREFIX


# ============================================================================
# Helpers
# ============================================================================


def _make_mock_proactivity_svc() -> MagicMock:
    """Cree un ProactivityService factice."""
    svc = MagicMock()
    svc.run_reminder_job = AsyncMock(return_value=3)
    svc.run_suggestion_job = AsyncMock(return_value=1)
    svc.get_proactivity_settings = AsyncMock()
    return svc


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(name="proactivity_client")
def proactivity_client_fixture(client: TestClient):
    """TestClient avec ProactivityService moque."""
    mock_svc = _make_mock_proactivity_svc()
    app.dependency_overrides[get_proactivity_service] = lambda: mock_svc
    yield client, mock_svc
    # dependency_overrides vide par la fixture parente `client`


# ============================================================================
# Tests GET /proactivity/status
# ============================================================================


def test_status_requires_auth(proactivity_client):
    client, _ = proactivity_client
    resp = client.get(f"{API_PREFIX}/proactivity/status")
    assert resp.status_code == 401


def test_status_requires_admin(proactivity_client, user_and_headers):
    client, _ = proactivity_client
    _, headers = user_and_headers
    resp = client.get(f"{API_PREFIX}/proactivity/status", headers=headers)
    assert resp.status_code == 403


def test_status_ok(proactivity_client, admin_headers):
    client, _ = proactivity_client
    resp = client.get(f"{API_PREFIX}/proactivity/status", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "scheduler_running" in data
    assert "jobs" in data
    assert isinstance(data["jobs"], list)


# ============================================================================
# Tests POST /proactivity/trigger
# ============================================================================


def test_trigger_requires_auth(proactivity_client):
    client, _ = proactivity_client
    resp = client.post(f"{API_PREFIX}/proactivity/trigger", params={"job": "reminder"})
    assert resp.status_code == 401


def test_trigger_requires_admin(proactivity_client, user_and_headers):
    client, _ = proactivity_client
    _, headers = user_and_headers
    resp = client.post(
        f"{API_PREFIX}/proactivity/trigger",
        params={"job": "reminder"},
        headers=headers,
    )
    assert resp.status_code == 403


def test_trigger_reminder(proactivity_client, admin_headers):
    client, mock_svc = proactivity_client
    resp = client.post(
        f"{API_PREFIX}/proactivity/trigger",
        params={"job": "reminder"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert "3" in data["message"]
    mock_svc.run_reminder_job.assert_awaited_once()


def test_trigger_suggestion(proactivity_client, admin_headers):
    client, mock_svc = proactivity_client
    resp = client.post(
        f"{API_PREFIX}/proactivity/trigger",
        params={"job": "suggestion"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert "1" in data["message"]
    mock_svc.run_suggestion_job.assert_awaited_once()


def test_trigger_invalid_job(proactivity_client, admin_headers):
    client, _ = proactivity_client
    resp = client.post(
        f"{API_PREFIX}/proactivity/trigger",
        params={"job": "invalid_job"},
        headers=admin_headers,
    )
    assert resp.status_code == 422
