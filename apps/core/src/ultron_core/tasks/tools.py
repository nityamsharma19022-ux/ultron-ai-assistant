"""The tool registry: every action ULTRON can take.

A tool has a typed argument model, a risk class, a permission scope and a
target (where it runs). Plans are only ever built from these tools, and
every argument is validated before anything runs, so model output can't
name an action that doesn't exist or smuggle in unchecked arguments.

Risk classes (docs/ULTRON_SECURITY.md):
- A: routine. Runs without asking when the user has granted its scope.
- B: consequential (overwriting, deleting). Always asks.
- C: external or high-impact (messages, purchases, sharing). Always asks.

Device tools are executed by the device's agent, which enforces its own
local allow-lists (folders, apps, workflows) as a second line of defence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Risk = Literal["A", "B", "C"]
Target = Literal["core", "windows", "android"]

MAX_PATH = 1000
MAX_TEXT = 200_000


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _no_nul(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


class PathArgs(ToolArgs):
    """Paths look like ``downloads/report.pdf``: an allowed root name, then a
    path inside it. The agent rejects anything outside its allowed roots."""

    path: str = Field(min_length=1, max_length=MAX_PATH)
    _chk = field_validator("path")(_no_nul)


# --- argument models -----------------------------------------------------------


class NoArgs(ToolArgs):
    pass


class MemorySaveArgs(ToolArgs):
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["preference", "fact", "project", "note"] = "note"


class MemorySearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=200)


class AiWriteArgs(ToolArgs):
    instructions: str = Field(min_length=1, max_length=4000)
    kind: Literal["report", "plan", "timetable", "notes", "summary", "email", "other"] = "other"
    # Text from an earlier step (e.g. a file that was read) to work from.
    # It is treated strictly as data, never as instructions.
    source_step: int | None = Field(default=None, ge=0, le=20)


class ReminderArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=500)
    due_at: datetime | None = None
    in_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 366)


class DocSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=300)


class DocReadArgs(ToolArgs):
    # A document's id or (part of) its name.
    document: str = Field(min_length=1, max_length=255)


class AppArgs(ToolArgs):
    app: str = Field(min_length=1, max_length=100)


class SearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=200)
    path: str | None = Field(default=None, max_length=MAX_PATH)
    limit: int = Field(default=20, ge=1, le=200)


class ReadArgs(PathArgs):
    max_chars: int = Field(default=20_000, ge=100, le=MAX_TEXT)


class WriteArgs(PathArgs):
    content: str | None = Field(default=None, max_length=MAX_TEXT)
    content_from_step: int | None = Field(default=None, ge=0, le=20)
    overwrite: bool = False


class MoveArgs(ToolArgs):
    source: str = Field(min_length=1, max_length=MAX_PATH)
    destination: str = Field(min_length=1, max_length=MAX_PATH)
    overwrite: bool = False


class OrganizeArgs(PathArgs):
    scheme: Literal["by_type", "by_date"] = "by_type"
    dry_run: bool = False


class WorkflowArgs(ToolArgs):
    name: str = Field(min_length=1, max_length=100)


class NotifyArgs(ToolArgs):
    title: str = Field(default="ULTRON", min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=500)


class AlarmArgs(ToolArgs):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    label: str = Field(default="ULTRON", max_length=100)


class TimerArgs(ToolArgs):
    seconds: int = Field(ge=1, le=24 * 3600)
    label: str = Field(default="ULTRON", max_length=100)


# --- registry ------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    target: Target
    scope: str
    risk: Risk
    args_model: type[ToolArgs]
    description: str
    describe: Callable[[Any], str]
    risk_for: Callable[[Any], Risk] | None = None
    max_attempts: int = 2

    def validate(self, args: dict[str, Any] | None) -> ToolArgs:
        return self.args_model.model_validate(args or {})

    def effective_risk(self, args: ToolArgs) -> Risk:
        return self.risk_for(args) if self.risk_for else self.risk

    def catalog_entry(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        return {
            "tool": self.name,
            "runs_on": self.target,
            "description": self.description,
            "args": schema.get("properties", {}),
            "required": schema.get("required", []),
        }


class ToolError(Exception):
    """A tool failed. ``retryable`` errors are tried again."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


def _overwrite_risk(args: Any) -> Risk:
    return "B" if getattr(args, "overwrite", False) else "A"


