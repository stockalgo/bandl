from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from bandl.models.account.base import AccountEntityBase
from bandl.models.account.types import OrderSide


class Position(AccountEntityBase):
    """Net open position (intraday or F&O carryforward)."""

    side: OrderSide
    quantity: Decimal  # signed: negative = short
    average_price: Decimal
    last_price: Decimal | None = None
    close_price: Decimal | None = None
    product: str

    multiplier: Decimal | None = None  # F&O lot size
    buy_quantity: Decimal | None = None
    sell_quantity: Decimal | None = None

    realized_pnl: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    pnl: Decimal | None = None


class Holding(AccountEntityBase):
    """Long-term equity holding / settled spot balance."""

    quantity: Decimal  # settled/realised
    t1_quantity: Decimal | None = None  # not-yet-settled (T+1)
    average_price: Decimal | None = None
    last_price: Decimal | None = None
    close_price: Decimal | None = None
    pnl: Decimal | None = None
    day_change: Decimal | None = None
    day_change_pct: Decimal | None = None
    collateral_quantity: Decimal | None = None
    collateral_type: str | None = None
    isin: str | None = None


class Balance(BaseModel):
    """Cash/fund balance, optionally scoped to a segment."""

    model_config = {"extra": "forbid"}

    source: str
    segment: str | None = None
    currency: str = "INR"
    available: Decimal
    used: Decimal
    total: Decimal
    provider_native: dict[str, Any] = Field(default_factory=dict)


class MarginInfo(BaseModel):
    """Account-level margin/funds snapshot."""

    model_config = {"extra": "forbid"}

    source: str
    currency: str = "INR"
    available: Decimal
    used: Decimal
    total: Decimal
    span: Decimal | None = None
    exposure: Decimal | None = None
    provider_native: dict[str, Any] = Field(default_factory=dict)
