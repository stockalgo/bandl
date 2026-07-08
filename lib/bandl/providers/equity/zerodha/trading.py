"""Zerodha Kite live trading (regular-variety orders only in this release)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.account_filters import AccountFilters
from bandl.core.capabilities import CapabilityDetail, TradeCapabilities
from bandl.core.resolver import resolve_symbol
from bandl.exceptions import ProviderError, UnsupportedCapabilityError
from bandl.models.account import AccountFill
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import OrderSide, OrderStatus, OrderType, Segment
from bandl.models.trading import Order, OrderRequest, ProductType, Validity, Variety
from bandl.providers.equity.zerodha.account import _canonical_symbol, _kite_segment
from bandl.providers.equity.zerodha.common import KITE_API, kite_unwrap
from bandl.providers.equity.zerodha.common import parse_kite_timestamp as _parse_kite_timestamp

if TYPE_CHECKING:
    from bandl.providers.equity.zerodha.provider import ZerodhaProvider

_PRODUCT_OUT: dict[str, str] = {
    ProductType.DELIVERY: "CNC",
    ProductType.INTRADAY: "MIS",
    ProductType.NORMAL: "NRML",
    ProductType.MTF: "MTF",
}
_PRODUCT_IN: dict[str, str] = {
    "CNC": ProductType.DELIVERY,
    "MIS": ProductType.INTRADAY,
    "NRML": ProductType.NORMAL,
    "MTF": ProductType.MTF,
    "CO": ProductType.COVER,
    "BO": ProductType.BRACKET,
}
_VALIDITY_OUT: dict[str, str] = {Validity.DAY: "DAY", Validity.IOC: "IOC"}
_VALIDITY_IN: dict[str, str] = {"DAY": Validity.DAY, "IOC": Validity.IOC, "TTL": Validity.TTL}
_ORDER_TYPE_OUT: dict[str, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "SL",
    OrderType.STOP: "SL-M",
}
_ORDER_TYPE_IN: dict[str, str] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "SL": OrderType.STOP_LIMIT,
    "SL-M": OrderType.STOP,
}
_VARIETY_IN: dict[str, str] = {
    "regular": Variety.REGULAR,
    "amo": Variety.AMO,
    "co": Variety.COVER,
    "bo": Variety.BRACKET,
    "iceberg": Variety.ICEBERG,
    "auction": Variety.AUCTION,
}
_STATUS_IN: dict[str, str] = {
    "OPEN": OrderStatus.OPEN,
    "COMPLETE": OrderStatus.COMPLETE,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "TRIGGER PENDING": OrderStatus.OPEN,
    "OPEN PENDING": OrderStatus.OPEN,
    "VALIDATION PENDING": OrderStatus.OPEN,
    "MODIFY PENDING": OrderStatus.OPEN,
    "MODIFY VALIDATION PENDING": OrderStatus.OPEN,
    "CANCEL PENDING": OrderStatus.OPEN,
    "PUT ORDER REQ RECEIVED": OrderStatus.OPEN,
    "AMO REQ RECEIVED": OrderStatus.OPEN,
}


class ZerodhaTradingMixin:
    """Live order write/read methods mixed into ZerodhaProvider."""

    def trade_capabilities(self: ZerodhaProvider) -> TradeCapabilities:
        return TradeCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.EQUITY_CASH, Segment.EQUITY_FNO, Segment.COMMODITY],
            place=CapabilityDetail(
                supported=True,
                notes=["variety=regular only; AMO/CO/BO/iceberg not writable in this release"],
            ),
            modify=CapabilityDetail(supported=True),
            cancel=CapabilityDetail(supported=True),
            get_open_orders=CapabilityDetail(supported=True, pagination="day_scoped"),
            get_order=CapabilityDetail(supported=True),
            get_trades=CapabilityDetail(supported=True, pagination="day_scoped"),
        )

    def _resolve_order_instrument(self: ZerodhaProvider, order: OrderRequest) -> tuple[str, str]:
        # deferred: provider.py imports this mixin, so a top-level import here would cycle.
        from bandl.providers.equity.zerodha.provider import _normalize_kite_exchange

        if order.contract is not None:
            ex = _normalize_kite_exchange(order.exchange or order.contract.exchange)
            return order.contract.canonical(), ex
        if order.instrument_id is not None:
            raise ProviderError(
                self.provider_id,
                "Zerodha order placement needs 'symbol' or 'contract' (tradingsymbol), "
                "not instrument_id",
            )
        if not order.symbol:
            raise ProviderError(self.provider_id, "OrderRequest requires 'symbol' or 'contract'")
        ex = _normalize_kite_exchange(order.exchange or "NSE")
        rs = resolve_symbol(order.symbol)
        ts = self._pick_tradingsymbol(rs, tradingsymbol=None)
        return ts, ex

    def _build_kite_order_body(
        self: ZerodhaProvider,
        order: OrderRequest,
        tradingsymbol: str,
        exchange: str,
    ) -> dict[str, Any]:
        if order.variety != Variety.REGULAR:
            raise UnsupportedCapabilityError(self.provider_id, f"variety={order.variety}")
        try:
            product = _PRODUCT_OUT[order.product]
        except KeyError as err:
            raise ProviderError(
                self.provider_id,
                f"product={order.product} not writable for zerodha (this release)",
            ) from err
        try:
            validity = _VALIDITY_OUT[order.validity]
        except KeyError as err:
            raise ProviderError(
                self.provider_id,
                f"validity={order.validity} not writable for zerodha (this release)",
            ) from err
        try:
            order_type = _ORDER_TYPE_OUT[order.order_type]
        except KeyError as err:
            raise ProviderError(
                self.provider_id,
                f"order_type={order.order_type} not writable for zerodha (this release)",
            ) from err
        if order_type in ("SL", "SL-M") and order.trigger_price is None:
            raise ProviderError(self.provider_id, f"{order_type} orders require trigger_price")

        body: dict[str, Any] = {
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "transaction_type": order.side.value.upper(),
            "order_type": order_type,
            "quantity": str(int(order.quantity)),
            "product": product,
            "validity": validity,
        }
        if order.price is not None:
            body["price"] = str(order.price)
        if order.trigger_price is not None:
            body["trigger_price"] = str(order.trigger_price)
        if order.disclosed_quantity is not None:
            body["disclosed_quantity"] = str(int(order.disclosed_quantity))
        if order.client_order_id:
            body["tag"] = order.client_order_id[:20]
        return body

    def place_order(self: ZerodhaProvider, order: OrderRequest) -> Order:
        tradingsymbol, exchange = self._resolve_order_instrument(order)
        body = self._build_kite_order_body(order, tradingsymbol, exchange)
        raw = self._http.post_json(
            f"{KITE_API}/orders/regular",
            provider=self.provider_id,
            body=body,
            headers=self._auth_headers(),
        )
        data = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(data, dict) or "order_id" not in data:
            raise ProviderError(self.provider_id, f"Unexpected place-order payload: {data!r}")
        return self.get_order(str(data["order_id"]))

    def modify_order(
        self: ZerodhaProvider,
        order_id: str,
        *,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        quantity: Decimal | None = None,
        validity: str | None = None,
    ) -> Order:
        body: dict[str, Any] = {}
        if price is not None:
            body["price"] = str(price)
        if trigger_price is not None:
            body["trigger_price"] = str(trigger_price)
        if quantity is not None:
            body["quantity"] = str(int(quantity))
        if validity is not None:
            body["validity"] = _VALIDITY_OUT.get(validity, str(validity))
        raw = self._http.put_json(
            f"{KITE_API}/orders/regular/{order_id}",
            provider=self.provider_id,
            body=body,
            headers=self._auth_headers(),
        )
        kite_unwrap(raw, provider_id=self.provider_id)
        return self.get_order(order_id)

    def cancel_order(self: ZerodhaProvider, order_id: str) -> Order:
        raw = self._http.delete_json(
            f"{KITE_API}/orders/regular/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        kite_unwrap(raw, provider_id=self.provider_id)
        return self.get_order(order_id)

    def get_open_orders(self: ZerodhaProvider, *, symbol: str | None = None) -> list[Order]:
        raw = self._http.get_json(
            f"{KITE_API}/orders",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list):
            raise ProviderError(self.provider_id, "Unexpected orders payload")
        out: list[Order] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            order = _kite_row_to_order(self.provider_id, row)
            if order.status != OrderStatus.OPEN:
                continue
            if symbol and symbol.upper() not in order.symbol.upper():
                continue
            out.append(order)
        return out

    def get_order(self: ZerodhaProvider, order_id: str) -> Order:
        raw = self._http.get_json(
            f"{KITE_API}/orders/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list) or not payload:
            raise ProviderError(self.provider_id, f"Order {order_id} not found")
        return _kite_row_to_order(self.provider_id, payload[-1])

    def get_trades(self: ZerodhaProvider, *, symbol: str | None = None) -> list[AccountFill]:
        return self.get_fills(AccountFilters(symbol=symbol))


def _kite_row_to_order(provider_id: str, row: dict[str, Any]) -> Order:
    oid = str(row.get("order_id", ""))
    exchange = str(row.get("exchange", "NSE"))
    tsym = str(row.get("tradingsymbol", ""))
    sym = _canonical_symbol(exchange, tsym)
    txn = str(row.get("transaction_type", "BUY")).upper()
    side = OrderSide.BUY if txn == "BUY" else OrderSide.SELL
    status = _STATUS_IN.get(str(row.get("status", "")).upper(), OrderStatus.UNKNOWN)
    order_type = _ORDER_TYPE_IN.get(str(row.get("order_type", "")).upper(), OrderType.OTHER)
    product = _PRODUCT_IN.get(str(row.get("product", "")).upper(), ProductType.OTHER)
    validity = _VALIDITY_IN.get(str(row.get("validity", "")).upper(), Validity.OTHER)
    variety = _VARIETY_IN.get(str(row.get("variety", "regular")).lower(), Variety.OTHER)
    created = (
        _parse_kite_timestamp(str(row["order_timestamp"]))
        if row.get("order_timestamp")
        else datetime.now(timezone.utc)
    )
    updated = (
        _parse_kite_timestamp(str(row["exchange_update_timestamp"]))
        if row.get("exchange_update_timestamp")
        else None
    )
    exch_ts = (
        _parse_kite_timestamp(str(row["exchange_timestamp"]))
        if row.get("exchange_timestamp")
        else None
    )
    return Order(
        order_id=oid,
        client_order_id=str(row["tag"]) if row.get("tag") else None,
        exchange_order_id=str(row["exchange_order_id"]) if row.get("exchange_order_id") else None,
        side=side,
        order_type=order_type,
        product=product,
        validity=validity,
        variety=variety,
        status=status,
        status_message=row.get("status_message") or None,
        quantity=Decimal(str(row.get("quantity", 0))),
        filled_quantity=Decimal(str(row.get("filled_quantity", 0))),
        pending_quantity=Decimal(str(row["pending_quantity"]))
        if row.get("pending_quantity") is not None
        else None,
        price=Decimal(str(row["price"])) if row.get("price") else None,
        trigger_price=Decimal(str(row["trigger_price"])) if row.get("trigger_price") else None,
        average_price=Decimal(str(row["average_price"])) if row.get("average_price") else None,
        created_at=created,
        updated_at=updated,
        exchange_timestamp=exch_ts,
        source=provider_id,
        segment=_kite_segment(exchange, str(row.get("product", ""))),
        symbol=sym,
        symbol_native=tsym,
        currency="INR",
        provider_native=row,
        dedup_key=make_dedup_key(provider_id, "order", oid),
    )
