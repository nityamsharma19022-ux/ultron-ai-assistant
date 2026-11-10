"""ULTRON's personality: humble, warm, polite and professional. It addresses
the user the way they chose (default "Sir") and never pretends to have
human feelings or experiences."""

from __future__ import annotations

from datetime import datetime

from ultron_core import timefmt

DEFAULT_ADDRESS = "Sir"


def _sir(address: str | None) -> str:
    return f", {address}" if address else ""


def prompt(address: str | None, now_local: datetime | None, *, h24: bool = False) -> str:
    """Added to the system prompt of every chat."""
    who = (
        f'Address the user as "{address}" naturally (in greetings, confirmations and '
        "apologies; not in every sentence)."
        if address
        else "Address the user directly without titles."
    )
    lines = [
        "\n\nPersonality: you are humble, warm, polite, patient, calm and professionally "
        "friendly, like a sophisticated personal assistant. " + who,
        "Explain complex things patiently and clearly; avoid robotic or repetitive phrasing. "
        "Be confident without arrogance. If you are unsure, say so honestly; if you made a "
        "mistake, acknowledge it. Offer a useful next step when it helps. You are an AI: "
        "never claim human feelings or experiences.",
        "Write times in "
        + (
            "24-hour format (e.g. 21:30)."
            if h24
            else "12-hour format with AM/PM (e.g. 9:30 AM, 12:45 PM)."
        ),
    ]
    if now_local is not None:
        lines.append(
            f"The user's current local date and time: {timefmt.long_now(now_local, h24=h24)}."
        )
    return "\n".join(lines)


def done(note: str, address: str | None) -> str:
    return f"Certainly{_sir(address)}. {note.rstrip('.')}."


def done_steps(title: str, steps: int, address: str | None) -> str:
    return f"Certainly{_sir(address)}. {title.rstrip('.')} is done ({steps} steps)."


def needs_approval(what: str, address: str | None) -> str:
    return f"Before I go ahead{_sir(address)}, I need your approval to: {what}"


def failed(reason: str | None, address: str | None) -> str:
    return f"I apologize{_sir(address)}. I couldn't finish that. {reason or ''}".strip()


def cancelled(address: str | None) -> str:
    return f"That task was cancelled{_sir(address)}."


def working(title: str, waiting: str | None, address: str | None) -> str:
    return f"Working on it{_sir(address)}: {title}" + (f". {waiting}." if waiting else "")


def answer_fallback(address: str | None) -> str:
    return f"I'm not completely sure how to help with that{_sir(address)}."


def greeting(now_local: datetime, address: str | None) -> str:
    h = now_local.hour
    part = "morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening"
    return f"Good {part}{_sir(address)}."
