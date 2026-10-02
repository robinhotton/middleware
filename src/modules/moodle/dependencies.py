"""Dependances FastAPI pour le domaine Moodle."""

from ...conf import get_redis_client, get_settings
from .repositories import MoodleRepository
from .services import MoodleService


def get_moodle_service() -> MoodleService:
    """Cree la chaine d'injection MoodleRepository -> MoodleService."""
    s = get_settings()
    return MoodleService(
        repository=MoodleRepository(
            base_url=s.MOODLE_BASE_URL,
            host_header=s.MOODLE_HTTP_HOST,
            plugin_secret=s.MOODLE_WEBHOOK_SECRET,
            token=s.MOODLE_ADMIN_TOKEN,
        ),
        redis=get_redis_client(),
        cache_ttl=s.MOODLE_CACHE_TTL_SECONDS,
    )
