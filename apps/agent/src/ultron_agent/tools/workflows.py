"""Named workflows from the config: commands run in order, no shell."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from ultron_agent import paths
from ultron_agent.tools import apps
from ultron_agent.tools.base import Cancelled, ToolContext, ToolError

OUTPUT_TAIL = 4000


def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    wf = ctx.config.workflow(args["name"])
    if wf is None:
        names = ", ".join(sorted(w.name for w in ctx.config.workflows.values())) or "none"
        raise ToolError(f"No workflow named '{args['name']}' (yours: {names})")
    cwd = paths.resolve(ctx.config.roots, wf.cwd, must_exist=True) if wf.cwd else None
    opened = [apps.open_app(ctx, {"app": name})["app"] for name in wf.open_apps]
    outputs: list[dict[str, Any]] = []
    deadline = time.monotonic() + wf.timeout_seconds
    for i, command in enumerate(wf.commands, 1):
        ctx.check(f"Step {i}/{len(wf.commands)}: {' '.join(command)[:120]}")
        argv = [os.path.expandvars(c) for c in command]
        try:
            proc = subprocess.Popen(  # noqa: S603 - argv from the user's own config, no shell
                argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            raise ToolError(f"Program not found: {argv[0]}") from None
        output = ""
        try:
            while True:
                try:
                    out, _ = proc.communicate(timeout=1)
                    output += out or ""
                    break
                except subprocess.TimeoutExpired:
                    # A cancel from the user wins over the time limit.
                    ctx.check(f"Step {i}/{len(wf.commands)} running…")
                    if time.monotonic() > deadline:
                        proc.kill()
                        proc.communicate()
                        raise ToolError(
                            f"The workflow took longer than {wf.timeout_seconds}s"
                        ) from None
        except Cancelled:
            proc.kill()
            raise
        outputs.append(
            {
                "command": " ".join(command),
                "exit_code": proc.returncode,
                "output": output[-OUTPUT_TAIL:],
            }
        )
        if proc.returncode != 0:
            return {
                "workflow": wf.name,
                "commands": outputs,
                "summary": f"Step {i} failed (exit code {proc.returncode})",
                "text": output[-OUTPUT_TAIL:],
                "verified": False,
            }
    note = f"Ran {len(wf.commands)} commands" if wf.commands else "Done"
    if opened:
        note += f"; opened {', '.join(opened)}"
    return {
        "workflow": wf.name,
        "commands": outputs,
        "summary": note,
        "text": "\n".join(o["output"] for o in outputs)[-OUTPUT_TAIL:],
        "verified": True,
    }
