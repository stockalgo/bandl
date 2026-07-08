from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from bandl.models.account.base import AccountEntityBase
from bandl.models.account.types import OrderSide, OrderType
from bandl.models.market.contract import OptionContract
from bandl.models.trading.types import ProductType, Validity, Variety


class OrderRequest(BaseModel):
    """Broker-agnostic order placement request.

    Instrument identity — pass exactly one of ``contract``, ``instrument_id``,
    or ``symbol`` (+``exchange``). ``contract``/``instrument_id`` are the most
    robust for options: they skip live scrip-master resolution ambiguity.
    """

    model_config = {"extra": "forbid"}

    symbol: str | None = None
    contract: OptionContract | None = None
    instrument_id: str | None = None
    exchange: str | None = None

    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    disclosed_quantity: Decimal | None = None

    product: ProductType = ProductType.DELIVERY
    validity: Validity = Validity.DAY
    variety: Variety = Variety.REGULAR

    client_order_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Order(AccountEntityBase):
    """Live order state (superset of ``AccountOrder`` for the trade-write path)."""

    order_id: str
    client_order_id: str | None = None
    exchange_order_id: str | None = None

    side: OrderSide
    order_type: str
    product: str
    validity: str
    variety: str = Variety.REGULAR

    status: str
    status_message: str | None = None

    quantity: Decimal
    filled_quantity: Decimal = Decimal(0)
    pending_quantity: Decimal | None = None

    price: Decimal | None = None
    trigger_price: Decimal | None = None
    average_price: Decimal | None = None

    created_at: datetime
    updated_at: datetime | None = None
    exchange_timestamp: datetime | None = None
