"""Tests pour la logique de session conversationnelle dans LLMService.

Couvre :
- cache profile_summary (hit, miss, fallback en cas d'echec LLM)
- creation/reutilisation de session
- compact automatique au-dela du seuil
- structure du prompt envoye au LLM
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from src.exceptions import NotFoundException
from src.modules.llm.models.chat_session import ChatSession, ChatTurn  # noqa: F401
from src.modules.llm.repositories.chat_session_repository import ChatSessionRepository
from src.modules.llm.repositories.llm_repository import LLMCompletion
from src.modules.llm.services.llm_service import (
    _COMPACT_AFTER_TURNS,
    LLMService,
    _build_chat_messages,
)
from src.modules.moodle.models.schemas import (
    LearnerProfile,
    MoodleCourse,
    MoodleUserRole,
)

# ============================================================================
# Fixtures BDD + service
# ============================================================================


@pytest.fixture(name="db_session")
async def db_session_fixture() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


@pytest.fixture(name="chat_repo")
def chat_repo_fixture(db_session: AsyncSession) -> ChatSessionRepository:
    return ChatSessionRepository(db_session)


def _llm_repo(text: str = "Reponse factice") -> MagicMock:
    repo = MagicMock()
    repo._model = "mistral-small-latest"
    repo.chat_completion = AsyncMock(
        return_value=LLMCompletion(
            text=text, prompt_tokens=10, completion_tokens=20, duration_ms=500
        )
    )
    return repo


def _log_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert = AsyncMock()
    repo.sum_tokens_for_user_since = AsyncMock(return_value=0)
    return repo


def _make_service(
    chat_repo: ChatSessionRepository,
    llm_repo=None,
    cache=None,
    profile_summary_ttl: int = 300,
) -> tuple[LLMService, MagicMock]:
    lr = llm_repo or _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=_log_repo(),
        cache=cache,
        chat_session_repository=chat_repo,
        profile_summary_ttl=profile_summary_ttl,
    )
    return svc, lr


def _profile(userid: int = 1, fullname: str = "Alice") -> LearnerProfile:
    p = LearnerProfile(
        moodle_userid=userid,
        username="u",
        fullname=fullname,
        email="a@test.com",
    )
    p.courses = [MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)]
    return p


# ============================================================================
# Cache profile_summary
# ============================================================================


async def test_profile_summary_cache_hit_skips_llm_call(
    chat_repo: ChatSessionRepository,
):
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=b"resume cache")
    cache.set = AsyncMock()
    svc, lr = _make_service(chat_repo, cache=cache)

    summary = await svc._profile_summary_for(_profile())

    assert summary == "resume cache"
    lr.chat_completion.assert_not_awaited()


async def test_profile_summary_cache_miss_calls_llm_and_stores(
    chat_repo: ChatSessionRepository,
):
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    svc, lr = _make_service(chat_repo, llm_repo=_llm_repo("resume genere"), cache=cache)

    summary = await svc._profile_summary_for(_profile(userid=42))

    assert summary == "resume genere"
    lr.chat_completion.assert_awaited_once()
    cache.set.assert_awaited_once()
    args, kwargs = cache.set.call_args
    assert args[0] == "llm:profile_summary:42"
    assert args[1] == "resume genere"
    assert kwargs.get("ex") == 300


async def test_profile_summary_fallback_on_llm_error(
    chat_repo: ChatSessionRepository,
):
    """Si le LLM echoue, on retombe sur la synthese deja calculee localement."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    failing_repo = _llm_repo()
    failing_repo.chat_completion = AsyncMock(side_effect=RuntimeError("boom"))
    svc, _ = _make_service(chat_repo, llm_repo=failing_repo, cache=cache)

    summary = await svc._profile_summary_for(_profile())
    # _build_learner_context renvoie une chaine non vide pour ce profil
    assert "Profil de l'apprenant" in summary
    cache.set.assert_not_awaited()


# ============================================================================
# Chat avec session
# ============================================================================


async def test_chat_creates_new_session_when_session_id_none(
    chat_repo: ChatSessionRepository,
):
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=b"resume cache")
    cache.set = AsyncMock()
    svc, lr = _make_service(chat_repo, cache=cache)

    response = await svc.chat(
        message="Aide",
        profiles=[_profile(userid=42)],
        moodle_userid=42,
        role=MoodleUserRole.STUDENT,
    )

    assert response.session_id is not None
    # Une session a bien ete creee en BDD
    persisted = await chat_repo.get_for_user(response.session_id, moodle_userid=42)
    assert persisted is not None
    assert persisted.profile_summary == "resume cache"
    # Et un tour persiste
    turns = await chat_repo.get_active_turns(response.session_id)
    assert len(turns) == 1
    assert turns[0].user_message == "Aide"
    assert turns[0].assistant_response == "Reponse factice"


async def test_chat_reuses_existing_session(chat_repo: ChatSessionRepository):
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=b"x")
    cache.set = AsyncMock()
    svc, lr = _make_service(chat_repo, cache=cache)

    # Tour 1 : nouvelle session
    r1 = await svc.chat(
        message="Q1",
        profiles=[_profile(userid=42)],
        moodle_userid=42,
    )
    # Tour 2 : on reutilise la meme session
    r2 = await svc.chat(
        message="Q2",
        profiles=[_profile(userid=42)],
        moodle_userid=42,
        session_id=r1.session_id,
    )

    assert r2.session_id == r1.session_id
    turns = await chat_repo.get_active_turns(r1.session_id)
    assert [t.user_message for t in turns] == ["Q1", "Q2"]


