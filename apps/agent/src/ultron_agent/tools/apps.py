"""Opening and switching apps. Only apps listed in the config."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

from ultron_agent.tools.base import ToolContext, ToolError

IS_WINDOWS = sys.platform == "win32"


def list_apps(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    names = sorted(a.name for a in ctx.config.apps.values())
    return {"apps": names, "summary": f"{len(names)} apps: {', '.join(names)}"}


def open_app(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    entry = ctx.config.app(args["app"])
    if entry is None:
        allowed = ", ".join(sorted(a.name for a in ctx.config.apps.values())) or "none"
        raise ToolError(f"'{args['app']}' isn't in your allowed apps ({allowed})")
    command = [os.path.expandvars(c) for c in entry.command]
    try:
        if IS_WINDOWS and len(command) == 1 and command[0].lower().endswith((".lnk", ".url")):
            os.startfile(command[0])  # type: ignore[attr-defined]  # noqa: S606
            return {"app": entry.name, "summary": f"Opened {entry.name}", "verified": True}
        flags = 0
        if IS_WINDOWS:
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        process = subprocess.Popen(  # noqa: S603 - argv from the user's own config, no shell
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
            start_new_session=not IS_WINDOWS,
        )
    except FileNotFoundError:
        raise ToolError(f"Couldn't find the program for {entry.name}: {command[0]}") from None
    except OSError as exc:
        raise ToolError(f"Couldn't start {entry.name}: {exc}", retryable=True) from None
    time.sleep(1.0)
    code = process.poll()
    # Launchers (code.cmd, explorer) often exit 0 after handing over.
    started = code is None or code == 0
    return {
        "app": entry.name,
        "pid": process.pid,
        "summary": f"Opened {entry.name}" if started else f"{entry.name} exited with code {code}",
        "verified": started,
    }


def focus_app(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    entry = ctx.config.app(args["app"])
    if entry is None:
        raise ToolError(f"'{args['app']}' isn't in your allowed apps")
    if not IS_WINDOWS:
        raise ToolError("Switching windows is only supported on Windows")
    title = (entry.window_title or entry.name).lower()
    found = _find_window(title)
    if found is None:
        raise ToolError(f"No open window for {entry.name}. Ask me to open it instead.")
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.ShowWindow(found, 9)  # SW_RESTORE
    ok = bool(user32.SetForegroundWindow(found))
    return {"app": entry.name, "summary": f"Switched to {entry.name}", "verified": ok}


def _find_window(title_part: str) -> int | None:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_part in buffer.value.lower():
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return found[0] if found else None
