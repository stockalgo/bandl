from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class OrderbookLevel(BaseModel):
    model_config = {"extra": "forbid"}

    price: Decimal
    quantity: Decimal


class Orderbook(BaseModel):
    model_config = {"extra": "forbid"}

    timestamp: datetime
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]
    symbol: str
    source: str
    is_snapshot: bool = True
