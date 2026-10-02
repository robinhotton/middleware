"""Acces a l'API LLM via HTTP (compatible OpenAI — swappable)."""

import time
from dataclasses import dataclass

import httpx

from ....exceptions import (
    AppException,
    BadRequestException,
    TooManyRequestsException,
)

_CHAT_PATH = "/chat/completions"
_DEFAULT_TIMEOUT = 60.0


class LLMAPIException(AppException):
    """Erreur retournee par l'API LLM (502 Bad Gateway)."""

    def __init__(self, detail: str = "Erreur API LLM"):
        super().__init__(status_code=502, detail=detail)


@dataclass
class LLMCompletion:
    """Resultat d'un appel chat_completion avec metriques."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int


class LLMRepository:
    """Encapsule les appels HTTP vers une API LLM compatible OpenAI.

    Swapper le LLM = instancier ce repository avec un autre base_url/api_key.
    L'interface reste identique pour le service.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 500,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> LLMCompletion:
        """Envoie les messages au LLM et retourne le texte et les metriques.

        model : surcharge le modele par defaut du repository (routage light/heavy).
        Mappe les erreurs HTTP du provider vers des exceptions metier :
        - 400 + context_length_exceeded -> BadRequestException (400)
        - 429 -> TooManyRequestsException (429)
        - autre 4xx/5xx -> LLMAPIException (502)
        - timeout / erreur reseau -> LLMAPIException (502, message clair)
        """
        used_model = model or self._model
        payload = {
            "model": used_model,
            "messages": messages,
            "max_tokens": self._max_tokens,
        }
        start = time.monotonic()
        try:
            response = await self._client.post(
                _CHAT_PATH,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._raise_for_provider_error(exc, model=used_model)
        except httpx.TimeoutException as exc:
            raise LLMAPIException(
                f"Timeout LLM apres {self._client.timeout.read}s sur le modele "
                f"'{used_model}' (max_tokens={self._max_tokens}, "
                f"messages={len(messages)}). Cause : {exc}. "
                "Verifier la latence du provider ou augmenter LLM_HTTP_TIMEOUT_SECONDS."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMAPIException(
                f"Impossible de joindre le LLM (modele '{used_model}') : "
                f"{type(exc).__name__} - {exc}. "
                "Verifier MISTRAL_BASE_URL et la connectivite reseau."
            ) from exc

        duration_ms = int((time.monotonic() - start) * 1000)
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return LLMCompletion(
                text=text,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                duration_ms=duration_ms,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMAPIException(
                f"Reponse LLM inattendue (modele '{used_model}'). "
                f"Champ manquant : {type(exc).__name__} {exc}. "
                f"Payload recu (300 premiers caracteres) : {str(data)[:300]}"
            ) from exc

    @staticmethod
    def _raise_for_provider_error(exc: httpx.HTTPStatusError, model: str = "?") -> None:
        """Traduit une erreur HTTP du provider LLM en exception applicative."""
        status = exc.response.status_code
        body = exc.response.text[:500]
        body_lower = body.lower()
        if status == 400 and "context_length" in body_lower:
            raise BadRequestException(
                f"Contexte trop long pour le modele LLM '{model}'. "
                "Reduire LLM_MAX_PROMPT_TOKENS, le nombre de tours conserves ou "
                "le profil apprenant injecte. "
                f"Reponse provider : {body}"
            ) from exc
        if status == 401:
            raise LLMAPIException(
                f"LLM HTTP 401 (modele '{model}') : cle API rejetee. "
                f"Verifier MISTRAL_API_KEY (secrets/mistral_api_key.txt). "
                f"Reponse provider : {body}"
            ) from exc
        if status == 404:
            raise LLMAPIException(
                f"LLM HTTP 404 : modele '{model}' introuvable cote provider. "
                f"Verifier MISTRAL_MODEL / MISTRAL_MODEL_LIGHT. "
                f"Reponse provider : {body}"
            ) from exc
        if status == 429:
            raise TooManyRequestsException(
                f"Quota LLM depasse cote provider Mistral (modele '{model}'). "
                "Patienter ou augmenter le quota cote console Mistral. "
                f"Reponse provider : {body}"
            ) from exc
        if status >= 500:
            raise LLMAPIException(
                f"LLM HTTP {status} (modele '{model}') : panne cote provider. "
                f"Reponse provider : {body}"
            ) from exc
        raise LLMAPIException(
            f"LLM HTTP {status} (modele '{model}') : reponse inattendue. "
            f"Reponse provider : {body}"
        ) from exc

    async def aclose(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        await self._client.aclose()
