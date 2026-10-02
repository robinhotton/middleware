"""Tests pour l'authentification JWT et la protection des routes."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.conf import utcnow
from src.modules.auth.models.email import EmailVerificationToken
from src.modules.auth.models.token import PasswordResetToken
from src.modules.auth.models.user import User
from tests.conftest import (
    API_PREFIX,
    NullEmailService,
    create_user,
    engine_test,
    verify_email_for_user,
)

# ============================================================================
# Helpers
# ============================================================================


async def _create_verified_user(
    client: TestClient, email: str = "user@example.com", password: str = "Testpassword1!"
) -> dict:
    """Cree un utilisateur et verifie son email (is_active=True)."""
    user = create_user(client, email=email, password=password)
    await verify_email_for_user(client, user["id"])
    return user


def _login(client: TestClient, email: str, password: str) -> dict:
    """Helper pour se connecter et retourner la reponse."""
    resp = client.post(
        f"{API_PREFIX}/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    return resp


def _auth_header(token: str) -> dict:
    """Construit le header Authorization Bearer."""
    return {"Authorization": f"Bearer {token}"}


async def _get_reset_token(email: str) -> PasswordResetToken | None:
    """Recupere le token de reinitialisation en base pour un email donne."""
    async with AsyncSession(engine_test) as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            return None
        result = await session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()


# ============================================================================
# POST /auth/register — Public
# ============================================================================


async def test_register_success(
    client: TestClient, null_email_service: NullEmailService
):
    """Verifie la creation d'un utilisateur via register (inactif jusqu'a verification)."""
    response = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            "email": "bob@example.com",
            "password": "Testpassword1!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "bob@example.com"
    assert data["is_active"] is False  # inactif jusqu'a verification de l'email
    assert "id" in data
    # Le role 'user' n'existe pas encore (pas de admin_headers) : liste vide attendue.
    assert data["roles"] == []
    assert "password" not in data
    assert "password_hash" not in data
    # L'email de verification doit avoir ete envoye en arriere-plan
    null_email_service.send_verification_link.assert_awaited_once()


async def test_register_assigns_user_role(client: TestClient, admin_headers: dict):
    """Verifie que le role 'user' est automatiquement assigne si le role existe en base."""
    response = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            "email": "autorole@example.com",
            "password": "Testpassword1!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    role_names = [r["name"] for r in data["roles"]]
    assert "user" in role_names


async def test_register_invalid_email(client: TestClient):
    """Verifie le rejet d'un email invalide (422)."""
    response = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            "email": "not-an-email",
            "password": "Testpassword1!",
        },
    )
    assert response.status_code == 422


async def test_register_duplicate_email(client: TestClient):
    """Verifie le rejet d'un email duplique (409)."""
    payload = {
        "email": "duplicate@example.com",
        "password": "Testpassword1!",
    }
    client.post(f"{API_PREFIX}/auth/register", json=payload)
    response = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "Testpassword1!",
        },
    )
    assert response.status_code == 409


# ============================================================================
# GET /auth/verify-email — Public
# ============================================================================


