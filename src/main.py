"""Point d'entree de l'application FastAPI."""

import asyncio
import fcntl
import logging
import os
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import IO

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlmodel import SQLModel

from .conf import (
    async_session_factory,
    engine,
    get_redis_client,
    get_settings,
    limiter,
    run_migrations,
    setup_logging,
)
from .middlewares import (
    add_security_headers,
    log_requests,
    register_exception_handlers,
    setup_cors,
)
from .modules import register_routers
from .modules.auth.repositories import RevokedTokenRepository
from .modules.llm.repositories import LLMLogRepository, LLMRepository
from .modules.moodle.repositories import MoodleRepository
from .modules.moodle.services import MoodleService
from .modules.proactivity.models.schemas import ProactivitySettingsRecord
from .modules.proactivity.repositories.proactivity_repository import (
    ProactivityEventRepository,
    ProactivityHttpRepository,
    ProactivitySettingsRepository,
)
from .modules.proactivity.services import ProactivityService
from .scripts import seed_database

logger = logging.getLogger(__name__)

_settings = get_settings()

_LLM_KEEPALIVE_INTERVAL = 4 * 60  # 4 minutes — sous le seuil de mise en veille Mistral
_KEEPALIVE_LOCK_FD: IO | None = None
# Chemin du fichier de verrou via l'API standard (evite B108 hardcoded /tmp)
_KEEPALIVE_LOCK_PATH = os.path.join(tempfile.gettempdir(), "llm_keepalive.lock")

# Crons par defaut — remplace a la premiere execution du job refresh
_DEFAULT_REMINDER_CRON = "0 9 * * 1-5"
_DEFAULT_SUGGESTION_CRON = "0 10 * * 1-5"


def _try_acquire_keepalive_lock() -> bool:
    """Tente d'acquerir le verrou exclusif de keepalive (un seul worker actif)."""
    global _KEEPALIVE_LOCK_FD
    try:
        fd = open(_KEEPALIVE_LOCK_PATH, "w")  # noqa: SIM115
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _KEEPALIVE_LOCK_FD = fd
            return True
        except OSError:
            fd.close()
            return False
    except OSError:
        return False


async def _cleanup_revoked_tokens() -> None:
    """Remove expired JTI entries from the blocklist at startup."""
    async with async_session_factory() as session:
        await RevokedTokenRepository(session).cleanup_expired()


def _make_proactivity_service(session) -> ProactivityService:
    """Instancie un ProactivityService complet pour une session donnee."""
    r = get_redis_client()
    moodle_repo = MoodleRepository(
        base_url=_settings.MOODLE_BASE_URL,
        token=_settings.MOODLE_ADMIN_TOKEN,
        host_header=_settings.MOODLE_HTTP_HOST,
        plugin_secret=_settings.MOODLE_WEBHOOK_SECRET,
    )
    return ProactivityService(
        event_repo=ProactivityEventRepository(session),
        llm_log_repo=LLMLogRepository(session),
        http_repo=ProactivityHttpRepository(
            base_url=_settings.MOODLE_BASE_URL,
            secret=_settings.MOODLE_WEBHOOK_SECRET,
            http_host=_settings.MOODLE_HTTP_HOST,
        ),
        moodle_svc=MoodleService(
            repository=moodle_repo,
            redis=r,
            cache_ttl=_settings.MOODLE_CACHE_TTL_SECONDS,
        ),
        llm_repo=LLMRepository(
            api_key=_settings.MISTRAL_API_KEY,
            base_url=_settings.MISTRAL_BASE_URL,
            model=_settings.MISTRAL_MODEL,
            max_tokens=_settings.MISTRAL_MAX_TOKENS,
        ),
        redis=r,
    )


