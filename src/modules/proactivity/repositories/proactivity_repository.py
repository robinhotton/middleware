"""Repositories du domaine proactivite : stockage SQL et appels HTTP plugin."""

import logging
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from ....exceptions import MoodleAPIException
from ...shared.base import BaseRepository
from ..models.schemas import ProactivityEvent, ProactivitySettingsRecord

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_SETTINGS_PATH = "/local/digilearnia/proactivity_settings.php"
_PUSH_PATH = "/local/digilearnia/push_notification.php"


class ProactivityEventRepository(BaseRepository[ProactivityEvent]):
    """CRUD pour la table proactivity_event."""

    model = ProactivityEvent

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def has_event_in_window(
        self, moodle_userid: int, event_type: str, since: datetime
    ) -> bool:
        """Retourne True si un evenement du type donne existe depuis `since`."""
        stmt = select(ProactivityEvent).where(
            ProactivityEvent.moodle_userid == moodle_userid,
            ProactivityEvent.event_type == event_type,
            ProactivityEvent.created_at >= since,
        )
        result = await self.session.execute(stmt.limit(1))
        return result.scalars().first() is not None

    async def get_last_event(
        self, moodle_userid: int, event_type: str
    ) -> ProactivityEvent | None:
        """Retourne le dernier evenement du type donne pour cet utilisateur."""
        stmt = (
            select(ProactivityEvent)
            .where(
                ProactivityEvent.moodle_userid == moodle_userid,
                ProactivityEvent.event_type == event_type,
            )
            .order_by(col(ProactivityEvent.created_at).desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_suggestion_module_ids(self, moodle_userid: int) -> set[int]:
        """Retourne l'ensemble des module_id deja suggeres a cet utilisateur."""
        stmt = select(ProactivityEvent).where(
            ProactivityEvent.moodle_userid == moodle_userid,
            ProactivityEvent.event_type == "suggestion",
        )
        result = await self.session.execute(stmt)
        events = result.scalars().all()
        module_ids: set[int] = set()
        for event in events:
            if event.payload and "module_id" in event.payload:
                module_ids.add(int(event.payload["module_id"]))
        return module_ids


class ProactivitySettingsRepository(BaseRepository[ProactivitySettingsRecord]):
    """CRUD pour la table proactivity_settings_record."""

    model = ProactivitySettingsRecord

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_latest(self) -> ProactivitySettingsRecord | None:
        """Retourne le dernier enregistrement de settings (le plus recent)."""
        stmt = (
            select(ProactivitySettingsRecord)
            .order_by(col(ProactivitySettingsRecord.fetched_at).desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def upsert(self, record: ProactivitySettingsRecord) -> ProactivitySettingsRecord:
        """Insere un nouvel enregistrement de settings et purge les anciens (garde les 5 derniers)."""
        self.session.add(record)
        await self.session.flush()

        # Purge : on ne garde que les 5 plus recents
        subq = (
            select(ProactivitySettingsRecord.id)
            .order_by(col(ProactivitySettingsRecord.fetched_at).desc())
            .offset(5)
        )
        result = await self.session.execute(subq)
        old_ids = [row[0] for row in result.all()]
        if old_ids:
            from sqlalchemy import delete

            await self.session.execute(
                delete(ProactivitySettingsRecord).where(
                    ProactivitySettingsRecord.id.in_(old_ids)  # type: ignore[union-attr]
                )
            )

        await self.session.commit()
        return record


async def _log_response(response: httpx.Response) -> None:
    """Event hook : loggue chaque reponse HTTP du plugin proactivite."""
    await response.aread()
    logger.info(
        "Proactivity HTTP <- %s %s  body_preview=%.200s",
        response.status_code,
        response.url,
        response.text,
    )


class ProactivityHttpRepository:
    """Encapsule les appels HTTP vers les endpoints proactivite du plugin Moodle.

    Authentification Bearer avec MOODLE_WEBHOOK_SECRET.
    """

    def __init__(
        self,
        base_url: str,
        secret: str,
        http_host: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = secret
        headers: dict[str, str] = {"Authorization": f"Bearer {secret}"}
        if http_host:
            headers["Host"] = http_host.strip()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=False,
            event_hooks={"response": [_log_response]},
        )

    async def get_settings(self) -> dict:
        """Recupere la configuration proactivite depuis le plugin Moodle."""
        logger.info("Proactivity : recuperation des settings depuis %s", self._base_url)
        try:
            response = await self._client.get(_SETTINGS_PATH)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleAPIException(
                f"Proactivity settings HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise MoodleAPIException(
                f"Impossible de joindre Moodle (proactivity_settings) : {exc}"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise MoodleAPIException(
                "Reponse proactivity_settings non-JSON"
            ) from exc

    async def push_notification(
        self,
        type_: str,
        moodle_userid: int,
        subject: str,
        message: str,
        url: str = "",
    ) -> None:
        """Envoie une notification proactive via le plugin Moodle.

        Leve MoodleAPIException en cas d'erreur HTTP ou de reponse invalide.
        """
        body = {
            "type": type_,
            "moodle_userid": moodle_userid,
            "subject": subject,
            "message": message,
        }
        if url:
            body["url"] = url

        logger.info(
            "Proactivity : push notification type=%s userid=%d",
            type_,
            moodle_userid,
        )
        try:
            response = await self._client.post(_PUSH_PATH, json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleAPIException(
                f"push_notification HTTP {exc.response.status_code} userid={moodle_userid}"
            ) from exc
        except httpx.RequestError as exc:
            raise MoodleAPIException(
                f"Impossible de joindre Moodle (push_notification) : {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise MoodleAPIException(
                "Reponse push_notification non-JSON"
            ) from exc

        if not isinstance(data, dict) or data.get("status") != "ok":
            raise MoodleAPIException(
                f"push_notification reponse inattendue : {str(data)[:200]}"
            )

    async def aclose(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        await self._client.aclose()
