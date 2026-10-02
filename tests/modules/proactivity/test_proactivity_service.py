"""Tests unitaires pour ProactivityService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.modules.moodle.models.schemas import (
    LearnerProfile,
    MoodleCompletion,
    MoodleResource,
)
from src.modules.proactivity.models.schemas import (
    ProactivityEvent,
    ProactivitySettings,
)
from src.modules.proactivity.services.proactivity_service import ProactivityService


# ============================================================================
# Helpers
# ============================================================================


def _make_settings(**kwargs) -> ProactivitySettings:
    """Cree un ProactivitySettings par defaut avec surcharges optionnelles."""
    defaults = {
        "reminder_enabled": True,
        "reminder_delay_hours": 48,
        "reminder_cron": "0 9 * * 1-5",
        "suggestion_enabled": True,
        "suggestion_cron": "0 10 * * 1-5",
        "notification_channel": "moodle",
        "target_roles": ["student"],
        "moodle_base_url": "https://moodle.example.com",
        "chat_url": "https://moodle.example.com/local/digilearnia/index.php",
        "recommendations_url": "https://moodle.example.com/local/digilearnia/recommendations.php",
    }
    defaults.update(kwargs)
    return ProactivitySettings(**defaults)


def _make_event_repo(**kwargs) -> MagicMock:
    repo = MagicMock()
    repo.has_event_in_window = AsyncMock(return_value=kwargs.get("has_event", False))
    repo.get_last_event = AsyncMock(return_value=kwargs.get("last_event", None))
    repo.get_suggestion_module_ids = AsyncMock(return_value=kwargs.get("module_ids", set()))
    repo.save = AsyncMock(side_effect=lambda x: x)
    repo.session = MagicMock()
    repo.session.commit = AsyncMock()
    return repo


def _make_llm_log_repo(
    inactive_ids: list[int] | None = None,
    active_ids: list[int] | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.get_inactive_userids = AsyncMock(return_value=inactive_ids or [])
    repo.get_active_userids = AsyncMock(return_value=active_ids or [])
    return repo


def _make_http_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_settings = AsyncMock(return_value=_make_settings().model_dump())
    repo.push_notification = AsyncMock()
    repo.aclose = AsyncMock()
    return repo


def _make_moodle_svc(
    profile=None,
    enrolled_learner_ids: set[int] | None = None,
) -> MagicMock:
    svc = MagicMock()
    svc.get_learner_profile = AsyncMock(return_value=profile or _make_minimal_profile())
    svc.get_enrolled_learner_ids = AsyncMock(return_value=enrolled_learner_ids or {42})
    return svc


def _make_llm_repo(text: str = "Essayez ce module supplementaire.") -> MagicMock:
    from src.modules.llm.repositories.llm_repository import LLMCompletion
    repo = MagicMock()
    repo.chat_completion = AsyncMock(
        return_value=LLMCompletion(
            text=text, prompt_tokens=20, completion_tokens=30, duration_ms=300
        )
    )
    return repo


def _make_minimal_profile(
    moodle_userid: int = 42,
    completions: dict | None = None,
    resources: dict | None = None,
) -> LearnerProfile:
    return LearnerProfile(
        moodle_userid=moodle_userid,
        username="jdoe",
        fullname="John Doe",
        email="jdoe@example.com",
        completion_by_course=completions or {},
        resources_by_course=resources or {},
    )


def _make_svc(
    event_repo=None,
    llm_log_repo=None,
    http_repo=None,
    moodle_svc=None,
    llm_repo=None,
    redis=None,
) -> ProactivityService:
    return ProactivityService(
        event_repo=event_repo or _make_event_repo(),
        llm_log_repo=llm_log_repo or _make_llm_log_repo(),
        http_repo=http_repo or _make_http_repo(),
        moodle_svc=moodle_svc or _make_moodle_svc(),
        llm_repo=llm_repo or _make_llm_repo(),
        redis=redis,
    )


# ============================================================================
# Tests get_proactivity_settings
# ============================================================================


async def test_get_settings_cache_miss():
    """Sans Redis : appelle http_repo.get_settings et retourne un ProactivitySettings."""
    http_repo = _make_http_repo()
    svc = _make_svc(http_repo=http_repo, redis=None)

    result = await svc.get_proactivity_settings()

    http_repo.get_settings.assert_awaited_once()
    assert result.reminder_enabled is True
    assert result.reminder_delay_hours == 48


async def test_get_settings_cache_hit():
    """Avec Redis cache chaud : n'appelle pas http_repo.get_settings."""
    http_repo = _make_http_repo()
    mock_redis = MagicMock()
    settings_obj = _make_settings()
    mock_redis.get = AsyncMock(return_value=settings_obj.model_dump_json())
    mock_redis.set = AsyncMock()

    svc = _make_svc(http_repo=http_repo, redis=mock_redis)
    result = await svc.get_proactivity_settings()

    http_repo.get_settings.assert_not_awaited()
    assert result.reminder_delay_hours == 48


