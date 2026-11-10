"""The agent loop against a fake ULTRON Core."""

import json
import sys

import httpx
import pytest

from ultron_agent import credentials
from ultron_agent.client import CoreClient
from ultron_agent.runner import capabilities, run


class FakeCore:
    def __init__(self, steps: list[dict]) -> None:
        self.steps = steps
        self.hello: dict | None = None
        self.results: list[tuple[str, dict]] = []
        self.refreshes = 0
        self.access = "access-1"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/refresh":
            self.refreshes += 1
            return httpx.Response(
                200, json={"access_token": self.access, "refresh_token": "r2", "device_id": "dev-1"}
            )
        if request.headers.get("authorization") != f"Bearer {self.access}":
            return httpx.Response(401, json={"detail": "Not authenticated"})
        if path == "/api/v1/agents/hello":
            self.hello = json.loads(request.content)
            return httpx.Response(200, json={})
        if path == "/api/v1/agents/steps/next":
            return (
                httpx.Response(200, json=self.steps.pop(0)) if self.steps else httpx.Response(204)
            )
        if path.endswith("/progress"):
            return httpx.Response(200, json={"cancel": False})
        if path.endswith("/result"):
            self.results.append((path.split("/")[-2], json.loads(request.content)))
            return httpx.Response(200, json={"cancel": False})
        return httpx.Response(404)


def step(sid: str, tool: str, args: dict) -> dict:
    return {
        "id": sid,
        "task_id": "t",
        "task_title": "x",
        "tool": tool,
        "args": args,
        "title": tool,
        "attempt": 1,
    }


def test_runs_steps_and_reports(config) -> None:
    credentials.save(config.data_dir, credentials.Credentials("dev-1", "r1"))
    core = FakeCore(
        [
            step("s1", "pc.files.write", {"path": "documents/n.md", "content": "hi"}),
            step("s2", "pc.files.read", {"path": "documents/../../etc/passwd"}),
            step("s3", "pc.apps.focus", {"app": "nope"}),
            step("s4", "pc.unknown", {}),
        ]
    )
    client = CoreClient(
        "http://core.test", config.data_dir, transport=httpx.MockTransport(core.handler)
    )
    run(config, client, once=True)
    assert core.refreshes == 1  # signed in from stored credentials
    assert core.hello["capabilities"] == capabilities(config)
    assert "pc.files.organize" in core.hello["tools"]
    assert "/" not in json.dumps(core.hello["capabilities"])  # names only, no paths
    results = dict(core.results)
    assert results["s1"]["ok"] and results["s1"]["result"]["verified"]
    assert not results["s2"]["ok"] and "'..'" in results["s2"]["error"]
    assert not results["s3"]["ok"]
    assert not results["s4"]["ok"] and "doesn't offer" in results["s4"]["error"]
    assert (config.roots["documents"] / "n.md").read_text() == "hi"
    # Refresh token rotated and stored.
    assert credentials.load(config.data_dir).refresh_token == "r2"  # noqa: S105


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses DPAPI instead")
def test_credentials_file_is_private(config) -> None:
    import os
    import stat

    credentials.save(config.data_dir, credentials.Credentials("d", "secret"))
    mode = stat.S_IMODE(os.stat(credentials.path(config.data_dir)).st_mode)
    assert mode == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_credentials_are_encrypted_with_dpapi(config) -> None:
    credentials.save(config.data_dir, credentials.Credentials("dev-9", "very-secret-token"))
    raw = credentials.path(config.data_dir).read_bytes()
    assert b"very-secret-token" not in raw  # encrypted at rest
    assert credentials.load(config.data_dir).refresh_token == "very-secret-token"  # noqa: S105
