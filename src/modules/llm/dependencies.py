"""Dependances FastAPI pour le domaine LLM."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...conf import get_redis_client, get_session, get_settings
from .repositories import ChatSessionRepository, LLMLogRepository, LLMRepository
from .services import LLMService


def get_llm_service(session: AsyncSession = Depends(get_session)) -> LLMService:
    """Cree la chaine LLMRepository + LLMLogRepository -> LLMService."""
    s = get_settings()
    return LLMService(
        repository=LLMRepository(
            api_key=s.MISTRAL_API_KEY,
            base_url=s.MISTRAL_BASE_URL,
            model=s.MISTRAL_MODEL,
            max_tokens=s.MISTRAL_MAX_TOKENS,
            timeout=s.LLM_HTTP_TIMEOUT_SECONDS,
        ),
        log_repository=LLMLogRepository(session),
        cache=get_redis_client(),
        model_light=s.MISTRAL_MODEL_LIGHT,
        daily_token_limit=s.LLM_DAILY_TOKEN_LIMIT_PER_USER,
        max_prompt_tokens=s.LLM_MAX_PROMPT_TOKENS,
        chat_session_repository=ChatSessionRepository(session),
        profile_summary_ttl=s.MOODLE_CACHE_TTL_SECONDS,
    )
