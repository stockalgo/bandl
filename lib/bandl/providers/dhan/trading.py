"""Dhan v2 live trading (regular-variety orders only in this release).

Order/modify/cancel require static-IP whitelisting on the Dhan account
(see https://dhanhq.co/docs/v2/orders/); surfaced via AuthenticationError
when the upstream call is rejected for that reason.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.capabilities import CapabilityDetail, TradeCapabilities
from bandl.exceptions import AuthenticationError, ProviderError, UnsupportedCapabilityError
from bandl.models.account import AccountFill
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import OrderSide, OrderStatus, OrderType, Segment
from bandl.models.trading import Order, OrderRequest, ProductType, Validity, Variety
from bandl.providers.dhan.common import DHAN_API, EXCHANGE_SEGMENT, SEGMENT_TO_EXCHANGE

if TYPE_CHECKING:
    from bandl.providers.dhan.provider import DhanProvider

_IST = timezone(timedelta(hours=5, minutes=30))

_PRODUCT_OUT: dict[str, str] = {
    ProductType.DELIVERY: "CNC",
    ProductType.INTRADAY: "INTRADAY",
    ProductType.MARGIN: "MARGIN",
    ProductType.MTF: "MTF",
}
_PRODUCT_IN: dict[str, str] = {
    "CNC": ProductType.DELIVERY,
    "INTRADAY": ProductType.INTRADAY,
    "MARGIN": ProductType.MARGIN,
    "MTF": ProductType.MTF,
    "CO": ProductType.COVER,
    "BO": ProductType.BRACKET,
}
_VALIDITY_OUT: dict[str, str] = {Validity.DAY: "DAY", Validity.IOC: "IOC"}
_VALIDITY_IN: dict[str, str] = {"DAY": Validity.DAY, "IOC": Validity.IOC}
_ORDER_TYPE_OUT: dict[str, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOP_LOSS",
    OrderType.STOP: "STOP_LOSS_MARKET",
}
_ORDER_TYPE_IN: dict[str, str] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP_LOSS": OrderType.STOP_LIMIT,
    "STOP_LOSS_MARKET": OrderType.STOP,
}
_STATUS_IN: dict[str, str] = {
    "TRANSIT": OrderStatus.OPEN,
    "PENDING": OrderStatus.OPEN,
    "PART_TRADED": OrderStatus.PARTIAL,
    "TRADED": OrderStatus.COMPLETE,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


def _bandl_segment(exchange_segment: str) -> str:
    seg = exchange_segment.upper()
    if seg == "MCX_COMM":
        return Segment.COMMODITY
    if seg in ("NSE_FNO", "BSE_FNO"):
        return Segment.EQUITY_FNO
    return Segment.EQUITY_CASH


def _parse_dhan_timestamp(raw: str) -> datetime:
    s = (raw or "").strip()
    if not s:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=_IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


class DhanTradingMixin:
    """Live order write/read methods mixed into DhanProvider."""

    def trade_capabilities(self: DhanProvider) -> TradeCapabilities:
        return TradeCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.EQUITY_CASH, Segment.EQUITY_FNO, Segment.COMMODITY],
            place=CapabilityDetail(
                supported=True,
                notes=[
                    "requires static-IP whitelisting on the Dhan account",
                    "variety=regular only; CO/BO/AMO not writable in this release",
                ],
            ),
            modify=CapabilityDetail(
                supported=True,
                notes=["requires static-IP whitelisting on the Dhan account"],
            ),
            cancel=CapabilityDetail(
                supported=True,
                notes=["requires static-IP whitelisting on the Dhan account"],
            ),
            get_open_orders=CapabilityDetail(supported=True, pagination="day_scoped"),
            get_order=CapabilityDetail(supported=True),
            get_trades=CapabilityDetail(supported=True, pagination="day_scoped"),
        )

    def _require_client_id(self: DhanProvider) -> str:
        client_id = self._settings.api_key
        if not client_id:
            raise AuthenticationError(
                self.provider_id,
                "Dhan order write requires api_key=<client_id> in ProviderSettings",
            )
        return client_id

    def _resolve_order_instrument(self: DhanProvider, order: OrderRequest) -> tuple[str, str, str]:
        """Return (securityId, exchangeSegment, canonical label)."""
        if order.instrument_id is not None:
            if not order.exchange:
                raise ProviderError(
                    self.provider_id,
                    "instrument_id requires exchange=... (e.g. 'MCX', 'NSE')",
                )
            segment = EXCHANGE_SEGMENT.get(order.exchange.upper(), order.exchange.upper())
            label = order.symbol or str(order.instrument_id)
            return str(order.instrument_id), segment, label
        if order.contract is not None:
            resolved = self._scrip.resolve_contract(order.contract)
            return resolved.security_id, resolved.exchange_segment, order.contract.canonical()
        if order.symbol:
            oc, label = self._coerce_contract(order.symbol, order.exchange, resolve=True)
            resolved = self._scrip.resolve_contract(oc)
            return resolved.security_id, resolved.exchange_segment, label
        raise ProviderError(
            self.provider_id,
            "OrderRequest requires 'instrument_id', 'contract', or 'symbol' (+exchange)",
        )

    def _build_dhan_order_body(
        self: DhanProvider,
        order: OrderRequest,
        client_id: str,
        security_id: str,
        segment: str,
    ) -> dict[str, Any]:
        if order.variety != Variety.REGULAR:
            raise UnsupportedCapabilityError(self.provider_id, f"variety={order.variety}")
        try:
            product = _PRODUCT_OUT[order.product]
        except KeyError as err:
            raise ProviderError(
                self.provider_id,
                f"product={order.product} not writable for dhan (this release)",
            ) from err
        try:
            validity = _VALIDITY_OUT[order.validity]
        except KeyError as err:
            raise ProviderError(
                self.provider_id,
                f"validity={order.validity} not writable for dhan (this release)",
            ) from err
        try:
            order_type = _ORDER_TYPE_OUT[order.order_type]
        except KeyError as err:
            raise ProviderError(
                self.provider_id,
                f"order_type={order.order_type} not writable for dhan (this release)",
            ) from err
        if order_type in ("STOP_LOSS", "STOP_LOSS_MARKET") and order.trigger_price is None:
            raise ProviderError(self.provider_id, f"{order_type} orders require trigger_price")

        body: dict[str, Any] = {
            "dhanClientId": client_id,
            "transactionType": order.side.value.upper(),
            "exchangeSegment": segment,
            "productType": product,
            "orderType": order_type,
            "validity": validity,
            "securityId": security_id,
            "quantity": int(order.quantity),
            "price": float(order.price) if order.price is not None else 0,
        }
        if order.trigger_price is not None:
            body["triggerPrice"] = float(order.trigger_price)
        if order.disclosed_quantity is not None:
            body["disclosedQuantity"] = int(order.disclosed_quantity)
        if order.client_order_id:
            body["correlationId"] = order.client_order_id[:30]
        return body

    def place_order(self: DhanProvider, order: OrderRequest) -> Order:
        client_id = self._require_client_id()
        security_id, segment, _label = self._resolve_order_instrument(order)
        body = self._build_dhan_order_body(order, client_id, security_id, segment)
        raw = self._http.post_json(
            f"{DHAN_API}/orders",
            provider=self.provider_id,
            body=body,
            headers=self._auth_headers(),
        )
        if not isinstance(raw, dict) or "orderId" not in raw:
            raise ProviderError(self.provider_id, f"Unexpected place-order payload: {raw!r}")
        return self.get_order(str(raw["orderId"]))

    def modify_order(
        self: DhanProvider,
        order_id: str,
        *,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        quantity: Decimal | None = None,
        validity: str | None = None,
    ) -> Order:
        client_id = self._require_client_id()
        body: dict[str, Any] = {"dhanClientId": client_id, "orderId": order_id}
        if price is not None:
            body["price"] = float(price)
        if trigger_price is not None:
            body["triggerPrice"] = float(trigger_price)
        if quantity is not None:
            body["quantity"] = int(quantity)
        if validity is not None:
            body["validity"] = _VALIDITY_OUT.get(validity, str(validity))
        self._http.put_json(
            f"{DHAN_API}/orders/{order_id}",
            provider=self.provider_id,
            body=body,
            headers=self._auth_headers(),
        )
        return self.get_order(order_id)

    def cancel_order(self: DhanProvider, order_id: str) -> Order:
        self._http.delete_json(
            f"{DHAN_API}/orders/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        return self.get_order(order_id)

    def get_open_orders(self: DhanProvider, *, symbol: str | None = None) -> list[Order]:
        raw = self._http.get_json(
            f"{DHAN_API}/orders",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        if not isinstance(raw, list):
            raise ProviderError(self.provider_id, "Unexpected orders payload")
        out: list[Order] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            order = _dhan_row_to_order(self.provider_id, row)
            if order.status not in (OrderStatus.OPEN, OrderStatus.PARTIAL):
                continue
            if symbol and symbol.upper() not in order.symbol.upper():
                continue
            out.append(order)
        return out

    def get_order(self: DhanProvider, order_id: str) -> Order:
        raw = self._http.get_json(
            f"{DHAN_API}/orders/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, f"Order {order_id} not found")
        return _dhan_row_to_order(self.provider_id, raw)

    def get_trades(self: DhanProvider, *, symbol: str | None = None) -> list[AccountFill]:
        raw = self._http.get_json(
            f"{DHAN_API}/trades",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        if not isinstance(raw, list):
            raise ProviderError(self.provider_id, "Unexpected trades payload")
        out: list[AccountFill] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            fill = _dhan_row_to_fill(self.provider_id, row)
            if symbol and symbol.upper() not in fill.symbol.upper():
                continue
            out.append(fill)
        return out


def _dhan_row_to_order(provider_id: str, row: dict[str, Any]) -> Order:
    oid = str(row.get("orderId", ""))
    seg_raw = str(row.get("exchangeSegment", ""))
    exchange = SEGMENT_TO_EXCHANGE.get(seg_raw.upper(), seg_raw)
    tsym = str(row.get("tradingSymbol", ""))
    sym = f"{exchange}:{tsym}" if exchange and tsym else tsym
    txn = str(row.get("transactionType", "BUY")).upper()
    side = OrderSide.BUY if txn == "BUY" else OrderSide.SELL
    status = _STATUS_IN.get(str(row.get("orderStatus", "")).upper(), OrderStatus.UNKNOWN)
    order_type = _ORDER_TYPE_IN.get(str(row.get("orderType", "")).upper(), OrderType.OTHER)
    product = _PRODUCT_IN.get(str(row.get("productType", "")).upper(), ProductType.OTHER)
    validity = _VALIDITY_IN.get(str(row.get("validity", "")).upper(), Validity.OTHER)
    created = _parse_dhan_timestamp(str(row.get("createTime", "")))
    updated = _parse_dhan_timestamp(str(row["updateTime"])) if row.get("updateTime") else None
    exch_ts = _parse_dhan_timestamp(str(row["exchangeTime"])) if row.get("exchangeTime") else None
    return Order(
        order_id=oid,
        client_order_id=row.get("correlationId") or None,
        exchange_order_id=None,
        side=side,
        order_type=order_type,
        product=product,
        validity=validity,
        variety=Variety.REGULAR,
        status=status,
        status_message=row.get("omsErrorDescription") or None,
        quantity=Decimal(str(row.get("quantity", 0))),
        filled_quantity=Decimal(str(row.get("filledQty", 0))),
        pending_quantity=_dec(row.get("remainingQuantity")),
        price=_dec(row.get("price")),
        trigger_price=_dec(row.get("triggerPrice")),
        average_price=_dec(row.get("averageTradedPrice")),
        created_at=created,
        updated_at=updated,
        exchange_timestamp=exch_ts,
        source=provider_id,
        segment=_bandl_segment(seg_raw),
        symbol=sym,
        symbol_native=tsym,
        instrument_id=str(row["securityId"]) if row.get("securityId") else None,
        currency="INR",
        provider_native=row,
        dedup_key=make_dedup_key(provider_id, "order", oid),
    )


def _dhan_row_to_fill(provider_id: str, row: dict[str, Any]) -> AccountFill:
    fid = str(row.get("exchangeTradeId") or row.get("orderId", ""))
    seg_raw = str(row.get("exchangeSegment", ""))
    exchange = SEGMENT_TO_EXCHANGE.get(seg_raw.upper(), seg_raw) if seg_raw else ""
    tsym = str(row.get("tradingSymbol", ""))
    sym = f"{exchange}:{tsym}" if exchange and tsym else tsym
    txn = str(row.get("transactionType", "BUY")).upper()
    side = OrderSide.BUY if txn == "BUY" else OrderSide.SELL
    qty = Decimal(str(row.get("tradedQuantity", 0)))
    price = Decimal(str(row.get("tradedPrice", 0)))
    executed = _parse_dhan_timestamp(str(row.get("exchangeTime") or row.get("createTime", "")))
    return AccountFill(
        fill_id=fid,
        order_id=str(row["orderId"]) if row.get("orderId") else None,
        side=side,
        quantity=qty,
        price=price,
        quote_quantity=qty * price,
        fee=None,
        executed_at=executed,
        source=provider_id,
        segment=_bandl_segment(seg_raw) if seg_raw else Segment.UNKNOWN,
        symbol=sym,
        symbol_native=tsym,
        instrument_id=str(row["securityId"]) if row.get("securityId") else None,
        currency="INR",
        provider_native=row,
        dedup_key=make_dedup_key(provider_id, "fill", fid),
    )
