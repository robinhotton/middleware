"""Tests pour les endpoints CRUD utilisateurs."""

from fastapi.testclient import TestClient

from tests.conftest import API_PREFIX, create_user

# ============================================================================
# GET /users — Admin only
# ============================================================================


async def test_get_users_empty(client: TestClient, admin_headers: dict):
    """Verifie que la liste est vide sans donnees (hors admin seed)."""
    response = client.get(f"{API_PREFIX}/users/", headers=admin_headers)
    assert response.status_code == 200
    # L'admin cree par la fixture est present
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


async def test_get_users_with_data(client: TestClient, admin_headers: dict):
    """Verifie que la liste contient les utilisateurs crees."""
    create_user(
        client,
        email="alice@example.com",
    )
    response = client.get(f"{API_PREFIX}/users/", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    emails = [u["email"] for u in data["items"]]
    assert "alice@example.com" in emails


async def test_get_users_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    response = client.get(f"{API_PREFIX}/users/")
    assert response.status_code == 401


async def test_get_users_forbidden_for_regular_user(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie le 403 pour un user sans role admin."""
    _, headers = user_and_headers
    response = client.get(f"{API_PREFIX}/users/", headers=headers)
    assert response.status_code == 403


# ============================================================================
# GET /users — Pagination
# ============================================================================


async def test_get_users_pagination_skip(client: TestClient, admin_headers: dict):
    """Verifie le comportement du parametre skip."""
    create_user(client, email="user1@example.com")
    create_user(client, email="user2@example.com")
    # admin_headers created 1 admin + 2 users = 3 total, skip=2 → 1 result
    response = client.get(f"{API_PREFIX}/users/?skip=2", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_get_users_pagination_limit(client: TestClient, admin_headers: dict):
    """Verifie le comportement du parametre limit."""
    create_user(client, email="user1@example.com")
    create_user(client, email="user2@example.com")
    create_user(client, email="user3@example.com")
    response = client.get(f"{API_PREFIX}/users/?limit=2", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


async def test_get_users_pagination_invalid_skip(
    client: TestClient, admin_headers: dict
):
    """Verifie le rejet de skip negatif (422)."""
    response = client.get(f"{API_PREFIX}/users/?skip=-1", headers=admin_headers)
    assert response.status_code == 422


async def test_get_users_pagination_invalid_limit(
    client: TestClient, admin_headers: dict
):
    """Verifie le rejet d'un limit invalide (422)."""
    response = client.get(f"{API_PREFIX}/users/?limit=0", headers=admin_headers)
    assert response.status_code == 422
    response = client.get(f"{API_PREFIX}/users/?limit=101", headers=admin_headers)
    assert response.status_code == 422


# ============================================================================
# GET /users/{id} — Self or admin
# ============================================================================


async def test_get_user_by_id_admin(client: TestClient, admin_headers: dict):
    """Verifie qu'un admin peut recuperer n'importe quel utilisateur."""
    user = create_user(
        client,
        email="charlie@example.com",
    )
    user_id = user["id"]
    response = client.get(f"{API_PREFIX}/users/{user_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "charlie@example.com"


async def test_get_user_by_id_self(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie qu'un user peut recuperer son propre profil."""
    user_data, headers = user_and_headers
    response = client.get(f"{API_PREFIX}/users/{user_data['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "regular@test.com"


async def test_get_user_by_id_other_forbidden(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie le 403 quand un user tente d'acceder au profil d'un autre."""
    _, headers = user_and_headers
    other = create_user(client, email="other@example.com")
    response = client.get(f"{API_PREFIX}/users/{other['id']}", headers=headers)
    assert response.status_code == 403


async def test_get_user_by_id_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 pour un utilisateur inexistant."""
    response = client.get(f"{API_PREFIX}/users/9999", headers=admin_headers)
    assert response.status_code == 404


async def test_get_user_by_id_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    response = client.get(f"{API_PREFIX}/users/1")
    assert response.status_code == 401


# ============================================================================
# PATCH /users/{id} — Self or admin
# ============================================================================


async def test_patch_user_admin(client: TestClient, admin_headers: dict):
    """Verifie qu'un admin peut mettre a jour le pseudo d'un utilisateur."""
    user = create_user(client, email="dave@example.com")
    user_id = user["id"]
    response = client.patch(
        f"{API_PREFIX}/users/{user_id}",
        json={"pseudo": "Dave Updated"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["pseudo"] == "Dave Updated"


async def test_patch_user_self(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie qu'un user peut modifier son propre pseudo."""
    user_data, headers = user_and_headers
    response = client.patch(
        f"{API_PREFIX}/users/{user_data['id']}",
        json={"pseudo": "Mon pseudo"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["pseudo"] == "Mon pseudo"


async def test_patch_user_self_cannot_change_is_active(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie qu'un user non-admin ne peut pas modifier is_active."""
    user_data, headers = user_and_headers
    response = client.patch(
        f"{API_PREFIX}/users/{user_data['id']}",
        json={
            "is_active": False,
        },
        headers=headers,
    )
    assert response.status_code == 200
    # is_active doit rester True car le champ est ignore pour non-admin
    assert response.json()["is_active"] is True


async def test_patch_user_admin_can_change_is_active(
    client: TestClient, admin_headers: dict
):
    """Verifie qu'un admin peut modifier is_active via l'endpoint admin."""
    user = create_user(client, email="target@example.com")
    response = client.patch(
        f"{API_PREFIX}/users/{user['id']}/admin",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_patch_user_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 pour un PATCH sur utilisateur inexistant."""
    response = client.patch(
        f"{API_PREFIX}/users/9999",
        json={
            "email": "ghost@example.com",
        },
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_patch_user_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    response = client.patch(f"{API_PREFIX}/users/1", json={"email": "nope@test.com"})
    assert response.status_code == 401


# ============================================================================
# DELETE /users/{id} — Self or admin (soft delete)
# ============================================================================


async def test_delete_user_deactivates(client: TestClient, admin_headers: dict):
    """Verifie que DELETE desactive l'utilisateur (soft delete)."""
    user = create_user(client, email="grace@example.com")
    user_id = user["id"]
    response = client.delete(f"{API_PREFIX}/users/{user_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["message"] == "User deactivated successfully"
    # L'utilisateur existe toujours mais est desactive
    get_resp = client.get(f"{API_PREFIX}/users/{user_id}", headers=admin_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["is_active"] is False


async def test_delete_user_self(
    client: TestClient, admin_headers: dict, user_and_headers
):
    """Verifie qu'un user peut se desactiver lui-meme."""
    user_data, headers = user_and_headers
    response = client.delete(f"{API_PREFIX}/users/{user_data['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["message"] == "User deactivated successfully"


async def test_delete_user_not_found(client: TestClient, admin_headers: dict):
    """Verifie le 404 pour un DELETE sur utilisateur inexistant."""
    response = client.delete(f"{API_PREFIX}/users/9999", headers=admin_headers)
    assert response.status_code == 404


async def test_delete_user_unauthorized(client: TestClient):
    """Verifie le 401 sans token."""
    response = client.delete(f"{API_PREFIX}/users/1")
    assert response.status_code == 401
