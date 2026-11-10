"""Human-readable times. ULTRON shows 12-hour times (9:30 PM) by default;
the user can switch to 24-hour in Settings. Times are stored in UTC and
converted to the user's local time only for display."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def clock(hour: int, minute: int, *, h24: bool = False) -> str:
    """9:30 AM, 12:00 PM (noon), 12:05 AM (just after midnight)."""
    if h24:
        return f"{hour:02d}:{minute:02d}"
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute:02d} {suffix}"


def time_of(dt: datetime, *, h24: bool = False) -> str:
    return clock(dt.hour, dt.minute, h24=h24)


def hhmm(value: str | None, *, h24: bool = False) -> str | None:
    """'22:00' -> '10:00 PM'."""
    if not value:
        return value
    h, m = value.split(":")
    return clock(int(h), int(m), h24=h24)


def offset_zone(minutes: int | None) -> tzinfo:
    return timezone(timedelta(minutes=minutes or 0))


def when(dt: datetime, now: datetime, *, h24: bool = False) -> str:
    """'today at 9:30 PM', 'tomorrow at 7:00 AM', 'on 12 Nov at 6:15 PM'.
    ``dt`` and ``now`` must be in the same (local) time zone."""
    t = time_of(dt, h24=h24)
    days = (dt.date() - now.date()).days
    if days == 0:
        return f"today at {t}"
    if days == 1:
        return f"tomorrow at {t}"
    return f"on {dt.day} {MONTHS[dt.month - 1]} at {t}"


def long_now(now: datetime, *, h24: bool = False) -> str:
    """'Tuesday, 10 November 2026, 9:24 PM' for the AI's context."""
    return f"{now:%A}, {now.day} {now:%B %Y}, {time_of(now, h24=h24)}"
