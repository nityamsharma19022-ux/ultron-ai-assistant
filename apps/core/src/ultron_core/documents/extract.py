"""Text extraction from uploaded files.

Supported: PDF (text layer), DOCX, plain text / Markdown / CSV / JSON and
other text formats, XLSX spreadsheets. Images and audio are refused with a
clear reason: ULTRON has no OCR, vision model or audio transcription on the
server yet.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import PurePath

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".log",
    ".xml",
    ".html",
    ".htm",
    ".yaml",
    ".yml",
    ".ini",
    ".toml",
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
    ".tex",
    ".rtf",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
MAX_CHARS = 2_000_000


class ExtractionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Extracted:
    kind: str
    text: str
    pages: int | None = None


def extract(name: str, data: bytes) -> Extracted:
    suffix = PurePath(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        raise ExtractionError(
            "Images can't be read yet: ULTRON has no OCR or vision model set up. "
            "Save text from it as a PDF or text file instead."
        )
    if suffix in AUDIO_EXTENSIONS:
        raise ExtractionError(
            "Audio files can't be transcribed on the server yet. Use the voice "
            "button instead (speech is turned into text on your device)."
        )
    if suffix == ".pdf" or data[:5] == b"%PDF-":
        return _pdf(data)
    if suffix == ".docx":
        return _docx(data)
    if suffix in (".xlsx", ".xlsm"):
        return _xlsx(data)
    if suffix in TEXT_EXTENSIONS or not suffix:
        return _text(data, "text")
    raise ExtractionError(f"{suffix} files aren't supported (PDF, Word, Excel and text are).")


def _limit(text: str) -> str:
    return text.replace("\x00", "")[:MAX_CHARS]


def _pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("The PDF is password-protected.")
        pages = [page.extract_text() or "" for page in reader.pages[:2000]]
    except PdfReadError:
        raise ExtractionError("The PDF couldn't be read (it may be damaged).") from None
    text = "\n\n".join(f"[Page {i + 1}]\n{p.strip()}" for i, p in enumerate(pages) if p.strip())
    if not text.strip():
        raise ExtractionError(
            "This PDF has no text layer (probably scanned). ULTRON can't read scans yet."
        )
    return Extracted("pdf", _limit(text), pages=len(pages))


def _docx(data: bytes) -> Extracted:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, KeyError, ValueError):
        raise ExtractionError("The Word file couldn't be read.") from None
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return Extracted("docx", _limit("\n".join(parts)))


def _xlsx(data: bytes) -> Extracted:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ExtractionError("The spreadsheet couldn't be read.") from None
    out = io.StringIO()
    writer = csv.writer(out)
    for sheet in workbook.worksheets[:20]:
        out.write(f"[Sheet {sheet.title}]\n")
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= 5000:
                break
            if any(v is not None for v in row):
                writer.writerow(["" if v is None else v for v in row])
    workbook.close()
    return Extracted("sheet", _limit(out.getvalue()))


def _text(data: bytes, kind: str) -> Extracted:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    if sum(1 for c in text[:4000] if c == "\x00" or (ord(c) < 32 and c not in "\r\n\t")) > 40:
        raise ExtractionError("That file looks binary, not text.")
    return Extracted(kind, _limit(text))


def chunks(text: str, size: int = 1500, overlap: int = 200) -> list[str]:
    """Overlapping pieces, cut at paragraph or sentence ends where possible."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if cut > size // 2:
                end = start + cut + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in out if c]