async def test_verify_email_success(client: TestClient):
    """Flux complet : register cree un compte inactif, verify-email l'active."""
    user = create_user(client, email="verify@example.com", password="Testpassword1!")
    assert user["is_active"] is False

    # Le compte est inactif : login impossible
    login_before = _login(client, "verify@example.com", "Testpassword1!")
    assert login_before.status_code == 401

    # Verification via le lien
    async with AsyncSession(engine_test) as session:
        result = await session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user["id"]
            )
        )
        verification = result.scalar_one()
    assert verification is not None

    resp = client.get(
        f"{API_PREFIX}/auth/verify-email", params={"token": verification.token}
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Email verified successfully."

    # Le compte est maintenant actif : login possible
    login_after = _login(client, "verify@example.com", "Testpassword1!")
    assert login_after.status_code == 200
    assert "access_token" in login_after.json()


async def test_verify_email_unknown_token(client: TestClient):
    """Verifie le 404 pour un token inexistant."""
    resp = client.get(
        f"{API_PREFIX}/auth/verify-email", params={"token": "tokeninexistant"}
    )
    assert resp.status_code == 404


async def test_verify_email_already_used(client: TestClient):
    """Verifie le 400 quand le token a deja ete utilise."""
    user = create_user(client, email="used@example.com")
    async with AsyncSession(engine_test) as session:
        result = await session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user["id"]
            )
        )
        verification = result.scalar_one()

    # Premier appel : succes
    client.get(f"{API_PREFIX}/auth/verify-email", params={"token": verification.token})
    # Deuxieme appel : token deja utilise
    resp = client.get(
        f"{API_PREFIX}/auth/verify-email", params={"token": verification.token}
    )
    assert resp.status_code == 400


async def test_verify_email_expired(client: TestClient):
    """Verifie le 400 quand le token est expire."""
    user = create_user(client, email="expired@example.com")

    # Injecte un token expire directement en base
    async with AsyncSession(engine_test) as session:
        expired_token = EmailVerificationToken(
            user_id=user["id"],
            token="expiredverif12345",
            expires_at=utcnow() - timedelta(hours=25),
        )
        session.add(expired_token)
        await session.commit()

    resp = client.get(
        f"{API_PREFIX}/auth/verify-email", params={"token": "expiredverif12345"}
    )
    assert resp.status_code == 400


# ============================================================================
# POST /auth/login — Public
# ============================================================================


async def test_login_success(client: TestClient):
    """Verifie qu'un login valide retourne un token."""
    await _create_verified_user(client, email="alice@example.com", password="Secretpass1!")
    resp = _login(client, "alice@example.com", "Secretpass1!")
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_before_email_verification(client: TestClient):
    """Verifie que le login est refuse avant la verification de l'email."""
    create_user(client, email="unverified@example.com", password="Testpassword1!")
    resp = _login(client, "unverified@example.com", "Testpassword1!")
    assert resp.status_code == 401


async def test_login_wrong_password(client: TestClient):
    """Verifie le 401 pour un mauvais mot de passe."""
    await _create_verified_user(client, email="bob@example.com", password="Correctpass1!")
    resp = _login(client, "bob@example.com", "wrongpass")
    assert resp.status_code == 401


async def test_login_unknown_email(client: TestClient):
    """Verifie le 401 pour un email inconnu."""
    resp = _login(client, "ghost@example.com", "whatever123")
    assert resp.status_code == 401


async def test_login_lockout_after_5_attempts(client: TestClient):
    """Verifie le verrou (1er cycle, 5 min) apres 5 tentatives echouees consecutives."""
    await _create_verified_user(
        client, email="lockout@example.com", password="Correctpass1!"
    )
    for _ in range(5):
        resp = _login(client, "lockout@example.com", "Wrongpass1!")
        assert resp.status_code == 401
    # Le 6e appel doit retourner 429
    resp = _login(client, "lockout@example.com", "Correctpass1!")
    assert resp.status_code == 429
    assert "bloque" in resp.json()["detail"].lower()


async def test_login_lockout_resets_on_success(client: TestClient):
    """Verifie que 4 echecs + 1 succes reinitialisent tous les compteurs."""
    await _create_verified_user(
        client, email="reset_counter@example.com", password="Correctpass1!"
    )
    for _ in range(4):
        _login(client, "reset_counter@example.com", "Wrongpass1!")
    # Connexion correcte : reinitialise failed_login_attempts ET lockout_count
    resp = _login(client, "reset_counter@example.com", "Correctpass1!")
    assert resp.status_code == 200
    # 5 nouveaux echecs sont necessaires pour reverrouiller (repart du 1er palier)
    for _ in range(4):
        _login(client, "reset_counter@example.com", "Wrongpass1!")
    resp = _login(client, "reset_counter@example.com", "Correctpass1!")
    assert resp.status_code == 200


