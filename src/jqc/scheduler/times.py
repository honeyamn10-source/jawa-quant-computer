"""Schedule math for the job scheduler (timezone aware)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jqc.core.errors import JqcError


def resolve_tz(tz: str | None) -> ZoneInfo:
    if not tz:
        return timezone_utc()
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise JqcError(f"Unknown timezone: {tz}") from exc


def local_tz_name() -> str:
    import time as _t

    return _t.tzname[0] or "UTC"


def now_utc() -> datetime:
    return datetime.now(timezone_utc())


def timezone_utc():

    return UTC


def compute_next(schedule_type: str, trigger: dict) -> datetime:
    """Return the next run time for a job. ``schedule_type``: once|interval|cron."""
    now = now_utc()
    if schedule_type == "once":
        at = _parse_at(trigger)
        return at if at > now else at
    if schedule_type == "interval":
        seconds = float(trigger.get("seconds") or 0) or _human_to_seconds(trigger.get("every", ""))
        if seconds <= 0:
            raise JqcError("interval schedule requires 'every' (e.g. '5 minutes') or 'seconds'")
        last = trigger.get("_last_run") or now
        last_dt = _coerce_dt(last)
        next_time = last_dt + timedelta(seconds=seconds)
        return next_time if next_time > now else now + timedelta(seconds=max(1.0, seconds))
    if schedule_type == "cron":
        return _next_cron(trigger, now)
    raise JqcError(f"Unknown schedule type: {schedule_type}")


def _parse_at(trigger: dict) -> datetime:
    raw = trigger.get("at")
    if raw is None:
        raise JqcError("once schedule requires 'at'")
    tz = resolve_tz(trigger.get("timezone"))
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone_utc())
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _coerce_dt(value) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone_utc())
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone_utc())
    return _parse_at(value)


def _human_to_seconds(s: str) -> float:
    s = s.strip().lower()
    if not s:
        return 0.0
    units = {
        "second": 1, "seconds": 1, "sec": 1,
        "minute": 60, "minutes": 60, "min": 60, "m": 60,
        "hour": 3600, "hours": 3600, "hr": 3600, "h": 3600,
        "day": 86400, "days": 86400, "d": 86400,
        "week": 604800, "weeks": 604800, "w": 604800,
    }
    try:
        number, unit = s.split(maxsplit=1)
        if unit not in units:
            # allow "5m", "1h"
            for key, mult in units.items():
                if unit.startswith(key[:1]) and key.startswith(unit[0]):
                    _ = mult
                    break
        return float(number) * units.get(unit, 60)
    except Exception:
        if s.endswith("s") and s[:-1].isdigit():
            return float(s[:-1])
        try:
            return float(s)
        except ValueError:
            raise JqcError(f"Cannot parse interval '{s}' (use e.g. '5 minutes', '1 hour')") from None


def _cron_field(trigger: dict, key: str) -> int | str:
    """Parse a cron field: ``*`` (or missing/empty) means any value."""
    value = trigger.get(key, "*")
    if value is None or value == "" or value == "*":
        return "*"
    try:
        return int(value)
    except (TypeError, ValueError):
        raise JqcError(f"Invalid cron {key} value: {value!r} (use an integer or '*')") from None


def _next_cron(trigger: dict, now: datetime) -> datetime:
    """Minimal cron: minute, hour, day-of-month, month, day-of-week (integers)."""
    minute = _cron_field(trigger, "minute")
    hour = _cron_field(trigger, "hour")
    dow = _cron_field(trigger, "day_of_week")
    resolve_tz(trigger.get("timezone"))
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 8):
        if minute != "*" and candidate.minute != minute:
            candidate += timedelta(minutes=1)
            continue
        if hour != "*" and candidate.hour != hour:
            candidate += timedelta(hours=1)
            candidate = candidate.replace(minute=0)
            continue
        if dow != "*" and candidate.weekday() != dow:
            candidate += timedelta(days=1)
            candidate = candidate.replace(hour=0, minute=0)
            continue
        return candidate
    raise JqcError("cron pattern too restrictive; no time found in the next 8 days")
