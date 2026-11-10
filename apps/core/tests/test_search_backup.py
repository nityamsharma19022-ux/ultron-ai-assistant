"""Conversation search, memory projects, pausing memory saving, data export
and the automatic safety pause."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import update

from tests.conftest import owner_headers
from tests.fakes import cloud
from tests.test_chat_api import new_conversation, send
from tests.test_tasks import drive, engine_app
from ultron_core import safety
from ultron_core.db.models import Task

pytestmark = pytest.mark.integration


async def test_search_conversations(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        physics = await new_conversation(client, h, title="Physics", project="Exams")
        other = await new_conversation(client, h, title="Cooking")
        await send(client, h, physics, "Explain the thermodynamics exam topics")
        await send(client, h, other, "A recipe for paneer tikka")
        gone = await new_conversation(client, h, title="Old")
        await send(client, h, gone, "thermodynamics notes from last year")
        await client.delete(f"/api/v1/conversations/{gone}", headers=h)

        hits = (
            await client.get("/api/v1/conversations/search", params={"q": "exams"}, headers=h)
        ).json()
        assert [x["conversation_id"] for x in hits] == [physics]  # deleted one hidden
        assert hits[0]["project"] == "Exams" and "«exam»" in hits[0]["snippet"]
        assert hits[0]["role"] == "user"
        none = await client.get("/api/v1/conversations/search", params={"q": "?!"}, headers=h)
        assert none.json() == []
        bad = await client.get("/api/v1/conversations/search", params={"q": ""}, headers=h)
        assert bad.status_code == 422

        moved = await client.patch(
            f"/api/v1/conversations/{other}", json={"project": "  Home   life "}, headers=h
        )
        assert moved.json()["project"] == "Home life"
        cleared = await client.patch(
            f"/api/v1/conversations/{other}", json={"project": ""}, headers=h
        )
        assert cleared.json()["project"] is None


async def test_project_memories_are_scoped(migrated_database) -> None:  # type: ignore[no-untyped-def]
    provider = cloud()
    async with engine_app(migrated_database, [provider]) as (app, client):
        h = await owner_headers(app, client)
        for content, project in (
            ("ULTRON deadline is Friday", "ULTRON"),
            ("Thesis deadline is Monday", "Thesis"),
            ("General deadline rule: start early", None),
        ):
            body = {"content": content, **({"project": project} if project else {})}
            assert (await client.post("/api/v1/memories", json=body, headers=h)).status_code == 201
        listed = (await client.get("/api/v1/memories?project=ultron", headers=h)).json()
        assert [m["content"] for m in listed] == ["ULTRON deadline is Friday"]

        cid = await new_conversation(client, h, project="ULTRON")
        await send(client, h, cid, "when is the deadline?")
        system = provider.calls[-1].system
        assert "Friday" in system and "start early" in system and "Monday" not in system

        plain = await new_conversation(client, h)
        await send(client, h, plain, "when is the deadline?")
        system = provider.calls[-1].system
        assert "Friday" in system and "Monday" in system  # no project: everything

        mem = listed[0]["id"]
        out = await client.patch(f"/api/v1/memories/{mem}", json={"project": ""}, headers=h)
        assert out.json()["project"] is None


async def test_pause_memory_saving(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        prefs = (await client.get("/api/v1/ai/preferences", headers=h)).json()
        assert prefs["memory_saving_paused"] is False
        prefs = (
            await client.put(
                "/api/v1/ai/preferences",
                json={"mode": "auto", "memory_saving_paused": True},
                headers=h,
            )
        ).json()
        assert prefs["memory_saving_paused"] is True and prefs["memory_enabled"] is True
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "save", "steps": [{"tool": "memory.save", "args": {"content": "x"}}]},
            headers=h,
        )
        await drive(app)
        ok = await client.post(
            f"/api/v1/tasks/{resp.json()['id']}/approve", json={"remember": False}, headers=h
        )
        assert ok.status_code == 200, ok.text
        await drive(app)
        task = (await client.get(f"/api/v1/tasks/{resp.json()['id']}", headers=h)).json()
        assert task["status"] == "failed" and "paused" in task["steps"][0]["error"]
        # Saving by hand still works.
        manual = await client.post("/api/v1/memories", json={"content": "by hand"}, headers=h)
        assert manual.status_code == 201


async def test_export(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h, title="Plans", project="Trip")
        await send(client, h, cid, "Plan a trip to Goa")
        await client.post("/api/v1/memories", json={"content": "Likes beaches"}, headers=h)
        data = (await client.get("/api/v1/export", headers=h)).json()
        assert data["format"] == "ultron-export/1" and data["includes_private"] is False
        assert data["user"]["email"]
        conv = data["conversations"][0]
        assert conv["title"] == "Plans" and conv["project"] == "Trip"
        assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
        assert data["memories"][0]["content"] == "Likes beaches"
        text = json.dumps(data)
        for secret in ("password", "token_hash", "refresh", "argon2"):
            assert secret not in text
        kinds = [e["kind"] for e in (await client.get("/api/v1/activity", headers=h)).json()]
        assert "data.exported" in kinds


async def test_safety_pause_after_many_failures(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        ids = []
        for i in range(safety.FAILURE_LIMIT):
            resp = await client.post(
                "/api/v1/tasks",
                json={
                    "title": f"t{i}",
                    "steps": [{"tool": "memory.search", "args": {"query": "x"}}],
                },
                headers=h,
            )
            ids.append(resp.json()["id"])
        async with app.state.sessionmaker() as s:
            await s.execute(update(Task).where(Task.id.in_(ids[:-1])).values(status="failed"))
            await s.execute(
                update(Task).where(Task.id.in_(ids[:-1])).values(finished_at=Task.created_at)
            )
            await s.commit()
            task = await s.get(Task, ids[-1])
            task.status = "failed"
            task.finished_at = task.created_at
            assert await safety.after_failure(s, task.user_id)
            await s.commit()
        auto = (await client.get("/api/v1/automation", headers=h)).json()
        assert auto["enabled"] is False
        notes = (await client.get("/api/v1/notifications", headers=h)).json()
        assert any(n["kind"] == "automation.paused" and n["priority"] == "urgent" for n in notes)
