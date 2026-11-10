"""The agent's main loop: say hello, wait for steps, run them, report."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ultron_agent.client import AuthError, CoreClient
from ultron_agent.config import AgentConfig
from ultron_agent.tools import registry
from ultron_agent.tools.base import Cancelled, ToolContext, ToolError

log = logging.getLogger("ultron.agent")
MAX_RESULT_CHARS = 200_000


def capabilities(config: AgentConfig) -> dict[str, list[str]]:
    """Names only (no paths), so the planner can use your real names."""
    return {
        "roots": sorted(config.roots),
        "apps": sorted(a.name for a in config.apps.values()),
        "workflows": sorted(w.name for w in config.workflows.values()),
    }


def execute(config: AgentConfig, client: CoreClient, work: dict[str, Any]) -> None:
    step_id = work["id"]
    tool = registry.TOOLS.get(work["tool"])
    if tool is None or work["tool"] not in registry.enabled(config):
        client.result(step_id, ok=False, error=f"This PC doesn't offer {work['tool']}")
        return

    last = [0.0]

    def progress(message: str) -> bool:
        now = time.monotonic()
        if now - last[0] < 2:
            return False
        last[0] = now
        return client.progress(step_id, message)

    ctx = ToolContext(config=config, progress=progress)
    log.info("step %s: %s", work["tool"], work["title"])
    try:
        result = tool(ctx, dict(work["args"]))
    except Cancelled:
        log.info("step cancelled by the user")
        client.result(step_id, ok=False, error="Cancelled")
        return
    except ToolError as exc:
        log.warning("step failed: %s", exc.message)
        client.result(step_id, ok=False, error=exc.message, retryable=exc.retryable)
        return
    except Exception as exc:
        log.exception("tool crashed")
        client.result(step_id, ok=False, error=f"Unexpected error: {type(exc).__name__}")
        return
    text = result.get("text")
    if isinstance(text, str) and len(text) > MAX_RESULT_CHARS:
        result["text"] = text[:MAX_RESULT_CHARS]
    client.result(step_id, ok=True, result=result)
    log.info("step done: %s", result.get("summary", "ok"))


def run(config: AgentConfig, client: CoreClient, *, once: bool = False) -> None:
    tools = registry.enabled(config)
    backoff = 1.0
    greeted = False
    while True:
        try:
            if not greeted:
                client.hello(tools, capabilities(config))
                greeted = True
                log.info("connected to %s; offering %d tools", config.server_url, len(tools))
            work = client.next_step(0 if once else config.poll_wait_seconds)
            backoff = 1.0
            if work is not None:
                execute(config, client, work)
            elif once:
                return
            # Re-announce now and then (keeps the agent shown as online).
            greeted = greeted and not (work is None and time.monotonic() % 60 < 1)
        except AuthError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            log.warning("connection problem (%s); retrying in %.0fs", type(exc).__name__, backoff)
            if once:
                raise
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            greeted = False
