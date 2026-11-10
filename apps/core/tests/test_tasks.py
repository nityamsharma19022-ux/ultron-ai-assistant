"""Task engine: planning, permissions, execution on Core and on agents,
approvals, retries, controls, emergency stop, reminders and schedules."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select, update

from tests.conftest import _reset_state, bearer, login, owner_headers
from tests.fakes import cloud, local
from ultron_core.db.models import Memory, PermissionGrant, Reminder, Schedule, TaskStep
from ultron_core.main import create_app
from ultron_core.tasks import planner

pytestmark = pytest.mark.integration


@contextlib.asynccontextmanager
async def engine_app(settings, providers=None) -> AsyncIterator[tuple]:  # type: ignore[no-untyped-def]
    """App with the background loop off: tests drive the engine."""
    app = create_app(settings, ai_providers=providers or [cloud()], start_task_engine=False)
    async with LifespanManager(app):
        await _reset_state(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://ultron.test") as c:
            yield app, c
        await _reset_state(app)


async def drive(app, rounds: int = 6) -> None:  # type: ignore[no-untyped-def]
    engine = app.state.task_engine
    for _ in range(rounds):
        await engine.tick()
        runs = list(engine._core_runs.values())
        if runs:
            await asyncio.gather(*runs, return_exceptions=True)


async def command(client, headers, text, **extra):  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/assistant/command", json={"text": text, **extra}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def get_task(client, headers, task_id):  # type: ignore[no-untyped-def]
    return (await client.get(f"/api/v1/tasks/{task_id}", headers=headers)).json()


async def grant(client, headers, scope, **extra):  # type: ignore[no-untyped-def]
    resp = await client.put(
        f"/api/v1/permissions/{scope}", json={"enabled": True, **extra}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def pc_agent(client, tools=("pc.apps.open", "pc.files.write", "pc.files.delete"), **caps):  # type: ignore[no-untyped-def]
    resp = await login(client, device_name="Desk PC", platform="windows")
    h = bearer(resp.json()["access_token"])
    hello = await client.post(
        "/api/v1/agents/hello",
        json={"tools": list(tools), "capabilities": caps, "version": "test"},
        headers=h,
    )
    assert hello.status_code == 200, hello.text
    return h


async def take(client, agent_h):  # type: ignore[no-untyped-def]
    resp = await client.get("/api/v1/agents/steps/next?wait=0", headers=agent_h)
    return None if resp.status_code == 204 else resp.json()


async def report(client, agent_h, step_id, **body):  # type: ignore[no-untyped-def]
    resp = await client.post(f"/api/v1/agents/steps/{step_id}/result", json=body, headers=agent_h)
    assert resp.status_code == 200, resp.text
    return resp.json()


def plan_provider(plan: dict) -> object:  # type: ignore[type-arg]
    return cloud(chunks=[json.dumps(plan)])


# --- planner units ---------------------------------------------------------------


def ctx(**kw) -> planner.PlanContext:  # type: ignore[no-untyped-def]
    base = {"targets": {"core", "windows"}, "origin": "android"}
    base.update(kw)
    return planner.PlanContext(**base)


def test_rules() -> None:
    c = ctx(
        now=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
        tz=ZoneInfo("Asia/Kolkata"),
        capabilities={"windows": {"workflows": ["Dev Env"]}},
    )
    c.origin = "windows"
    p = planner.rule_plan("Hey ULTRON, please open Visual Studio Code.", c)
    assert [(s.tool, s.args) for s in p.steps] == [("pc.apps.open", {"app": "Visual Studio Code"})]
    p = planner.rule_plan("organize my downloads folder by date", c)
    assert p.steps[0].args == {"path": "downloads", "scheme": "by_date", "dry_run": False}
    p = planner.rule_plan("remind me to call mom at 9 pm", c)
    due = datetime.fromisoformat(p.steps[0].args["due_at"])
    assert due.astimezone(ZoneInfo("Asia/Kolkata")).hour == 21
    p = planner.rule_plan("remind me to stretch in 20 minutes", c)
    assert datetime.fromisoformat(p.steps[0].args["due_at"]) == c.now + timedelta(minutes=20)
    assert planner.rule_plan("run the dev env workflow", c).steps[0].args == {"name": "Dev Env"}
    assert planner.rule_plan("run the unknown workflow", c) is None
    assert planner.rule_plan("remember that my locker code is 42", c).steps[0].tool == "memory.save"
    assert planner.rule_plan("organize my secret-stuff", c) is None  # not a known folder
    assert planner.rule_plan("what is the capital of France?", c) is None
    # No PC connected: "open" goes to the phone instead.
    p = planner.rule_plan("open spotify", ctx(targets={"core", "android"}))
    assert p.steps[0].tool == "phone.apps.open"
    # Asked from the phone with both connected: the phone opens it.
    both = ctx(targets={"core", "windows", "android"})
    assert planner.rule_plan("open spotify", both).steps[0].tool == "phone.apps.open"
    # Only tools the online agents announced are used.
    limited = ctx(targets={"core", "windows"}, device_tools={"pc.status"})
    assert planner.rule_plan("open spotify", limited) is None
    assert planner.rule_plan("pc status", limited).steps[0].tool == "pc.status"


def test_plan_validation() -> None:
    assert planner.parse_plan_json('<think>x</think>```json\n{"steps": []}\n```') == {"steps": []}
    with pytest.raises(planner.PlanError):
        planner.parse_plan_json("I can't do that")
    with pytest.raises(planner.PlanError, match="Unknown tool"):
        planner.build_steps([{"tool": "shell.exec", "args": {"cmd": "rm -rf /"}}])
    with pytest.raises(planner.PlanError, match="Invalid arguments"):
        planner.build_steps([{"tool": "pc.apps.open", "args": {"app": "x", "argv": ["evil"]}}])
    with pytest.raises(planner.PlanError, match="earlier step"):
        planner.build_steps(
            [{"tool": "pc.files.write", "args": {"path": "documents/a.md", "content_from_step": 0}}]
        )
    steps = planner.build_steps(
        [
            {
                "tool": "pc.files.write",
                "args": {"path": "documents/a.md", "content": "x", "overwrite": True},
            }
        ]
    )
    assert steps[0].risk == "B"  # overwriting asks
    with pytest.raises(planner.PlanError, match="more than"):
        planner.build_steps([{"tool": "pc.status"}] * 11)


# --- Core tools, approvals, permissions ----------------------------------------------


async def test_routine_action_asks_once_then_runs_by_itself(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        out = await command(client, h, "Remember that my locker code is 4521")
        task = out["task"]
        await drive(app)
        task = await get_task(client, h, task["id"])
        assert task["status"] == "awaiting_approval"
        assert task["steps"][0]["status"] == "awaiting_approval"

        resp = await client.post(
            f"/api/v1/tasks/{task['id']}/approve", json={"remember": True}, headers=h
        )
        assert resp.status_code == 200
        await drive(app)
        task = await get_task(client, h, task["id"])
        assert task["status"] == "completed", task
        assert "Saved to memory" in task["summary"]
        async with app.state.sessionmaker() as s:
            assert (await s.scalar(select(Memory.content))) == "my locker code is 4521"

        perms = {p["scope"]: p for p in (await client.get("/api/v1/permissions", headers=h)).json()}
        assert perms["memory.write"]["granted"] is True
        # Second time: no question asked.
        out = await command(client, h, "remember that I like green tea")
        await drive(app)
        assert (await get_task(client, h, out["task"]["id"]))["status"] == "completed"


async def test_command_waits_and_reports_done(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "reminders")
        app.state.task_engine.start()  # the real background loop
        out = await command(client, h, "remind me to stretch in 15 minutes", wait=True)
        assert out["type"] == "task"
        assert out["task"]["status"] == "completed"
        assert out["message"].startswith("Done. ")
        reminders = (await client.get("/api/v1/reminders", headers=h)).json()
        assert reminders[0]["text"] == "stretch"
        assert (await client.get("/api/v1/reminders?due=true", headers=h)).json() == []
        async with app.state.sessionmaker() as s:
            await s.execute(
                update(Reminder).values(due_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await s.commit()
        due = (await client.get("/api/v1/reminders?due=true", headers=h)).json()
        assert len(due) == 1
        await client.patch(f"/api/v1/reminders/{due[0]['id']}", json={"delivered": True}, headers=h)
        assert (await client.get("/api/v1/reminders?due=true", headers=h)).json() == []


async def test_questions_get_answers_not_tasks(migrated_database) -> None:  # type: ignore[no-untyped-def]
    ai = plan_provider({"title": "Answer", "steps": [], "answer": "Paris."})
    async with engine_app(migrated_database, [ai]) as (app, client):
        h = await owner_headers(app, client)
        out = await command(client, h, "What is the capital of France?")
        assert out == {"type": "answer", "message": "Paris.", "task": None}
        assert (await client.get("/api/v1/tasks", headers=h)).json() == []
        assert "Available tools" in ai.calls[0].system


async def test_bad_ai_plans_are_rejected(migrated_database) -> None:  # type: ignore[no-untyped-def]
    ai = plan_provider(
        {"title": "x", "steps": [{"tool": "shell.exec", "args": {"cmd": "format c:"}}]}
    )
    async with engine_app(migrated_database, [ai]) as (app, client):
        h = await owner_headers(app, client)
        out = await command(client, h, "wipe my disk")
        assert out["type"] == "answer"
        assert "Unknown tool" in out["message"]
        assert (await client.get("/api/v1/tasks", headers=h)).json() == []


async def test_private_tasks_plan_with_local_ai_only(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = plan_provider({"title": "x", "steps": [], "answer": "cloud"})
    lo = local(chunks=[json.dumps({"title": "x", "steps": [], "answer": "local"})])
    async with engine_app(migrated_database, [c, lo]) as (app, client):
        h = await owner_headers(app, client)
        out = await command(client, h, "Summarise my private notes", private=True)
        assert out["message"] == "local"
        assert c.calls == []


# --- agents --------------------------------------------------------------------


async def test_pc_step_runs_on_the_agent(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "pc.apps")
        agent = await pc_agent(client, apps=["VS Code", "Notepad"])
        agents = (await client.get("/api/v1/agents", headers=h)).json()
        assert agents[0]["online"] is True and agents[0]["capabilities"]["apps"] == [
            "VS Code",
            "Notepad",
        ]

        out = await command(client, h, "open VS Code")
        await drive(app)
        task = await get_task(client, h, out["task"]["id"])
        assert task["steps"][0]["status"] == "ready"
        assert "Waiting for your PC" in task["steps"][0]["progress"]

        work = await take(client, agent)
        assert work["tool"] == "pc.apps.open" and work["args"] == {"app": "VS Code"}
        assert await take(client, agent) is None  # claimed once only
        progress = await client.post(
            f"/api/v1/agents/steps/{work['id']}/progress",
            json={"message": "Starting"},
            headers=agent,
        )
        assert progress.json() == {"cancel": False}
        await report(
            client, agent, work["id"], ok=True, result={"summary": "Opened", "verified": True}
        )
        await drive(app)
        task = await get_task(client, h, out["task"]["id"])
        assert task["status"] == "completed"
        kinds = [e["kind"] for e in (await client.get("/api/v1/activity", headers=h)).json()]
        assert {"task.created", "step.succeeded", "task.completed"} <= set(kinds)


async def test_agent_boundaries(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)  # an Android device
        await grant(client, h, "pc.apps")
        # Android devices can't announce PC tools.
        resp = await client.post(
            "/api/v1/agents/hello", json={"tools": ["pc.apps.open"]}, headers=h
        )
        assert resp.json()["tools"] == []
        other = bearer(
            (await login(client, device_name="?", platform="other")).json()["access_token"]
        )
        resp = await client.post("/api/v1/agents/hello", json={"tools": []}, headers=other)
        assert resp.status_code == 400
        agent = await pc_agent(client)
        out = await command(client, h, "open notepad")
        await drive(app)
        assert await take(client, h) is None  # the phone doesn't get PC work
        work = await take(client, agent)
        # Another device can't report this step's result.
        resp = await client.post(
            f"/api/v1/agents/steps/{work['id']}/result", json={"ok": True}, headers=h
        )
        assert resp.status_code == 404
        await report(client, agent, work["id"], ok=True)
        await drive(app)
        assert (await get_task(client, h, out["task"]["id"]))["status"] == "completed"


async def test_ai_plan_passes_text_between_steps(migrated_database) -> None:  # type: ignore[no-untyped-def]
    plan = {
        "title": "Weekly study timetable",
        "steps": [
            {
                "tool": "ai.write",
                "args": {"instructions": "Weekly study timetable", "kind": "timetable"},
            },
            {
                "tool": "pc.files.write",
                "args": {"path": "documents/Study/timetable.md", "content_from_step": 0},
            },
        ],
    }
    planner_ai = plan_provider(plan)
    async with engine_app(migrated_database, [planner_ai]) as (app, client):
        h = await owner_headers(app, client)
        for scope in ("ai.write", "pc.files.write"):
            await grant(client, h, scope)
        agent = await pc_agent(client, roots=["documents", "downloads"])
        planner_ai.chunks = [json.dumps(plan)]
        out = await command(client, h, "prepare my weekly study timetable")
        assert [s["tool"] for s in out["task"]["steps"]] == ["ai.write", "pc.files.write"]
        assert "documents, downloads" in planner_ai.calls[0].system  # real folder names
        planner_ai.chunks = ["Mon: maths", "\nTue: physics"]  # the writer's reply
        await drive(app)
        work = await take(client, agent)
        assert work["args"]["content"] == "Mon: maths\nTue: physics"
        assert "content_from_step" not in work["args"]
        await report(
            client, agent, work["id"], ok=True, result={"summary": "Created", "verified": True}
        )
        await drive(app)
        task = await get_task(client, h, out["task"]["id"])
        assert task["status"] == "completed", task


async def test_consequential_actions_always_ask(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        resp = await client.put(
            "/api/v1/permissions/pc.files.delete", json={"enabled": True}, headers=h
        )
        assert resp.status_code == 409
        await grant(client, h, "pc.files.write")
        await pc_agent(client)
        resp = await client.post(
            "/api/v1/tasks",
            json={
                "title": "Replace notes",
                "steps": [
                    {
                        "tool": "pc.files.write",
                        "args": {"path": "documents/n.md", "content": "x", "overwrite": True},
                    },
                    {"tool": "pc.files.delete", "args": {"path": "downloads/old.zip"}},
                ],
            },
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        task = resp.json()
        assert [s["risk"] for s in task["steps"]] == ["B", "B"]
        await drive(app)
        task = await get_task(client, h, task["id"])
        assert task["status"] == "awaiting_approval"  # even though pc.files.write is granted
        # "Always allow" is never stored for class B.
        await client.post(f"/api/v1/tasks/{task['id']}/approve", json={"remember": True}, headers=h)
        perms = {p["scope"]: p for p in (await client.get("/api/v1/permissions", headers=h)).json()}
        assert perms["pc.files.delete"]["granted"] is False


async def test_retries_then_failure_then_manual_retry(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "pc.apps")
        agent = await pc_agent(client)
        out = await command(client, h, "open notepad")
        tid = out["task"]["id"]
        await drive(app)
        work = await take(client, agent)
        await report(client, agent, work["id"], ok=False, error="App is starting", retryable=True)
        task = await get_task(client, h, tid)
        assert (
            task["steps"][0]["status"] == "pending" and "Retrying" in task["steps"][0]["progress"]
        )
        async with app.state.sessionmaker() as s:
            await s.execute(update(TaskStep).values(not_before=None))
            await s.commit()
        await drive(app)
        work = await take(client, agent)
        assert work["attempt"] == 2
        await report(
            client, agent, work["id"], ok=False, error="Notepad isn't allowed", retryable=True
        )
        await drive(app)  # max_attempts (2) reached
        task = await get_task(client, h, tid)
        assert task["status"] == "failed" and "isn't allowed" in task["error"]

        task = (await client.post(f"/api/v1/tasks/{tid}/retry", headers=h)).json()
        assert task["status"] == "queued" and task["steps"][0]["attempts"] == 0
        await drive(app)
        work = await take(client, agent)
        await report(client, agent, work["id"], ok=True)
        await drive(app)
        assert (await get_task(client, h, tid))["status"] == "completed"


async def test_unverified_result_fails(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "pc.apps")
        agent = await pc_agent(client)
        out = await command(client, h, "open notepad")
        await drive(app)
        work = await take(client, agent)
        await report(
            client, agent, work["id"], ok=True, result={"verified": False, "summary": "No window"}
        )
        await drive(app)
        task = await get_task(client, h, out["task"]["id"])
        assert task["status"] == "failed" and task["error"] == "No window"


async def test_pause_resume_cancel(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "pc.apps")
        agent = await pc_agent(client)
        out = await command(client, h, "open notepad")
        tid = out["task"]["id"]
        assert (await client.post(f"/api/v1/tasks/{tid}/pause", headers=h)).json()[
            "status"
        ] == "paused"
        await drive(app)
        assert await take(client, agent) is None  # paused: nothing dispatched
        assert (await client.post(f"/api/v1/tasks/{tid}/resume", headers=h)).json()[
            "status"
        ] == "queued"
        await drive(app)
        work = await take(client, agent)
        task = (await client.post(f"/api/v1/tasks/{tid}/cancel", headers=h)).json()
        assert task["status"] == "cancelled"
        control = await client.post(
            f"/api/v1/agents/steps/{work['id']}/progress", json={"message": "x"}, headers=agent
        )
        assert control.json() == {"cancel": True}  # the agent is told to stop
        assert (await report(client, agent, work["id"], ok=True)) == {"cancel": True}
        assert (await client.post(f"/api/v1/tasks/{tid}/cancel", headers=h)).status_code == 409


async def test_emergency_stop_and_master_switch(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "pc.apps")
        await grant(client, h, "memory.write")
        await pc_agent(client)
        first = await command(client, h, "open notepad")
        stop = await client.post("/api/v1/automation/emergency-stop", headers=h)
        assert stop.json()["stopped"] is True
        assert (await get_task(client, h, first["task"]["id"]))["status"] == "cancelled"

        later = await command(client, h, "remember the stop test")
        await drive(app)
        task = await get_task(client, h, later["task"]["id"])
        assert task["status"] == "queued"
        assert task["steps"][0]["progress"] == "Waiting: automation is paused"

        await client.put("/api/v1/automation", json={"stopped": False}, headers=h)
        await drive(app)
        assert (await get_task(client, h, later["task"]["id"]))["status"] == "completed"

        await client.put("/api/v1/automation", json={"enabled": False}, headers=h)
        off = await command(client, h, "remember the switch test")
        await drive(app)
        assert (await get_task(client, h, off["task"]["id"]))["status"] == "queued"
        kinds = [e["kind"] for e in (await client.get("/api/v1/activity", headers=h)).json()]
        assert "automation.emergency_stop" in kinds and "automation.switched" in kinds


async def test_expired_permission_asks_again(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "memory.write", expires_in_days=1)
        async with app.state.sessionmaker() as s:
            await s.execute(
                update(PermissionGrant).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await s.commit()
        out = await command(client, h, "remember that grants expire")
        await drive(app)
        assert (await get_task(client, h, out["task"]["id"]))["status"] == "awaiting_approval"
        # Revoking works too.
        resp = await client.put(
            "/api/v1/permissions/memory.write", json={"enabled": False}, headers=h
        )
        assert resp.json()["granted"] is False


async def test_recurring_task(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "memory.write")
        out = await command(client, h, "remember to drink water")
        await drive(app)
        resp = await client.post(
            f"/api/v1/tasks/{out['task']['id']}/repeat",
            json={"every": "daily", "at": "08:30", "timezone": "Asia/Kolkata"},
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        sched = resp.json()
        local = datetime.fromisoformat(sched["next_run_at"]).astimezone(ZoneInfo("Asia/Kolkata"))
        assert (local.hour, local.minute) == (8, 30)
        async with app.state.sessionmaker() as s:
            await s.execute(
                update(Schedule).values(next_run_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await s.commit()
        await drive(app)
        tasks = (await client.get("/api/v1/tasks", headers=h)).json()
        assert len(tasks) == 2 and tasks[0]["plan_source"] == "schedule"
        assert tasks[0]["status"] == "completed"
        schedules = (await client.get("/api/v1/schedules", headers=h)).json()
        assert datetime.fromisoformat(schedules[0]["next_run_at"]) > datetime.now(UTC)


async def test_device_wait_timeout(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        await grant(client, h, "pc.apps")
        await pc_agent(client)
        out = await command(client, h, "open notepad")
        await drive(app)
        async with app.state.sessionmaker() as s:
            await s.execute(
                update(TaskStep).values(started_at=datetime.now(UTC) - timedelta(hours=2))
            )
            await s.commit()
        await drive(app)
        task = await get_task(client, h, out["task"]["id"])
        assert task["status"] == "failed" and "didn't connect" in task["error"]


async def test_task_validation(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        bad = await client.post(
            "/api/v1/tasks", json={"title": "x", "steps": [{"tool": "nope", "args": {}}]}, headers=h
        )
        assert bad.status_code == 422 and "Unknown tool" in bad.json()["detail"]
        resp = await client.post("/api/v1/assistant/command", json={"text": "  "}, headers=h)
        assert resp.status_code == 422
        assert (
            await client.post("/api/v1/assistant/command", json={"text": "hi"})
        ).status_code == 401
