"""Turns a request into a validated plan.

1. Built-in rules recognise common commands ("open VS Code", "organize my
   downloads", "remind me to ... in 10 minutes") without needing AI.
2. Otherwise the AI plans, using only the tool catalog. Its answer is
   treated as untrusted data: parsed as JSON, every tool name checked
   against the registry and every argument validated. Anything else is
   rejected. The plan is fixed before execution starts, so text read from
   files or documents later can never change which actions run.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ultron_core.ai.router import AIRouter, Completed, RoutingError, RoutingPreferences
from ultron_core.ai.types import ChatMessage, ChatRequest, TextDelta
from ultron_core.tasks import tools
from ultron_core.tasks.permissions import area_of

MAX_STEPS = 10
MAX_STEPS_WORKFLOWS = 20


class PlanError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class PlannedStep:
    tool: str
    args: dict[str, Any]
    title: str
    target: str
    risk: str
    scope: str
    max_attempts: int


@dataclass
class Plan:
    title: str
    steps: list[PlannedStep]
    source: str  # rules | ai | manual
    answer: str | None = None


@dataclass
class PlanContext:
    targets: set[str]  # reachable: always "core", plus online agents
    capabilities: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Device tools announced by online agents (None: every tool of a target).
    device_tools: set[str] | None = None
    # Areas ULTRON may act in (operating mode and autonomy level 0 remove
    # areas); None: all.
    allowed_areas: set[str] | None = None
    max_steps: int = 10
    origin: str | None = None  # target of the device that asked
    tz: tzinfo = field(default_factory=lambda: ZoneInfo("UTC"))
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


def zone(name: str | None, utc_offset_minutes: int | None = None) -> tzinfo:
    """The user's time zone: an IANA name, else a fixed UTC offset, else UTC."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    if utc_offset_minutes is not None:
        return timezone(timedelta(minutes=utc_offset_minutes))
    return ZoneInfo("UTC")


def zone_name(tz: tzinfo) -> str:
    return getattr(tz, "key", None) or str(tz)


def build_steps(
    raw_steps: list[Any], *, max_steps: int = MAX_STEPS, allowed_areas: set[str] | None = None
) -> list[PlannedStep]:
    if not isinstance(raw_steps, list):
        raise PlanError("The plan's steps must be a list.")
    if len(raw_steps) > max_steps:
        raise PlanError(f"The plan has more than {max_steps} steps.")
    steps: list[PlannedStep] = []
    for idx, raw in enumerate(raw_steps):
        if not isinstance(raw, dict) or not isinstance(raw.get("tool"), str):
            raise PlanError(f"Step {idx + 1} is not a valid step.")
        try:
            spec, args = tools.validate_step(raw["tool"], raw.get("args"))
        except tools.ToolError as exc:
            raise PlanError(f"Step {idx + 1}: {exc.message}") from None
        if allowed_areas is not None and area_of(spec.name) not in allowed_areas:
            raise PlanError(
                f"Step {idx + 1}: ULTRON isn't allowed to act on the {area_of(spec.name)} "
                "(operating mode or autonomy level 0)."
            )
        for ref in ("content_from_step", "source_step"):
            value = getattr(args, ref, None)
            if value is not None and value >= idx:
                raise PlanError(f"Step {idx + 1} can only use the result of an earlier step.")
        dumped = args.model_dump(mode="json", exclude_none=True)
        steps.append(
            PlannedStep(
                tool=spec.name,
                args=dumped,
                title=spec.describe(args)[:300],
                target=spec.target,
                risk=spec.effective_risk(args),
                scope=spec.scope,
                max_attempts=spec.max_attempts,
            )
        )
    return steps


# --- built-in rules -----------------------------------------------------------

_PREFIX = re.compile(r"^(hey\s+|ok\s+)?ultron[,:!.]?\s+", re.IGNORECASE)
_POLITE = re.compile(r"^(please|can you|could you|would you)\s+", re.IGNORECASE)
_FOLDERS = {"downloads", "desktop", "documents", "pictures", "music", "videos"}


def normalize(text: str) -> str:
    text = text.strip().rstrip(".!?")
    text = _PREFIX.sub("", text)
    text = _POLITE.sub("", text)
    return re.sub(r"\s+please$", "", text, flags=re.IGNORECASE).strip()


