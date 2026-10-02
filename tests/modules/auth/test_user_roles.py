"""Tests pour l'assignation et le retrait de roles sur les utilisateurs."""

from fastapi.testclient import TestClient

from tests.conftest import API_PREFIX, create_user


def _get_role_id(client: TestClient, admin_headers: dict, name: str) -> int:
    """Retourne l'identifiant d'un role seede par son nom."""
    roles = client.get(f"{API_PREFIX}/roles/", headers=admin_headers).json()["items"]
    return next(r["id"] for r in roles if r["name"] == name)


# ============================================================================
# POST /users/{id}/roles/{role_id} — Assignation (admin only)
# ============================================================================


async def test_assign_role_to_user_success(client: TestClient, admin_headers: dict):
    """Verifie l'assignation du role admin a un utilisateur."""
    user = create_user(client)
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    response = client.post(
        f"{API_PREFIX}/users/{user['id']}/roles/{admin_role_id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    # Le user a deja le role 'user' par defaut : 'user' + 'admin' = 2 roles
    assert len(data["roles"]) == 2
    role_names = [r["name"] for r in data["roles"]]
    assert "admin" in role_names


async def test_assign_role_user_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 quand l'utilisateur n'existe pas."""
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    response = client.post(
        f"{API_PREFIX}/users/9999/roles/{admin_role_id}",
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_assign_role_role_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 quand le role n'existe pas."""
    user = create_user(client)
    response = client.post(
        f"{API_PREFIX}/users/{user['id']}/roles/9999",
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_assign_role_duplicate(client: TestClient, admin_headers: dict):
    """Verifie le 409 quand le role est deja assigne."""
    user = create_user(client)
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    client.post(
        f"{API_PREFIX}/users/{user['id']}/roles/{admin_role_id}",
        headers=admin_headers,
    )
    response = client.post(
        f"{API_PREFIX}/users/{user['id']}/roles/{admin_role_id}",
        headers=admin_headers,
    )
    assert response.status_code == 409


async def test_assign_role_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    response = client.post(f"{API_PREFIX}/users/1/roles/1")
    assert response.status_code == 401


async def test_assign_role_forbidden_for_regular_user(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie le 403 pour un user sans role admin."""
    _, headers = user_and_headers
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    response = client.post(
        f"{API_PREFIX}/users/1/roles/{admin_role_id}", headers=headers
    )
    assert response.status_code == 403


# ============================================================================
# DELETE /users/{id}/roles/{role_id} — Retrait (admin only)
# ============================================================================


async def test_remove_role_from_user_success(client: TestClient, admin_headers: dict):
    """Verifie le retrait du role admin d'un utilisateur."""
    user = create_user(client)
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    client.post(
        f"{API_PREFIX}/users/{user['id']}/roles/{admin_role_id}",
        headers=admin_headers,
    )
    response = client.delete(
        f"{API_PREFIX}/users/{user['id']}/roles/{admin_role_id}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    # Le role 'admin' est retire, mais le role 'user' par defaut reste
    assert len(data["roles"]) == 1
    assert data["roles"][0]["name"] == "user"


async def test_remove_role_user_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 quand l'utilisateur n'existe pas."""
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    response = client.delete(
        f"{API_PREFIX}/users/9999/roles/{admin_role_id}",
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_remove_role_role_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 quand le role n'existe pas."""
    user = create_user(client)
    response = client.delete(
        f"{API_PREFIX}/users/{user['id']}/roles/9999",
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_remove_role_not_assigned(client: TestClient, admin_headers: dict):
    """Verifie le 404 quand le role n'est pas assigne a l'utilisateur."""
    user = create_user(client)
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    response = client.delete(
        f"{API_PREFIX}/users/{user['id']}/roles/{admin_role_id}",
        headers=admin_headers,
    )
    assert response.status_code == 404


# ============================================================================
# Verification croisee — Role contient les users
# ============================================================================


async def test_role_contains_assigned_users(client: TestClient, admin_headers: dict):
    """Verifie que GET /roles/{id} affiche les utilisateurs assignes."""
    user = create_user(client, email="alice@example.com")
    admin_role_id = _get_role_id(client, admin_headers, "admin")
    client.post(
        f"{API_PREFIX}/users/{user['id']}/roles/{admin_role_id}",
        headers=admin_headers,
    )
    response = client.get(f"{API_PREFIX}/roles/{admin_role_id}", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    user_ids = [u["id"] for u in data["users"]]
    assert user["id"] in user_ids
