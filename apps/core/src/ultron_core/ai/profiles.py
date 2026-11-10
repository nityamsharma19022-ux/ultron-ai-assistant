"""Task-type model routing.

Each request is classified (chat, reasoning, coding, writing, summarize,
planning). If the owner configured preferred providers for that kind
(ULTRON_AI_TASK_PROFILES, e.g. "coding=groq,openrouter;reasoning=anthropic"),
those are tried first; the user's normal cloud order follows as fallback.
Private requests still use local AI only (the router enforces that).
"""

from __future__ import annotations

import re

from ultron_core.ai.router import RoutingPreferences

KINDS = ("chat", "reasoning", "coding", "writing", "summarize", "planning")

_CODE = re.compile(
    r"```|\b(def|class|function|import|stack ?trace|traceback|exception|compile|bug|"
    r"python|javascript|typescript|dart|flutter|kotlin|java|sql|regex|api|json|"
    r"refactor|unit tests?|git|docker)\b",
    re.I,
)
_REASON = re.compile(
    r"\b(why|prove|proof|derive|calculate|solve|step by step|compare|trade-?offs?|"
    r"analy[sz]e|evaluate|which is better|reason)\b",
    re.I,
)
_SUMMARY = re.compile(r"\b(summari[sz]e|summary|tl;?dr|key points|in short)\b", re.I)
_WRITE = re.compile(r"\b(write|draft|compose|essay|email|letter|report|story|poem)\b", re.I)


def classify(text: str) -> str:
    if _CODE.search(text):
        return "coding"
    if _SUMMARY.search(text):
        return "summarize"
    if _REASON.search(text):
        return "reasoning"
    if _WRITE.search(text):
        return "writing"
    return "chat"


def parse(spec: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in spec.split(";"):
        if "=" not in part:
            continue
        kind, _, names = part.partition("=")
        kind = kind.strip().lower()
        if kind in KINDS:
            out[kind] = [n.strip().lower() for n in names.split(",") if n.strip()]
    return out


def preferences_for(kind: str, base: RoutingPreferences, spec: str) -> RoutingPreferences:
    preferred = parse(spec).get(kind)
    if not preferred:
        return base
    rest = [p for p in base.cloud_order if p not in preferred]
    return RoutingPreferences(mode=base.mode, cloud_order=(*preferred, *rest))