async def test_get_settings_cache_miss_stores_in_redis():
    """Sans cache : stocke le resultat dans Redis."""
    http_repo = _make_http_repo()
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    svc = _make_svc(http_repo=http_repo, redis=mock_redis)
    await svc.get_proactivity_settings()

    mock_redis.set.assert_awaited_once()


# ============================================================================
# Tests run_reminder_job (M1-008)
# ============================================================================


async def test_reminder_job_disabled():
    """reminder_enabled=False → 0 notifications, aucun appel Moodle."""
    http_repo = _make_http_repo()
    http_repo.get_settings = AsyncMock(
        return_value=_make_settings(reminder_enabled=False).model_dump()
    )
    svc = _make_svc(http_repo=http_repo)

    count = await svc.run_reminder_job()

    assert count == 0
    http_repo.push_notification.assert_not_awaited()


async def test_reminder_job_sends_notification():
    """Apprenant inscrit Moodle, inactif (pas de chat recent) → notification envoyee."""
    event_repo = _make_event_repo(has_event=False)
    llm_log_repo = _make_llm_log_repo(active_ids=[])
    http_repo = _make_http_repo()
    moodle_svc = _make_moodle_svc(enrolled_learner_ids={42})

    svc = _make_svc(
        event_repo=event_repo,
        llm_log_repo=llm_log_repo,
        http_repo=http_repo,
        moodle_svc=moodle_svc,
    )
    count = await svc.run_reminder_job()

    assert count == 1
    http_repo.push_notification.assert_awaited_once()
    call_kwargs = http_repo.push_notification.call_args.kwargs
    assert call_kwargs["type_"] == "reminder"
    assert call_kwargs["moodle_userid"] == 42
    event_repo.save.assert_awaited_once()


async def test_reminder_job_skips_duplicate():
    """Reminder deja envoye dans la fenetre → skip."""
    event_repo = _make_event_repo(has_event=True)
    llm_log_repo = _make_llm_log_repo(active_ids=[])
    http_repo = _make_http_repo()
    moodle_svc = _make_moodle_svc(enrolled_learner_ids={42})

    svc = _make_svc(
        event_repo=event_repo,
        llm_log_repo=llm_log_repo,
        http_repo=http_repo,
        moodle_svc=moodle_svc,
    )
    count = await svc.run_reminder_job()

    assert count == 0
    http_repo.push_notification.assert_not_awaited()


async def test_reminder_job_skips_trainer():
    """Formateur exclu par get_enrolled_learner_ids → aucun utilisateur a traiter."""
    event_repo = _make_event_repo(has_event=False)
    llm_log_repo = _make_llm_log_repo(active_ids=[])
    http_repo = _make_http_repo()
    # Aucun apprenant retourne (le formateur est deja filtre par MoodleService)
    moodle_svc = _make_moodle_svc(enrolled_learner_ids=set())

    svc = _make_svc(
        event_repo=event_repo,
        llm_log_repo=llm_log_repo,
        http_repo=http_repo,
        moodle_svc=moodle_svc,
    )
    count = await svc.run_reminder_job()

    assert count == 0
    http_repo.push_notification.assert_not_awaited()


# ============================================================================
# Tests run_suggestion_job (M1-009)
# ============================================================================


async def test_suggestion_job_disabled():
    """suggestion_enabled=False → 0 suggestions."""
    http_repo = _make_http_repo()
    http_repo.get_settings = AsyncMock(
        return_value=_make_settings(suggestion_enabled=False).model_dump()
    )
    svc = _make_svc(http_repo=http_repo)

    count = await svc.run_suggestion_job()

    assert count == 0
    http_repo.push_notification.assert_not_awaited()


