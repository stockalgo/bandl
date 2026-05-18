from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from bandl.v2.models.types import Interval


class OHLCV(BaseModel):
    """Canonical OHLCV bar."""

    model_config = {"extra": "forbid"}

    timestamp: datetime = Field(description="Open time in UTC")
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None = None
    trades: int | None = None
    symbol: str = Field(description="Canonical symbol (e.g. BTCUSDT, RELIANCE, NIFTY50)")
    interval: Interval | str
    source: str = Field(description="Provider id, e.g. binance, zerodha")
