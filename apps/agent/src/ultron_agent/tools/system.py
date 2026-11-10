"""PC status."""

from __future__ import annotations

import platform
import time
from typing import Any

import psutil

from ultron_agent.tools.base import ToolContext


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
