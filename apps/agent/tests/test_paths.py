import os
from pathlib import Path

import pytest

from ultron_agent import paths
from ultron_agent.tools.base import ToolError


@pytest.mark.parametrize(
    "spec",
    [
        "/etc/passwd",
        "C:\\Windows\\System32",
        "c:/windows",
        "\\\\server\\share\\x",
        "downloads/../../secret",
        "downloads/..",
        "nope/file.txt",
        "downloads/con",
        "downloads/a:b",
        "downloads/nul.txt",
        "",
    ],
)
def test_rejects_paths_outside_roots(config, spec: str) -> None:
    with pytest.raises(ToolError):
        paths.resolve(config.roots, spec)


def test_resolves_inside_roots(config) -> None:
    p = paths.resolve(config.roots, "Downloads\\Reports/2026.pdf")
    assert p == (config.roots["downloads"] / "Reports" / "2026.pdf").resolve()
    assert paths.display(config.roots, p) == "downloads/Reports/2026.pdf"
    assert paths.resolve(config.roots, "documents") == config.roots["documents"].resolve()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need admin rights on Windows")
def test_symlink_escape_is_blocked(config, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (config.roots["downloads"] / "link").symlink_to(outside)
    with pytest.raises(ToolError, match="outside"):
        paths.resolve(config.roots, "downloads/link/x.txt")
