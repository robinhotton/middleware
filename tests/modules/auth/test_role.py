"""Tests pour les endpoints de lecture des roles."""

from fastapi.testclient import TestClient

from tests.conftest import API_PREFIX

# Les roles 'admin' et 'user' sont crees par la fixture admin_headers.
# Le CRUD (POST/PATCH/DELETE) n'est pas expose : les roles sont une config interne.

# ============================================================================
# GET /roles — Admin only
# ============================================================================


async def test_get_roles_returns_seeded_roles(client: TestClient, admin_headers: dict):
    """Verifie que les deux roles seedes (admin, user) sont bien presentes."""
    response = client.get(f"{API_PREFIX}/roles/", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    names = {r["name"] for r in data["items"]}
    assert names == {"admin", "user"}


async def test_get_roles_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    response = client.get(f"{API_PREFIX}/roles/")
    assert response.status_code == 401


async def test_get_roles_forbidden_for_regular_user(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie le 403 pour un user sans role admin."""
    _, headers = user_and_headers
    response = client.get(f"{API_PREFIX}/roles/", headers=headers)
    assert response.status_code == 403


# ============================================================================
# GET /roles — Pagination
# ============================================================================


async def test_get_roles_pagination_skip(client: TestClient, admin_headers: dict):
    """Verifie le comportement du parametre skip (2 roles fixes)."""
    response = client.get(f"{API_PREFIX}/roles/?skip=1", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_get_roles_pagination_limit(client: TestClient, admin_headers: dict):
    """Verifie le comportement du parametre limit."""
    response = client.get(f"{API_PREFIX}/roles/?limit=1", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_get_roles_pagination_invalid_skip(
    client: TestClient, admin_headers: dict
):
    """Verifie le rejet de skip negatif (422)."""
    response = client.get(f"{API_PREFIX}/roles/?skip=-1", headers=admin_headers)
    assert response.status_code == 422


async def test_get_roles_pagination_invalid_limit(
    client: TestClient, admin_headers: dict
):
    """Verifie le rejet d'un limit invalide (422)."""
    response = client.get(f"{API_PREFIX}/roles/?limit=0", headers=admin_headers)
    assert response.status_code == 422
    response = client.get(f"{API_PREFIX}/roles/?limit=101", headers=admin_headers)
    assert response.status_code == 422


# ============================================================================
# GET /roles/{id} — Admin only
# ============================================================================


async def test_get_role_by_id_success(client: TestClient, admin_headers: dict):
    """Verifie la recuperation du role admin par son identifiant."""
    roles = client.get(f"{API_PREFIX}/roles/", headers=admin_headers).json()["items"]
    admin_role = next(r for r in roles if r["name"] == "admin")
    response = client.get(f"{API_PREFIX}/roles/{admin_role['id']}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "admin"


async def test_get_role_by_id_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 pour un role inexistant."""
    response = client.get(f"{API_PREFIX}/roles/9999", headers=admin_headers)
    assert response.status_code == 404
