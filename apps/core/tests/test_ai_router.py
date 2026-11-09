"""Cloud-first, local-fallback routing (unit tests, fake providers only)."""

from __future__ import annotations

import pytest

from tests.fakes import cloud, local
from ultron_core.ai.cooldown import CooldownStore
from ultron_core.ai.errors import (
    ProviderOfflineError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRefusalError,
    ProviderUnavailableError,
)
from ultron_core.ai.router import (
    AIRouter,
    Completed,
    MidStreamError,
    ProviderSelected,
    RoutingError,
    RoutingPreferences,
)
from ultron_core.ai.types import ChatMessage, ChatRequest, ProviderKind, TextDelta
from ultron_core.config import Settings

AUTO = RoutingPreferences()


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        local_database_url="postgresql://u:p@localhost/x",
        jwt_secret="r" * 40,
    )


def make_router(*providers, order=()):  # type: ignore[no-untyped-def]
    return AIRouter(list(providers), CooldownStore(None, _settings()), default_cloud_order=order)


def _request(_provider) -> ChatRequest:  # type: ignore[no-untyped-def]
    return ChatRequest(messages=(ChatMessage("user", "hi"),), system="sys")


async def run(router: AIRouter, prefs: RoutingPreferences = AUTO, private: bool = False):  # type: ignore[no-untyped-def]
    text, selected, completed = [], None, None
    async for event in router.stream(_request, prefs, private=private):
        if isinstance(event, ProviderSelected):
            selected = event.route
        elif isinstance(event, TextDelta):
            text.append(event.text)
        elif isinstance(event, Completed):
            completed = event.route
    assert selected is not None and completed is not None
    return "".join(text), completed


# --- Cloud first ----------------------------------------------------------


async def test_cloud_provider_success() -> None:
    c, loc = cloud(), local()
    text, route = await run(make_router(c, loc))
    assert text == "Hello from ULTRON"
    assert (route.provider, route.kind, route.fallback_used) == (
        "fake-cloud",
        ProviderKind.CLOUD,
        False,
    )
    assert loc.calls == []  # local not used when cloud works


async def test_local_provider_success() -> None:
    text, route = await run(make_router(local()), RoutingPreferences(mode="local_only"))
    assert text == "Local reply"
    assert route.kind is ProviderKind.LOCAL


async def test_cloud_failure_falls_back_to_local() -> None:
    c = cloud(error=ProviderUnavailableError("down"))
    loc = local()
    router = make_router(c, loc)
    text, route = await run(router)
    assert text == "Local reply"
    assert route.kind is ProviderKind.LOCAL
    assert route.fallback_used is True
    assert [a.outcome for a in route.attempts] == ["unavailable", "ok"]
    # The failed provider cools down, so the next reply skips it entirely.
    await run(router)
    assert len(c.calls) == 1


async def test_missing_api_keys_skip_cloud_without_calling_it() -> None:
    c = cloud(configured=False)
    loc = local()
    _, route = await run(make_router(c, loc))
    assert route.kind is ProviderKind.LOCAL
    assert c.calls == []
    assert route.attempts[0].outcome == "not_configured"
    assert route.fallback_used is False  # nothing failed; cloud just isn't set up


async def test_missing_api_keys_and_no_local_gives_clear_error() -> None:
    router = make_router(cloud(configured=False), local(configured=False))
    with pytest.raises(RoutingError) as err:
        await run(router)
    assert err.value.code == "no_ai_available"
    assert {a.outcome for a in err.value.attempts} == {"not_configured"}


async def test_quota_exhaustion_moves_to_next_provider_and_cools_down() -> None:
    first = cloud("first", error=ProviderQuotaExhaustedError("quota"))
    second = cloud("second")
    router = make_router(first, second, local(), order=("first", "second"))
    _, route = await run(router)
    assert route.provider == "second"
    assert route.fallback_used is True
    cooldown = await router.cooldowns.get("first")
    assert cooldown is not None and cooldown.code == "quota_exhausted"
    assert cooldown.remaining > 3000  # long cooldown for quota
    await run(router)
    assert len(first.calls) == 1  # skipped while cooling down


async def test_quota_exhausted_everywhere_uses_local() -> None:
    a = cloud("a", error=ProviderQuotaExhaustedError("quota"))
    b = cloud("b", error=ProviderQuotaExhaustedError("quota"))
    _, route = await run(make_router(a, b, local()))
    assert route.kind is ProviderKind.LOCAL
    assert [x.outcome for x in route.attempts] == ["quota_exhausted", "quota_exhausted", "ok"]