async def test_suggestion_job_new_module():
    """Module complete recemment non suggere → LLM appele + notification envoyee."""
    now = datetime.now(UTC).replace(tzinfo=None)
    completed_ts = int((now - timedelta(hours=1)).replace(tzinfo=UTC).timestamp())
    last_check_dt = now - timedelta(days=2)

    last_check_event = ProactivityEvent(
        id=1,
        moodle_userid=42,
        event_type="suggestion_check",
        created_at=last_check_dt,
    )

    completion = MoodleCompletion(cmid=101, modname="page", state=1, timecompleted=completed_ts)
    resource = MoodleResource(
        cmid=101, name="Introduction au Python", modname="page",
        section_name="Section 1",
    )
    profile = _make_minimal_profile(
        completions={1: [completion]},
        resources={1: [resource]},
    )

    event_repo = _make_event_repo(last_event=last_check_event, module_ids=set())
    http_repo = _make_http_repo()
    moodle_svc = _make_moodle_svc(profile=profile, enrolled_learner_ids={42})
    llm_repo = _make_llm_repo()

    svc = _make_svc(
        event_repo=event_repo,
        http_repo=http_repo,
        moodle_svc=moodle_svc,
        llm_repo=llm_repo,
    )
    count = await svc.run_suggestion_job()

    assert count == 1
    llm_repo.chat_completion.assert_awaited_once()
    http_repo.push_notification.assert_awaited_once()
    call_kwargs = http_repo.push_notification.call_args.kwargs
    assert call_kwargs["type_"] == "suggestion"
    assert call_kwargs["moodle_userid"] == 42


async def test_suggestion_job_already_suggested():
    """Module deja suggere → skip."""
    now = datetime.now(UTC).replace(tzinfo=None)
    completed_ts = int((now - timedelta(hours=1)).replace(tzinfo=UTC).timestamp())
    last_check_dt = now - timedelta(days=2)

    last_check_event = ProactivityEvent(
        id=1,
        moodle_userid=42,
        event_type="suggestion_check",
        created_at=last_check_dt,
    )
    completion = MoodleCompletion(cmid=101, modname="page", state=1, timecompleted=completed_ts)
    profile = _make_minimal_profile(completions={1: [completion]})

    event_repo = _make_event_repo(last_event=last_check_event, module_ids={101})
    http_repo = _make_http_repo()
    moodle_svc = _make_moodle_svc(profile=profile, enrolled_learner_ids={42})
    llm_repo = _make_llm_repo()

    svc = _make_svc(
        event_repo=event_repo,
        http_repo=http_repo,
        moodle_svc=moodle_svc,
        llm_repo=llm_repo,
    )
    count = await svc.run_suggestion_job()

    assert count == 0
    llm_repo.chat_completion.assert_not_awaited()
    http_repo.push_notification.assert_not_awaited()


async def test_suggestion_job_no_new_completion():
    """Aucun module complete depuis le dernier check → 0 suggestions."""
    now = datetime.now(UTC).replace(tzinfo=None)
    # Module complete AVANT le dernier check
    old_completed_ts = int((now - timedelta(days=5)).replace(tzinfo=UTC).timestamp())
    last_check_dt = now - timedelta(days=2)

    last_check_event = ProactivityEvent(
        id=1,
        moodle_userid=42,
        event_type="suggestion_check",
        created_at=last_check_dt,
    )
    completion = MoodleCompletion(cmid=101, modname="page", state=1, timecompleted=old_completed_ts)
    profile = _make_minimal_profile(completions={1: [completion]})

    event_repo = _make_event_repo(last_event=last_check_event, module_ids=set())
    http_repo = _make_http_repo()
    moodle_svc = _make_moodle_svc(profile=profile, enrolled_learner_ids={42})
    llm_repo = _make_llm_repo()

    svc = _make_svc(
        event_repo=event_repo,
        http_repo=http_repo,
        moodle_svc=moodle_svc,
        llm_repo=llm_repo,
    )
    count = await svc.run_suggestion_job()

    assert count == 0
    llm_repo.chat_completion.assert_not_awaited()
    http_repo.push_notification.assert_not_awaited()
    # suggestion_check doit quand meme etre enregistre
    event_repo.save.assert_awaited()
