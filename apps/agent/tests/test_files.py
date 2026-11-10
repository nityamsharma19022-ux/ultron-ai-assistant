import os
import time

import docx
import pytest

from ultron_agent.tools import files
from ultron_agent.tools.base import Cancelled, ToolContext, ToolError


def test_write_read_text_and_docx(ctx, config) -> None:
    out = files.write(ctx, {"path": "documents/Study/plan.md", "content": "# Plan\n- maths"})
    assert out["verified"] and out["path"] == "documents/Study/plan.md"
    assert files.read(ctx, {"path": "documents/Study/plan.md"})["text"] == "# Plan\n- maths"

    files.write(ctx, {"path": "documents/report.docx", "content": "# Title\nBody text\n- point"})
    doc = docx.Document(str(config.roots["documents"] / "report.docx"))
    assert [p.style.name for p in doc.paragraphs] == ["Heading 1", "Normal", "List Bullet"]
    assert "Body text" in files.read(ctx, {"path": "documents/report.docx"})["text"]


def test_write_refuses_overwrite_and_bad_types(ctx) -> None:
    files.write(ctx, {"path": "documents/a.txt", "content": "one"})
    with pytest.raises(ToolError, match="already exists"):
        files.write(ctx, {"path": "documents/a.txt", "content": "two"})
    files.write(ctx, {"path": "documents/a.txt", "content": "two", "overwrite": True})
    assert files.read(ctx, {"path": "documents/a.txt"})["text"] == "two"
    with pytest.raises(ToolError, match="Can only create"):
        files.write(ctx, {"path": "documents/run.bat", "content": "del *"})
    with pytest.raises(ToolError, match="No content"):
        files.write(ctx, {"path": "documents/b.txt"})


def test_read_rejects_binary_types(ctx, config) -> None:
    (config.roots["downloads"] / "setup.exe").write_bytes(b"MZ")
    with pytest.raises(ToolError, match="Can't read"):
        files.read(ctx, {"path": "downloads/setup.exe"})


def test_list_and_search(ctx, config) -> None:
    (config.roots["documents"] / "Physics notes.md").write_text("x")
    (config.roots["documents"] / "sub").mkdir()
    (config.roots["documents"] / "sub" / "physics-lab.pdf").write_bytes(b"%PDF")
    (config.roots["documents"] / ".hidden-physics").write_text("x")
    listed = files.list_dir(ctx, {"path": "documents"})
    assert [i["name"] for i in listed["items"]] == ["sub", "Physics notes.md"]
    found = files.search(ctx, {"query": "PHYSICS"})
    assert sorted(i["path"] for i in found["items"]) == [
        "documents/Physics notes.md",
        "documents/sub/physics-lab.pdf",
    ]


def test_organize_by_type_with_undo(ctx, config) -> None:
    dl = config.roots["downloads"]
    for name in ("a.pdf", "b.PNG", "c.zip", "d.weird", "e.crdownload", ".hidden.pdf"):
        (dl / name).write_text("x")
    (dl / "Documents").mkdir()
    (dl / "Documents" / "a.pdf").write_text("older")  # name clash

    preview = files.organize(ctx, {"path": "downloads", "dry_run": True})
    assert preview["moved"] == 0 and (dl / "a.pdf").exists()
    assert preview["summary"].startswith("Would move 4 files")

    out = files.organize(ctx, {"path": "downloads"})
    assert out["verified"] and out["moved"] == 4
    assert (dl / "Documents" / "a (1).pdf").exists()
    assert (dl / "Images" / "b.PNG").exists() and (dl / "Archives" / "c.zip").exists()
    assert (dl / "Other" / "d.weird").exists()
    assert (dl / "e.crdownload").exists() and (dl / ".hidden.pdf").exists()  # left alone

    restored = files.undo_organize(config, out["undo_file"])
    assert restored == 4 and (dl / "a.pdf").exists() and not (dl / "Images").exists()
    assert (dl / "Documents" / "a.pdf").read_text() == "older"


def test_organize_by_month(ctx, config) -> None:
    f = config.roots["downloads"] / "old.txt"
    f.write_text("x")
    stamp = time.mktime((2025, 3, 15, 12, 0, 0, 0, 0, -1))
    os.utime(f, (stamp, stamp))
    files.organize(ctx, {"path": "downloads", "scheme": "by_date"})
    assert (config.roots["downloads"] / "2025-03" / "old.txt").exists()


def test_organize_can_be_cancelled(config) -> None:
    for i in range(3):
        (config.roots["downloads"] / f"{i}.txt").write_text("x")
    cancelling = ToolContext(config=config, progress=lambda _m: True)
    with pytest.raises(Cancelled):
        files.organize(cancelling, {"path": "downloads"})


def test_move_and_folder(ctx, config) -> None:
    files.create_folder(ctx, {"path": "documents/Archive"})
    (config.roots["downloads"] / "x.pdf").write_text("x")
    out = files.move(ctx, {"source": "downloads/x.pdf", "destination": "documents/Archive"})
    assert out["verified"] and out["to"] == "documents/Archive/x.pdf"
    (config.roots["downloads"] / "x.pdf").write_text("y")
    with pytest.raises(ToolError, match="already exists"):
        files.move(ctx, {"source": "downloads/x.pdf", "destination": "documents/Archive/x.pdf"})
    with pytest.raises(ToolError, match="root folder"):
        files.move(ctx, {"source": "downloads", "destination": "documents/dl"})
    with pytest.raises(ToolError, match="into itself"):
        files.move(ctx, {"source": "documents/Archive", "destination": "documents/Archive/inner"})


def test_delete_goes_to_trash(ctx, config, monkeypatch) -> None:
    trashed = []
    monkeypatch.setattr("send2trash.send2trash", lambda p: (trashed.append(p), os.remove(p)))
    (config.roots["downloads"] / "junk.tmp.txt").write_text("x")
    out = files.delete(ctx, {"path": "downloads/junk.tmp.txt"})
    assert out["verified"] and len(trashed) == 1
    with pytest.raises(ToolError, match="root folder"):
        files.delete(ctx, {"path": "downloads"})
