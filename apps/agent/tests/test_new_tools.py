import sys

import pytest

from ultron_agent.tools import apps, files, registry
from ultron_agent.tools.base import ToolError


def test_copy_file_and_folder(ctx, config) -> None:
    downloads = config.roots["downloads"]
    (downloads / "notes.txt").write_text("hello")
    out = files.copy(ctx, {"source": "downloads/notes.txt", "destination": "documents"})
    assert out["verified"] and (config.roots["documents"] / "notes.txt").read_text() == "hello"
    assert (downloads / "notes.txt").exists()  # copy keeps the original
    with pytest.raises(ToolError, match="already exists"):
        files.copy(ctx, {"source": "downloads/notes.txt", "destination": "documents/notes.txt"})
    (downloads / "notes.txt").write_text("v2")
    files.copy(
        ctx,
        {"source": "downloads/notes.txt", "destination": "documents/notes.txt", "overwrite": True},
    )
    assert (config.roots["documents"] / "notes.txt").read_text() == "v2"

    (downloads / "set" / "inner").mkdir(parents=True)
    (downloads / "set" / "inner" / "a.md").write_text("x")
    files.copy(ctx, {"source": "downloads/set", "destination": "project/set-copy"})
    assert (config.roots["project"] / "set-copy" / "inner" / "a.md").exists()
    with pytest.raises(ToolError, match="into itself"):
        files.copy(ctx, {"source": "downloads/set", "destination": "downloads/set/inner/deep"})
    with pytest.raises(ToolError):
        files.copy(ctx, {"source": "downloads/notes.txt", "destination": "../outside.txt"})


def test_rename(ctx, config) -> None:
    downloads = config.roots["downloads"]
    (downloads / "draft.txt").write_text("x")
    (downloads / "taken.txt").write_text("y")
    out = files.rename(ctx, {"path": "downloads/draft.txt", "new_name": "final.txt"})
    assert out["verified"] and (downloads / "final.txt").exists()
    for bad in ("../escape.txt", "a/b.txt", "..", "", "x:y"):
        with pytest.raises(ToolError, match="valid file name"):
            files.rename(ctx, {"path": "downloads/final.txt", "new_name": bad})
    with pytest.raises(ToolError, match="already there"):
        files.rename(ctx, {"path": "downloads/final.txt", "new_name": "taken.txt"})
    with pytest.raises(ToolError, match="root folder"):
        files.rename(ctx, {"path": "downloads", "new_name": "Other"})


def test_running_and_close_app(ctx) -> None:
    running = apps.running(ctx, {})
    assert running["verified"] and running["apps"]
    opened = apps.open_app(ctx, {"app": "sleeper"})
    assert opened["verified"]
    out = apps.close_app(ctx, {"app": "sleeper"})
    assert out["verified"] and out["closed"] == 1
    again = apps.close_app(ctx, {"app": "sleeper"})
    assert "wasn't running" in again["summary"]
    with pytest.raises(ToolError, match="allowed apps"):
        apps.close_app(ctx, {"app": "explorer"})


def test_open_url_only_http(ctx, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, new=0: opened.append(url) or True)
    assert apps.open_url(ctx, {"url": "https://example.com/a"})["verified"]
    assert opened == ["https://example.com/a"]
    for bad in ("file:///C:/Windows", "javascript:alert(1)", "ms-settings:"):
        with pytest.raises(ToolError, match="http and https"):
            apps.open_url(ctx, {"url": bad})


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_notify_and_registry_off_windows(ctx, config) -> None:
    with pytest.raises(ToolError, match="only supported on Windows"):
        apps.notify(ctx, {"title": "t", "text": "x"})
    names = registry.enabled(config)
    assert "pc.notify" not in names
    for name in (
        "pc.files.copy",
        "pc.files.rename",
        "pc.apps.running",
        "pc.apps.close",
        "pc.web.open",
    ):
        assert name in names
