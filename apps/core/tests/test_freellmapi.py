"""FreeLLMAPI gateway: configuration, streaming, privacy, test and usage
endpoints. Mocked HTTP only: no gateway, no keys, no cost."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from tests.conftest import make_test_settings, owner_headers, running_app
from tests.fakes import cloud, local
from tests.test_ai_providers import FAKE_KEY, REQUEST, collect, sse_body
from tests.test_ai_router import make_router, run
from tests.test_chat_api import new_conversation, send
from ultron_core.ai.registry import _v1, build_providers
from ultron_core.ai.types import ProviderKind
from ultron_core.config import Settings


def gateway(handler, **overrides):  # type: ignore[no-untyped-def]
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        jwt_secret="j" * 40,
        local_database_url="postgresql://u:p@db/x",
        **overrides,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return next(p for p in build_providers(settings, http) if p.name == "freellmapi")


def test_configuration() -> None:
    off = gateway(lambda r: httpx.Response(500))
    assert not off.is_configured()  # no key: skipped, never called
    assert off.missing_configuration() == "missing API key"
    on = gateway(lambda r: httpx.Response(500), freellmapi_api_key=SecretStr(FAKE_KEY))
    assert on.is_configured() and on.kind is ProviderKind.CLOUD and on.model == "auto"
    defaults = Settings(
        _env_file=None, jwt_secret="j" * 40, local_database_url="postgresql://u:p@db/x"
    )  # type: ignore[call-arg]
    assert defaults.cloud_provider_order[0] == "freellmapi"
    assert _v1("http://127.0.0.1:31415") == "http://127.0.0.1:31415/v1"
    assert _v1("http://127.0.0.1:31415/v1/") == "http://127.0.0.1:31415/v1"
    assert _v1("http://host.docker.internal:3001/") == "http://host.docker.internal:3001/v1"


async def test_streams_through_gateway_and_reports_routed_model() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        body = sse_body(
            {"model": "auto", "choices": [{"delta": {"content": "Hello"}}]},
            {"choices": [{"delta": {"content": " there"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}},
        )
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream", "x-routed-via": "groq/llama-3.3-70b"},
        )

    p = gateway(
        handler,
        freellmapi_api_key=SecretStr(FAKE_KEY),
        freellmapi_base_url="http://127.0.0.1:31415",
        freellmapi_model="auto:smart",
    )
    text, end = await collect(p, REQUEST)
    assert text == "Hello there"
    assert seen["url"] == "http://127.0.0.1:31415/v1/chat/completions"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["body"]["model"] == "auto:smart"
    assert seen["body"]["stream_options"] == {"include_usage": True}
    assert "tools" not in seen["body"]  # text only, never tool calls
    assert end.model == "groq/llama-3.3-70b"  # which upstream model really answered
    assert (end.input_tokens, end.output_tokens) == (12, 3)


async def test_gateway_down_is_offline_and_rate_limit_falls_back() -> None:
    from ultron_core.ai import errors

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    p = gateway(refused, freellmapi_api_key=SecretStr(FAKE_KEY))
    with pytest.raises(errors.ProviderOfflineError):
        await collect(p)
    limited = gateway(
        lambda r: httpx.Response(429, json={"error": "all free tiers exhausted"}),
        freellmapi_api_key=SecretStr(FAKE_KEY),
    )
    with pytest.raises(errors.ProviderError):
        await collect(limited)


async def test_private_chats_never_use_the_gateway() -> None:
    gw, loc = cloud("freellmapi"), local()
    _, route = await run(make_router(gw, loc, order=("freellmapi",)), private=True)
    assert route.kind is ProviderKind.LOCAL and gw.calls == []
    # Not private: the gateway is tried first.
    gw2, loc2 = cloud("freellmapi"), local()
    _, route = await run(make_router(gw2, loc2, order=("freellmapi",)))
    assert route.provider == "freellmapi"


@pytest.mark.integration
async def test_provider_test_endpoint(migrated_database) -> None:  # type: ignore[no-untyped-def]
    ok, broken = cloud("freellmapi"), cloud("groq", configured=False)
    async with running_app(migrated_database, [ok, broken, local()]) as (app, client):
        h = await owner_headers(app, client)
        out = (await client.post("/api/v1/ai/providers/freellmapi/test", headers=h)).json()
        assert out["ok"] is True and out["kind"] == "cloud" and out["reply"]
        bad = (await client.post("/api/v1/ai/providers/groq/test", headers=h)).json()
        assert bad["ok"] is False and "Not set up" in bad["error"]
        missing = await client.post("/api/v1/ai/providers/nope/test", headers=h)
        assert missing.status_code == 404
        anon = await client.post("/api/v1/ai/providers/freellmapi/test")
        assert anon.status_code == 401


@pytest.mark.integration
async def test_usage_endpoint(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud("freellmapi"), local()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        for _ in range(2):
            assert (await send(client, h, cid, "hi")).status_code == 200
        usage = (await client.get("/api/v1/ai/usage?days=1", headers=h)).json()
        assert usage["total_replies"] == 2
        row = usage["rows"][0]
        assert row["provider"] == "freellmapi" and row["kind"] == "cloud" and row["replies"] == 2


def test_settings_example_mentions_gateway() -> None:
    from pathlib import Path

    example = (Path(__file__).parents[3] / ".env.example").read_text()
    assert "ULTRON_FREELLMAPI_API_KEY=\n" in example  # never a real key
    assert make_test_settings().freellmapi_api_key is None
