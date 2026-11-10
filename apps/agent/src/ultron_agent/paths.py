"""Safe paths: ``root/relative/path`` -> a real path inside that root.

Rejects absolute paths, ``..``, drive letters, UNC paths, device names and
anything that resolves (through links) outside the root.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from ultron_agent.tools.base import ToolError

_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.IGNORECASE)
_BAD_CHARS = set('<>:"|?*') | {chr(i) for i in range(32)}


def split(spec: str) -> tuple[str, list[str]]:
    text = spec.strip().replace("\\", "/")
    if not text or text.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", text):
        raise ToolError(
            f"Use a path inside an allowed folder, like 'documents/report.md' (got '{spec}')"
        )
    parts = [p for p in PurePosixPath(text).parts if p not in ("", ".")]
    if not parts:
        raise ToolError("Empty path")
    for part in parts:
        if part == "..":
            raise ToolError("'..' is not allowed in paths")
        if any(c in _BAD_CHARS for c in part) or _WINDOWS_RESERVED.match(part):
            raise ToolError(f"'{part}' is not a valid file name")
    return parts[0].lower(), parts[1:]


def resolve(roots: dict[str, Path], spec: str, *, must_exist: bool = False) -> Path:
    root_name, rest = split(spec)
    root = roots.get(root_name)
    if root is None:
        allowed = ", ".join(sorted(roots)) or "none configured"
        raise ToolError(f"'{root_name}' is not an allowed folder (allowed: {allowed})")
    base = root.resolve()
    target = base.joinpath(*rest)
    real = target.resolve()
    if real != base and not real.is_relative_to(base):
        raise ToolError("That path leads outside the allowed folder")
    if must_exist and not real.exists():
        raise ToolError(f"Not found: {spec}")
    return real


def display(roots: dict[str, Path], path: Path) -> str:
    """The ``root/relative`` form of a real path (for results)."""
    real = path.resolve()
    for name, root in roots.items():
        base = root.resolve()
        if real == base or real.is_relative_to(base):
            rel = real.relative_to(base).as_posix()
            return name if rel == "." else f"{name}/{rel}"
    return path.name
