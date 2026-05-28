from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class MarketTrade(BaseModel):
    """Public market tape trade (not the user's account execution)."""

    model_config = {"extra": "forbid"}

    timestamp: datetime
    price: Decimal
    quantity: Decimal
    side: Literal["buy", "sell"] | None = None
    trade_id: str | None = None
    symbol: str
    source: str


# Deprecated alias for one release cycle.
Trade = MarketTrade
