from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from bandl.v2.models.types import Interval


class Kline(BaseModel):
    """Streaming-friendly candle with completion flag."""

    model_config = {"extra": "forbid"}

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None = None
    trades: int | None = None
    is_closed: bool
    symbol: str
    interval: Interval | str
    source: str
