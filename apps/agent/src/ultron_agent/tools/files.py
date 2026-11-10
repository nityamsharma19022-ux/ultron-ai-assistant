"""File tools. Everything stays inside the configured roots."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ultron_agent import paths
from ultron_agent.tools.base import ToolContext, ToolError

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".log",
    ".ini",
    ".cfg",
    ".toml",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".dart",
    ".java",
    ".kt",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".go",
    ".rs",
    ".sql",
    ".ps1",
    ".bat",
    ".sh",
}
WRITE_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".docx"}
SKIP_SUFFIXES = {".crdownload", ".part", ".partial", ".tmp", ".download"}

CATEGORIES: dict[str, set[str]] = {
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages"},
    "Spreadsheets": {".xls", ".xlsx", ".ods", ".csv", ".tsv"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".tif", ".tiff"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Installers": {".exe", ".msi", ".msix", ".appx", ".apk"},
    "Code": {
        ".py",
        ".js",
        ".ts",
        ".dart",
        ".java",
        ".kt",
        ".c",
        ".cpp",
        ".cs",
        ".go",
        ".rs",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".html",
        ".css",
        ".sql",
        ".ipynb",
    },
}


def _info(ctx: ToolContext, p: Path) -> dict[str, Any]:
    st = p.stat()
    return {
        "path": paths.display(ctx.config.roots, p),
        "name": p.name,
        "is_dir": p.is_dir(),
        "size": st.st_size if p.is_file() else None,
        "modified": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(timespec="seconds"),
    }


def list_dir(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    folder = paths.resolve(ctx.config.roots, args["path"], must_exist=True)
    if not folder.is_dir():
        raise ToolError(f"{args['path']} is not a folder")
    entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:500]
    items = [_info(ctx, p) for p in entries if not p.name.startswith(".")]
    return {"items": items, "summary": f"{len(items)} items in {args['path']}"}


def search(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = args["query"].lower()
    limit = int(args.get("limit", 20))
    if args.get("path"):
        bases = [paths.resolve(ctx.config.roots, args["path"], must_exist=True)]
    else:
        bases = [r for r in ctx.config.roots.values() if r.exists()]
    found: list[dict[str, Any]] = []
    scanned = 0
    for base in bases:
        for p in base.rglob("*"):
            scanned += 1
            if scanned % 2000 == 0:
                ctx.check(f"Searching… {scanned} items checked")
            if scanned > 200_000:
                break
            if any(part.startswith(".") for part in p.relative_to(base).parts):
                continue
            if query in p.name.lower():
                found.append(_info(ctx, p))
                if len(found) >= limit:
                    break
        if len(found) >= limit:
            break
    return {"items": found, "summary": f"Found {len(found)} matching '{args['query']}'"}


def read_text(path: Path, max_chars: int) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:200])
    elif suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        text = "\n".join(p.text for p in document.paragraphs)
    elif suffix in TEXT_EXTENSIONS or not suffix:
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        raise ToolError(f"Can't read {suffix} files (text, Markdown, PDF and DOCX are supported)")
    return text[:max_chars]


def read(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path = paths.resolve(ctx.config.roots, args["path"], must_exist=True)
    if not path.is_file():
        raise ToolError(f"{args['path']} is not a file")
    if path.stat().st_size > ctx.config.max_read_bytes:
        raise ToolError("The file is too large to read")
    text = read_text(path, int(args.get("max_chars", 20_000)))
    return {
        "text": text,
        "chars": len(text),
        "summary": f"Read {len(text)} characters from {args['path']}",
        "verified": True,
    }


def create_folder(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    folder = paths.resolve(ctx.config.roots, args["path"])
    existed = folder.exists()
    if existed and not folder.is_dir():
        raise ToolError(f"{args['path']} exists and is a file")
    folder.mkdir(parents=True, exist_ok=True)
    return {
        "path": paths.display(ctx.config.roots, folder),
        "summary": "Folder already existed" if existed else "Folder created",
        "verified": folder.is_dir(),
    }


def _write_docx(path: Path, content: str) -> None:
    import docx

    document = docx.Document()
    for line in content.splitlines():
        stripped = line.lstrip()
        level = len(stripped) - len(stripped.lstrip("#"))
        if 1 <= level <= 6 and stripped[level : level + 1] == " ":
            document.add_heading(stripped[level + 1 :].strip(), level=min(level, 4))
        elif stripped.startswith(("- ", "* ")):
            document.add_paragraph(stripped[2:], style="List Bullet")
        else:
            document.add_paragraph(line)
    document.save(str(path))


def write(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path = paths.resolve(ctx.config.roots, args["path"])
    content = args.get("content")
    if content is None:
        raise ToolError("No content to write")
    suffix = path.suffix.lower()
    if suffix not in WRITE_EXTENSIONS:
        raise ToolError(f"Can only create {', '.join(sorted(WRITE_EXTENSIONS))} files")
    if path.exists() and not args.get("overwrite"):
        raise ToolError(f"{args['path']} already exists (overwriting needs your approval)")
    if path.is_dir():
        raise ToolError(f"{args['path']} is a folder")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".ultron-tmp")
    if suffix == ".docx":
        _write_docx(tmp, content)
    else:
        tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    ok = path.is_file() and path.stat().st_size > 0
    return {
        "path": paths.display(ctx.config.roots, path),
        "bytes": path.stat().st_size,
        "summary": f"Saved {paths.display(ctx.config.roots, path)}",
        "verified": ok,
    }


def _free_name(dest: Path) -> Path:
    if not dest.exists():
        return dest
    for n in range(1, 1000):
        candidate = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not candidate.exists():
            return candidate
    raise ToolError(f"Too many files named like {dest.name}")


def move(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    source = paths.resolve(ctx.config.roots, args["source"], must_exist=True)
    dest = paths.resolve(ctx.config.roots, args["destination"])
    if dest.is_dir():
        dest = dest / source.name
    if source in (dest, *dest.parents):
        raise ToolError("Can't move a folder into itself")
    if dest.exists() and not args.get("overwrite"):
        raise ToolError(f"{args['destination']} already exists (overwriting needs your approval)")
    if any(r.resolve() == source for r in ctx.config.roots.values()):
        raise ToolError("Can't move an allowed root folder itself")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            raise ToolError("Won't overwrite a folder")
        dest.unlink()
    shutil.move(str(source), str(dest))
    return {
        "from": args["source"],
        "to": paths.display(ctx.config.roots, dest),
        "summary": f"Moved to {paths.display(ctx.config.roots, dest)}",
        "verified": dest.exists() and not source.exists(),
    }


def _category(p: Path, scheme: str) -> str:
    if scheme == "by_date":
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m")
    suffix = p.suffix.lower()
    for name, exts in CATEGORIES.items():
        if suffix in exts:
            return name
    return "Other"


def organize(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    folder = paths.resolve(ctx.config.roots, args["path"], must_exist=True)
    if not folder.is_dir():
        raise ToolError(f"{args['path']} is not a folder")
    scheme = args.get("scheme", "by_type")
    dry_run = bool(args.get("dry_run"))
    moves: list[dict[str, str]] = []
    files = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() not in SKIP_SUFFIXES
        and not p.name.startswith("~$")
    ]
    for i, p in enumerate(files):
        if i % 50 == 0:
            ctx.check(f"Organizing… {i}/{len(files)}")
        target = _free_name(folder / _category(p, scheme) / p.name)
        moves.append({"from": p.name, "to": target.relative_to(folder).as_posix()})
        if not dry_run:
            target.parent.mkdir(exist_ok=True)
            p.rename(target)
    journal = None
    if moves and not dry_run:
        undo_dir = ctx.config.data_dir / "undo"
        undo_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        journal = undo_dir / f"organize-{stamp}.json"
        journal.write_text(
            json.dumps({"folder": str(folder), "moves": moves}, indent=2), encoding="utf-8"
        )
    counts: dict[str, int] = {}
    for m in moves:
        counts[m["to"].split("/")[0]] = counts.get(m["to"].split("/")[0], 0) + 1
    summary = (
        f"{'Would move' if dry_run else 'Moved'} {len(moves)} files: "
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        if moves
        else "Nothing to organize"
    )
    verified = dry_run or all((folder / m["to"]).exists() for m in moves)
    return {
        "moves": moves[:500],
        "moved": 0 if dry_run else len(moves),
        "undo_file": journal.name if journal else None,
        "summary": summary,
        "verified": verified,
    }


def undo_organize(config: Any, journal_name: str) -> int:
    """Puts files back (used by `ultron-agent undo`)."""
    journal = config.data_dir / "undo" / journal_name
    data = json.loads(journal.read_text(encoding="utf-8"))
    folder = Path(data["folder"])
    restored = 0
    for m in reversed(data["moves"]):
        src, dest = folder / m["to"], folder / m["from"]
        if src.exists() and not dest.exists():
            src.rename(dest)
            restored += 1
    for sub in {m["to"].split("/")[0] for m in data["moves"]}:
        d = folder / sub
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return restored


def delete(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from send2trash import send2trash

    path = paths.resolve(ctx.config.roots, args["path"], must_exist=True)
    if any(r.resolve() == path for r in ctx.config.roots.values()):
        raise ToolError("Can't delete an allowed root folder itself")
    send2trash(str(path))
    return {
        "path": args["path"],
        "summary": f"Moved {args['path']} to the Recycle Bin",
        "verified": not path.exists(),
    }
