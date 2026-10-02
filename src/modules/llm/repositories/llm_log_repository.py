"""Repository pour la persistance et la consultation des logs LLM."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from ...shared.base import BaseRepository
from ..models.log import LLMLog


class LLMLogRepository(BaseRepository[LLMLog]):
    """Persiste et interroge les metriques d'appel LLM en base."""

    model = LLMLog

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def insert(self, log: LLMLog) -> None:
        """Insere un log et commite immediatement."""
        self.session.add(log)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Lecture filtree et statistiques
    # ------------------------------------------------------------------

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 20,
        moodle_userid: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Sequence[LLMLog]:
        """Recupere les logs filtres et pagines (plus recent en premier)."""
        stmt = select(LLMLog).order_by(LLMLog.created_at.desc())
        if moodle_userid is not None:
            stmt = stmt.where(LLMLog.moodle_userid == moodle_userid)
        if date_from is not None:
            stmt = stmt.where(LLMLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(LLMLog.created_at <= date_to)
        result = await self.session.execute(stmt.offset(skip).limit(limit))
        return result.scalars().all()

    async def count_filtered(
        self,
        moodle_userid: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """Compte les logs selon les memes filtres."""
        stmt = select(func.count()).select_from(LLMLog)
        if moodle_userid is not None:
            stmt = stmt.where(LLMLog.moodle_userid == moodle_userid)
        if date_from is not None:
            stmt = stmt.where(LLMLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(LLMLog.created_at <= date_to)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def sum_tokens_for_user_since(
        self, moodle_userid: int, since: datetime
    ) -> int:
        """Retourne la somme prompt+completion tokens pour un user depuis `since`."""
        stmt = select(
            func.coalesce(func.sum(LLMLog.prompt_tokens + LLMLog.completion_tokens), 0)
        ).where(
            LLMLog.moodle_userid == moodle_userid,
            LLMLog.created_at >= since,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def get_inactive_userids(self, cutoff: datetime) -> list[int]:
        """Retourne les moodle_userid dont le DERNIER log est avant `cutoff`.

        Utilise pour identifier les apprenants inactifs (M1-008).
        Exclut les utilisateurs ayant un log plus recent que cutoff.
        """
        # Sous-requete : users actifs apres cutoff
        active_sub = (
            select(LLMLog.moodle_userid)
            .where(
                col(LLMLog.moodle_userid).is_not(None),
                LLMLog.created_at > cutoff,
            )
            .distinct()
            .scalar_subquery()
        )
        stmt = (
            select(LLMLog.moodle_userid)
            .where(
                col(LLMLog.moodle_userid).is_not(None),
                col(LLMLog.moodle_userid).not_in(active_sub),
            )
            .distinct()
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_active_userids(self, since: datetime) -> list[int]:
        """Retourne les moodle_userid avec au moins un log depuis `since`.

        Utilise pour identifier les apprenants actifs recemment (M1-009).
        """
        stmt = (
            select(LLMLog.moodle_userid)
            .where(
                col(LLMLog.moodle_userid).is_not(None),
                LLMLog.created_at >= since,
            )
            .distinct()
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_stats(
        self,
        moodle_userid: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Mapping:
        """Retourne les statistiques agregees des appels LLM."""
        stmt = select(
            func.count().label("total_calls"),
            func.coalesce(func.sum(LLMLog.prompt_tokens), 0).label("total_prompt"),
            func.coalesce(func.sum(LLMLog.completion_tokens), 0).label(
                "total_completion"
            ),
            func.coalesce(func.avg(LLMLog.prompt_tokens), 0).label("avg_prompt"),
            func.coalesce(func.avg(LLMLog.completion_tokens), 0).label(
                "avg_completion"
            ),
            func.coalesce(func.avg(LLMLog.duration_ms), 0).label("avg_duration"),
        ).select_from(LLMLog)
        if moodle_userid is not None:
            stmt = stmt.where(LLMLog.moodle_userid == moodle_userid)
        if date_from is not None:
            stmt = stmt.where(LLMLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(LLMLog.created_at <= date_to)
        result = await self.session.execute(stmt)
        return result.mappings().one()