def _write_desc(a: WriteArgs) -> str:
    return f"{'Overwrite' if a.overwrite else 'Create'} the file {a.path}"


_SPECS: list[ToolSpec] = [
    # Core (runs inside ULTRON Core)
    ToolSpec(
        "memory.save",
        "core",
        "memory.write",
        "A",
        MemorySaveArgs,
        "Save something the user wants remembered.",
        lambda a: f"Remember: {a.content[:80]}",
    ),
    ToolSpec(
        "memory.search",
        "core",
        "memory.read",
        "A",
        MemorySearchArgs,
        "Search the user's saved memories.",
        lambda a: f"Search memories for '{a.query}'",
    ),
    ToolSpec(
        "ai.write",
        "core",
        "ai.write",
        "A",
        AiWriteArgs,
        "Write text with AI (report, plan, timetable, notes, summary, email draft). Uses the "
        "model's own knowledge; it cannot browse the web. Result: {text}.",
        lambda a: f"Write a {a.kind}: {a.instructions[:80]}",
        max_attempts=2,
    ),
    ToolSpec(
        "docs.search",
        "core",
        "docs.read",
        "A",
        DocSearchArgs,
        "Search the user's uploaded documents. Result: {text} with matching passages.",
        lambda a: f"Search your documents for '{a.query}'",
    ),
    ToolSpec(
        "docs.read",
        "core",
        "docs.read",
        "A",
        DocReadArgs,
        "Read one uploaded document (by name or id). Result: {text}. Use with ai.write "
        "source_step to summarise or analyse it.",
        lambda a: f"Read the document '{a.document}'",
    ),
    ToolSpec(
        "reminders.create",
        "core",
        "reminders",
        "A",
        ReminderArgs,
        "Create a reminder at a time (due_at, ISO 8601 with timezone) or in N minutes.",
        lambda a: f"Remind you: {a.text[:80]}",
    ),
    # Windows PC (runs in the ULTRON Windows agent)
    ToolSpec(
        "pc.status",
        "windows",
        "pc.system",
        "A",
        NoArgs,
        "PC status: CPU, memory, disks, battery, uptime.",
        lambda a: "Check your PC's status",
    ),
    ToolSpec(
        "pc.apps.list",
        "windows",
        "pc.apps",
        "A",
        NoArgs,
        "List the apps ULTRON may open on the PC.",
        lambda a: "List the apps ULTRON may open",
    ),
    ToolSpec(
        "pc.apps.open",
        "windows",
        "pc.apps",
        "A",
        AppArgs,
        "Open an allowed app on the PC by its name.",
        lambda a: f"Open {a.app} on your PC",
    ),
    ToolSpec(
        "pc.apps.focus",
        "windows",
        "pc.apps",
        "A",
        AppArgs,
        "Bring an allowed app's window to the front.",
        lambda a: f"Switch to {a.app}",
    ),
    ToolSpec(
        "pc.files.list",
        "windows",
        "pc.files.read",
        "A",
        PathArgs,
        "List a folder inside an allowed root.",
        lambda a: f"List {a.path}",
    ),
    ToolSpec(
        "pc.files.search",
        "windows",
        "pc.files.read",
        "A",
        SearchArgs,
        "Find files by name inside the allowed roots (or one path).",
        lambda a: f"Search files for '{a.query}'",
    ),
    ToolSpec(
        "pc.files.read",
        "windows",
        "pc.files.read",
        "A",
        ReadArgs,
        "Read a text, Markdown, PDF or DOCX file. Result: {text}.",
        lambda a: f"Read {a.path}",
    ),
    ToolSpec(
        "pc.files.create_folder",
        "windows",
        "pc.files.write",
        "A",
        PathArgs,
        "Create a folder.",
        lambda a: f"Create the folder {a.path}",
    ),
    ToolSpec(
        "pc.files.write",
        "windows",
        "pc.files.write",
        "A",
        WriteArgs,
        "Create a document (.txt, .md, .docx) with content, or with the text of an earlier "
        "step via content_from_step. Overwriting asks the user first.",
        _write_desc,
        risk_for=_overwrite_risk,
    ),
    ToolSpec(
        "pc.files.move",
        "windows",
        "pc.files.organize",
        "A",
        MoveArgs,
        "Move or rename a file or folder inside the allowed roots.",
        lambda a: f"Move {a.source} to {a.destination}",
        risk_for=_overwrite_risk,
    ),
    ToolSpec(
        "pc.files.organize",
        "windows",
        "pc.files.organize",
        "A",
        OrganizeArgs,
        "Sort a folder's files into subfolders by type or by month. Undo information is kept.",
        lambda a: f"Organize {a.path} {'by type' if a.scheme == 'by_type' else 'by month'}",
    ),
    ToolSpec(
        "pc.files.delete",
        "windows",
        "pc.files.delete",
        "B",
        PathArgs,
        "Move a file or folder to the Recycle Bin.",
        lambda a: f"Move {a.path} to the Recycle Bin",
        max_attempts=1,
    ),
    ToolSpec(
        "pc.workflows.run",
        "windows",
        "pc.workflows",
        "A",
        WorkflowArgs,
        "Run a workflow the user set up on the PC (by name), such as opening the dev "
        "environment or running tests.",
        lambda a: f"Run the '{a.name}' workflow",
        max_attempts=1,
    ),
    # Android phone (runs in the ULTRON app)
    ToolSpec(
        "phone.status",
        "android",
        "phone.system",
        "A",
        NoArgs,
        "Phone status: battery, network.",
        lambda a: "Check your phone's status",
    ),
    ToolSpec(
        "phone.apps.open",
        "android",
        "phone.apps",
        "A",
        AppArgs,
        "Open an app on the phone by name.",
        lambda a: f"Open {a.app} on your phone",
    ),
    ToolSpec(
        "phone.notify",
        "android",
        "phone.notify",
        "A",
        NotifyArgs,
        "Show a notification on the phone.",
        lambda a: f"Notify you: {a.text[:80]}",
    ),
    ToolSpec(
        "phone.alarm.set",
        "android",
        "phone.alarm",
        "A",
        AlarmArgs,
        "Set an alarm in the phone's clock app.",
        lambda a: f"Set an alarm for {a.hour:02d}:{a.minute:02d}",
    ),
    ToolSpec(
        "phone.timer.set",
        "android",
        "phone.alarm",
        "A",
        TimerArgs,
        "Start a timer in the phone's clock app.",
        lambda a: f"Start a {a.seconds // 60 or 1}-minute timer",
    ),
]

