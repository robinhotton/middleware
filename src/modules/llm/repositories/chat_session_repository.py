"""Repository pour les sessions conversationnelles persistantes."""

from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ....conf.utils import utcnow
from ...shared.base import BaseRepository
from ..models.chat_session import ChatSession, ChatTurn


class ChatSessionRepository(BaseRepository[ChatSession]):
    """Persiste et interroge les sessions conversationnelles et leurs tours."""

    model = ChatSession

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create(
        self, moodle_userid: int, profile_summary: str = ""
    ) -> ChatSession:
        """Cree une nouvelle session pour un utilisateur Moodle."""
        chat_session = ChatSession(
            moodle_userid=moodle_userid,
            profile_summary=profile_summary,
        )
        self.session.add(chat_session)
        await self.session.commit()
        await self.session.refresh(chat_session)
        return chat_session

    async def get_for_user(
        self, session_id: int, moodle_userid: int
    ) -> ChatSession | None:
        """Recupere une session si elle appartient bien au moodle_userid donne."""
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.moodle_userid == moodle_userid,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def touch(self, chat_session: ChatSession) -> None:
        """Met a jour `last_active_at` au timestamp courant."""
        chat_session.last_active_at = utcnow()
        self.session.add(chat_session)
        await self.session.commit()

    async def update_summary(self, chat_session: ChatSession, summary: str) -> None:
        """Persiste un nouveau resume des tours compactes."""
        chat_session.summary = summary
        chat_session.last_active_at = utcnow()
        self.session.add(chat_session)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Tours
    # ------------------------------------------------------------------

    async def append_turn(
        self,
        session_id: int,
        user_message: str,
        assistant_response: str,
    ) -> ChatTurn:
        """Ajoute un tour a la session avec un `turn_num` auto-incremente."""
        next_num_stmt = select(func.coalesce(func.max(ChatTurn.turn_num), 0)).where(
            ChatTurn.session_id == session_id
        )
        result = await self.session.execute(next_num_stmt)
        next_num = int(result.scalar_one()) + 1

        turn = ChatTurn(
            session_id=session_id,
            turn_num=next_num,
            user_message=user_message,
            assistant_response=assistant_response,
        )
        self.session.add(turn)
        await self.session.commit()
        await self.session.refresh(turn)
        return turn

    async def get_active_turns(self, session_id: int) -> Sequence[ChatTurn]:
        """Retourne les tours non compactes ordonnes par turn_num croissant."""
        stmt = (
            select(ChatTurn)
            .where(
                ChatTurn.session_id == session_id,
                ChatTurn.is_compacted == False,  # noqa: E712
            )
            .order_by(ChatTurn.turn_num.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def mark_compacted(self, turn_ids: list[int]) -> None:
        """Marque les tours specifies comme compactes (inclus dans summary)."""
        if not turn_ids:
            return
        stmt = select(ChatTurn).where(ChatTurn.id.in_(turn_ids))
        result = await self.session.execute(stmt)
        for turn in result.scalars().all():
            turn.is_compacted = True
            self.session.add(turn)
        await self.session.commit()