async def _expire_lockout(email: str) -> None:
    """Helper : expire le verrou en base pour simuler l'ecoulement du temps."""
    async with AsyncSession(engine_test) as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.locked_until = utcnow() - timedelta(seconds=1)
        session.add(user)
        await session.commit()


async def test_login_progressive_lockout(client: TestClient):
    """Verifie la progression des durees de blocage sur plusieurs cycles."""
    await _create_verified_user(
        client, email="progressive@example.com", password="Correctpass1!"
    )

    # Cycle 1 → 5 min
    for _ in range(5):
        _login(client, "progressive@example.com", "Wrongpass1!")
    assert _login(client, "progressive@example.com", "Correctpass1!").status_code == 429

    # Expiration simulee + cycle 2 → 30 min
    await _expire_lockout("progressive@example.com")
    for _ in range(5):
        _login(client, "progressive@example.com", "Wrongpass1!")
    assert _login(client, "progressive@example.com", "Correctpass1!").status_code == 429

    # Expiration simulee + cycle 3 → 2h
    await _expire_lockout("progressive@example.com")
    for _ in range(5):
        _login(client, "progressive@example.com", "Wrongpass1!")
    assert _login(client, "progressive@example.com", "Correctpass1!").status_code == 429

    # Expiration simulee + cycle 4 → blocage definitif
    await _expire_lockout("progressive@example.com")
    for _ in range(5):
        _login(client, "progressive@example.com", "Wrongpass1!")
    resp = _login(client, "progressive@example.com", "Correctpass1!")
    assert resp.status_code == 429
    assert "definitivement" in resp.json()["detail"].lower()


async def test_login_lockout_admin_can_unlock(client: TestClient, admin_headers: dict):
    """Verifie qu'un admin peut deverrouiller un blocage temporaire via PATCH."""
    user = await _create_verified_user(
        client, email="unlock@example.com", password="Correctpass1!"
    )
    for _ in range(5):
        _login(client, "unlock@example.com", "Wrongpass1!")
    assert _login(client, "unlock@example.com", "Correctpass1!").status_code == 429

    # Admin deverrouille : efface le verrou ET remet le compteur de cycles a zero
    client.patch(
        f"{API_PREFIX}/users/{user['id']}/admin",
        json={"locked_until": None, "lockout_count": 0},
        headers=admin_headers,
    )

    resp = _login(client, "unlock@example.com", "Correctpass1!")
    assert resp.status_code == 200


async def test_login_permanent_lockout_reset_via_password(client: TestClient):
    """Verifie qu'un blocage definitif est leve par un reset de mot de passe."""
    user = await _create_verified_user(
        client, email="perm@example.com", password="Correctpass1!"
    )

    # Declencher 4 cycles de blocage
    for _ in range(4):
        for _ in range(5):
            _login(client, "perm@example.com", "Wrongpass1!")
        await _expire_lockout("perm@example.com")

    assert _login(client, "perm@example.com", "Correctpass1!").status_code == 429

    # Reset mot de passe → leve le blocage definitif
    client.post(
        f"{API_PREFIX}/auth/reset-password",
        json={
            "email": "perm@example.com",
        },
    )
    async with AsyncSession(engine_test) as session:
        result = await session.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user["id"])
        )
        token = result.scalar_one()
    client.post(
        f"{API_PREFIX}/auth/confirm-reset",
        json={"token": token.token, "new_password": "NewPassword1!"},
    )

    resp = _login(client, "perm@example.com", "NewPassword1!")
    assert resp.status_code == 200


