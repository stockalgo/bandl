from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from bandl.models.account.base import AccountEntityBase
from bandl.models.account.types import OrderSide, OrderType
from bandl.models.market.contract import OptionContract
from bandl.models.trading.types import ProductType, Validity, Variety


class QuantityUnit(str, Enum):
    BASE = "base"
    QUOTE = "quote"
    CONTRACTS = "contracts"


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    BOTH = "both"


class OrderAcknowledgement(BaseModel):
    """Immediate acknowledgement returned upon accepted order mutation.

    `status` contains raw native response metadata from the broker acknowledgement payload
    (such as Dhan's immediate 'orderStatus'), distinct from normalized Order.status.
    If the broker response only confirms acceptance by returning an ID (e.g. Zerodha),
    `status` is None.
    """

    model_config = {"extra": "forbid"}

    operation: Literal["place", "modify", "cancel"]
    provider_id: str
    account_id: str | None = None
    order_id: str | None = None
    client_order_id: str | None = None
    status: str | None = None
    received_at: datetime
    provider_native: dict[str, Any] = Field(default_factory=dict)


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
    position_side: PositionSide | None = None
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal
    quantity_unit: QuantityUnit = QuantityUnit.BASE
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    disclosed_quantity: Decimal | None = None

    product: ProductType = ProductType.DELIVERY
    validity: Validity = Validity.DAY
    variety: Variety = Variety.REGULAR

    reduce_only: bool = False
    post_only: bool = False

    client_order_id: str | None = None
    account_id: str | None = None
    market: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_order_request(self) -> OrderRequest:
        identities: list[str] = []
        if self.symbol is not None:
            if not isinstance(self.symbol, str) or not self.symbol.strip():
                raise ValueError("symbol cannot be empty or whitespace-only")
            identities.append("symbol")
        if self.contract is not None:
            identities.append("contract")
        if self.instrument_id is not None:
            if not isinstance(self.instrument_id, str) or not self.instrument_id.strip():
                raise ValueError("instrument_id cannot be empty or whitespace-only")
            identities.append("instrument_id")

        if len(identities) != 1:
            raise ValueError(
                "OrderRequest requires exactly one of 'symbol', 'contract', or 'instrument_id'; "
                f"got {len(identities)}"
            )

        if not isinstance(self.quantity, Decimal):
            try:
                self.quantity = Decimal(str(self.quantity))
            except Exception as err:
                raise ValueError(f"Invalid quantity: {self.quantity}") from err
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError(
                f"OrderRequest quantity must be finite and positive, got {self.quantity}"
            )

        if self.price is not None:
            if not isinstance(self.price, Decimal):
                try:
                    self.price = Decimal(str(self.price))
                except Exception as err:
                    raise ValueError(f"Invalid price: {self.price}") from err
            if not self.price.is_finite() or self.price <= 0:
                raise ValueError(f"price must be finite and positive, got {self.price}")

        if self.trigger_price is not None:
            if not isinstance(self.trigger_price, Decimal):
                try:
                    self.trigger_price = Decimal(str(self.trigger_price))
                except Exception as err:
                    raise ValueError(f"Invalid trigger_price: {self.trigger_price}") from err
            if not self.trigger_price.is_finite() or self.trigger_price <= 0:
                raise ValueError(
                    f"trigger_price must be finite and positive, got {self.trigger_price}"
                )

        if self.disclosed_quantity is not None:
            if not isinstance(self.disclosed_quantity, Decimal):
                try:
                    self.disclosed_quantity = Decimal(str(self.disclosed_quantity))
                except Exception as err:
                    raise ValueError(
                        f"Invalid disclosed_quantity: {self.disclosed_quantity}"
                    ) from err
            if not self.disclosed_quantity.is_finite() or self.disclosed_quantity < 0:
                raise ValueError(
                    "disclosed_quantity must be finite and non-negative, "
                    f"got {self.disclosed_quantity}"
                )
            if self.disclosed_quantity > self.quantity:
                raise ValueError(
                    f"disclosed_quantity ({self.disclosed_quantity}) cannot exceed "
                    f"quantity ({self.quantity})"
                )

        if self.client_order_id is not None and not self.client_order_id.strip():
            raise ValueError("client_order_id cannot be empty or whitespace-only")

        return self


class Order(AccountEntityBase):
    """Live order state (superset of ``AccountOrder`` for the trade-write path)."""

    order_id: str
    client_order_id: str | None = None
    exchange_order_id: str | None = None

    side: OrderSide
    position_side: PositionSide | None = None
    order_type: str
    product: str
    validity: str
    variety: str = Variety.REGULAR

    status: str
    raw_status: str | None = None
    status_message: str | None = None

    quantity: Decimal
    filled_quantity: Decimal = Decimal(0)
    pending_quantity: Decimal | None = None
    cancelled_quantity: Decimal | None = None

    price: Decimal | None = None
    trigger_price: Decimal | None = None
    average_price: Decimal | None = None

    created_at: datetime
    updated_at: datetime | None = None
    exchange_timestamp: datetime | None = None