def available(ctx: PlanContext, tool: str) -> bool:
    spec = tools.get(tool)
    if spec is None or spec.target not in ctx.targets:
        return False
    if ctx.allowed_areas is not None and area_of(tool) not in ctx.allowed_areas:
        return False
    return spec.target == "core" or ctx.device_tools is None or tool in ctx.device_tools


def _device_tool(ctx: PlanContext, pc_tool: str, phone_tool: str | None) -> str | None:
    """Where a device action goes: the asking device if it can do it, else
    the PC, else the phone."""
    order = [("windows", pc_tool), ("android", phone_tool)]
    if ctx.origin == "android":
        order.reverse()
    for _target, tool in order:
        if tool and available(ctx, tool):
            return tool
    return None


def _due(ctx: PlanContext, m: re.Match[str]) -> datetime | None:
    if m.group("n"):
        n = int(m.group("n"))
        unit = m.group("unit").lower()
        return ctx.now + (timedelta(hours=n) if unit.startswith("h") else timedelta(minutes=n))
    hour, minute = int(m.group("h")), int(m.group("m") or 0)
    ampm = (m.group("ampm") or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    local = ctx.now.astimezone(ctx.tz)
    due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= local:
        due += timedelta(days=1)
    return due


_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^remember(?: that)?\s+(?P<x>.+)$", re.I), "remember"),
    (
        re.compile(
            r"^remind me (?:to\s+)?(?P<text>.+?)\s+"
            r"(?:in (?P<n>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?)"
            r"|at (?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?)$",
            re.I,
        ),
        "remind",
    ),
    (
        re.compile(
            r"^(?:open|launch|start)\s+(?:the\s+)?(?P<app>[\w .+#-]{1,60}?)(?:\s+app)?$", re.I
        ),
        "open",
    ),
    (re.compile(r"^(?:switch to|go to|show)\s+(?P<app>[\w .+#-]{1,60})$", re.I), "focus"),
    (
        re.compile(
            r"^(?:organi[sz]e|clean up|tidy(?: up)?|sort)\s+(?:my\s+|the\s+)?(?P<folder>\w+)"
            r"(?:\s+folder)?(?P<date>\s+by (?:date|month))?$",
            re.I,
        ),
        "organize",
    ),
    (re.compile(r"^run (?:the |my )?(?P<wf>[\w .-]{1,60}?)(?: workflow)?$", re.I), "workflow"),
    (
        re.compile(
            r"^(?:(?:pc|computer|system|phone) status|how(?:'s| is) my (?:pc|computer|phone)"
            r"(?: doing)?|check my (?:pc|computer|phone))$",
            re.I,
        ),
        "status",
    ),
]


def rule_plan(text: str, ctx: PlanContext) -> Plan | None:
    t = normalize(text)
    for pattern, kind in _RULES:
        m = pattern.match(t)
        if not m:
            continue
        raw: list[dict[str, Any]]
        if kind == "remember":
            raw = [{"tool": "memory.save", "args": {"content": m.group("x")}}]
        elif kind == "remind":
            due = _due(ctx, m)
            if due is None:
                return None
            raw = [
                {
                    "tool": "reminders.create",
                    "args": {"text": m.group("text"), "due_at": due.isoformat()},
                }
            ]
        elif kind in ("open", "focus"):
            tool = (
                _device_tool(ctx, "pc.apps.open", "phone.apps.open")
                if kind == "open"
                else _device_tool(ctx, "pc.apps.focus", None)
            )
            if tool is None:
                return None
            raw = [{"tool": tool, "args": {"app": m.group("app").strip()}}]
        elif kind == "organize":
            folder = m.group("folder").lower()
            if folder not in _FOLDERS or not available(ctx, "pc.files.organize"):
                return None
            scheme = "by_date" if m.group("date") else "by_type"
            raw = [{"tool": "pc.files.organize", "args": {"path": folder, "scheme": scheme}}]
        elif kind == "workflow":
            if not available(ctx, "pc.workflows.run"):
                return None
            names = ctx.capabilities.get("windows", {}).get("workflows", [])
            wf = m.group("wf").strip().lower()
            match = next((n for n in names if n.lower() == wf), None)
            if match is None:
                return None
            raw = [{"tool": "pc.workflows.run", "args": {"name": match}}]
        else:  # status
            tool = "phone.status" if "phone" in t.lower() else "pc.status"
            if not available(ctx, tool):
                return None
            raw = [{"tool": tool, "args": {}}]
        steps = build_steps(raw, allowed_areas=ctx.allowed_areas)
        return Plan(title=steps[0].title, steps=steps, source="rules")
    return None


