"""Breeze live trading integration (place/modify/cancel order, order book)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.capabilities import CapabilityDetail, TradeCapabilities
from bandl.exceptions import (
    InsufficientFundsError,
    OrderRejectedError,
    ProviderError,
)
from bandl.models.account.types import OrderSide, OrderStatus, OrderType, Segment
from bandl.models.trading import (
    Order,
    OrderAcknowledgement,
    OrderRequest,
    ProductType,
    Validity,
)
from bandl.trade.validation import (
    extract_broker_order_id,
    resolve_account_binding,
    validate_broker_order_request,
    validate_order_modification,
    verify_account_binding,
)

if TYPE_CHECKING:
    from bandl.providers.breeze.provider import BreezeProvider

_PRODUCT_TO_BREEZE: dict[str, str] = {
    ProductType.DELIVERY: "cash",
    ProductType.INTRADAY: "margin",
    ProductType.NORMAL: "futures",
    ProductType.MARGIN: "options",
}

_BREEZE_TO_PRODUCT: dict[str, str] = {
    "cash": ProductType.DELIVERY,
    "margin": ProductType.INTRADAY,
    "futures": ProductType.NORMAL,
    "options": ProductType.MARGIN,
}


def _parse_breeze_status(status_str: str | None) -> str:
    s = (status_str or "").strip().lower()
    if "executed" in s or "traded" in s or "complete" in s:
        return OrderStatus.COMPLETE
    if "partial" in s:
        return OrderStatus.PARTIAL
    if "ordered" in s or "open" in s or "requested" in s or "queued" in s:
        return OrderStatus.OPEN
    if "cancelled" in s or "canceled" in s:
        return OrderStatus.CANCELLED
    if "rejected" in s:
        return OrderStatus.REJECTED
    if "expired" in s:
        return OrderStatus.EXPIRED
    return OrderStatus.UNKNOWN


class BreezeTradingMixin:
    """Live trade mutation and order tracking mixed into BreezeProvider."""

    def trade_capabilities(self: BreezeProvider) -> TradeCapabilities:
        return TradeCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.EQUITY_CASH, Segment.EQUITY_FNO, Segment.COMMODITY],
            place=CapabilityDetail(
                supported=True,
                notes=["Breeze POST /order (regular variety)"],
            ),
            modify=CapabilityDetail(
                supported=True,
                notes=["Breeze PUT /order"],
            ),
            cancel=CapabilityDetail(
                supported=True,
                notes=["Breeze DELETE /order"],
            ),
            get_open_orders=CapabilityDetail(
                supported=True,
                notes=["Filtered from Breeze GET /order (recent 7-10 days)"],
            ),
            get_orders=CapabilityDetail(
                supported=True,
                notes=["Breeze GET /order"],
            ),
            get_order=CapabilityDetail(
                supported=True,
                notes=["Breeze GET /order with order_id"],
            ),
            get_order_history=CapabilityDetail(
                supported=True,
                notes=["Breeze GET /orderdetail with order_id"],
            ),
            get_trades=CapabilityDetail(
                supported=False,
                notes=["Breeze get_trade_detail requires product_type and stock_code filters"],
            ),
            idempotency=CapabilityDetail(supported=False),
            order_types=["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
            products=["cash", "margin", "futures", "options"],
            validities=["day", "ioc"],
            varieties=["regular"],
        )

    def place_order(
        self: BreezeProvider,
        order: OrderRequest,
        *,
        account_id: str | None = None,
    ) -> OrderAcknowledgement:
        effective_account_id = resolve_account_binding(
            self, account_id=account_id, order_account_id=order.account_id
        )
        validate_broker_order_request(self.provider_id, order)

        # Resolve stock_code and exchange
        stock_code = order.symbol or (order.contract.underlying if order.contract else "")
        exchange = (
            order.exchange or (order.contract.exchange if order.contract else "NSE")
        ).upper()

        # Product type
        product = _PRODUCT_TO_BREEZE.get(order.product, "cash")
        action = "buy" if order.side == OrderSide.BUY else "sell"
        order_type = "market" if order.order_type == OrderType.MARKET else "limit"

        body: dict[str, Any] = {
            "stock_code": stock_code,
            "exchange_code": exchange,
            "product": product,
            "action": action,
            "order_type": order_type,
            "quantity": str(order.quantity),
            "price": str(order.price or "0"),
            "validity": "ioc" if order.validity == Validity.IOC else "day",
            "disclosed_quantity": str(order.disclosed_quantity or "0"),
        }

        if order.trigger_price is not None:
            body["stoploss"] = str(order.trigger_price)

        if order.contract is not None:
            c = order.contract
            body["product"] = "options"
            body["expiry_date"] = c.expiry.strftime("%Y-%m-%dT06:00:00.000Z")
            body["strike_price"] = str(c.strike)
            body["right"] = "call" if c.option_type.value.lower() in ("call", "ce") else "put"

        raw = self._request_v1("POST", "order", body=body)
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, "Unexpected place_order payload from Breeze")

        err = raw.get("Error")
        if err:
            err_lower = str(err).lower()
            if "fund" in err_lower or "margin" in err_lower:
                raise InsufficientFundsError(self.provider_id, str(err))
            raise OrderRejectedError(self.provider_id, str(err), raw_status="REJECTED")

        success = raw.get("Success") or {}
        order_id = success.get("order_id") if isinstance(success, dict) else str(success)

        return OrderAcknowledgement(
            operation="place",
            provider_id=self.provider_id,
            account_id=effective_account_id,
            order_id=str(order_id) if order_id else None,
            client_order_id=order.client_order_id,
            status=None,
            received_at=datetime.now(timezone.utc),
            provider_native=raw,
        )

    def cancel_order(
        self: BreezeProvider,
        order_id: str | Order,
        *,
        account_id: str | None = None,
        exchange: str = "NSE",
    ) -> OrderAcknowledgement:
        verify_account_binding(self, account_id)
        clean_order_id = extract_broker_order_id(order_id)

        body = {
            "order_id": clean_order_id,
            "exchange_code": exchange.upper(),
        }
        raw = self._request_v1("DELETE", "order", body=body)
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, "Unexpected cancel_order payload from Breeze")

        err = raw.get("Error")
        if err:
            raise ProviderError(self.provider_id, f"Cancel order failed: {err}")

        return OrderAcknowledgement(
            operation="cancel",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=clean_order_id,
            status=None,
            received_at=datetime.now(timezone.utc),
            provider_native=raw,
        )

    def modify_order(
        self: BreezeProvider,
        order_id: str | Order,
        *,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        disclosed_quantity: Decimal | None = None,
        validity: Validity | None = None,
        order_type: OrderType | None = None,
        account_id: str | None = None,
        exchange: str = "NSE",
    ) -> OrderAcknowledgement:
        verify_account_binding(self, account_id)
        clean_order_id = extract_broker_order_id(order_id)
        validate_order_modification(
            self.provider_id,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            validity=validity,
        )

        body: dict[str, Any] = {
            "order_id": clean_order_id,
            "exchange_code": exchange.upper(),
        }
        if quantity is not None:
            body["quantity"] = str(quantity)
        if price is not None:
            body["price"] = str(price)
        if trigger_price is not None:
            body["stoploss"] = str(trigger_price)
        if disclosed_quantity is not None:
            body["disclosed_quantity"] = str(disclosed_quantity)
        if validity is not None:
            body["validity"] = "ioc" if validity == Validity.IOC else "day"
        if order_type is not None:
            body["order_type"] = "market" if order_type == OrderType.MARKET else "limit"

        raw = self._request_v1("PUT", "order", body=body)
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, "Unexpected modify_order payload from Breeze")

        err = raw.get("Error")
        if err:
            raise ProviderError(self.provider_id, f"Modify order failed: {err}")

        return OrderAcknowledgement(
            operation="modify",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=clean_order_id,
            status=None,
            received_at=datetime.now(timezone.utc),
            provider_native=raw,
        )
