"""PC status."""

from __future__ import annotations

import platform
import time
from typing import Any

import psutil

from ultron_agent.tools.base import ToolContext


def metrics(config: Any) -> dict[str, Any]:
    """Live numbers for the Command Center (sent every half minute)."""
    memory = psutil.virtual_memory()
    out: dict[str, Any] = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": memory.percent,
        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
    }
    roots = [r for r in config.roots.values() if r.exists()]
    if roots:
        out["disk_free_gb"] = round(psutil.disk_usage(str(roots[0])).free / 1e9, 1)
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if battery:
        out["battery_percent"] = battery.percent
        out["charging"] = bool(battery.power_plugged)
    stats = psutil.net_if_stats()
    up = [n for n, s in stats.items() if s.isup and not n.lower().startswith(("lo", "loopback"))]
    out["network"] = "connected" if up else "offline"
    return out


def status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disks = []
    seen: set[str] = set()
    for root in ctx.config.roots.values():
        anchor = root.anchor or "/"
        if anchor in seen or not root.exists():
            continue
        seen.add(anchor)
        usage = psutil.disk_usage(str(root))
        disks.append(
            {"drive": anchor, "free_gb": round(usage.free / 1e9, 1), "used_percent": usage.percent}
        )
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    cpu = psutil.cpu_percent(interval=0.5)
    uptime_h = round((time.time() - psutil.boot_time()) / 3600, 1)
    result: dict[str, Any] = {
        "os": f"{platform.system()} {platform.release()}",
        "cpu_percent": cpu,
        "memory_used_percent": memory.percent,
        "memory_free_gb": round(memory.available / 1e9, 1),
        "disks": disks,
        "uptime_hours": uptime_h,
        "battery": (
            {"percent": battery.percent, "plugged_in": battery.power_plugged} if battery else None
        ),
    }
    parts = [f"CPU {cpu:.0f}%", f"memory {memory.percent:.0f}% used"]
    parts += [f"{d['drive']} {d['free_gb']} GB free" for d in disks]
    if battery:
        parts.append(f"battery {battery.percent:.0f}%")
    result["summary"] = ", ".join(parts)
    result["verified"] = True
    return result
