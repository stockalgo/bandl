"""Shared datetime helpers for market and account APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def ensure_utc(dt: datetime) -> datetime:
    """Normalize naive or aware datetimes to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def default_time_range(
    start: datetime | None,
    end: datetime | None,
    *,
    default_days: int = 30,
) -> tuple[datetime, datetime]:
    """Default ``[start, end)`` window ending now (UTC) when bounds omitted."""
    end_dt = end or datetime.now(timezone.utc)
    if start is None:
        start_dt = end_dt - timedelta(days=default_days)
    else:
        start_dt = start
    end_dt = ensure_utc(end_dt)
    start_dt = ensure_utc(start_dt)
    if start_dt >= end_dt:
        from bandl.exceptions import BandlError

        raise BandlError("start must be before end")
    return start_dt, end_dt


def parse_epoch_ms(raw: Any) -> datetime:
    """Parse Unix timestamp in seconds or milliseconds to UTC."""
    ms = int(float(raw))
    if ms < 10_000_000_000:
        ms *= 1000
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def to_epoch_ms(dt: datetime) -> int:
    return int(ensure_utc(dt).timestamp() * 1000)


def to_epoch_sec(dt: datetime) -> int:
    return int(ensure_utc(dt).timestamp())
