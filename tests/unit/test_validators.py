"""Tests unitaires pour les validateurs Pydantic (Settings et UserPost)."""

import pytest
from pydantic import ValidationError

from src.conf.settings import Settings

# Marqueur identifiant la cle de developpement (detecte par le validateur)
_DEV_KEY_MARKER = "sfXKFSOIsn8TsuMjxbs"
_DEV_PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    + _DEV_KEY_MARKER
    + "\n-----END RSA PRIVATE KEY-----"
)

_PROD_OVERRIDES = {
    "ENVIRONMENT": "production",
    "ADMIN_PASSWORD": "NewSecure123!",
    "APP_BASE_URL": "https://api.example.com",
    "ALLOWED_ORIGINS": ["https://app.example.com"],
    # Cle differente de la cle dev (ne contient pas le marqueur "sfXKFSOIsn8TsuMjxbs")
    "JWT_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEAtYKJdpXpRF9LHzIbUDg1PROD\n-----END RSA PRIVATE KEY-----",
    "JWT_PUBLIC_KEY": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8PROD\n-----END PUBLIC KEY-----",
}


def _make_settings(**kwargs) -> Settings:
    """Cree une instance Settings en ignorant le fichier .env."""
    defaults = {
        "ENVIRONMENT": "development",
        "ADMIN_PASSWORD": "Admin123!",
        "APP_BASE_URL": "http://localhost:8000",
    }
    defaults.update(kwargs)
    return Settings.model_validate(defaults)


# ============================================================================
# validate_jwt_private_key
# ============================================================================


def test_jwt_private_key_default_rejected_in_production():
    """Verifie que la cle privee dev est rejetee en production."""
    with pytest.raises(ValidationError, match="remplace"):
        _make_settings(
            **{
                **_PROD_OVERRIDES,
                "JWT_PRIVATE_KEY": _DEV_PRIVATE_KEY,
            }
        )


def test_jwt_private_key_default_rejected_in_staging():
    """Verifie que la cle privee dev est rejetee en staging."""
    with pytest.raises(ValidationError, match="remplace"):
        _make_settings(
            ENVIRONMENT="staging",
            JWT_PRIVATE_KEY=_DEV_PRIVATE_KEY,
        )


def test_jwt_private_key_custom_accepted_in_production():
    """Verifie qu'une cle differente de la cle dev est acceptee en production."""
    s = _make_settings(**_PROD_OVERRIDES)
    assert "sfXKFSOIsn8TsuMjxbs" not in s.JWT_PRIVATE_KEY


def test_jwt_private_key_default_accepted_in_development():
    """Verifie que la cle dev par defaut est acceptee en developpement."""
    s = _make_settings(ENVIRONMENT="development")
    assert "-----BEGIN RSA PRIVATE KEY-----" in s.JWT_PRIVATE_KEY


# ============================================================================
# validate_admin_password
# ============================================================================


def test_admin_password_default_rejected_in_production():
    """Verifie que le mot de passe admin par defaut est rejete en production."""
    with pytest.raises(ValidationError, match="ADMIN_PASSWORD"):
        _make_settings(**{**_PROD_OVERRIDES, "ADMIN_PASSWORD": "Admin123!"})


def test_admin_password_default_accepted_in_development():
    """Verifie que le mot de passe admin par defaut est accepte en developpement."""
    s = _make_settings(ENVIRONMENT="development")
    assert s.ADMIN_PASSWORD == "Admin123!"


# ============================================================================
# validate_app_base_url
# ============================================================================


def test_app_base_url_http_rejected_in_production():
    """Verifie que HTTP est rejete en production."""
    with pytest.raises(ValidationError, match="HTTPS"):
        _make_settings(**{**_PROD_OVERRIDES, "APP_BASE_URL": "http://api.example.com"})


def test_app_base_url_localhost_rejected_in_production():
    """Verifie que localhost est rejete en production."""
    with pytest.raises(ValidationError, match="localhost"):
        _make_settings(**{**_PROD_OVERRIDES, "APP_BASE_URL": "https://localhost:8000"})


# ============================================================================
# UserPost password validation
# ============================================================================


def test_user_password_without_uppercase_rejected():
    """Verifie le rejet d'un mot de passe sans majuscule."""
    from src.modules.auth.models.user import UserPost

    with pytest.raises(ValidationError):
        UserPost(
            email="test@example.com",
            password="lowercase1234!",
        )


def test_user_password_without_digit_rejected():
    """Verifie le rejet d'un mot de passe sans chiffre."""
    from src.modules.auth.models.user import UserPost

    with pytest.raises(ValidationError):
        UserPost(
            email="test@example.com",
            password="NoDigitPass!",
        )


def test_user_password_valid_accepted():
    """Verifie qu'un mot de passe valide est accepte."""
    from src.modules.auth.models.user import UserPost

    user = UserPost(
        email="test@example.com",
        password="Validpassword1!",
    )
    assert user.password == "Validpassword1!"
