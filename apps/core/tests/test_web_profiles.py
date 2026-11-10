"""web.read safety, task-type model routing and the new PC tool specs."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from ultron_core import web
from ultron_core.ai import profiles
from ultron_core.ai.router import RoutingPreferences
from ultron_core.tasks import tools
from ultron_core.tasks.permissions import Policy

PUBLIC = "93.184.215.14"
HOSTS = {
    "example.com": [PUBLIC],
    "intranet.test": ["192.168.1.1"],
    "mixed.test": [PUBLIC, "10.0.0.5"],
    "loop.test": ["127.0.0.1"],
    "mapped.test": ["::ffff:127.0.0.1"],
    "meta.test": ["169.254.169.254"],
    "127.0.0.1": ["127.0.0.1"],
    "::1": ["::1"],
}


@pytest.fixture
async def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def getaddrinfo(host, port, **_kw):  # type: ignore[no-untyped-def]
        if host not in HOSTS:
            raise socket.gaierror("unknown")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in HOSTS[host]]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)


def client_for(routes: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_refuses_private_and_odd_addresses(fake_dns) -> None:  # type: ignore[no-untyped-def]
    for url in (
        "http://intranet.test/",
        "http://mixed.test/",
        "http://loop.test:8000/api",
        "http://mapped.test/",
        "http://meta.test/latest/meta-data",
        "http://127.0.0.1/",
        "http://[::1]/",
    ):
        with pytest.raises(web.WebError, match="private or local"):
            await web.check_url(url)
    for url in ("file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)"):
        with pytest.raises(web.WebError, match="Only http"):
            await web.check_url(url)
    with pytest.raises(web.WebError, match="user name"):
        await web.check_url("http://user:pw@example.com/")
    with pytest.raises(web.WebError, match="Couldn't find") as info:
        await web.check_url("http://nowhere.test/")
    assert info.value.retryable


async def test_reads_page_text_and_rechecks_redirects(fake_dns) -> None:  # type: ignore[no-untyped-def]
    html = (
        "<html><head><title> My  Page </title><script>evil()</script></head>"
        "<body><nav>menu</nav><h1>Hello</h1><p>First &amp; second</p>"
        "<style>.x{}</style><p>Last</p></body></html>"
    )
    routes = {
        "http://example.com/old": httpx.Response(301, headers={"location": "/new"}),
        "http://example.com/new": httpx.Response(
            200, text=html, headers={"content-type": "text/html; charset=utf-8"}
        ),
        "http://example.com/sneaky": httpx.Response(
            302, headers={"location": "http://intranet.test/admin"}
        ),
        "http://example.com/file.zip": httpx.Response(
            200, content=b"PK", headers={"content-type": "application/zip"}
        ),
        "http://example.com/down": httpx.Response(503),
    }
    async with client_for(routes) as client:
        page = await web.read("http://example.com/old", client)
        assert page["url"] == "http://example.com/new"
        assert page["title"] == "My Page"
        assert page["text"] == "Hello\nFirst & second\nLast"
        with pytest.raises(web.WebError, match="private or local"):
            await web.read("http://example.com/sneaky", client)
        with pytest.raises(web.WebError, match="isn't a web page"):
            await web.read("http://example.com/file.zip", client)
        with pytest.raises(web.WebError, match="HTTP 503") as info:
            await web.read("http://example.com/down", client)
        assert info.value.retryable


def test_classify_and_parse_profiles() -> None:
    assert profiles.classify("fix this python traceback") == "coding"
    assert profiles.classify("summarize the meeting notes") == "summarize"
    assert profiles.classify("why is the sky blue? explain step by step") == "reasoning"
    assert profiles.classify("draft an email to my teacher") == "writing"
    assert profiles.classify("good morning") == "chat"
    spec = "coding=Groq, openrouter; reasoning=anthropic; bogus=x; nonsense"
    assert profiles.parse(spec) == {"coding": ["groq", "openrouter"], "reasoning": ["anthropic"]}
    base = RoutingPreferences(mode="auto", cloud_order=("gemini", "openrouter"))
    coding = profiles.preferences_for("coding", base, spec)
    assert coding.cloud_order == ("groq", "openrouter", "gemini") and coding.mode == "auto"
    assert profiles.preferences_for("chat", base, spec) is base
    private = RoutingPreferences(mode="local_only")
    assert profiles.preferences_for("coding", private, spec).mode == "local_only"


def test_new_pc_tool_specs() -> None:
    _, args = tools.validate_step("pc.web.open", {"url": "https://example.com"})
    with pytest.raises(tools.ToolError):
        tools.validate_step("pc.web.open", {"url": "file:///C:/secret"})
    with pytest.raises(tools.ToolError):
        tools.validate_step("pc.files.rename", {"path": "downloads/a", "new_name": "../b"})
    spec, args = tools.validate_step(
        "pc.files.copy", {"source": "downloads/a", "destination": "documents", "overwrite": True}
    )
    assert spec.effective_risk(args) == "B"  # overwriting asks
    close = tools.get("pc.apps.close")
    assert close is not None and close.risk == "B" and close.target == "windows"
    policy = Policy(levels={"core": 5, "pc": 5, "phone": 5})
    assert policy.decide(scope="pc.apps.close", risk="A", approved=False) == "ask"
    assert tools.get("web.read").target == "core"  # type: ignore[union-attr]
