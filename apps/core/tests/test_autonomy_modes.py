"""Autonomy levels per area and operating modes."""

from __future__ import annotations

import json

import pytest

from tests.conftest import owner_headers
from tests.fakes import cloud
from tests.test_chat_api import new_conversation, send
from tests.test_tasks import command, drive, engine_app, get_task, grant, pc_agent
from ultron_core.tasks.permissions import Policy

pytestmark = pytest.mark.integration


def test_level_rules() -> None:
    def decide(level: int, scope: str, risk: str = "A", granted: bool = False) -> str:
        p = Policy(levels={"core": level, "pc": level, "phone": level})
        if granted:
            from types import SimpleNamespace

            p.grants[scope] = SimpleNamespace(enabled=True, expires_at=None)  # type: ignore[assignment]
        return p.decide(scope=scope, risk=risk, approved=False)

    assert decide(1, "pc.system", granted=True) == "ask"  # suggest: always asks
    assert decide(2, "pc.system") == "auto"  # prepare: read-only runs
    assert decide(2, "pc.files.write", granted=True) == "ask"
    assert decide(3, "pc.apps") == "ask" and decide(3, "pc.apps", granted=True) == "auto"
    assert decide(4, "pc.files.organize") == "auto"  # safe routines run
    for level in range(6):
        assert decide(level, "pc.files.write", risk="B", granted=True) == "ask"  # B always asks
        assert decide(level, "pc.files.delete") == "ask"


async def test_levels_api_and_effect(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with engine_app(migrated_database) as (app, client):
        h = await owner_headers(app, client)
        auto = (await client.get("/api/v1/automation", headers=h)).json()
        assert auto["levels"] == {"core": 3, "pc": 3, "phone": 3}
        assert auto["level_names"]["4"] == "Safe routines"
        bad = await client.put("/api/v1/automation", json={"levels": {"pc": 9}}, headers=h)
        assert bad.status_code == 422
        await client.put("/api/v1/automation", json={"levels": {"pc": 4}}, headers=h)
        await pc_agent(client)
        out = await command(client, h, "open notepad")  # pc.apps not granted
        await drive(app)
        task = await get_task(client, h, out["task"]["id"])
        assert task["steps"][0]["status"] == "ready"  # level 4: no approval needed

        await client.put("/api/v1/automation", json={"levels": {"core": 0}}, headers=h)
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "x", "steps": [{"tool": "memory.save", "args": {"content": "y"}}]},
            headers=h,
        )
        assert resp.status_code == 422 and "isn't allowed" in resp.json()["detail"]
        kinds = [e["kind"] for e in (await client.get("/api/v1/activity", headers=h)).json()]
        assert "automation.levels" in kinds


async def test_level_zero_hides_tools_from_the_planner(migrated_database) -> None:  # type: ignore[no-untyped-def]
    ai = cloud(chunks=[json.dumps({"title": "x", "steps": [], "answer": "I can only answer."})])
    async with engine_app(migrated_database, [ai]) as (app, client):
        h = await owner_headers(app, client)
        await pc_agent(client)
        await client.put("/api/v1/automation", json={"levels": {"pc": 0}}, headers=h)
        out = await command(client, h, "open notepad")  # rule can't use PC tools now
        assert out["type"] == "answer"
        assert "pc.apps.open" not in ai.calls[0].system


async def test_modes(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with engine_app(migrated_database, [c]) as (app, client):
        h = await owner_headers(app, client)
        modes = (await client.get("/api/v1/modes", headers=h)).json()
        assert [m["key"] for m in modes][:5] == ["normal", "work", "developer", "study", "focus"]
        assert next(m for m in modes if m["key"] == "normal")["active"] is True

        resp = await client.put("/api/v1/modes/active", json={"key": "developer"}, headers=h)
        assert resp.json()["active"] is True
        cid = await new_conversation(client, h)
        await send(client, h, cid, "Hi")
        assert "Current mode: Developer" in c.calls[-1].system

        custom = await client.post(
            "/api/v1/modes",
            json={
                "name": "Exam prep",
                "personality": "Quiz me.",
                "memory": False,
                "tool_areas": ["core"],
            },
            headers=h,
        )
        assert custom.status_code == 201 and custom.json()["key"] == "exam-prep"
        await client.post(
            "/api/v1/memories", json={"content": "Call me Nity", "pinned": True}, headers=h
        )
        await client.put("/api/v1/modes/active", json={"key": "exam-prep"}, headers=h)
        await send(client, h, cid, "Hi again")
        assert "Quiz me." in c.calls[-1].system and "Nity" not in c.calls[-1].system

        await pc_agent(client)
        await grant(client, h, "pc.apps")
        out = await command(client, h, "open notepad")  # PC not in this mode's areas
        assert out["type"] == "answer"

        assert (
            await client.put("/api/v1/modes/work", json={"name": "x"}, headers=h)
        ).status_code == 409
        assert (await client.delete("/api/v1/modes/exam-prep", headers=h)).status_code == 204
        active = [m for m in (await client.get("/api/v1/modes", headers=h)).json() if m["active"]]
        assert active[0]["key"] == "normal"  # deleting the active mode falls back
        assert (
            await client.put("/api/v1/modes/active", json={"key": "nope"}, headers=h)
        ).status_code == 404
