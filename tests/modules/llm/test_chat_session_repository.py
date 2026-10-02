"""Tests unitaires pour ChatSessionRepository (CRUD + tours)."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

# Import explicite pour que SQLModel.metadata enregistre les tables
from src.modules.llm.models.chat_session import ChatSession, ChatTurn  # noqa: F401
from src.modules.llm.repositories.chat_session_repository import ChatSessionRepository


@pytest.fixture(name="session")
async def session_fixture() -> AsyncGenerator[AsyncSession]:
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


@pytest.fixture(name="repo")
def repo_fixture(session: AsyncSession) -> ChatSessionRepository:
    return ChatSessionRepository(session)


# ============================================================================
# create + get_for_user
# ============================================================================


async def test_create_returns_persisted_session(repo: ChatSessionRepository):
    s = await repo.create(moodle_userid=42, profile_summary="resume")
    assert s.id is not None
    assert s.moodle_userid == 42
    assert s.profile_summary == "resume"
    assert s.summary == ""


async def test_get_for_user_returns_session_when_owner_matches(
    repo: ChatSessionRepository,
):
    created = await repo.create(moodle_userid=42)
    fetched = await repo.get_for_user(created.id, moodle_userid=42)
    assert fetched is not None
    assert fetched.id == created.id


async def test_get_for_user_returns_none_for_other_user(
    repo: ChatSessionRepository,
):
    created = await repo.create(moodle_userid=42)
    fetched = await repo.get_for_user(created.id, moodle_userid=99)
    assert fetched is None


async def test_get_for_user_returns_none_when_session_missing(
    repo: ChatSessionRepository,
):
    assert await repo.get_for_user(9999, moodle_userid=42) is None


# ============================================================================
# append_turn
# ============================================================================


async def test_append_turn_assigns_incremental_turn_num(
    repo: ChatSessionRepository,
):
    s = await repo.create(moodle_userid=1)
    t1 = await repo.append_turn(s.id, user_message="Q1", assistant_response="R1")
    t2 = await repo.append_turn(s.id, user_message="Q2", assistant_response="R2")
    t3 = await repo.append_turn(s.id, user_message="Q3", assistant_response="R3")
    assert t1.turn_num == 1
    assert t2.turn_num == 2
    assert t3.turn_num == 3


async def test_append_turn_isolates_sessions(repo: ChatSessionRepository):
    s1 = await repo.create(moodle_userid=1)
    s2 = await repo.create(moodle_userid=2)
    await repo.append_turn(s1.id, "Q", "R")
    t = await repo.append_turn(s2.id, "Q", "R")
    assert t.turn_num == 1


# ============================================================================
# get_active_turns
# ============================================================================


async def test_get_active_turns_returns_only_non_compacted_in_order(
    repo: ChatSessionRepository,
):
    s = await repo.create(moodle_userid=1)
    t1 = await repo.append_turn(s.id, "Q1", "R1")
    t2 = await repo.append_turn(s.id, "Q2", "R2")
    t3 = await repo.append_turn(s.id, "Q3", "R3")
    await repo.mark_compacted([t1.id])

    active = await repo.get_active_turns(s.id)
    nums = [t.turn_num for t in active]
    assert nums == [t2.turn_num, t3.turn_num]


async def test_get_active_turns_empty_session(repo: ChatSessionRepository):
    s = await repo.create(moodle_userid=1)
    assert list(await repo.get_active_turns(s.id)) == []


# ============================================================================
# mark_compacted + update_summary + touch
# ============================================================================


async def test_mark_compacted_no_op_for_empty_list(repo: ChatSessionRepository):
    s = await repo.create(moodle_userid=1)
    t = await repo.append_turn(s.id, "Q", "R")
    await repo.mark_compacted([])
    active = await repo.get_active_turns(s.id)
    assert [x.id for x in active] == [t.id]


async def test_update_summary_persists_summary_and_bumps_last_active(
    repo: ChatSessionRepository,
):
    s = await repo.create(moodle_userid=1)
    initial = s.last_active_at
    await repo.update_summary(s, "nouveau resume")
    refreshed = await repo.get_for_user(s.id, moodle_userid=1)
    assert refreshed.summary == "nouveau resume"
    assert refreshed.last_active_at >= initial


async def test_touch_bumps_last_active(repo: ChatSessionRepository):
    s = await repo.create(moodle_userid=1)
    initial = s.last_active_at
    await repo.touch(s)
    assert s.last_active_at >= initial
