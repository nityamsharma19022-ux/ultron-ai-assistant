"""Instant fast path: clear commands run without any AI call."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import owner_headers
from tests.fakes import cloud
from tests.test_chat_api import new_conversation, parse_sse
from tests.test_tasks import ctx, engine_app, grant, pc_agent
from ultron_core.tasks import planner


def test_timer_and_alarm_rules() -> None:
    now = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)  # 8:30 PM in India
    ist = ZoneInfo("Asia/Kolkata")
    phone = ctx(targets={"core", "android"}, now=now, tz=ist)
    p = planner.rule_plan("set a timer for 5 minutes", phone)
    assert (p.rule, p.steps[0].tool, p.steps[0].args["seconds"]) == (
        "timer",
        "phone.timer.set",
        300,
    )
    assert planner.rule_plan("start a 90 second timer", phone).steps[0].args["seconds"] == 90
    p = planner.rule_plan("wake me up at 6:30 am", phone)
    assert (p.steps[0].tool, p.steps[0].args["hour"], p.steps[0].args["minute"]) == (
        "phone.alarm.set",
        6,
        30,
    )
    assert planner.rule_plan("set an alarm for 7 pm", phone).steps[0].args["hour"] == 19
    assert planner.rule_plan("set an alarm for 12 am", phone).steps[0].args["hour"] == 0
    # No phone: a reminder does the job.
    pc = ctx(targets={"core", "windows"}, now=now, tz=ist)
    p = planner.rule_plan("set a timer for 2 hours", pc)
    assert (p.steps[0].tool, p.steps[0].args["in_minutes"]) == ("reminders.create", 120)
    p = planner.rule_plan("set an alarm for 7 pm", pc)
    due = datetime.fromisoformat(p.steps[0].args["due_at"]).astimezone(ist)
    assert (due.hour, due.minute, due.date()) == (
        19,
        0,
        (now + timedelta(days=1)).astimezone(ist).date(),
    )
    assert planner.rule_plan("set an alarm for 25:00", pc) is None


def test_status_answers_instantly_when_offline() -> None:
    p = planner.rule_plan("how is my pc doing", ctx(targets={"core"}))
    assert p is not None and p.steps == [] and "agent isn't connected" in (p.answer or "")
    p = planner.rule_plan("check my phone", ctx(targets={"core"}))
    assert "phone" in (p.answer or "")


@pytest.mark.integration
async def test_chat_commands_skip_the_ai(migrated_database) -> None:  # type: ignore[no-untyped-def]
    provider = cloud()
    async with engine_app(migrated_database, [provider]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)

        # PC status with no agent: an instant answer, no AI call, no task.
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "How is my PC doing?"},
            headers=h,
        )
        body = r.json()
        assert r.status_code == 200, r.text
        assert body["assistant_message"]["provider"] == "ultron"
        assert "agent isn't connected" in body["assistant_message"]["content"]
        assert body["assistant_message"]["first_token_ms"] is not None
        assert provider.calls == []

        # A timer (no phone): a reminder task through the permission system.
        await grant(client, h, "reminders")
        app.state.task_engine.start()
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "set a timer for 5 minutes", "stream": True},
            headers=h,
        )
        events = parse_sse(r.text)
        assert [e for e, _ in events] == [
            "message.created",
            "provider.selected",
            "delta",
            "message.completed",
        ]
        text = events[-1][1]["assistant_message"]["content"]
        assert text.startswith("Certainly, Sir. Reminder set for today at ")
        assert provider.calls == []
        tasks = (await client.get("/api/v1/tasks", headers=h)).json()
        assert tasks[0]["steps"][0]["tool"] == "reminders.create"

        # Only looks like a command: goes to the AI as normal.
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "open your heart to new ideas"},
            headers=h,
        )
        assert r.json()["assistant_message"]["provider"] == "fake-cloud"
        assert len(provider.calls) == 1

        # Without permission the command asks, still without any AI.
        await client.put("/api/v1/permissions/reminders", json={"enabled": False}, headers=h)
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "wake me up at 6:30 am"},
            headers=h,
        )
        assert r.json()["assistant_message"]["content"].startswith("Before I go ahead, Sir")
        assert len(provider.calls) == 1


@pytest.mark.integration
async def test_chat_open_app_only_when_announced(migrated_database) -> None:  # type: ignore[no-untyped-def]
    provider = cloud()
    async with engine_app(migrated_database, [provider]) as (app, client):
        h = await owner_headers(app, client)
        await pc_agent(client, apps=["Notepad", "File Explorer"])
        cid = await new_conversation(client, h)
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": "open files"}, headers=h
        )
        msg = r.json()["assistant_message"]
        assert msg["provider"] == "ultron" and "File Explorer" in msg["content"]
        assert provider.calls == []
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": "open photoshop"}, headers=h
        )
        assert r.json()["assistant_message"]["provider"] == "fake-cloud"
