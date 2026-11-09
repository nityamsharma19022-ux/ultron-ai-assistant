"""Live tests against a REAL Ollama runtime (and model, when given).

Skipped unless ULTRON_TEST_OLLAMA_URL is set. Tests that need an installed
model also need ULTRON_TEST_OLLAMA_MODEL. No cloud provider is ever called:
the "cloud" used for fallback tests points at a closed local port.

Windows PowerShell, from apps\\core:

    $env:ULTRON_TEST_OLLAMA_URL = "http://localhost:11434"
    $env:ULTRON_TEST_OLLAMA_MODEL = "qwen3.5:4b"
    uv run pytest -m ollama_live -v -s
"""

from __future__ import annotations

import os
import time

import httpx
import pytest
from pydantic import SecretStr

from tests.conftest import make_test_settings, owner_headers, running_app
from tests.fakes import cloud
from ultron_core.ai.cooldown import CooldownStore
from ultron_core.ai.errors import ModelNotInstalledError
from ultron_core.ai.providers.ollama import OllamaProvider
from ultron_core.ai.providers.openai_compat import OpenAICompatibleProvider
from ultron_core.ai.router import AIRouter, Completed, RoutingError, RoutingPreferences
from ultron_core.ai.types import ChatMessage, ChatRequest, ProviderKind, StreamEnd, TextDelta
from ultron_core.config import Settings

OLLAMA_URL = os.environ.get("ULTRON_TEST_OLLAMA_URL", "").strip()
MODEL = os.environ.get("ULTRON_TEST_OLLAMA_MODEL", "").strip()
MISSING_MODEL = "ultron-test-missing-model:0b"
DEAD_CLOUD_URL = "http://127.0.0.1:9/v1"  # nothing listens here: behaves like being offline

pytestmark = [
    pytest.mark.ollama_live,
    pytest.mark.skipif(not OLLAMA_URL, reason="set ULTRON_TEST_OLLAMA_URL to run live tests"),
]
needs_model = pytest.mark.skipif(
    not MODEL, reason="set ULTRON_TEST_OLLAMA_MODEL to a pulled model (e.g. qwen3.5:4b)"
)

PROMPT = ChatRequest(
    messages=(ChatMessage("user", "Reply with one short sentence that includes the word ULTRON."),),
    system="You are ULTRON, a concise assistant.",
    max_output_tokens=256,
)


def ollama(model: str) -> OllamaProvider:
    return OllamaProvider(
        http=httpx.AsyncClient(),
        base_url=OLLAMA_URL,
        model=model,
        context_char_budget=16_000,
        connect_timeout=5,
        read_timeout=300,  # first use loads the model from disk
        think="false",
        num_ctx=8192,
    )


def dead_cloud() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="custom",
        http=httpx.AsyncClient(),
        base_url=DEAD_CLOUD_URL,
        api_key=SecretStr("fallback-test-not-a-real-key"),
        model="fallback-test",
        context_char_budget=48_000,
        connect_timeout=2,
        read_timeout=5,
    )


def router(*providers) -> AIRouter:  # type: ignore[no-untyped-def]
    settings = Settings(  # router-only: no database needed
        _env_file=None,  # type: ignore[call-arg]
        local_database_url="postgresql://unused@localhost/unused",
        jwt_secret="live-test-" + "x" * 32,
    )
    return AIRouter(list(providers), CooldownStore(None, settings))


async def route_once(r: AIRouter, *, private: bool = False, prefs=None):  # type: ignore[no-untyped-def]
    text, completed = [], None
    async for event in r.stream(lambda _p: PROMPT, prefs or RoutingPreferences(), private=private):
        if isinstance(event, TextDelta):
            text.append(event.text)
        elif isinstance(event, Completed):
            completed = event
    assert completed is not None
    return "".join(text), completed.route


# --- Runtime and unavailable-model handling (no model needed) ------------------------


async def test_ollama_runtime_is_reachable() -> None:
    async with httpx.AsyncClient() as http:
        resp = await http.get(f"{OLLAMA_URL}/api/version", timeout=5)
    assert resp.status_code == 200
    print(f"\nOllama version: {resp.json().get('version')}")


async def test_missing_model_is_reported_as_not_installed() -> None:
    availability = await ollama(MISSING_MODEL).availability()
    assert availability.available is False
    assert availability.reason == f"local model '{MISSING_MODEL}' is not installed"


