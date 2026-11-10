"""Speed: provider ranking, Instant-mode racing, Ollama CPU/GPU and
keep-alive defaults."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import update

from tests.conftest import owner_headers, running_app
from tests.fakes import cloud, local
from tests.test_ai_router import AUTO, _request, make_router, run
from tests.test_chat_api import new_conversation
from ultron_core.ai import errors, speed
from ultron_core.ai.providers.ollama import OllamaProvider
from ultron_core.ai.router import Completed
from ultron_core.ai.types import ProviderKind
from ultron_core.db.models import Message


def test_rank_fastest_first_with_preferences_and_new_providers() -> None:
    order = ["freellmapi", "groq", "gemini", "custom"]
    avg = {"freellmapi": 750.0, "custom": 450.0, "groq": 900.0}
    assert speed.rank(order, [], avg) == (
        "gemini",
        "custom",
        "freellmapi",
        "groq",
    )  # unmeasured first
    assert speed.rank(order, ["groq"], avg) == ("groq", "gemini", "custom", "freellmapi")
    assert speed.rank(order, [], {}) == tuple(order)


async def test_race_fastest_wins_and_loser_is_cancelled() -> None:
    slow = cloud("slow", block=asyncio.Event())  # never starts talking
    fast = cloud("fast")
    router = make_router(slow, fast, local(), order=("slow", "fast"))
    events = []
    async for e in router.stream(_request, AUTO, private=False, race=2):
        events.append(e)

    done = next(e for e in events if isinstance(e, Completed))
    assert done.route.provider == "fast"
    assert {a.outcome for a in done.route.attempts if a.provider == "slow"} == {"raced_out"}
    assert done.route.fallback_used is False
    assert len(slow.calls) == 1 and len(fast.calls) == 1  # both started at once


async def test_race_falls_back_when_both_fail_and_never_runs_private() -> None:
    a = cloud("a", error=errors.ProviderUnavailableError("down"))
    b = cloud("b", error=errors.ProviderUnavailableError("down"))
    loc = local()
    _, route = await run(make_router(a, b, loc, order=("a", "b")), AUTO)  # warm-up path
    assert route.kind is ProviderKind.LOCAL
    a2 = cloud("a", error=errors.ProviderUnavailableError("down"))
    b2 = cloud("b", error=errors.ProviderUnavailableError("down"))
    loc2 = local()
    router = make_router(a2, b2, loc2, order=("a", "b"))

    events = [e async for e in router.stream(_request, AUTO, private=False, race=2)]
    route = next(e for e in events if isinstance(e, Completed)).route
    assert route.provider == "fake-local" and route.fallback_used is True
    assert len(a2.calls) == len(b2.calls) == 1
    # Private: no race, no cloud.
    a3, b3, loc3 = cloud("a"), cloud("b"), local()
    router = make_router(a3, b3, loc3, order=("a", "b"))
    _ = [e async for e in router.stream(_request, AUTO, private=True, race=2)]
    assert a3.calls == [] and b3.calls == []


async def test_race_with_one_failing_first() -> None:
    bad = cloud("bad", error=errors.ProviderQuotaExhaustedError("quota"))
    good = cloud("good", block=None)
    router = make_router(bad, good, order=("bad", "good"))
    events = [e async for e in router.stream(_request, AUTO, private=False, race=2)]
    route = next(e for e in events if isinstance(e, Completed)).route
    assert route.provider == "good"


def ps(*models: dict) -> httpx.Response:
    return httpx.Response(200, json={"models": list(models)})


@pytest.mark.parametrize(
    ("size", "vram", "expected"),
    [(4_000, 0, "cpu"), (4_000, 4_000, "gpu"), (4_000, 1_500, "partial")],
)
async def test_ollama_reports_cpu_or_gpu(size: int, vram: int, expected: str) -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: ps({"name": "qwen3.5:4b", "size": size, "size_vram": vram})
        )
    )
    p = OllamaProvider(
        http=http,
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
        context_char_budget=1000,
        connect_timeout=1,
        read_timeout=1,
    )
    assert await p.processor() == expected


def test_keep_alive_defaults_to_always_loaded() -> None:
    from ultron_core.config import Settings

    base = {
        "_env_file": None,
        "jwt_secret": "j" * 40,
        "local_database_url": "postgresql://u:p@db/x",
    }
    assert Settings(**base).ollama_keep_alive == "-1"  # type: ignore[arg-type]
    assert Settings(**base, ollama_keep_alive="").ollama_keep_alive == "-1"  # type: ignore[arg-type]
    assert Settings(**base, ollama_keep_alive="30m").ollama_keep_alive == "30m"  # type: ignore[arg-type]
    assert Settings(**base).memory_context_limit == 5  # type: ignore[arg-type]


@pytest.mark.integration
async def test_chat_ranks_by_measured_speed_and_races_in_instant(migrated_database) -> None:  # type: ignore[no-untyped-def]
    first = cloud("freellmapi")
    second = cloud("custom")
    settings = migrated_database.model_copy(update={"ai_cloud_providers": "freellmapi,custom"})
    async with running_app(settings, [first, second, local()]) as (app, client):
        h = await owner_headers(app, client)
        cid = await new_conversation(client, h)
        speed.forget()
        # Before any measurements: configured order.
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": "hi"}, headers=h
        )
        assert r.json()["assistant_message"]["provider"] == "freellmapi"
        await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": "hi"}, headers=h
        )
        # Pretend: freellmapi has been slow, custom fast.
        async with app.state.sessionmaker() as s:
            await s.execute(
                update(Message).where(Message.role == "assistant").values(first_token_ms=900)
            )
            await s.commit()
        second_msg = await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": "hello"}, headers=h
        )
        speed.forget()
        async with app.state.sessionmaker() as s:
            await s.execute(
                update(Message).where(Message.provider == "custom").values(first_token_ms=100)
            )
            await s.commit()
        # custom only has data after it was used; make sure it has some.
        assert second_msg.status_code == 200
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages", json={"content": "again"}, headers=h
        )
        assert r.json()["assistant_message"]["provider"] == "custom"
        # Deep mode keeps the configured order (quality first).
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "think", "response_mode": "deep"},
            headers=h,
        )
        assert r.json()["assistant_message"]["provider"] == "freellmapi"
        # Instant: both start at once.
        calls = (len(first.calls), len(second.calls))
        r = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "quick", "response_mode": "instant"},
            headers=h,
        )
        assert r.status_code == 200
        assert (len(first.calls), len(second.calls)) == (calls[0] + 1, calls[1] + 1)
    speed.forget()