async def test_rate_limit_retry_after_sets_cooldown() -> None:
    limited = cloud(error=ProviderRateLimitedError("slow down", retry_after=42))
    router = make_router(limited, local())
    await run(router)
    cooldown = await router.cooldowns.get("fake-cloud")
    assert cooldown is not None and 35 < cooldown.remaining <= 42


# --- Privacy ----------------------------------------------------------------


async def test_private_conversation_never_reaches_cloud() -> None:
    c, loc = cloud(), local()
    _, route = await run(make_router(c, loc), private=True)
    assert route.kind is ProviderKind.LOCAL
    assert c.calls == []


async def test_private_conversation_without_local_ai_fails_instead_of_using_cloud() -> None:
    c = cloud()
    router = make_router(c, local(available=False))
    with pytest.raises(RoutingError) as err:
        await run(router, private=True)
    assert err.value.code == "private_requires_local_ai"
    assert "not installed" in err.value.message
    assert c.calls == []


async def test_private_ignores_cloud_only_preference() -> None:
    c, loc = cloud(), local()
    _, route = await run(make_router(c, loc), RoutingPreferences(mode="cloud_only"), private=True)
    assert route.kind is ProviderKind.LOCAL
    assert c.calls == []


# --- Offline ------------------------------------------------------------------


async def test_offline_skips_remaining_cloud_providers_and_uses_local() -> None:
    a = cloud("a", error=ProviderOfflineError("no network"))
    b = cloud("b")
    _, route = await run(make_router(a, b, local(), order=("a", "b")))
    assert route.kind is ProviderKind.LOCAL
    assert b.calls == []  # didn't waste time on another cloud provider
    assert [x.outcome for x in route.attempts] == ["offline", "skipped_offline", "ok"]


async def test_offline_without_installed_local_model_does_not_claim_offline_ai() -> None:
    loc = local(available=False)
    router = make_router(cloud(error=ProviderOfflineError("no network")), loc)
    with pytest.raises(RoutingError) as err:
        await run(router)
    assert err.value.code == "offline_no_local_ai"
    assert "not installed" in err.value.message
    assert loc.calls == []  # never "used" a model that isn't there


async def test_uninstalled_local_model_is_skipped_when_cloud_fails() -> None:
    router = make_router(cloud(error=ProviderUnavailableError("down")), local(available=False))
    with pytest.raises(RoutingError) as err:
        await run(router)
    assert err.value.code == "no_ai_available"


# --- Preferences and other rules -----------------------------------------------


async def test_user_cloud_order_is_respected() -> None:
    a, b = cloud("a"), cloud("b")
    _, route = await run(
        make_router(a, b, order=("a", "b")), RoutingPreferences(cloud_order=("b",))
    )
    assert route.provider == "b"
    assert a.calls == []


async def test_cloud_only_mode_never_falls_back_to_local() -> None:
    loc = local()
    router = make_router(cloud(error=ProviderUnavailableError("down")), loc)
    with pytest.raises(RoutingError) as err:
        await run(router, RoutingPreferences(mode="cloud_only"))
    assert err.value.code == "cloud_ai_unavailable"
    assert loc.calls == []


async def test_local_only_mode_never_uses_cloud() -> None:
    c = cloud()
    router = make_router(c, local(available=False))
    with pytest.raises(RoutingError) as err:
        await run(router, RoutingPreferences(mode="local_only"))
    assert err.value.code == "local_ai_unavailable"
    assert c.calls == []


async def test_failure_after_partial_output_is_not_stitched_with_another_model() -> None:
    c = cloud(error=ProviderUnavailableError("dropped"), error_after=1)
    loc = local()
    router = make_router(c, loc)
    received = []
    with pytest.raises(MidStreamError) as err:
        async for event in router.stream(_request, AUTO, private=False):
            if isinstance(event, TextDelta):
                received.append(event.text)
    assert received == ["Hello"]
    assert err.value.route.provider == "fake-cloud"
    assert loc.calls == []


async def test_refusal_is_not_retried_on_another_provider() -> None:
    loc = local()
    router = make_router(cloud(error=ProviderRefusalError("declined")), loc)
    with pytest.raises(RoutingError) as err:
        await run(router)
    assert err.value.code == "refused"
    assert loc.calls == []
