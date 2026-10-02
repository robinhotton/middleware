"""Dependances FastAPI pour le domaine proactivite."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...conf import get_redis_client, get_session, get_settings
from ..llm.repositories import LLMLogRepository, LLMRepository
from ..moodle.repositories import MoodleRepository
from ..moodle.services import MoodleService
from .repositories.proactivity_repository import (
    ProactivityEventRepository,
    ProactivityHttpRepository,
)
from .services import ProactivityService


def get_proactivity_service(
    session: AsyncSession = Depends(get_session),
) -> ProactivityService:
    """Cree la chaine d'injection complete pour le domaine proactivite."""
    s = get_settings()
    redis = get_redis_client()
    moodle_repo = MoodleRepository(
        base_url=s.MOODLE_BASE_URL,
        token=s.MOODLE_ADMIN_TOKEN,
        host_header=s.MOODLE_HTTP_HOST,
        plugin_secret=s.MOODLE_WEBHOOK_SECRET,
    )
    return ProactivityService(
        event_repo=ProactivityEventRepository(session),
        llm_log_repo=LLMLogRepository(session),
        http_repo=ProactivityHttpRepository(
            base_url=s.MOODLE_BASE_URL,
            secret=s.MOODLE_WEBHOOK_SECRET,
            http_host=s.MOODLE_HTTP_HOST,
        ),
        moodle_svc=MoodleService(
            repository=moodle_repo,
            redis=redis,
            cache_ttl=s.MOODLE_CACHE_TTL_SECONDS,
        ),
        llm_repo=LLMRepository(
            api_key=s.MISTRAL_API_KEY,
            base_url=s.MISTRAL_BASE_URL,
            model=s.MISTRAL_MODEL,
            max_tokens=s.MISTRAL_MAX_TOKENS,
        ),
        redis=redis,
    )
