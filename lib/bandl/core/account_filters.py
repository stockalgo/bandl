from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class AccountFilters:
    start: datetime | None = None
    end: datetime | None = None
    symbol: str | None = None
    segment: str | None = None
    side: str | None = None
    status: str | None = None
    order_id: str | None = None
    limit: int | None = None


def default_account_range(
    start: datetime | None,
    end: datetime | None,
    *,
    default_days: int = 30,
) -> tuple[datetime, datetime]:
    end_dt = end or datetime.now(timezone.utc)
    if start is None:
        start_dt = end_dt - timedelta(days=default_days)
    else:
        start_dt = start
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if start_dt >= end_dt:
        from bandl.exceptions import BandlError

        raise BandlError("start must be before end")
    return start_dt, end_dt
