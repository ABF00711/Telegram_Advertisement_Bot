import re
from datetime import datetime, timedelta, timezone

from config import LOCAL_TZ, TIMEZONE

_RELATIVE = re.compile(
    r"^\+\s*(\d+)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d)$",
    re.IGNORECASE,
)


def time_help() -> str:
    return (
        "Send the time in one of these forms:\n"
        "- 2026-11-25 14:30\n"
        "- 14:30\n"
        "- +30m, +2h, or +1d\n"
        f"Times use {TIMEZONE}. A clock time is today, or tomorrow if it has already passed."
    )


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """Return an aware datetime in the configured local timezone."""
    now = now or datetime.now(LOCAL_TZ)
    raw = (text or "").strip()
    relative = _RELATIVE.fullmatch(raw)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        if unit.startswith("d"):
            if amount > 3650:
                raise ValueError("Pick a time within 10 years.")
            return now + timedelta(days=amount)
        if unit.startswith("h"):
            if amount > 24 * 3650:
                raise ValueError("Pick a time within 10 years.")
            return now + timedelta(hours=amount)
        if amount > 60 * 24 * 3650:
            raise ValueError("Pick a time within 10 years.")
        return now + timedelta(minutes=amount)

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=LOCAL_TZ)

    try:
        parsed = datetime.strptime(raw, "%H:%M")
    except ValueError as exc:
        raise ValueError(time_help()) from exc

    candidate = now.replace(
        hour=parsed.hour,
        minute=parsed.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Expected a timezone-aware datetime.")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def format_local(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
