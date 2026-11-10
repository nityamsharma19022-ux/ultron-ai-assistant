"""Tool name (as Core knows it) -> implementation."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from ultron_agent.tools import apps, files, system, workflows
from ultron_agent.tools.base import ToolContext

Tool = Callable[[ToolContext, dict[str, Any]], dict[str, Any]]

TOOLS: dict[str, Tool] = {
    "pc.status": system.status,
    "pc.apps.list": apps.list_apps,
    "pc.apps.open": apps.open_app,
    "pc.apps.focus": apps.focus_app,
    "pc.files.list": files.list_dir,
    "pc.files.search": files.search,
    "pc.files.read": files.read,
    "pc.files.create_folder": files.create_folder,
    "pc.files.write": files.write,
    "pc.files.move": files.move,
    "pc.files.organize": files.organize,
    "pc.files.delete": files.delete,
    "pc.workflows.run": workflows.run,
    "pc.files.copy": files.copy,
    "pc.files.rename": files.rename,
    "pc.apps.running": apps.running,
    "pc.apps.close": apps.close_app,
    "pc.web.open": apps.open_url,
    "pc.notify": apps.notify,
}


def enabled(config: Any) -> list[str]:
    """Tools this agent offers, given its config."""
    names = []
    for name in TOOLS:
        if name in config.disabled_tools:
            continue
        if name.startswith("pc.files.") and not config.roots:
            continue
        if (
            name in ("pc.apps.open", "pc.apps.focus", "pc.apps.close", "pc.apps.list")
            and not config.apps
        ):
            continue
        if name == "pc.notify" and sys.platform != "win32":
            continue
        if name == "pc.workflows.run" and not config.workflows:
            continue
        names.append(name)
    return names
