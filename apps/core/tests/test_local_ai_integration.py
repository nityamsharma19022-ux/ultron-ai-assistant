"""Local AI integration: local-only guard, warm-up, loading states, keep-alive,
reply time limit. Fake providers / mocked HTTP only."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.conftest import make_test_settings, owner_headers, running_app
from tests.fakes import cloud, local
from tests.test_chat_api import new_conversation, parse_sse, send
from ultron_core.ai.errors import (
    ModelNotInstalledError,
    ProviderOfflineError,
    ProviderUnavailableError,
)
from ultron_core.ai.local_policy import ollama_address_problem
from ultron_core.ai.providers.ollama import OllamaProvider
from ultron_core.ai.registry import build_providers
from ultron_core.config import Settings

# --- Local-only guard (unit) --------------------------------------------------------


def policy_settings(url: str, **kw: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        local_database_url="postgresql://u:p@localhost/x",
        jwt_secret="p" * 40,
        ollama_base_url=url,
        **kw,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://[::1]:11434",
        "http://host.docker.internal:11434",
        "http://ollama:11434",
    ],
)
def test_local_addresses_are_allowed_on_local_backend(url: str) -> None:
    assert ollama_address_problem(policy_settings(url)) is None


@pytest.mark.parametrize(
    "url", ["http://192.168.1.20:11434", "http://my-pc.example.com:11434", "https://ai.example.com"]
)
def test_other_addresses_are_blocked_on_local_backend(url: str) -> None:
    problem = ollama_address_problem(policy_settings(url))
    assert problem is not None and "not on this machine" in problem


def test_remote_ollama_needs_explicit_opt_in_and_https() -> None:
    assert (
        ollama_address_problem(policy_settings("https://ai.example.com", ollama_allow_remote=True))
        is None
    )
    assert (
        ollama_address_problem(
            policy_settings("http://192.168.1.20:11434", ollama_allow_remote=True)
        )
        is not None
    )  # opt-in still requires https


def test_cloud_backend_never_uses_local_addresses() -> None:
    problem = ollama_address_problem(policy_settings("http://127.0.0.1:11434", deployment="cloud"))
    assert problem is not None and "disabled on a cloud backend" in problem
    assert (
        ollama_address_problem(
            policy_settings("https://ai.example.com", deployment="cloud", ollama_allow_remote=True)
        )
        is None
    )


def test_invalid_address_is_reported() -> None:
    assert ollama_address_problem(policy_settings("127.0.0.1:11434")) is not None


def test_blocked_provider_is_not_configured_and_says_why() -> None:
    providers = build_providers(policy_settings("http://10.0.0.5:11434"), httpx.AsyncClient())
    ollama = next(p for p in providers if p.name == "ollama")
    assert ollama.is_configured() is False
    assert "not on this machine" in (ollama.missing_configuration() or "")


def test_default_local_model_is_qwen() -> None:
    assert policy_settings("http://127.0.0.1:11434").ollama_model == "qwen3.5:4b"


# --- Ollama warm-up and loaded-model detection (mocked HTTP) ------------------------------


def ollama_with(handler) -> OllamaProvider:  # type: ignore[no-untyped-def]
    return OllamaProvider(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
        context_char_budget=16_000,
        connect_timeout=1,
        read_timeout=5,
        keep_alive="30m",
    )


async def test_model_loaded_uses_api_ps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})

    assert await ollama_with(handler).model_loaded() is True
    empty = ollama_with(lambda r: httpx.Response(200, json={"models": []}))
    assert await empty.model_loaded() is False
    broken = ollama_with(lambda r: httpx.Response(500))
    assert await broken.model_loaded() is None


async def test_warmup_loads_model_with_empty_chat() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"model": "qwen3.5:4b", "done": True, "done_reason": "load"}
        )

    assert await ollama_with(handler).warmup() is False
    assert seen == [{"model": "qwen3.5:4b", "messages": [], "keep_alive": "30m"}]


async def test_warmup_missing_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(404, json={"error": "model 'qwen3.5:4b' not found"})

    with pytest.raises(ModelNotInstalledError):
        await ollama_with(handler).warmup()


# --- API: loading states, keep-alive, time limit, warm-up, status ------------------------

pytestmark_integration = pytest.mark.integration


@pytestmark_integration
async def test_loading_state_when_local_model_is_not_in_memory(migrated_database) -> None:  # type: ignore[no-untyped-def]
    providers = [cloud(error=ProviderOfflineError("offline")), local(loaded=False)]
    async with running_app(migrated_database, providers) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        events = parse_sse((await send(client, h, cid, stream=True)).text)
        statuses = [d for e, d in events if e == "status"]
        assert [s["phase"] for s in statuses] == [
            "routing",
            "waiting",
            "loading_model",
            "generating",
        ]
        assert statuses[1]["kind"] == "cloud"
        assert statuses[2] == {
            "phase": "loading_model",
            "provider": "fake-local",
            "kind": "local",
            "model": "fake-local-model",
            "model_loaded": False,
        }
        assert statuses[3]["kind"] == "local"


@pytestmark_integration
async def test_keepalive_comments_while_waiting(migrated_database) -> None:  # type: ignore[no-untyped-def]
    gate = asyncio.Event()
    slow = local(block=gate)
    settings = make_test_settings(ai_stream_keepalive_seconds=0.05)
    async with running_app(settings, [slow]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        pending = asyncio.create_task(send(client, h, cid, stream=True))
        await asyncio.wait_for(slow.started.wait(), timeout=5)
        await asyncio.sleep(0.3)
        gate.set()
        resp = await asyncio.wait_for(pending, timeout=5)
        assert ": keep-alive" in resp.text
        assert parse_sse(resp.text)[-1][0] == "message.completed"


@pytestmark_integration
async def test_reply_time_limit_before_any_text(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(ai_max_reply_seconds=1)
    async with running_app(settings, [local(block=asyncio.Event())]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        resp = await send(client, h, cid)
        assert resp.status_code == 504
        assert resp.json()["detail"]["code"] == "timeout"
        assert resp.json()["assistant_message"]["status"] == "failed"


@pytestmark_integration
async def test_reply_time_limit_keeps_partial_text(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(ai_max_reply_seconds=1)
    async with running_app(settings, [local(block_after=1)]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        events = parse_sse((await send(client, h, cid, stream=True)).text)
        assert events[-1][0] == "error"
        assert events[-1][1]["code"] == "timeout"
        assert events[-1][1]["assistant_message"]["status"] == "incomplete"
        assert events[-1][1]["assistant_message"]["content"] == "Local"


@pytestmark_integration
async def test_warmup_endpoint(migrated_database) -> None:  # type: ignore[no-untyped-def]
    loc = local(loaded=False)
    async with running_app(migrated_database, [cloud(), loc]) as (app, client):
        h = await owner_headers(app, client)
        first = await client.post("/api/v1/ai/local/warmup", headers=h)
        assert first.status_code == 200, first.text
        assert first.json()["already_loaded"] is False
        assert first.json()["model"] == "fake-local-model"
        second = (await client.post("/api/v1/ai/local/warmup", headers=h)).json()
        assert second["already_loaded"] is True
        status = (await client.get("/api/v1/ai/status", headers=h)).json()
        fake = next(p for p in status["providers"] if p["name"] == "fake-local")
        assert fake["model_loaded"] is True
        for _ in range(4):
            await client.post("/api/v1/ai/local/warmup", headers=h)
        assert (await client.post("/api/v1/ai/local/warmup", headers=h)).status_code == 429
        assert (await client.post("/api/v1/ai/local/warmup")).status_code == 401


@pytestmark_integration
@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (local(configured=False), 409),
        (local(warmup_error=ModelNotInstalledError("local model 'x' is not installed")), 409),
        (local(warmup_error=ProviderUnavailableError("local AI runtime is not running")), 503),
    ],
)
async def test_warmup_failures(migrated_database, provider, expected) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [provider]) as (app, client):
        h = await owner_headers(app, client)
        resp = await client.post("/api/v1/ai/local/warmup", headers=h)
        assert resp.status_code == expected
        assert resp.json()["detail"]


@pytestmark_integration
async def test_blocked_ollama_address_is_explained_everywhere(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(
        ollama_base_url="http://192.168.1.50:11434", ollama_model="qwen3.5:4b"
    )
    async with running_app(settings) as (app, client):
        ready = (await client.get("/health/ready")).json()["checks"]["local_ai"]
        assert ready["status"] == "not_configured"
        assert "not on this machine" in ready["reason"]
        h = await owner_headers(app, client)
        status = (await client.get("/api/v1/ai/status", headers=h)).json()
        ollama = next(p for p in status["providers"] if p["name"] == "ollama")
        assert ollama["status"] == "not_configured"
        assert "not on this machine" in ollama["reason"]
        warm = await client.post("/api/v1/ai/local/warmup", headers=h)
        assert warm.status_code == 409
