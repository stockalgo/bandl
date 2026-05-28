from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bandl.core.time import default_time_range


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
    return default_time_range(start, end, default_days=default_days)
