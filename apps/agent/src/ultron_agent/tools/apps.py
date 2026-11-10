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


def running(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import psutil

    seen: dict[str, float] = {}
    for proc in psutil.process_iter(["name", "memory_info"]):
        name = proc.info.get("name") or ""
        mem = proc.info.get("memory_info")
        if not name or mem is None:
            continue
        seen[name] = seen.get(name, 0) + mem.rss / 1e6
    top = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)[:30]
    apps = [{"name": n, "memory_mb": round(m)} for n, m in top]
    return {
        "apps": apps,
        "summary": f"{len(seen)} programs running; biggest: "
        + ", ".join(a["name"] for a in apps[:5]),
        "verified": True,
    }


def _matches(proc: Any, command: list[str]) -> bool:
    """Same program; when the app is started with arguments, the same arguments too
    (so "python script.py" never matches every Python process)."""
    name = (proc.info.get("name") or "").lower()
    exe = os.path.basename(command[0]).lower()
    if name != exe and os.path.splitext(name)[0] != os.path.splitext(exe)[0]:
        return False
    if len(command) == 1:
        return True
    cmdline = proc.info.get("cmdline") or []
    return cmdline[1:] == command[1:]


def close_app(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Asks an allowed app's processes to close (never this agent or its parents)."""
    import psutil

    entry = ctx.config.app(args["app"])
    if entry is None:
        raise ToolError(f"'{args['app']}' isn't in your allowed apps")
    command = [os.path.expandvars(c) for c in entry.command]
    me = psutil.Process()
    protected = {me.pid, *(p.pid for p in me.parents())}
    procs = [
        p
        for p in psutil.process_iter(["name", "cmdline"])
        if p.pid not in protected and _matches(p, command)
    ]
    if not procs:
        return {"app": entry.name, "summary": f"{entry.name} wasn't running", "verified": True}
    for p in procs:
        try:
            p.terminate()  # a polite close request, like closing the window
        except psutil.Error:
            pass
    gone, alive = psutil.wait_procs(procs, timeout=8)
    return {
        "app": entry.name,
        "closed": len(gone),
        "summary": f"Closed {entry.name}"
        if not alive
        else f"{entry.name} didn't close ({len(alive)} left)",
        "verified": not alive,
    }


def open_url(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import webbrowser

    url = str(args["url"])
    if not url.startswith(("http://", "https://")):
        raise ToolError("Only http and https addresses can be opened")
    ok = webbrowser.open(url, new=2)
    return {"url": url, "summary": f"Opened {url[:80]}", "verified": bool(ok)}


def notify(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """A Windows toast notification (title/text passed as data, not code)."""
    title = str(args.get("title") or "ULTRON")[:100]
    text = str(args.get("text") or "")[:500]
    if not IS_WINDOWS:
        raise ToolError("PC notifications are only supported on Windows")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null;"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n = $t.GetElementsByTagName('text');"
        "$n.Item(0).AppendChild($t.CreateTextNode($env:ULTRON_TITLE)) | Out-Null;"
        "$n.Item(1).AppendChild($t.CreateTextNode($env:ULTRON_TEXT)) | Out-Null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ULTRON')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    env = {**os.environ, "ULTRON_TITLE": title, "ULTRON_TEXT": text}
    result = subprocess.run(  # noqa: S603 - fixed script; user text only via environment
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    ok = result.returncode == 0
    return {"summary": "Notification shown" if ok else "Notification failed", "verified": ok}
