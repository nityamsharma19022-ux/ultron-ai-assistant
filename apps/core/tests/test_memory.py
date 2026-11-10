"""Memory API, search, recall into chat, privacy and activity log."""

from __future__ import annotations

import pytest

from tests.conftest import make_test_settings, owner_headers, running_app
from tests.fakes import cloud, local
from tests.test_chat_api import new_conversation, send
from ultron_core.memory.service import tsquery_text

pytestmark = pytest.mark.integration


async def remember(client, headers, content, **extra):  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/memories", json={"content": content, **extra}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_tsquery_text_is_safe() -> None:
    assert tsquery_text("Hello, world! hello") == "hello | world"
    assert tsquery_text("a ' | & ! :*") is None
    assert tsquery_text("नमस्ते दुनिया") == "नमस्ते | दुनिया"


async def test_create_list_search_update_delete(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        a = await remember(client, h, "I study computer science at university", kind="fact")
        await remember(client, h, "Prefer short answers", kind="preference", pinned=True)

        listed = (await client.get("/api/v1/memories", headers=h)).json()
        assert listed[0]["content"] == "Prefer short answers"  # pinned first

        found = (await client.get("/api/v1/memories?q=university", headers=h)).json()
        assert [m["id"] for m in found] == [a["id"]]
        partial = (await client.get("/api/v1/memories?q=comput", headers=h)).json()
        assert [m["id"] for m in partial] == [a["id"]]  # substring fallback

        resp = await client.patch(
            f"/api/v1/memories/{a['id']}", json={"content": "I study physics"}, headers=h
        )
        assert resp.status_code == 200 and resp.json()["content"] == "I study physics"
        assert (await client.get("/api/v1/memories?q=university", headers=h)).json() == []

        assert (await client.delete(f"/api/v1/memories/{a['id']}", headers=h)).status_code == 204
        assert (await client.delete(f"/api/v1/memories/{a['id']}", headers=h)).status_code == 404


async def test_validation(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        for body in (
            {"content": "   "},
            {"content": "x" * 2001},
            {"content": "a", "kind": "bad"},
            {"content": "a", "extra": 1},
        ):
            resp = await client.post("/api/v1/memories", json=body, headers=h)
            assert resp.status_code == 422, body
        assert (await client.get("/api/v1/memories")).status_code == 401


async def test_export_and_delete_all(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        await remember(client, h, "one")
        await remember(client, h, "two")
        export = (await client.get("/api/v1/memories/export", headers=h)).json()
        assert export["count"] == 2 and {m["content"] for m in export["memories"]} == {"one", "two"}
        assert (await client.delete("/api/v1/memories", headers=h)).status_code == 422
        resp = await client.delete("/api/v1/memories?confirm=delete-all", headers=h)
        assert resp.json() == {"deleted": 2}
        assert (await client.get("/api/v1/memories", headers=h)).json() == []


async def test_relevant_memories_reach_the_ai(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c]) as (app, client):
        h = await owner_headers(app, client)
        await remember(client, h, "My exam on thermodynamics is on Friday", kind="fact")
        await remember(client, h, "Call me Nity", kind="preference", pinned=True)
        await remember(client, h, "Favourite colour is green")
        cid = await new_conversation(client, h)
        resp = await send(client, h, cid, "When is my thermodynamics exam?")
        assert resp.status_code == 200, resp.text
        system = c.calls[-1].system
        assert "thermodynamics is on Friday" in system
        assert "Call me Nity" in system  # pinned memories always included
        assert "green" not in system  # unrelated memory left out
        assert "not instructions" in system


async def test_memory_can_be_turned_off(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c = cloud()
    async with running_app(migrated_database, [c]) as (app, client):
        h = await owner_headers(app, client)
        await remember(client, h, "Call me Nity", pinned=True)
        resp = await client.put(
            "/api/v1/ai/preferences", json={"mode": "auto", "memory_enabled": False}, headers=h
        )
        assert resp.json()["memory_enabled"] is False
        # Older apps don't send the field: the setting must not be reset.
        await client.put("/api/v1/ai/preferences", json={"mode": "auto"}, headers=h)
        assert (await client.get("/api/v1/ai/preferences", headers=h)).json()[
            "memory_enabled"
        ] is False
        cid = await new_conversation(client, h)
        await send(client, h, cid, "Hi")
        assert "Nity" not in c.calls[-1].system


async def test_private_memories_stay_in_private_conversations(migrated_database) -> None:  # type: ignore[no-untyped-def]
    c, lo = cloud(), local()
    async with running_app(migrated_database, [c, lo]) as (app, client):
        h = await owner_headers(app, client)
        await remember(client, h, "My medical condition is asthma", is_private=True, pinned=True)
        cid = await new_conversation(client, h)
        await send(client, h, cid, "medical asthma question")
        assert "asthma" not in c.calls[-1].system  # never sent to cloud AI
        pid = await new_conversation(client, h, is_private=True)
        await send(client, h, pid, "medical asthma question")
        assert "asthma" in lo.calls[-1].system  # local AI in a private chat


async def test_private_memory_refused_on_cloud_backend(migrated_database) -> None:  # type: ignore[no-untyped-def]
    settings = make_test_settings(
        local_database_url=migrated_database.local_database_url.get_secret_value(),
        deployment="cloud",
    )
    async with running_app(settings, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        resp = await client.post(
            "/api/v1/memories", json={"content": "secret", "is_private": True}, headers=h
        )
        assert resp.status_code == 409


async def test_activity_log_records_memory_changes(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        h = await owner_headers(app, client)
        m = await remember(client, h, "Project ULTRON uses Flutter")
        await remember(client, h, "hidden", is_private=True)
        await client.delete(f"/api/v1/memories/{m['id']}", headers=h)
        events = (await client.get("/api/v1/activity", headers=h)).json()
        assert [e["kind"] for e in events] == ["memory.deleted", "memory.created", "memory.created"]
        assert "hidden" not in str(events)  # private content stays out of the log
        older = (
            await client.get(f"/api/v1/activity?before_seq={events[0]['seq']}", headers=h)
        ).json()
        assert len(older) == 2