async def test_chat_unknown_session_raises_not_found(
    chat_repo: ChatSessionRepository,
):
    svc, _ = _make_service(chat_repo)
    with pytest.raises(NotFoundException):
        await svc.chat(
            message="Q",
            profiles=[_profile(userid=42)],
            moodle_userid=42,
            session_id=999999,
        )


async def test_chat_session_isolated_between_users(
    chat_repo: ChatSessionRepository,
):
    """Un userid B ne peut pas reprendre une session d'un userid A."""
    svc, _ = _make_service(chat_repo)
    r_a = await svc.chat(
        message="Q",
        profiles=[_profile(userid=1)],
        moodle_userid=1,
    )
    with pytest.raises(NotFoundException):
        await svc.chat(
            message="Q",
            profiles=[_profile(userid=2)],
            moodle_userid=2,
            session_id=r_a.session_id,
        )


async def test_chat_legacy_path_when_no_session_repository():
    """Sans `chat_session_repository`, le service garde le comportement legacy."""
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=_log_repo(),
        chat_session_repository=None,
    )
    response = await svc.chat(message="Q", moodle_userid=42)
    assert response.session_id is None
    lr.chat_completion.assert_awaited_once()


# ============================================================================
# Compact automatique
# ============================================================================


async def test_compact_no_op_under_threshold(chat_repo: ChatSessionRepository):
    """Sous le seuil de tours, _compact_session_if_needed ne fait rien."""
    svc, lr = _make_service(chat_repo)
    s = await chat_repo.create(moodle_userid=1)
    for i in range(_COMPACT_AFTER_TURNS):
        await chat_repo.append_turn(s.id, f"Q{i}", f"R{i}")

    lr.chat_completion.reset_mock()
    await svc._compact_session_if_needed(s)

    # Aucun appel LLM, aucun tour marque compact
    lr.chat_completion.assert_not_awaited()
    active = await chat_repo.get_active_turns(s.id)
    assert len(active) == _COMPACT_AFTER_TURNS


async def test_compact_triggered_above_threshold(chat_repo: ChatSessionRepository):
    """Au-dessus du seuil, le compact LLM est declenche et marque les vieux tours."""
    svc, lr = _make_service(chat_repo, llm_repo=_llm_repo("resume conv"))
    s = await chat_repo.create(moodle_userid=1)
    n = _COMPACT_AFTER_TURNS + 3  # 3 tours au-dessus du seuil
    for i in range(n):
        await chat_repo.append_turn(s.id, f"Q{i}", f"R{i}")

    lr.chat_completion.reset_mock()
    await svc._compact_session_if_needed(s)

    # Un appel LLM : le compact
    lr.chat_completion.assert_awaited_once()

    refreshed = await chat_repo.get_for_user(s.id, moodle_userid=1)
    assert refreshed.summary == "resume conv"

    # Apres compact, seuls les _MAX_RECENT_TURNS derniers restent actifs
    active = await chat_repo.get_active_turns(s.id)
    from src.modules.llm.services.llm_service import _MAX_RECENT_TURNS

    assert len(active) == _MAX_RECENT_TURNS


async def test_compact_failure_keeps_turns_active(chat_repo: ChatSessionRepository):
    """Si le compact LLM echoue, on n'altere pas la session (graceful degradation)."""
    failing_repo = _llm_repo()
    failing_repo.chat_completion = AsyncMock(side_effect=RuntimeError("boom"))
    svc, _ = _make_service(chat_repo, llm_repo=failing_repo)
    s = await chat_repo.create(moodle_userid=1)
    n = _COMPACT_AFTER_TURNS + 2
    for i in range(n):
        await chat_repo.append_turn(s.id, f"Q{i}", f"R{i}")

    await svc._compact_session_if_needed(s)

    # Aucun tour marque compact, summary inchange
    refreshed = await chat_repo.get_for_user(s.id, moodle_userid=1)
    assert refreshed.summary == ""
    active = await chat_repo.get_active_turns(s.id)
    assert len(active) == n


# ============================================================================
# _build_chat_messages : structure du prompt
# ============================================================================


def test_build_chat_messages_structure_minimal_session():
    chat_session = ChatSession(moodle_userid=1, profile_summary="", summary="")
    messages = _build_chat_messages(
        role=MoodleUserRole.STUDENT,
        prompt_id=None,
        chat_session=chat_session,
        recent_turns=[],
        new_message="Salut",
    )
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "Salut"}


def test_build_chat_messages_includes_profile_and_session_summaries():
    chat_session = ChatSession(
        moodle_userid=1,
        profile_summary="Alice, niveau intermediaire",
        summary="Discussion precedente sur les closures.",
    )
    messages = _build_chat_messages(
        role=MoodleUserRole.STUDENT,
        prompt_id=None,
        chat_session=chat_session,
        recent_turns=[],
        new_message="Question",
    )
    system_content = messages[0]["content"]
    assert "Profil apprenant (resume)" in system_content
    assert "Alice, niveau intermediaire" in system_content
    assert "Resume de la conversation precedente" in system_content
    assert "Discussion precedente sur les closures." in system_content


def test_build_chat_messages_alternates_recent_turns():
    chat_session = ChatSession(moodle_userid=1)
    turn = ChatTurn(
        session_id=1, turn_num=1, user_message="Q1", assistant_response="R1"
    )
    messages = _build_chat_messages(
        role=MoodleUserRole.STUDENT,
        prompt_id=None,
        chat_session=chat_session,
        recent_turns=[turn],
        new_message="Q2",
    )
    # Ordre attendu : system, user Q1, assistant R1, user Q2
    assert len(messages) == 4
    assert messages[1] == {"role": "user", "content": "Q1"}
    assert messages[2] == {"role": "assistant", "content": "R1"}
    assert messages[3] == {"role": "user", "content": "Q2"}
