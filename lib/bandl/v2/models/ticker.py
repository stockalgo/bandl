from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Ticker(BaseModel):
    model_config = {"extra": "forbid"}

    timestamp: datetime
    last_price: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    high_24h: Decimal | None = None
    low_24h: Decimal | None = None
    volume_24h: Decimal | None = None
    change_24h: Decimal | None = None
    symbol: str
    source: str