# --- AI planner ----------------------------------------------------------------

PLANNER_PROMPT = """You are the task planner of ULTRON, a personal assistant that can act on \
the user's PC and phone through a fixed set of tools.

Turn the user's request into a plan. Reply with ONLY one JSON object, no other text:
{{"title": "<short title>", "steps": [{{"tool": "<tool name>", "args": {{...}}}}], \
"answer": null}}

Rules:
- Use only the tools listed below, with their exact argument names. Never invent tools.
- If the request is a question or conversation that needs no action, return \
{{"title": "Answer", "steps": [], "answer": "<your reply>"}}.
- If it needs a tool that isn't listed (for example because a device is offline), return \
no steps and explain in "answer" what is missing.
- At most {max_steps} steps. Steps run in order.
- To use text produced by an earlier step (ai.write or pc.files.read) in a later step, set \
"content_from_step" (pc.files.write) or "source_step" (ai.write) to that step's index \
(0-based) instead of copying the text.
- File paths start with one of the allowed PC folder names, e.g. "documents/Study/plan.md".
- Times: now is {now} ({tz}). Use ISO 8601 with offset for due_at.

Available tools:
{catalog}

The user's setup:
{setup}"""


def _setup_text(ctx: PlanContext) -> str:
    lines = []
    for target, caps in sorted(ctx.capabilities.items()):
        name = "PC" if target == "windows" else "Phone"
        for key in ("roots", "apps", "workflows"):
            if caps.get(key):
                lines.append(f"- {name} {key}: {', '.join(map(str, caps[key]))}")
    offline = [n for t, n in (("windows", "PC"), ("android", "phone")) if t not in ctx.targets]
    if offline:
        lines.append(f"- Not connected right now: {', '.join(offline)}")
    return "\n".join(lines) or "- No devices connected."


def parse_plan_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise PlanError("The AI didn't return a plan.")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        raise PlanError("The AI's plan wasn't valid JSON.") from None
    if not isinstance(data, dict):
        raise PlanError("The AI's plan wasn't a JSON object.")
    return data


async def ai_plan(
    text: str,
    ctx: PlanContext,
    router: AIRouter,
    prefs: RoutingPreferences,
    *,
    private: bool,
    max_output_tokens: int = 1500,
) -> Plan:
    system = PLANNER_PROMPT.format(
        max_steps=ctx.max_steps,
        now=ctx.now.astimezone(ctx.tz).isoformat(timespec="minutes"),
        tz=zone_name(ctx.tz),
        catalog=json.dumps(
            [e for e in tools.catalog(ctx.targets) if available(ctx, e["tool"])],
            separators=(",", ":"),
        ),
        setup=_setup_text(ctx),
    )
    request = ChatRequest(
        messages=(ChatMessage("user", text),), system=system, max_output_tokens=max_output_tokens
    )
    parts: list[str] = []
    try:
        async with contextlib.aclosing(
            router.stream(lambda _p: request, prefs, private=private)
        ) as ev:
            async for event in ev:
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                elif isinstance(event, Completed):
                    break
    except RoutingError as exc:
        raise PlanError(f"No AI is available to plan this ({exc.message}).") from None
    data = parse_plan_json("".join(parts))
    steps = build_steps(
        data.get("steps") or [], max_steps=ctx.max_steps, allowed_areas=ctx.allowed_areas
    )
    answer = data.get("answer")
    title = str(data.get("title") or (steps[0].title if steps else "Answer"))[:200]
    return Plan(
        title=title,
        steps=steps,
        source="ai",
        answer=str(answer)[:8000] if isinstance(answer, str) and answer.strip() else None,
    )
