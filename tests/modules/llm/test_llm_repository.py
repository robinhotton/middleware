"""Tests unitaires pour LLMRepository — mapping des erreurs HTTP du provider."""

import httpx
import pytest

from src.exceptions import BadRequestException, TooManyRequestsException
from src.modules.llm.repositories.llm_repository import (
    LLMAPIException,
    LLMRepository,
)


def _repo_with_handler(handler) -> LLMRepository:
    """Cree un LLMRepository dont le client httpx utilise un MockTransport."""
    repo = LLMRepository(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="m",
        max_tokens=100,
        timeout=30.0,
    )
    transport = httpx.MockTransport(handler)
    repo._client = httpx.AsyncClient(
        base_url="https://api.test/v1",
        transport=transport,
        headers={"Authorization": "Bearer test-key"},
    )
    return repo


# ============================================================================
# Cas nominal
# ============================================================================


async def test_chat_completion_success_returns_metrics():
    """Reponse 200 valide -> LLMCompletion peuplee."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Salut"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    repo = _repo_with_handler(handler)
    result = await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert result.text == "Salut"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    await repo.aclose()


# ============================================================================
# Mapping erreurs HTTP
# ============================================================================


async def test_chat_completion_maps_context_length_exceeded_to_400():
    """400 + context_length_exceeded -> BadRequestException (non 502)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "message": (
                    "context_length_exceeded: input is 35000 tokens but max is 32768"
                )
            },
        )

    repo = _repo_with_handler(handler)
    with pytest.raises(BadRequestException) as exc:
        await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert exc.value.status_code == 400
    assert "Contexte trop long" in exc.value.detail
    await repo.aclose()


async def test_chat_completion_maps_429_to_too_many_requests():
    """429 cote provider -> TooManyRequestsException (preserve la semantique)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "rate limit exceeded"})

    repo = _repo_with_handler(handler)
    with pytest.raises(TooManyRequestsException) as exc:
        await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert exc.value.status_code == 429
    assert "Quota LLM" in exc.value.detail
    await repo.aclose()


async def test_chat_completion_maps_400_generic_to_502():
    """400 sans context_length_exceeded -> LLMAPIException 502 (mauvaise config)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "invalid model"})

    repo = _repo_with_handler(handler)
    with pytest.raises(LLMAPIException) as exc:
        await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert exc.value.status_code == 502
    await repo.aclose()


async def test_chat_completion_maps_500_to_502():
    """5xx provider -> LLMAPIException 502."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "service unavailable"})

    repo = _repo_with_handler(handler)
    with pytest.raises(LLMAPIException) as exc:
        await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert exc.value.status_code == 502
    assert "503" in exc.value.detail
    await repo.aclose()


# ============================================================================
# Erreurs reseau / timeout
# ============================================================================


async def test_chat_completion_timeout_raises_llm_api_exception():
    """Timeout HTTP -> LLMAPIException 502 avec message specifique."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timeout")

    repo = _repo_with_handler(handler)
    with pytest.raises(LLMAPIException) as exc:
        await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert exc.value.status_code == 502
    assert "Timeout" in exc.value.detail
    await repo.aclose()


async def test_chat_completion_network_error_raises_llm_api_exception():
    """Erreur reseau -> LLMAPIException 502."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    repo = _repo_with_handler(handler)
    with pytest.raises(LLMAPIException) as exc:
        await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert exc.value.status_code == 502
    assert "joindre" in exc.value.detail
    await repo.aclose()


# ============================================================================
# Reponse malformee
# ============================================================================


async def test_chat_completion_unexpected_response_raises_llm_api_exception():
    """Reponse 200 sans 'choices' -> LLMAPIException."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    repo = _repo_with_handler(handler)
    with pytest.raises(LLMAPIException) as exc:
        await repo.chat_completion([{"role": "user", "content": "Hi"}])
    assert "inattendue" in exc.value.detail
    await repo.aclose()


# ============================================================================
# Configuration
# ============================================================================


def test_repository_accepts_timeout_parameter():
    """Le timeout est configurable au niveau du constructeur."""
    repo = LLMRepository(
        api_key="k",
        base_url="https://api.test",
        model="m",
        timeout=120.0,
    )
    assert repo._client.timeout.read == 120.0
