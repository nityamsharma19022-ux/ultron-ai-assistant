"""Notifications, quiet hours, proactive rules and device metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from tests.conftest import bearer, login, owner_headers
from tests.test_tasks import command, drive, engine_app, grant, pc_agent, report, take
from ultron_core.db.models import Reminder, Task, TaskStep
from ultron_core.notifications import in_quiet_hours, should_announce


def _s(**kw):  # type: ignore[no-untyped-def]
    base = {
        "quiet_start": None,
        "quiet_end": None,
        "utc_offset_minutes": 0,
        "min_priority": "normal",
    }
    return SimpleNamespace(**{**base, **kw})


def _n(priority: str, read: bool = False):  # type: ignore[no-untyped-def]
    return SimpleNamespace(priority=priority, read_at=datetime.now(UTC) if read else None)


def test_announce_rules() -> None:
    at_23 = datetime(2026, 11, 10, 17, 30, tzinfo=UTC)  # 23:00 in India (+05:30)
    quiet = _s(quiet_start="22:00", quiet_end="07:00", utc_offset_minutes=330)
    assert in_quiet_hours(quiet, at_23)
    assert not in_quiet_hours(quiet, datetime(2026, 11, 10, 6, 30, tzinfo=UTC))  # 12:00 local
    assert should_announce(_n("urgent"), quiet, mode_quiet=False, now=at_23)
    assert not should_announce(_n("high"), quiet, mode_quiet=False, now=at_23)
    day = _s()
    assert should_announce(_n("normal"), day, mode_quiet=False)
    assert not should_announce(_n("low"), day, mode_quiet=False)
    assert not should_announce(_n("normal"), day, mode_quiet=True)  # Focus mode
    assert should_announce(_n("high"), day, mode_quiet=True)
    assert not should_announce(_n("urgent", read=True), day, mode_quiet=False)


@pytest.mark.integration
async def test_proactive_rules_and_api(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        engine = app.state.task_engine
        await grant(client, h, "pc.apps")
        agent = await pc_agent(client)

        # A failed task -> high priority notification.
        out = await command(client, h, "open notepad")
        await drive(app)
        work = await take(client, agent)
        await report(client, agent, work["id"], ok=False, error="Not allowed")
        await drive(app)

        # Waiting approval, an offline device with waiting steps, a due reminder.
        waiting = await command(client, h, "remember the milk")
        stuck = await command(client, h, "open calculator")
        await drive(app)
        async with app.state.sessionmaker() as s:
            old = datetime.now(UTC) - timedelta(minutes=20)
            await s.execute(
                update(Task).where(Task.id == waiting["task"]["id"]).values(updated_at=old)
            )
            await s.execute(
                update(TaskStep)
                .where(TaskStep.task_id == stuck["task"]["id"])
                .values(started_at=old)
            )
            from ultron_core.db.models import AgentInfo

            await s.execute(update(AgentInfo).values(last_seen_at=old))
            s.add(
                Reminder(
                    user_id=(
                        await s.scalar(
                            Task.__table__.select().with_only_columns(Task.user_id).limit(1)
                        )
                    ),
                    text="Call mom",
                    due_at=old,
                )
            )
            await s.commit()
        await engine._run_proactive(force=True)
        await engine._run_proactive(force=True)  # deduplicated: nothing new

        items = (await client.get("/api/v1/notifications", headers=h)).json()
        kinds = sorted(i["kind"] for i in items)
        assert kinds == ["device.offline", "reminder", "task.approval", "task.failed"], items
        failed = next(i for i in items if i["kind"] == "task.failed")
        assert failed["priority"] == "high" and failed["task_id"] == out["task"]["id"]
        assert "Not allowed" in failed["body"] and failed["announce"] is True

        # Quiet mode: only high/urgent announce.
        await client.put("/api/v1/modes/active", json={"key": "focus"}, headers=h)
        items = (await client.get("/api/v1/notifications", headers=h)).json()
        approval = next(i for i in items if i["kind"] == "task.approval")
        assert approval["announce"] is False

        await client.post(f"/api/v1/notifications/{failed['id']}/read", headers=h)
        unread = (await client.get("/api/v1/notifications?unread=true", headers=h)).json()
        assert len(unread) == 3
        assert (await client.post("/api/v1/notifications/read-all", headers=h)).json() == {
            "marked": 3
        }


@pytest.mark.integration
async def test_settings_briefing_and_metrics(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        bad = await client.put(
            "/api/v1/notifications/settings", json={"quiet_start": "25:00"}, headers=h
        )
        assert bad.status_code == 422
        resp = await client.put(
            "/api/v1/notifications/settings",
            json={
                "quiet_start": "23:00",
                "quiet_end": "07:00",
                "utc_offset_minutes": 330,
                "min_priority": "normal",
                "daily_briefing": "00:00",
            },
            headers=h,
        )
        assert resp.json()["daily_briefing"] == "00:00"
        await command(client, h, "remember to drink water")  # waits for approval
        await app.state.task_engine._run_proactive(force=True)
        items = (await client.get("/api/v1/notifications", headers=h)).json()
        briefing = next(i for i in items if i["kind"] == "briefing")
        assert briefing["body"].startswith("1 task(s) waiting")

        # Metrics: the PC reports, low battery is noticed.
        pc = bearer(
            (await login(client, device_name="Desk PC", platform="windows")).json()["access_token"]
        )
        r = await client.post(
            "/api/v1/devices/metrics",
            json={
                "cpu_percent": 12.5,
                "memory_percent": 40,
                "battery_percent": 9,
                "charging": False,
            },
            headers=pc,
        )
        assert r.status_code == 204
        assert (
            await client.post("/api/v1/devices/metrics", json={"cpu_percent": 300}, headers=pc)
        ).status_code == 422
        metrics = (await client.get("/api/v1/devices/metrics", headers=h)).json()
        assert (
            metrics[0]["device_name"] == "Desk PC" and metrics[0]["metrics"]["cpu_percent"] == 12.5
        )
        await app.state.task_engine._run_proactive(force=True)
        kinds = [i["kind"] for i in (await client.get("/api/v1/notifications", headers=h)).json()]
        assert "device.battery" in kinds