async def _llm_keepalive(repo: LLMRepository) -> None:
    """Envoie une requete minimale periodique pour maintenir le LLM eveille."""
    while True:
        await asyncio.sleep(_LLM_KEEPALIVE_INTERVAL)
        try:
            await repo.chat_completion(
                messages=[{"role": "user", "content": "ok"}],
                model=_settings.MISTRAL_MODEL_LIGHT,
            )
            logger.debug("LLM keepalive OK")
        except Exception as exc:
            logger.debug("LLM keepalive echec : %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialise la base de donnees et les donnees initiales au demarrage."""
    setup_logging(_settings.LOG_LEVEL, _settings.LOG_DIR)
    if not _settings.is_production:
        # Dev : create_all() cree le schema courant — migrations inutiles
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        # Prod : BDD persistante — migrations incrementales uniquement
        async with engine.begin() as conn:
            await run_migrations(conn)
    await _cleanup_revoked_tokens()
    await seed_database()

    keepalive_task = None
    llm_repo = None
    if _settings.MISTRAL_API_KEY and _try_acquire_keepalive_lock():
        llm_repo = LLMRepository(
            api_key=_settings.MISTRAL_API_KEY,
            base_url=_settings.MISTRAL_BASE_URL,
            model=_settings.MISTRAL_MODEL_LIGHT,
            max_tokens=1,
        )
        keepalive_task = asyncio.create_task(_llm_keepalive(llm_repo))

    # --- Chargement initial de la config proactivite ---
    # Priorite : Moodle (live) > DB (derniere config connue) > defaults hardcodes
    reminder_cron = _DEFAULT_REMINDER_CRON
    suggestion_cron = _DEFAULT_SUGGESTION_CRON

    try:
        async with async_session_factory() as session:
            svc = _make_proactivity_service(session)
            settings_repo = ProactivitySettingsRepository(session)
            try:
                moodle_settings = await svc.get_proactivity_settings()
                reminder_cron = moodle_settings.reminder_cron
                suggestion_cron = moodle_settings.suggestion_cron
                # Persister en DB pour les prochains demarrages
                await settings_repo.upsert(
                    ProactivitySettingsRecord.from_settings(moodle_settings)
                )
                logger.info(
                    "Config proactivite chargee depuis Moodle : reminder=%s suggestion=%s",
                    reminder_cron,
                    suggestion_cron,
                )
            except Exception as exc:
                logger.warning(
                    "Config proactivite : Moodle injoignable (%s), tentative DB...", exc
                )
                db_record = await settings_repo.get_latest()
                if db_record is not None:
                    reminder_cron = db_record.reminder_cron
                    suggestion_cron = db_record.suggestion_cron
                    logger.info(
                        "Config proactivite chargee depuis DB (fetched_at=%s) : "
                        "reminder=%s suggestion=%s",
                        db_record.fetched_at,
                        reminder_cron,
                        suggestion_cron,
                    )
                else:
                    logger.warning(
                        "Config proactivite : aucune config en DB, "
                        "utilisation des defaults : reminder=%s suggestion=%s",
                        reminder_cron,
                        suggestion_cron,
                    )
    except Exception as exc:
        logger.error("Config proactivite : erreur inattendue au chargement : %s", exc)

    # --- Scheduler proactivite ---
    scheduler = AsyncIOScheduler()

    async def _proactivity_reminder() -> None:
        import time as _time

        logger.info("Cron reminder : demarrage")
        start = _time.monotonic()
        try:
            async with async_session_factory() as session:
                count = await _make_proactivity_service(session).run_reminder_job()
            elapsed = int((_time.monotonic() - start) * 1000)
            logger.info("Cron reminder : termine — %d notification(s), %d ms", count, elapsed)
        except Exception as exc:
            elapsed = int((_time.monotonic() - start) * 1000)
            logger.error("Cron reminder : echec apres %d ms — %s", elapsed, exc)

    async def _proactivity_suggestion() -> None:
        import time as _time

        logger.info("Cron suggestion : demarrage")
        start = _time.monotonic()
        try:
            async with async_session_factory() as session:
                count = await _make_proactivity_service(session).run_suggestion_job()
            elapsed = int((_time.monotonic() - start) * 1000)
            logger.info("Cron suggestion : termine — %d suggestion(s), %d ms", count, elapsed)
        except Exception as exc:
            elapsed = int((_time.monotonic() - start) * 1000)
            logger.error("Cron suggestion : echec apres %d ms — %s", elapsed, exc)

    async def _proactivity_refresh() -> None:
        """Refetch la config Moodle, persiste en DB, et reconfigure les crons."""
        logger.info("Cron refresh : demarrage")
        # Invalider le cache des inscrits pour forcer un rechargement frais
        r = get_redis_client()
        if r:
            await r.delete("moodle:enrolled_learner_ids")
        async with async_session_factory() as session:
            svc = _make_proactivity_service(session)
            settings_repo = ProactivitySettingsRepository(session)
            try:
                proactivity_settings = await svc.get_proactivity_settings()
                # Persister la config fraiche en DB
                await settings_repo.upsert(
                    ProactivitySettingsRecord.from_settings(proactivity_settings)
                )
                scheduler.reschedule_job(
                    "proactivity_reminder",
                    trigger=CronTrigger.from_crontab(proactivity_settings.reminder_cron),
                )
                scheduler.reschedule_job(
                    "proactivity_suggestion",
                    trigger=CronTrigger.from_crontab(proactivity_settings.suggestion_cron),
                )
                logger.info(
                    "Cron refresh : config persistee et crons reconfigures "
                    "reminder=%s suggestion=%s",
                    proactivity_settings.reminder_cron,
                    proactivity_settings.suggestion_cron,
                )
            except Exception as exc:
                logger.warning("Cron refresh : reconfiguration echouee : %s", exc)

    scheduler.add_job(
        _proactivity_reminder,
        CronTrigger.from_crontab(reminder_cron),
        id="proactivity_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        _proactivity_suggestion,
        CronTrigger.from_crontab(suggestion_cron),
        id="proactivity_suggestion",
        replace_existing=True,
    )
    scheduler.add_job(
        _proactivity_refresh,
        IntervalTrigger(hours=1),
        id="proactivity_refresh",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Scheduler proactivite demarre — %d job(s) : %s",
        len(scheduler.get_jobs()),
        ", ".join(j.id for j in scheduler.get_jobs()),
    )

    logger.info(
        "Application demarree — %s v%s [%s]",
        _settings.APP_NAME,
        _settings.APP_VERSION,
        _settings.ENVIRONMENT,
    )
    yield

    scheduler.shutdown(wait=False)
    if keepalive_task:
        keepalive_task.cancel()
    if llm_repo:
        await llm_repo.aclose()
    logger.info("Application arretee")


_contact: dict[str, str] = {}
if _settings.CONTACT_NAME:
    _contact["name"] = _settings.CONTACT_NAME
if _settings.CONTACT_URL:
    _contact["url"] = _settings.CONTACT_URL
if _settings.CONTACT_EMAIL:
    _contact["email"] = _settings.CONTACT_EMAIL

app = FastAPI(
    title=_settings.APP_NAME,
    description=_settings.APP_DESCRIPTION,
    version=_settings.APP_VERSION,
    contact=_contact or None,
    openapi_tags=[
        {
            "name": "auth",
            "description": (
                "Authentification, inscription et reinitialisation du mot de passe."
            ),
        },
        {
            "name": "users",
            "description": "Gestion des utilisateurs et de leurs roles.",
        },
        {
            "name": "roles",
            "description": "Gestion des roles (acces admin uniquement).",
        },
        {
            "name": "moodle",
            "description": "Proxy Moodle — profil apprenant agrege pour LLM.",
        },
        {
            "name": "llm",
            "description": "Analyse pedagogique LLM d'un profil apprenant Moodle.",
        },
        {
            "name": "proactivity",
            "description": (
                "Notifications proactives : rappels d'inactivite (M1-008) "
                "et suggestions post-module (M1-009)."
            ),
        },
        {
            "name": "health",
            "description": "Endpoints de diagnostic.",
        },
    ],
    servers=[{"url": "/", "description": "Serveur courant"}],
    lifespan=lifespan,
)

app.state.limiter = limiter

# --- Middlewares ---

setup_cors(app, _settings)
app.middleware("http")(add_security_headers)
app.middleware("http")(log_requests)
register_exception_handlers(app)

# --- Routes ---

register_routers(app, prefix=_settings.API_PREFIX)


@app.get("/", include_in_schema=False)
async def home() -> RedirectResponse:
    return RedirectResponse(url="/docs")