TOOLS: dict[str, ToolSpec] = {s.name: s for s in _SPECS}

# Permission scopes, for the permissions dashboard.
SCOPES: dict[str, str] = {
    "memory.write": "Save memories",
    "memory.read": "Search memories",
    "ai.write": "Write documents, plans and reports with AI",
    "reminders": "Create reminders",
    "docs.read": "Search and read your uploaded documents",
    "pc.system": "Read PC status",
    "pc.apps": "Open and switch apps on the PC",
    "pc.files.read": "Search and read files in allowed PC folders",
    "pc.files.write": "Create folders and new documents on the PC",
    "pc.files.organize": "Move and organize files in allowed PC folders",
    "pc.files.delete": "Move files to the Recycle Bin (always asks)",
    "pc.workflows": "Run your saved PC workflows",
    "phone.system": "Read phone status",
    "phone.apps": "Open apps on the phone",
    "phone.notify": "Show phone notifications",
    "phone.alarm": "Set alarms and timers on the phone",
}

# Scopes whose tools are all class B/C: never auto-approved.
ALWAYS_ASK_SCOPES = {"pc.files.delete"}


def register(spec: ToolSpec, scope_title: str | None = None) -> None:
    """Adds a tool (used by tests and future extensions)."""
    TOOLS[spec.name] = spec
    SCOPES.setdefault(spec.scope, scope_title or spec.scope)


def unregister(name: str) -> None:
    TOOLS.pop(name, None)


def get(name: str) -> ToolSpec | None:
    return TOOLS.get(name)


def validate_step(tool: str, args: dict[str, Any] | None) -> tuple[ToolSpec, ToolArgs]:
    spec = TOOLS.get(tool)
    if spec is None:
        raise ToolError(f"Unknown tool '{tool}'")
    try:
        return spec, spec.validate(args)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'args'}: {e['msg']}" for e in exc.errors()
        )
        raise ToolError(f"Invalid arguments for {tool}: {problems}") from None


def catalog(targets: set[str]) -> list[dict[str, Any]]:
    """Tools the planner may use, given which targets are reachable."""
    return [s.catalog_entry() for s in TOOLS.values() if s.target in targets]