async def test_chat_with_missing_model_raises_model_not_installed() -> None:
    with pytest.raises(ModelNotInstalledError):
        async for _ in ollama(MISSING_MODEL).stream(PROMPT):
            pass


async def test_offline_with_missing_model_does_not_claim_offline_ai() -> None:
    with pytest.raises(RoutingError) as err:
        await route_once(router(dead_cloud(), ollama(MISSING_MODEL)))
    assert err.value.code == "offline_no_local_ai"
    assert "not installed" in err.value.message


# --- Real model -------------------------------------------------------------------------


@needs_model
async def test_configured_model_is_installed() -> None:
    availability = await ollama(MODEL).availability()
    assert availability.available, availability.reason


@needs_model
async def test_real_local_reply_streams() -> None:
    started = time.perf_counter()
    first_token_at = None
    text, end = [], None
    async for event in ollama(MODEL).stream(PROMPT):
        if isinstance(event, TextDelta):
            first_token_at = first_token_at or time.perf_counter()
            text.append(event.text)
        elif isinstance(event, StreamEnd):
            end = event
    reply = "".join(text).strip()
    assert reply, "the model returned no text"
    assert "<think>" not in reply
    assert end is not None and (end.output_tokens or 0) > 0
    print(
        f"\nReply: {reply!r}\nFirst token after {first_token_at - started:.1f}s, "  # type: ignore[operator]
        f"total {time.perf_counter() - started:.1f}s, {end.output_tokens} tokens"
    )


@needs_model
async def test_cloud_failure_falls_back_to_real_local_model() -> None:
    text, route = await route_once(router(dead_cloud(), ollama(MODEL)))
    assert text.strip()
    assert route.kind is ProviderKind.LOCAL
    assert route.fallback_used is True
    assert [a.outcome for a in route.attempts] == ["offline", "ok"]


@needs_model
async def test_private_conversation_uses_only_real_local_model() -> None:
    spy = cloud("spy-cloud")
    text, route = await route_once(router(spy, ollama(MODEL)), private=True)
    assert text.strip()
    assert route.kind is ProviderKind.LOCAL
    assert spy.calls == []


@needs_model
@pytest.mark.integration
async def test_full_chat_api_with_real_local_model(migrated_database) -> None:  # type: ignore[no-untyped-def]
    """Whole backend: HTTP -> router -> real Ollama, with a dead cloud provider."""
    settings = make_test_settings(
        ollama_base_url=OLLAMA_URL,
        ollama_model=MODEL,
        custom_ai_base_url=DEAD_CLOUD_URL,
        custom_ai_api_key="fallback-test-not-a-real-key",
        custom_ai_model="fallback-test",
        ai_cloud_providers="custom",
    )
    async with running_app(settings) as (app, client):
        h = await owner_headers(app, client)
        status = (await client.get("/api/v1/ai/status", headers=h)).json()
        assert status["local_ai_available"] is True

        cid = (await client.post("/api/v1/conversations", json={}, headers=h)).json()["id"]
        resp = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "Say hello in one short sentence."},
            headers=h,
            timeout=300,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["assistant_message"]["provider_kind"] == "local"
        assert body["assistant_message"]["model"] == MODEL
        assert body["routing"]["fallback_used"] is True
        assert body["assistant_message"]["content"].strip()

        private = (
            await client.post("/api/v1/conversations", json={"is_private": True}, headers=h)
        ).json()["id"]
        resp = await client.post(
            f"/api/v1/conversations/{private}/messages",
            json={"content": "Reply with one word.", "stream": True},
            headers=h,
            timeout=300,
        )
        assert "event: message.completed" in resp.text
        assert '"kind": "local"' in resp.text
        assert '"provider": "custom"' not in resp.text  # cloud never attempted


async def test_missing_model_is_not_loaded_and_cannot_warm_up() -> None:
    provider = ollama(MISSING_MODEL)
    assert await provider.model_loaded() is False
    with pytest.raises(ModelNotInstalledError):
        await provider.warmup()


@needs_model
async def test_warmup_loads_real_model() -> None:
    provider = ollama(MODEL)
    started = time.perf_counter()
    await provider.warmup()
    assert await provider.model_loaded() is True
    print(f"\nWarm-up took {time.perf_counter() - started:.1f}s; model is in memory")
