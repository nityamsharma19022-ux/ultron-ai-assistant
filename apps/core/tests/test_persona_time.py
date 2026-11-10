"""12-hour time, ULTRON's personality, response modes and reply timing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
from pydantic import SecretStr

from tests.conftest import owner_headers, running_app
from tests.fakes import cloud, local
from tests.test_ai_providers import FAKE_KEY
from tests.test_chat_api import new_conversation
from tests.test_freellmapi import gateway
from tests.test_tasks import command, engine_app
from ultron_core import persona, timefmt
from ultron_core.ai.types import ChatMessage, ChatRequest
from ultron_core.tasks import tools


def test_clock_handles_midnight_noon_and_am_pm() -> None:
    assert timefmt.clock(0, 5) == "12:05 AM"  # just after midnight
    assert timefmt.clock(0, 0) == "12:00 AM"
    assert timefmt.clock(9, 30) == "9:30 AM"
    assert timefmt.clock(12, 0) == "12:00 PM"  # noon
    assert timefmt.clock(12, 45) == "12:45 PM"
    assert timefmt.clock(18, 15) == "6:15 PM"
    assert timefmt.clock(23, 59) == "11:59 PM"
    assert timefmt.clock(18, 15, h24=True) == "18:15"
    assert timefmt.hhmm("22:00") == "10:00 PM" and timefmt.hhmm("07:00") == "7:00 AM"
    assert timefmt.hhmm(None) is None


def test_when_uses_local_days() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 11, 10, 23, 30, tzinfo=ist)
    assert timefmt.when(now + timedelta(minutes=40), now) == "tomorrow at 12:10 AM"
    assert timefmt.when(datetime(2026, 11, 10, 23, 45, tzinfo=ist), now) == "today at 11:45 PM"
    assert timefmt.when(datetime(2026, 11, 11, 0, 10, tzinfo=ist), now) == "tomorrow at 12:10 AM"
    assert timefmt.when(datetime(2026, 11, 14, 18, 15, tzinfo=ist), now) == "on 14 Nov at 6:15 PM"
    # Stored in UTC, shown in local time: 17:30 UTC is 11:00 PM in India.
    utc = datetime(2026, 11, 10, 17, 30, tzinfo=UTC)
    assert timefmt.when(utc.astimezone(ist), now) == "today at 11:00 PM"
    assert timefmt.long_now(now) == "Tuesday, 10 November 2026, 11:30 PM"


def test_persona_phrases() -> None:
    assert persona.done("Opened VS Code", "Sir") == "Certainly, Sir. Opened VS Code."
    assert persona.done("Opened VS Code", "") == "Certainly. Opened VS Code."
    assert persona.failed("No agent", "Sir").startswith("I apologize, Sir.")
    assert persona.greeting(datetime(2026, 1, 1, 8, 0), "Sir") == "Good morning, Sir."
    assert persona.greeting(datetime(2026, 1, 1, 19, 0), None) == "Good evening."
    prompt = persona.prompt("Sir", datetime(2026, 11, 10, 21, 24))
    assert '"Sir"' in prompt and "12-hour" in prompt and "9:24 PM" in prompt
    assert "never claim human feelings" in prompt
    assert "24-hour" in persona.prompt(None, None, h24=True)


def test_alarm_step_reads_in_12_hours() -> None:
    spec, args = tools.validate_step("phone.alarm.set", {"hour": 6, "minute": 30})
    assert spec.describe(args) == "Set an alarm for 6:30 AM"


async def test_freellmapi_model_per_response_mode() -> None:
    gw = gateway(lambda r: httpx.Response(500), freellmapi_api_key=SecretStr(FAKE_KEY))
    req = ChatRequest(messages=(ChatMessage("user", "hi"),), system="s")
    assert gw.model_for(req) == "auto"
    assert (
        gw.model_for(ChatRequest(messages=req.messages, system="s", variant="fast")) == "auto:fast"
    )
    assert (
        gw.model_for(ChatRequest(messages=req.messages, system="s", variant="smart"))
        == "auto:smart"
    )
    fixed = gateway(
        lambda r: httpx.Response(500),
        freellmapi_api_key=SecretStr(FAKE_KEY),
        freellmapi_model="qwen3.8-27b",
    )
    assert (
        fixed.model_for(ChatRequest(messages=req.messages, system="s", variant="fast"))
        == "qwen3.8-27b"
    )


@pytest.mark.integration
async def test_preferences_persona_modes_and_timing(migrated_database) -> None:  # type: ignore[no-untyped-def]
    provider = cloud()
    async with running_app(migrated_database, [provider, local()]) as (app, client):
        h = await owner_headers(app, client)
        prefs = (await client.get("/api/v1/ai/preferences", headers=h)).json()
        assert (prefs["time_format"], prefs["address_as"], prefs["response_mode"]) == (
            "12h",
            "Sir",
            "balanced",
        )
        cid = await new_conversation(client, h)
        resp = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "hello", "utc_offset_minutes": 330},
            headers=h,
        )
        assert resp.status_code == 200
        req = provider.calls[-1]
        assert (
            '"Sir"' in req.system and "12-hour" in req.system and "current local date" in req.system
        )
        assert req.variant == "default"
        reply = resp.json()["assistant_message"]
        assert (
            reply["first_token_ms"] is not None and reply["duration_ms"] >= reply["first_token_ms"]
        )

        # Per-message Instant and Deep modes.
        await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "quick one", "response_mode": "instant"},
            headers=h,
        )
        fast = provider.calls[-1]
        assert fast.variant == "fast" and fast.max_output_tokens <= 1024
        assert "briefly" in fast.system
        await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "why is the sky blue", "response_mode": "deep"},
            headers=h,
        )
        deep = provider.calls[-1]
        assert deep.variant == "smart" and "carefully" in deep.system

        # Preferences: no title, 24-hour clock, Instant by default.
        saved = (
            await client.put(
                "/api/v1/ai/preferences",
                json={
                    "mode": "auto",
                    "address_as": "  ",
                    "time_format": "24h",
                    "response_mode": "instant",
                },
                headers=h,
            )
        ).json()
        assert saved["address_as"] == "" and saved["time_format"] == "24h"
        await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": "hi"}, headers=h
        )
        last = provider.calls[-1]
        assert "Sir" not in last.system and "24-hour" in last.system and last.variant == "fast"
        bad = await client.put(
            "/api/v1/ai/preferences", json={"mode": "auto", "time_format": "13h"}, headers=h
        )
        assert bad.status_code == 422

        usage = (await client.get("/api/v1/ai/usage", headers=h)).json()
        assert usage["rows"][0]["avg_first_token_ms"] is not None
        assert usage["rows"][0]["avg_duration_ms"] is not None


@pytest.mark.integration
async def test_commands_use_the_chosen_address(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await client.put(
            "/api/v1/ai/preferences", json={"mode": "auto", "address_as": "Boss"}, headers=h
        )
        out = await command(client, h, "remind me to stretch in 15 minutes")
        assert out["message"] == "Working on it, Boss: Remind you: stretch"