async def test_login_deactivated_user(client: TestClient, admin_headers: dict):
    """Verifie le 401 quand un utilisateur desactive tente de se connecter."""
    user = await _create_verified_user(
        client, email="deactivated@example.com", password="Password1234!"
    )
    # Admin desactive l'utilisateur
    client.delete(f"{API_PREFIX}/users/{user['id']}", headers=admin_headers)
    # Tentative de login
    resp = _login(client, "deactivated@example.com", "Password1234!")
    assert resp.status_code == 401


# ============================================================================
# POST /auth/reset-password + POST /auth/confirm-reset — Public
# ============================================================================


async def test_reset_password_success(
    client: TestClient, null_email_service: NullEmailService
):
    """Flux complet : POST envoie un email, POST /confirm-reset applique le changement."""
    await _create_verified_user(client, email="reset@example.com", password="Oldpassword1!")

    # Etape 1 : demande de reinitialisation (sans nouveau mot de passe)
    resp = client.post(
        f"{API_PREFIX}/auth/reset-password",
        json={
            "email": "reset@example.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "A confirmation email has been sent."
    # L'email de reset doit avoir ete envoye en arriere-plan
    null_email_service.send_reset_link.assert_awaited_once()

    # L'ancien mot de passe fonctionne encore (pas encore confirme)
    login_old = _login(client, "reset@example.com", "Oldpassword1!")
    assert login_old.status_code == 200

    # Recupere le token directement en base
    reset_token = await _get_reset_token("reset@example.com")
    assert reset_token is not None

    # Etape 2 : confirmation via le lien (avec le nouveau mot de passe)
    confirm_resp = client.post(
        f"{API_PREFIX}/auth/confirm-reset",
        json={
            "token": reset_token.token,
            "new_password": "Newpassword4!",
        },
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["message"] == "Password reset successfully."

    # L'ancien mot de passe ne fonctionne plus
    login_old_after = _login(client, "reset@example.com", "Oldpassword1!")
    assert login_old_after.status_code == 401

    # Le nouveau mot de passe fonctionne
    login_new = _login(client, "reset@example.com", "Newpassword4!")
    assert login_new.status_code == 200
    assert "access_token" in login_new.json()


async def test_reset_password_not_applied_before_confirmation(client: TestClient):
    """Verifie que le mot de passe n'est pas change avant la confirmation."""
    await _create_verified_user(
        client, email="pending@example.com", password="Oldpassword1!"
    )
    client.post(
        f"{API_PREFIX}/auth/reset-password",
        json={
            "email": "pending@example.com",
        },
    )
    # L'ancien mot de passe doit toujours fonctionner
    login_old = _login(client, "pending@example.com", "Oldpassword1!")
    assert login_old.status_code == 200
    # Un mot de passe arbitraire ne fonctionne pas encore
    login_new = _login(client, "pending@example.com", "Newpassword4!")
    assert login_new.status_code == 401


async def test_reset_password_unknown_email(client: TestClient):
    """Verifie que la reponse est 200 meme pour un email inconnu (anti-enumeration)."""
    resp = client.post(
        f"{API_PREFIX}/auth/reset-password",
        json={
            "email": "unknown@example.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "A confirmation email has been sent."


async def test_confirm_reset_unknown_token(client: TestClient):
    """Verifie le 404 pour un token inexistant."""
    resp = client.post(
        f"{API_PREFIX}/auth/confirm-reset",
        json={
            "token": "tokeninexistant",
            "new_password": "Newpassword4!",
        },
    )
    assert resp.status_code == 404


async def test_confirm_reset_already_used(client: TestClient):
    """Verifie le 400 quand le token a deja ete utilise."""
    await _create_verified_user(client, email="used@example.com", password="Oldpassword1!")
    client.post(
        f"{API_PREFIX}/auth/reset-password",
        json={
            "email": "used@example.com",
        },
    )
    reset_token = await _get_reset_token("used@example.com")
    assert reset_token is not None
    # Premier appel : succes
    client.post(
        f"{API_PREFIX}/auth/confirm-reset",
        json={"token": reset_token.token, "new_password": "Newpassword4!"},
    )
    # Deuxieme appel : token deja utilise
    resp = client.post(
        f"{API_PREFIX}/auth/confirm-reset",
        json={"token": reset_token.token, "new_password": "Newpassword4!"},
    )
    assert resp.status_code == 400


async def test_confirm_reset_expired(client: TestClient):
    """Verifie le 400 quand le token est expire."""
    await _create_verified_user(
        client, email="expired@example.com", password="Oldpassword1!"
    )

    # Injecte un token expire directement en base
    async with AsyncSession(engine_test) as session:
        result = await session.execute(
            select(User).where(User.email == "expired@example.com")
        )
        user = result.scalar_one()
        expired_token = PasswordResetToken(
            user_id=user.id,
            token="expiredtoken12345",
            expires_at=utcnow() - timedelta(hours=2),
        )
        session.add(expired_token)
        await session.commit()

    resp = client.post(
        f"{API_PREFIX}/auth/confirm-reset",
        json={
            "token": "expiredtoken12345",
            "new_password": "Newpassword4!",
        },
    )
    assert resp.status_code == 400


# ============================================================================
# Token d'un user desactive est refuse
# ============================================================================


async def test_deactivated_user_token_rejected(client: TestClient, admin_headers: dict):
    """Verifie qu'un token existant d'un user desactive est refuse."""
    user = await _create_verified_user(
        client, email="willdeactivate@example.com", password="Password1234!"
    )
    login_resp = _login(client, "willdeactivate@example.com", "Password1234!")
    token = login_resp.json()["access_token"]
    user_headers = _auth_header(token)
    # Verifie que le token fonctionne avant desactivation
    resp = client.get(f"{API_PREFIX}/users/{user['id']}", headers=user_headers)
    assert resp.status_code == 200
    # Admin desactive l'utilisateur
    client.delete(f"{API_PREFIX}/users/{user['id']}", headers=admin_headers)
    # Le token existant doit etre refuse
    resp = client.get(f"{API_PREFIX}/users/{user['id']}", headers=user_headers)
    assert resp.status_code == 401


# ============================================================================
# Password jamais expose
# ============================================================================


async def test_password_not_exposed_in_response(
    client: TestClient, admin_headers: dict
):
    """Verifie que password et password_hash ne sont jamais dans les reponses."""
    resp = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            "email": "safe@example.com",
            "password": "Secretpass1!",
        },
    )
    data = resp.json()
    assert "password" not in data
    assert "password_hash" not in data

    user_id = data["id"]
    get_resp = client.get(f"{API_PREFIX}/users/{user_id}", headers=admin_headers)
    get_data = get_resp.json()
    assert "password" not in get_data
    assert "password_hash" not in get_data


# ============================================================================
# POST /auth/logout — JTI blocklist
# ============================================================================


async def test_logout_success(client: TestClient, user_and_headers):
    """Verifie qu'un logout retourne 200 avec un message de confirmation."""
    _, headers = user_and_headers
    resp = client.post(f"{API_PREFIX}/auth/logout", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out successfully."


async def test_logout_token_rejected_after(client: TestClient, user_and_headers):
    """Verifie que le token est refuse sur toute route protegee apres logout."""
    user_data, headers = user_and_headers
    # Verifie que le token fonctionne avant logout
    resp = client.get(f"{API_PREFIX}/users/{user_data['id']}", headers=headers)
    assert resp.status_code == 200
    # Logout
    client.post(f"{API_PREFIX}/auth/logout", headers=headers)
    # Le token doit etre refuse apres logout
    resp = client.get(f"{API_PREFIX}/users/{user_data['id']}", headers=headers)
    assert resp.status_code == 401


async def test_logout_unauthenticated(client: TestClient):
    """Verifie le 401 quand aucun token n'est fourni."""
    resp = client.post(f"{API_PREFIX}/auth/logout")
    assert resp.status_code == 401
