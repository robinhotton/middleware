"""Tests unitaires pour la logique de brute-force dans AuthService."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.conf.security import hash_password
from src.conf.utils import utcnow
from src.exceptions import TooManyRequestsException, UnauthorizedException
from src.modules.auth.services.auth_service import AuthService

CORRECT_PASSWORD = "Correct1!"
WRONG_PASSWORD = "wrongpass"


def _make_service():
    """Cree un AuthService avec tous les repositories mockes."""
    repo = AsyncMock()
    role_repo = AsyncMock()
    reset_repo = AsyncMock()
    email_verification_repo = AsyncMock()
    service = AuthService(
        repository=repo,
        role_repository=role_repo,
        reset_token_repository=reset_repo,
        email_verification_token_repository=email_verification_repo,
        revoked_token_repository=AsyncMock(),
    )
    return service, repo


def _make_user(**kwargs):
    """Cree un utilisateur mock avec les valeurs par defaut."""
    user = MagicMock()
    user.id = 1
    user.email = "test@example.com"
    user.password_hash = hash_password(CORRECT_PASSWORD)
    user.is_active = True
    user.failed_login_attempts = 0
    user.locked_until = None
    user.lockout_count = 0
    user.roles = []
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user


async def _setup_update_mock(repo, user):
    """Configure le mock update pour mettre a jour les attributs du user."""

    async def mock_update(u, data):
        for k, v in data.items():
            setattr(u, k, v)
        return u

    repo.update.side_effect = mock_update
    repo.get_by_email.return_value = user


async def test_lockout_after_threshold_attempts():
    """Verifie le verrou apres N tentatives consecutives (1er cycle)."""
    service, repo = _make_service()
    user = _make_user()
    await _setup_update_mock(repo, user)

    # 4 echecs : pas encore bloque
    for _ in range(4):
        with pytest.raises(UnauthorizedException):
            await service.login(user.email, WRONG_PASSWORD)

    # 5e echec : declenche le blocage (cycle 1)
    with pytest.raises(UnauthorizedException):
        await service.login(user.email, WRONG_PASSWORD)

    # Le lockout_count est maintenant 1 et locked_until est dans le futur
    assert user.lockout_count == 1
    assert user.locked_until is not None
    assert user.locked_until > utcnow()


async def test_lockout_blocks_further_attempts():
    """Verifie que le compte bloque retourne 429."""
    service, repo = _make_service()
    user = _make_user(lockout_count=1, locked_until=utcnow() + timedelta(minutes=5))
    repo.get_by_email.return_value = user

    with pytest.raises(TooManyRequestsException):
        await service.login(user.email, WRONG_PASSWORD)


async def test_progressive_lockout_cycle_2():
    """Verifie la progression vers le 2e palier (30 min)."""
    service, repo = _make_service()
    # Simule un user apres expiration du cycle 1
    user = _make_user(lockout_count=1, locked_until=utcnow() - timedelta(seconds=1))
    await _setup_update_mock(repo, user)

    # 5 echecs apres expiration du cycle 1
    for _ in range(4):
        with pytest.raises(UnauthorizedException):
            await service.login(user.email, WRONG_PASSWORD)
    with pytest.raises(UnauthorizedException):
        await service.login(user.email, WRONG_PASSWORD)

    assert user.lockout_count == 2
    assert user.locked_until is not None
    # Cycle 2 = 30 min → locked_until dans 25-35 min
    delta = (user.locked_until - utcnow()).total_seconds() / 60
    assert 25 <= delta <= 35


async def test_permanent_lockout_after_all_cycles():
    """Verifie le blocage definitif apres depassement du dernier palier."""
    service, repo = _make_service()
    # Simule un user apres expiration du cycle 3 (dernier palier)
    user = _make_user(lockout_count=3, locked_until=utcnow() - timedelta(seconds=1))
    await _setup_update_mock(repo, user)

    # 5 echecs : declenche le blocage definitif (cycle 4 > len([5, 30, 120]))
    for _ in range(4):
        with pytest.raises(UnauthorizedException):
            await service.login(user.email, WRONG_PASSWORD)
    with pytest.raises(UnauthorizedException):
        await service.login(user.email, WRONG_PASSWORD)

    assert user.lockout_count == 4
    # Pas de locked_until pour le blocage definitif
    assert user.locked_until is None


async def test_permanent_lockout_raises_429():
    """Verifie que le blocage definitif retourne 429."""
    service, repo = _make_service()
    # lockout_count > len(LOCKOUT_DURATIONS_MINUTES) = 3
    user = _make_user(lockout_count=4)
    repo.get_by_email.return_value = user

    with pytest.raises(TooManyRequestsException) as exc_info:
        await service.login(user.email, CORRECT_PASSWORD)
    assert "definitivement" in str(exc_info.value.detail).lower()


async def test_counters_reset_on_successful_login():
    """Verifie la reinitialisation des compteurs apres une connexion reussie."""
    service, repo = _make_service()
    user = _make_user(failed_login_attempts=3, lockout_count=1)
    await _setup_update_mock(repo, user)

    result = await service.login(user.email, CORRECT_PASSWORD)

    assert result.access_token
    assert user.failed_login_attempts == 0
    assert user.locked_until is None
    assert user.lockout_count == 0


async def test_base_resets_after_lockout_expiry():
    """Verifie que failed_login_attempts repart de 0 apres expiration d'un verrou."""
    service, repo = _make_service()
    # Simule un user avec verrou expire et 3 tentatives accumulees
    user = _make_user(
        failed_login_attempts=3,
        locked_until=utcnow() - timedelta(seconds=1),
        lockout_count=1,
    )
    await _setup_update_mock(repo, user)

    # Echec apres expiration : le compteur repart de 0 + 1
    with pytest.raises(UnauthorizedException):
        await service.login(user.email, WRONG_PASSWORD)

    assert user.failed_login_attempts == 1


async def test_inactive_user_rejected_before_lockout_check():
    """Verifie que is_active=False est verifie avant la logique de lockout."""
    service, repo = _make_service()
    user = _make_user(is_active=False)
    repo.get_by_email.return_value = user

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.login(user.email, CORRECT_PASSWORD)
    assert "Invalid email or password" in str(exc_info.value.detail)
    # update ne doit pas avoir ete appele (pas d'increment de compteur)
    repo.update.assert_not_awaited()
