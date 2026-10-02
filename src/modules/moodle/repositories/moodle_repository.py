"""Acces aux donnees Moodle via HTTP (couche repository)."""

import logging
from typing import Any

import httpx

from ....exceptions import MoodleAPIException

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_REST_PATH = "/webservice/rest/server.php"
_RELATED_LEARNERS_PATH = "/local/digilearnia/related_learners.php"


async def _log_response(response: httpx.Response) -> None:
    """Event hook : loggue chaque reponse HTTP, y compris les redirects intermediaires."""
    await response.aread()
    logger.info(
        "Moodle HTTP <- %s %s  location=%s  body_preview=%.300s",
        response.status_code,
        response.url,
        response.headers.get("location", "-"),
        response.text,
    )


class MoodleRepository:
    """Encapsule les appels HTTP vers les Moodle Web Services.

    Equivalent du Repository de la couche auth, mais la source de donnees
    est l'API REST Moodle au lieu d'une base SQL.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        host_header: str | None = None,
        plugin_secret: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._host_header = host_header.strip() if host_header else None
        self._plugin_secret = plugin_secret.strip() if plugin_secret else None
        headers = {"Host": self._host_header} if self._host_header else None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=False,
            event_hooks={"response": [_log_response]},
        )

    async def call(self, wsfunction: str, **params: Any) -> Any:
        """Appelle une wsfunction Moodle et retourne la reponse JSON.

        Leve MoodleAPIException si :
        - la reponse HTTP est 4xx ou 5xx (ou redirect non suivi)
        - Moodle retourne un objet {"exception": "..."}
        """
        data: dict[str, Any] = {
            "wstoken": self._token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
            **params,
        }
        log_params = {k: v for k, v in params.items()}
        logger.info(
            "Moodle WS request  wsfunction=%s url=%s%s host=%s params=%s",
            wsfunction,
            self._base_url,
            _REST_PATH,
            self._host_header or "-",
            log_params,
        )
        try:
            response = await self._client.post(_REST_PATH, data=data)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleAPIException(
                f"Moodle HTTP {exc.response.status_code} pour {wsfunction}"
            ) from exc
        except httpx.RequestError as exc:
            raise MoodleAPIException(
                f"Impossible de joindre Moodle ({wsfunction}) : {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            # json.JSONDecodeError est une sous-classe de ValueError
            raise MoodleAPIException(
                f"Reponse Moodle non-JSON ({wsfunction}) : reponse inattendue"
            ) from exc

        if isinstance(data, dict) and "exception" in data:
            message = data.get("message", data["exception"])
            raise MoodleAPIException(f"Moodle exception ({wsfunction}) : {message}")

        return data

    async def get_related_learners(self, userid: int) -> list[dict[str, Any]]:
        """Retourne les apprenants lies a un utilisateur via l'endpoint du plugin."""
        if not self._plugin_secret:
            return []

        logger.info(
            "Moodle plugin request path=%s host=%s userid=%s",
            _RELATED_LEARNERS_PATH,
            self._host_header or "-",
            userid,
        )

        try:
            response = await self._client.get(
                _RELATED_LEARNERS_PATH,
                params={"userid": str(userid)},
                headers={"Authorization": f"Bearer {self._plugin_secret}"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleAPIException(
                f"Moodle HTTP {exc.response.status_code} pour related_learners"
            ) from exc
        except httpx.RequestError as exc:
            raise MoodleAPIException(
                f"Impossible de joindre Moodle (related_learners) : {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise MoodleAPIException(
                "Reponse Moodle non-JSON (related_learners) : reponse inattendue"
            ) from exc

        learners = data.get("learners", []) if isinstance(data, dict) else []
        if not isinstance(learners, list):
            raise MoodleAPIException(
                "Reponse Moodle invalide (related_learners) : champ learners absent"
            )

        return [item for item in learners if isinstance(item, dict)]

    async def aclose(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        await self._client.aclose()
