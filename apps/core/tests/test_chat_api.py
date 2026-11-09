"""Chat API end to end (real Postgres + Redis, fake AI providers)."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from tests.conftest import make_test_settings, owner_headers, running_app
from tests.fakes import cloud, local
from ultron_core.ai.errors import (
    ProviderOfflineError,
    ProviderQuotaExhaustedError,
    ProviderUnavailableError,
)
from ultron_core.ai.providers.openai_compat import OpenAICompatibleProvider
from ultron_core.chat.service import mark_stale_generations_failed
from ultron_core.db.models import Message

pytestmark = pytest.mark.integration


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        if block.startswith(":"):
            continue  # keep-alive comment
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def new_conversation(client, headers, **body) -> str:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/conversations", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def send(client, headers, cid, content="Hello?", stream=False):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": content, "stream": stream},
        headers=headers,
    )


# --- Basic chat -------------------------------------------------------------------


async def test_send_message_uses_cloud_and_stores_history(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c, local()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        resp = await send(client, h, cid, "What is ULTRON?")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["assistant_message"]["content"] == "Hello from ULTRON"
        assert body["assistant_message"]["status"] == "complete"
        assert body["assistant_message"]["provider_kind"] == "cloud"
        assert body["routing"]["kind"] == "cloud"
        assert body["routing"]["fallback_used"] is False

        detail = (await client.get(f"/api/v1/conversations/{cid}", headers=h)).json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["conversation"]["title"] == "What is ULTRON?"


async def test_streaming_events(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud(), local()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        resp = await send(client, h, cid, stream=True)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(resp.text)
        names = [e for e, _ in events]
        assert names == [
            "message.created",
            "status",
            "status",
            "provider.selected",
            "status",
            "delta",
            "delta",
            "delta",
            "message.completed",
        ]
        phases = [d["phase"] for e, d in events if e == "status"]
        assert phases == ["routing", "waiting", "generating"]
        assert events[3][1]["kind"] == "cloud"
        assert "".join(d["text"] for e, d in events if e == "delta") == "Hello from ULTRON"
        assert events[-1][1]["assistant_message"]["status"] == "complete"


async def test_conversation_history_is_sent_as_context(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        await send(client, h, cid, "My name is Nova.")
        await send(client, h, cid, "What is my name?")
        sent = c.calls[-1].messages
        assert [(m.role, m.content) for m in sent] == [
            ("user", "My name is Nova."),
            ("assistant", "Hello from ULTRON"),
            ("user", "What is my name?"),
        ]
        assert "cannot run commands" in c.calls[-1].system


async def test_context_is_trimmed_to_the_provider_budget(migrated_database) -> None:  # type: ignore[no-untyped-def]
    small = cloud(context_char_budget=60)
    async with running_app(migrated_database, [small]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        for i in range(4):
            await send(client, h, cid, f"message number {i} " + "x" * 20)
        sent = small.calls[-1].messages
        assert sent[-1].content.startswith("message number 3")
        assert sum(len(m.content) for m in sent) <= 60
        assert sent[0].role == "user"


# --- Fallback, quota, offline ----------------------------------------------------------


async def test_cloud_failure_falls_back_to_local_via_api(migrated_database) -> None:  # type: ignore[no-untyped-def]
    providers = [cloud(error=ProviderUnavailableError("down")), local()]
    async with running_app(migrated_database, providers) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        body = (await send(client, h, cid)).json()
        assert body["assistant_message"]["content"] == "Local reply"
        assert body["assistant_message"]["provider_kind"] == "local"
        assert body["assistant_message"]["fallback_used"] is True


async def test_quota_exhaustion_via_api(migrated_database) -> None:  # type: ignore[no-untyped-def]
    providers = [cloud(error=ProviderQuotaExhaustedError("quota")), local()]
    async with running_app(migrated_database, providers) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        body = (await send(client, h, cid)).json()
        assert body["routing"]["kind"] == "local"
        assert body["routing"]["attempts"][0]["outcome"] == "quota_exhausted"
        status = (await client.get("/api/v1/ai/status", headers=h)).json()
        fake = next(p for p in status["providers"] if p["name"] == "fake-cloud")
        assert fake["status"] == "cooldown_quota_exhausted"
        assert fake["available"] is False


async def test_offline_with_local_model(migrated_database) -> None:  # type: ignore[no-untyped-def]
    providers = [cloud(error=ProviderOfflineError("offline")), local()]
    async with running_app(migrated_database, providers) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        body = (await send(client, h, cid)).json()
        assert body["assistant_message"]["provider_kind"] == "local"


async def test_offline_without_local_model(migrated_database) -> None:  # type: ignore[no-untyped-def]
    providers = [cloud(error=ProviderOfflineError("offline")), local(available=False)]
    async with running_app(migrated_database, providers) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        resp = await send(client, h, cid)
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["code"] == "offline_no_local_ai"
        assert body["assistant_message"]["status"] == "failed"
        status = (await client.get("/api/v1/ai/status", headers=h)).json()
        assert status["local_ai_available"] is False  # never claims offline AI


async def test_no_providers_configured(migrated_database) -> None:  # type: ignore[no-untyped-def]
    # Default app: no API keys and no local model in test settings.
    async with running_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        resp = await send(client, h, cid)
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "no_ai_available"
        status = (await client.get("/api/v1/ai/status", headers=h)).json()
        assert status["cloud_available"] is False
        assert status["local_ai_available"] is False
        assert {p["status"] for p in status["providers"]} == {"not_configured"}


async def test_mid_stream_failure_keeps_partial_reply(migrated_database) -> None:  # type: ignore[no-untyped-def]
    providers = [cloud(error=ProviderUnavailableError("dropped"), error_after=1), local()]
    async with running_app(migrated_database, providers) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        resp = await send(client, h, cid)
        assert resp.status_code == 502
        assert resp.json()["assistant_message"]["status"] == "incomplete"
        assert resp.json()["assistant_message"]["content"] == "Hello"


# --- Privacy --------------------------------------------------------------------------


async def test_private_conversation_uses_only_local_ai(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c, local()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h, is_private=True)
        body = (await send(client, h, cid, "my secret")).json()
        assert body["assistant_message"]["provider_kind"] == "local"
        assert c.calls == []


async def test_private_conversation_without_local_ai_is_refused(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c, local(available=False)]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h, is_private=True)
        resp = await send(client, h, cid, "my secret")
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "private_requires_local_ai"
        assert c.calls == []


async def test_private_by_default_preference(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c, local()]) as (app, client):
        h = await owner_headers(app, client)
        await client.put("/api/v1/ai/preferences", json={"private_by_default": True}, headers=h)
        cid = await new_conversation(client, h)
        detail = (await client.get(f"/api/v1/conversations/{cid}", headers=h)).json()
        assert detail["conversation"]["is_private"] is True
        await send(client, h, cid)
        assert c.calls == []


async def test_privacy_cannot_be_switched_off(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [local()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h, is_private=True)
        resp = await client.patch(
            f"/api/v1/conversations/{cid}", json={"is_private": False}, headers=h
        )
        assert resp.status_code == 422
        ok = await client.patch(f"/api/v1/conversations/{cid}", json={"title": "Diary"}, headers=h)
        assert ok.json()["is_private"] is True


async def test_private_conversations_refused_on_cloud_backend(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(deployment="cloud")
    async with running_app(settings, [cloud(), local()]) as (app, client):
        h = await owner_headers(app, client)
        resp = await client.post("/api/v1/conversations", json={"is_private": True}, headers=h)
        assert resp.status_code == 409
        assert "local" in resp.json()["detail"]


# --- Validation, limits, cancellation ----------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"content": ""},
        {"content": "   \n "},
        {"content": "bad\x00byte"},
        {"content": "hi", "unexpected": 1},
        {"content": 123},
        {},
    ],
)
async def test_invalid_messages_are_rejected(migrated_database, payload) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        resp = await client.post(f"/api/v1/conversations/{cid}/messages", json=payload, headers=h)
        assert resp.status_code == 422
        assert c.calls == []


async def test_message_length_limit(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(chat_max_message_chars=100)
    async with running_app(settings, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        assert (await send(client, h, cid, "x" * 101)).status_code == 422


async def test_chat_rate_limit(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(chat_rate_limit_per_minute=2)
    async with running_app(settings, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        assert (await send(client, h, cid)).status_code == 200
        assert (await send(client, h, cid)).status_code == 200
        blocked = await send(client, h, cid)
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "60"


async def test_cancel_stops_generation(migrated_database) -> None:  # type: ignore[no-untyped-def]
    gate = asyncio.Event()  # never set: the provider hangs until cancelled
    slow = cloud(block=gate)
    async with running_app(migrated_database, [slow]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        pending = asyncio.create_task(send(client, h, cid, stream=True))
        await asyncio.wait_for(slow.started.wait(), timeout=5)

        busy = await send(client, h, cid, "another")
        assert busy.status_code == 409  # one reply at a time

        cancel = await client.post(f"/api/v1/conversations/{cid}/cancel", headers=h)
        assert cancel.status_code == 202
        resp = await asyncio.wait_for(pending, timeout=5)
        events = parse_sse(resp.text)
        assert events[-1][0] == "message.cancelled"
        assert events[-1][1]["assistant_message"]["status"] == "cancelled"

        again = await client.post(f"/api/v1/conversations/{cid}/cancel", headers=h)
        assert again.status_code == 409  # nothing running any more


async def test_unknown_or_deleted_conversation(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        assert (await send(client, h, str(uuid.uuid4()))).status_code == 404
        cid = await new_conversation(client, h)
        assert (await client.delete(f"/api/v1/conversations/{cid}", headers=h)).status_code == 204
        assert (await client.get(f"/api/v1/conversations/{cid}", headers=h)).status_code == 404
        listing = (await client.get("/api/v1/conversations", headers=h)).json()
        assert listing == []


async def test_chat_requires_authentication(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (_app, client):
        assert (await client.get("/api/v1/conversations")).status_code == 401
        assert (await client.get("/api/v1/ai/status")).status_code == 401


# --- AI status, preferences, security -------------------------------------------------------


async def test_ai_status_never_exposes_api_keys(migrated_database) -> None:  # type: ignore[no-untyped-def]
    secret = "sk-live-TOPSECRET-should-never-leak"
    real = OpenAICompatibleProvider(
        name="groq",
        http=httpx.AsyncClient(),
        base_url="https://api.example.test/v1",
        api_key=SecretStr(secret),
        model="m-1",
        context_char_budget=1000,
        connect_timeout=1,
        read_timeout=1,
    )
    async with running_app(migrated_database, [real, local()]) as (app, client):
        h = await owner_headers(app, client)
        resp = await client.get("/api/v1/ai/status", headers=h)
        assert resp.status_code == 200
        assert secret not in resp.text
        groq = next(p for p in resp.json()["providers"] if p["name"] == "groq")
        assert groq["configured"] is True and groq["kind"] == "cloud"
        openapi = await client.get("/openapi.json")
        assert secret not in openapi.text


async def test_preferences_round_trip_and_validation(migrated_database) -> None:  # type: ignore[no-untyped-def]
    a, b = cloud("a"), cloud("b")
    async with running_app(migrated_database, [a, b, local()]) as (app, client):
        h = await owner_headers(app, client)
        default = (await client.get("/api/v1/ai/preferences", headers=h)).json()
        assert default["mode"] == "auto"
        assert set(default["available_cloud_providers"]) == {"a", "b"}

        ok = await client.put(
            "/api/v1/ai/preferences", json={"mode": "auto", "cloud_order": ["b", "a"]}, headers=h
        )
        assert ok.status_code == 200
        cid = await new_conversation(client, h)
        assert (await send(client, h, cid)).json()["routing"]["provider"] == "b"

        bad = await client.put("/api/v1/ai/preferences", json={"cloud_order": ["nope"]}, headers=h)
        assert bad.status_code == 422
        bad_mode = await client.put("/api/v1/ai/preferences", json={"mode": "x"}, headers=h)
        assert bad_mode.status_code == 422


async def test_local_only_preference(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c, local()]) as (app, client):
        h = await owner_headers(app, client)
        await client.put("/api/v1/ai/preferences", json={"mode": "local_only"}, headers=h)
        cid = await new_conversation(client, h)
        assert (await send(client, h, cid)).json()["routing"]["kind"] == "local"
        assert c.calls == []


async def test_ai_output_is_stored_as_text_and_never_executed(migrated_database) -> None:  # type: ignore[no-untyped-def]
    tricky = '{"tool": "shell", "command": "rm -rf /"} <script>alert(1)</script>'
    async with running_app(migrated_database, [cloud(chunks=(tricky,))]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        body = (await send(client, h, cid, "do something")).json()
        # Returned verbatim as data; the backend has no code path that acts on it.
        assert body["assistant_message"]["content"] == tricky


async def test_interrupted_replies_are_marked_failed(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        await send(client, h, cid)
        async with app.state.sessionmaker() as session:
            await session.execute(
                update(Message)
                .where(Message.role == "assistant")
                .values(
                    status="streaming",
                    updated_at=Message.updated_at - __import__("datetime").timedelta(hours=1),
                )
            )
            await session.commit()
            assert await mark_stale_generations_failed(session) == 1
            msg = await session.scalar(select(Message).where(Message.role == "assistant"))
            assert (msg.status, msg.error_code) == ("failed", "interrupted")
