"""
Configuration de l'application avec Pydantic Settings.

Ce module centralise toute la configuration de l'application en utilisant
les meilleures pratiques de gestion de configuration :
- Separation des environnements (dev, staging, prod)
- Validation stricte des types avec Pydantic
- Chargement depuis variables d'environnement et fichier .env
"""

import re
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuration principale de l'application.

    Toutes les valeurs peuvent etre surchargees via :
    1. Variables d'environnement
    2. Fichier .env a la racine du projet

    Les variables d'environnement ont la priorite sur le fichier .env.
    """

    # ============================================================================
    # INFORMATIONS DE L'APPLICATION
    # ============================================================================

    APP_NAME: str = Field(description="Nom de l'application")

    APP_DESCRIPTION: str = Field(
        description="Description de l'application pour la documentation",
    )

    APP_VERSION: str = Field(
        description="Version de l'application (semantic versioning)"
    )

    # ============================================================================
    # ENVIRONNEMENT ET MODE DE FONCTIONNEMENT
    # ============================================================================

    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        description="Environnement d'execution de l'application"
    )

    DEBUG: bool = Field(description="Active le mode debug (desactiver en production)")

    # ============================================================================
    # SERVEUR ET API
    # ============================================================================

    HOST: str = Field(
        description="Adresse d'ecoute du serveur (docker-compose surcharge en 0.0.0.0)",
    )

    PORT: int = Field(ge=1, le=65535, description="Port d'ecoute du serveur")

    API_PREFIX: str = Field(description="Prefixe pour toutes les routes de l'API")

    ALLOWED_ORIGINS: list[str] = Field(description="Origines autorisees pour CORS")

    # ============================================================================
    # JWT ET AUTHENTIFICATION
    # ============================================================================

    JWT_ALGORITHM: Literal["RS256", "ES256"] = Field(
        description="Algorithme de signature JWT asymetrique (RS256 ou ES256)",
    )

    JWT_PRIVATE_KEY: str = Field(
        description=(
            "Cle privee RSA/EC PEM pour signer les JWT (\\n echappe autorise). "
            "Generer : openssl genrsa 2048 > jwt_private_key.pem"
        ),
    )

    JWT_PUBLIC_KEY: str = Field(
        description=(
            "Cle publique RSA/EC PEM pour verifier les JWT (\\n echappe ok). "
            "Extraire : openssl rsa -in jwt_private_key.pem -pubout "
            "> jwt_public_key.pem"
        ),
    )

    JWT_EXPIRATION_MINUTES: int = Field(
        ge=1,
        description="Duree de validite des tokens JWT en minutes",
    )

    ADMIN_EMAIL: str = Field(
        description="Email de l'administrateur par defaut",
    )

    ADMIN_PSEUDO: str = Field(
        description="Pseudo de l'administrateur par defaut",
    )

    ADMIN_PASSWORD: str = Field(
        description=(
            "Mot de passe du compte admin cree au seed. "
            "Min 12 caracteres, majuscule, chiffre et symbole requis en prod/staging."
        ),
    )

    # ============================================================================
    # RATE LIMITING
    # ============================================================================

    REDIS_URL: str = Field(
        description=(
            "URL Redis pour le backend du rate limiter (ex: redis://redis:6379). "
            "Vide = stockage in-memory (workers=1 uniquement). "
            "Obligatoire si plusieurs workers Gunicorn sont utilises."
        ),
    )

    # ============================================================================
    # SECURITE — PROTECTION ANTI BRUTE-FORCE
    # ============================================================================

    FAILED_LOGIN_THRESHOLD: int = Field(
        ge=1,
        description="Nombre d'echecs consecutifs avant le premier blocage du compte",
    )

    LOCKOUT_DURATIONS_MINUTES: list[int] = Field(
        description=(
            "Durees de blocage progressives en minutes (1er, 2e, 3e cycle). "
            "Au-dela du dernier palier le compte est bloque definitivement."
        ),
    )

    # ============================================================================
    # TOKENS — VERIFICATION EMAIL ET RESET MOT DE PASSE
    # ============================================================================

    EMAIL_VERIFICATION_EXPIRY_MINUTES: int = Field(
        ge=1,
        description="Duree de validite du token de verification email (minutes)",
    )

    RESET_TOKEN_EXPIRY_MINUTES: int = Field(
        ge=1,
        description="Duree de validite du token de reinitialisation (minutes)",
    )

    TOKEN_BYTES: int = Field(
        ge=16,
        description="Entropie des tokens de securite en octets (secrets.token_urlsafe)",
    )

    # ============================================================================
    # CONFIGURATION DE LA BASE DE DONNEES
    # ============================================================================

    DB_DRIVER: Literal["sqlite", "postgresql"] = Field(
        description="Dialecte BDD (docker-compose surcharge en postgresql)",
    )

    DB_USER: str = Field(description="Nom d'utilisateur de la base de donnees")

    DB_PASSWORD: str = Field(description="Mot de passe de la base de donnees")

    DB_NAME: str = Field(description="Nom de la base de donnees")

    DB_HOST: str = Field(description="Hote de la base de donnees")

    DB_PORT: int = Field(
        ge=1,
        le=65535,
        description="Port de la base de donnees (5432 = PostgreSQL)",
    )

    DB_ECHO: bool = Field(description="Active les logs SQL (utile en developpement)")

    DB_POOL_SIZE: int = Field(ge=1, le=100, description="Taille du pool de connexions")

    DB_MAX_OVERFLOW: int = Field(
        ge=0,
        le=100,
        description="Nombre maximum de connexions supplementaires au pool",
    )

    # ============================================================================
    # MAIL
    # ============================================================================

    MAIL_USERNAME: str = Field(description="Nom d'utilisateur SMTP")
    MAIL_PASSWORD: str = Field(description="Mot de passe SMTP")
    MAIL_FROM: str = Field(description="Adresse expediteur")
    MAIL_FROM_NAME: str = Field(description="Nom expediteur")
    MAIL_SERVER: str = Field(description="Hote SMTP")
    MAIL_PORT: int = Field(
        ge=1,
        le=65535,
        description="Port SMTP (1025=Mailpit dev, 587=STARTTLS, 465=SSL)",
    )
    MAIL_STARTTLS: bool = Field(description="Activer STARTTLS")
    MAIL_SSL_TLS: bool = Field(description="Activer SSL/TLS")
    MAIL_SUPPRESS_SEND: bool = Field(
        description="Desactiver l'envoi reel (True en tests)"
    )
    APP_BASE_URL: str = Field(description="URL de base pour les liens dans les emails")

    # ============================================================================
    # MISTRAL LLM
    # ============================================================================

    MISTRAL_API_KEY: str = Field(description="Cle API Mistral AI")

    MISTRAL_MODEL: str = Field(description="Modele Mistral principal")

    MISTRAL_BASE_URL: str = Field(
        description="URL de base de l'API LLM (compatible OpenAI)"
    )

    MISTRAL_MAX_TOKENS: int = Field(
        ge=50,
        le=100000,
        description=(
            "Nombre maximum de tokens en sortie par appel LLM. "
            "Plafonne le cout output (300-500 suffisent pour le tuteur)."
        ),
    )

    MISTRAL_MODEL_LIGHT: str = Field(
        description=(
            "Modele leger pour les questions simples sans profil apprenant. "
            "~7x moins cher que mistral-small-latest."
        ),
    )

    MOODLE_WEBHOOK_SECRET: str = Field(
        description=(
            "Secret partage pour authentifier les appels entrants depuis Moodle. "
            'Generer avec : python3 -c "import secrets; print(secrets.token_hex(32))"'
        ),
    )

    AI_NAME: str = Field(
        default="DigilearIA",
        description=(
            "Nom de l'IA affiche dans les prompts systeme et les interfaces Moodle. "
            "Ex: DigilearnIA, TutorIA, MonAssistant."
        ),
    )

    PLATFORM_POLICIES: str = Field(
        description=(
            "Regles et consignes de la plateforme injectees dans le prompt du tuteur. "
            "Laisser vide pour desactiver."
        ),
    )

    LLM_DAILY_TOKEN_LIMIT_PER_USER: int = Field(
        default=1000000,
        ge=0,
        description=(
            "Limite quotidienne de tokens (prompt + completion) par moodle_userid. "
            "0 = limite desactivee. La fenetre se reinitialise a 00:00 UTC."
        ),
    )

    LLM_HTTP_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        ge=5.0,
        le=300.0,
        description=(
            "Timeout HTTP du client vers l'API LLM (secondes). "
            "Augmenter si les prompts sont longs ou si la latence Mistral fluctue."
        ),
    )

    LLM_MAX_PROMPT_TOKENS: int = Field(
        default=100000,
        ge=1000,
        le=200000,
        description=(
            "Budget maximal estime de tokens en entree avant l'appel LLM. "
            "Au-dela, le contexte apprenant est tronque pour eviter les timeouts "
            "et les depassements de context window."
        ),
    )

    # ============================================================================
    # MOODLE
    # ============================================================================

    MOODLE_BASE_URL: str = Field(
        description="URL de base Moodle (ex: https://moodle.example.com)"
    )

    MOODLE_HTTP_HOST: str | None = Field(
        default=None,
        description=(
            "Valeur optionnelle du header HTTP Host pour joindre Moodle via une "
            "URL interne Docker tout en conservant une URL publique differente."
        ),
    )

    MOODLE_ADMIN_TOKEN: str = Field(
        description="Token du web service Moodle (genere dans Moodle)"
    )

    MOODLE_SERVICE_NAME: str = Field(description="Nom du service Moodle")

    MOODLE_CACHE_TTL_SECONDS: int = Field(
        description="TTL Redis du cache LearnerProfile (secondes). 0 = desactive.",
    )

    PROACTIVITY_SETTINGS_CACHE_TTL: int = Field(
        default=3600,
        ge=0,
        description=(
            "TTL Redis du cache ProactivitySettings (secondes). "
            "0 = desactive. Recharge la config Moodle a chaque appel."
        ),
    )

    # ============================================================================
    # CONTACT — metadata OpenAPI
    # ============================================================================

    CONTACT_NAME: str = Field(description="Nom du contact OpenAPI")
    CONTACT_URL: str = Field(description="URL du contact OpenAPI")
    CONTACT_EMAIL: str = Field(description="Email du contact OpenAPI")

    # ============================================================================
    # LOGGING
    # ============================================================================

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        description="Niveau de logging de l'application"
    )

    LOG_DIR: str | None = Field(
        default=None,
        description=(
            "Repertoire des fichiers de log (rotation quotidienne, 30 jours). "
            "Si absent, logs sur stdout uniquement."
        ),
    )

    # ============================================================================
    # CONFIGURATION PYDANTIC
    # ============================================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        use_enum_values=True,
        validate_default=True,
    )

    # ============================================================================
    # PROPRIETES CALCULEES
    # ============================================================================

    @property
    def database_url(self) -> str:
        """
        Construit l'URL de connexion a la base de donnees (driver async).
        sqlite -> aiosqlite | postgresql -> asyncpg
        Le mot de passe est encode (% encoding) pour eviter toute ambiguite
        avec les caracteres speciaux (@, /, etc.) dans l'URL.
        """
        if self.DB_DRIVER == "sqlite":
            return "sqlite+aiosqlite:///./database.db"

        from sqlalchemy.engine.url import URL

        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)

    @property
    def is_development(self) -> bool:
        """Retourne True si l'environnement est 'development'."""
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        """Retourne True si l'environnement est 'production'."""
        return self.ENVIRONMENT == "production"

    @property
    def is_staging(self) -> bool:
        """Retourne True si l'environnement est 'staging'."""
        return self.ENVIRONMENT == "staging"

    # ============================================================================
    # VALIDATEURS
    # ============================================================================

    @model_validator(mode="before")
    @classmethod
    def resolve_docker_secrets(cls, data: dict) -> dict:
        """
        Lit les secrets depuis :
        1. /run/secrets/<nom>       — Docker secrets (prod)
        2. secrets/<nom>.txt        — Fichier local (dev)
        Le champ doit etre absent ou vide pour que le fichier soit lu.
        """
        secret_files = {
            "DB_PASSWORD": "db_password",  # nosec B105
            "MAIL_PASSWORD": "brevo_smtp_key",  # nosec B105
            "JWT_PRIVATE_KEY": "jwt_private_key",  # nosec B105
            "JWT_PUBLIC_KEY": "jwt_public_key",  # nosec B105
            "ADMIN_PASSWORD": "admin_password",  # nosec B105
            "MISTRAL_API_KEY": "mistral_api_key",  # nosec B105
            "MOODLE_ADMIN_TOKEN": "moodle_admin_token",  # nosec B105
            "MOODLE_WEBHOOK_SECRET": "moodle_webhook_secret",  # nosec B105
        }
        for field_name, secret_name in secret_files.items():
            if field_name not in data or data[field_name] == "":
                for path in [
                    Path(f"/run/secrets/{secret_name}"),  # Docker
                    Path(f"secrets/{secret_name}.txt"),  # Local
                ]:
                    if path.is_file():
                        data[field_name] = path.read_text().strip()
                        break
        return data

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def validate_allowed_origins(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """En production, ALLOWED_ORIGINS ne doit pas contenir localhost."""
        if info.data.get("ENVIRONMENT") == "production":
            for origin in v:
                if "localhost" in origin or "127.0.0.1" in origin:
                    raise ValueError(
                        "ALLOWED_ORIGINS ne doit pas contenir localhost en production"
                    )
        return v

    @field_validator("LOCKOUT_DURATIONS_MINUTES")
    @classmethod
    def validate_lockout_durations(cls, v: list[int]) -> list[int]:
        """Verifie que les durees de blocage sont valides."""
        if not v:
            raise ValueError("LOCKOUT_DURATIONS_MINUTES ne peut pas etre vide")
        for duration in v:
            if duration <= 0:
                raise ValueError(
                    "Toutes les durees dans LOCKOUT_DURATIONS_MINUTES doivent etre > 0"
                )
        return v

    @field_validator("JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY")
    @classmethod
    def unescape_pem_newlines(cls, v: str) -> str:
        """Normalise les \\n echappes (simple ou double niveau) en vrais sauts de ligne.

        Cas couverts :
        - Cle avec \\\\n (double echappement, ex: env var passee via CI/CD) → newline
        - Cle avec \\n (simple echappement, convention .env) → newline
        - Cle avec de vrais sauts de ligne → inchangee
        """
        v = v.replace("\\\\n", "\n")  # Double echappement en premier
        v = v.replace("\\n", "\n")  # Simple echappement ensuite
        return v.strip()

    @field_validator("JWT_PRIVATE_KEY")
    @classmethod
    def validate_jwt_private_key(cls, v: str, info: ValidationInfo) -> str:
        """Verifie que la cle privee est non vide et non la cle dev en prod/staging."""
        if not v:
            raise ValueError(
                "JWT_PRIVATE_KEY est obligatoire. "
                "Generer : openssl genrsa 2048 > jwt_private_key.pem"
            )
        _dev_marker = "sfXKFSOIsn8TsuMjxbs"
        if info.data.get("ENVIRONMENT") in ("production", "staging"):
            if _dev_marker in v:
                raise ValueError(
                    "JWT_PRIVATE_KEY doit etre remplace en production/staging"
                )
        return v

    @field_validator("JWT_PUBLIC_KEY")
    @classmethod
    def validate_jwt_public_key(cls, v: str) -> str:
        """Verifie que la cle publique est non vide."""
        if not v:
            raise ValueError(
                "JWT_PUBLIC_KEY est obligatoire. "
                "Extraire : openssl rsa -in jwt_private_key.pem -pubout "
                "> jwt_public_key.pem"
            )
        return v

    @field_validator("ADMIN_PASSWORD")
    @classmethod
    def validate_admin_password(cls, v: str, info: ValidationInfo) -> str:
        """Verifie que le mot de passe admin est non vide et robuste en prod/staging."""
        if not v:
            raise ValueError(
                "ADMIN_PASSWORD est obligatoire. "
                "Definir dans .env ou via Docker secret admin_password."
            )
        if info.data.get("ENVIRONMENT") in ("production", "staging"):
            errors = []
            if len(v) < 12:
                errors.append("12 caracteres minimum")
            if not re.search(r"[A-Z]", v):
                errors.append("une majuscule")
            if not re.search(r"[a-z]", v):
                errors.append("une minuscule")
            if not re.search(r"\d", v):
                errors.append("un chiffre")
            if not re.search(r"[^a-zA-Z0-9]", v):
                errors.append("un caractere special")
            if errors:
                raise ValueError(
                    "ADMIN_PASSWORD doit contenir au moins : " + ", ".join(errors)
                )
        return v

    @field_validator("DEBUG")
    @classmethod
    def validate_debug_mode(cls, v: bool, info: ValidationInfo) -> bool:
        environment = info.data.get("ENVIRONMENT", "development")

        if v and environment == "production":
            warnings.warn(
                "Le mode DEBUG est active en PRODUCTION !", UserWarning, stacklevel=2
            )

        return v

    @field_validator("APP_BASE_URL")
    @classmethod
    def validate_app_base_url(cls, v: str, info: ValidationInfo) -> str:
        """En production, APP_BASE_URL doit utiliser HTTPS (pas de localhost)."""
        if info.data.get("ENVIRONMENT") == "production":
            if not v.startswith("https://"):
                raise ValueError("APP_BASE_URL doit utiliser HTTPS en production")
            if "localhost" in v or "127.0.0.1" in v:
                raise ValueError(
                    "APP_BASE_URL ne peut pas pointer vers localhost en production"
                )
        return v

    @field_validator("DB_ECHO")
    @classmethod
    def validate_db_echo(cls, v: bool, info: ValidationInfo) -> bool:
        environment = info.data.get("ENVIRONMENT", "development")

        if v and environment == "production":
            return False

        return v


# ============================================================================
# SINGLETON
# ============================================================================


@lru_cache
def get_settings() -> Settings:
    return Settings()
