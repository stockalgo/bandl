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
from bandl.core.http import _redact_dict, _redact_text, _safe_diagnostic
from bandl.exceptions import (
    AuthenticationError,
    InsufficientFundsError,
    InvalidOrderError,
    OrderRejectedError,
    ProviderError,
    UncertainOutcomeError,
    UnsupportedCapabilityError,
)
from bandl.models.account import AccountFill
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import OrderSide, OrderStatus, OrderType, Segment
from bandl.models.trading import (
    Order,
    OrderAcknowledgement,
    OrderRequest,
    ProductType,
    Validity,
    Variety,
)
from bandl.providers.dhan.common import DHAN_API, EXCHANGE_SEGMENT, SEGMENT_TO_EXCHANGE
from bandl.trade.validation import (
    extract_broker_order_id,
    resolve_account_binding,
    validate_broker_order_request,
    validate_order_modification,
    verify_account_binding,
)

if TYPE_CHECKING:
    from bandl.providers.dhan.provider import DhanProvider
    from bandl.providers.dhan.scrip import ResolvedInstrument

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
            get_open_orders=CapabilityDetail(
                supported=True,
                pagination="day_scoped",
                notes=["current trading day open orders"],
            ),
            get_orders=CapabilityDetail(
                supported=True,
                pagination="day_scoped",
                notes=[
                    "current trading day orders only; "
                    "historical days not available via this endpoint"
                ],
            ),
            get_order=CapabilityDetail(
                supported=True,
                notes=["current trading day single order state"],
            ),
            get_order_history=CapabilityDetail(
                supported=False,
                notes=[
                    "Dhan API does not offer an order lifecycle history endpoint; "
                    "use get_order for current state"
                ],
            ),
            get_trades=CapabilityDetail(
                supported=True,
                pagination="day_scoped",
                notes=["current trading day trades only"],
            ),
            idempotency=CapabilityDetail(
                supported=False,
                notes=[
                    "correlationId is correlation-only, max 30 chars; "
                    "Dhan does not enforce broker-side idempotency"
                ],
            ),
            order_types=[OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT],
            products=[
                ProductType.DELIVERY,
                ProductType.INTRADAY,
                ProductType.MARGIN,
                ProductType.MTF,
            ],
            validities=[Validity.DAY, Validity.IOC],
            varieties=[Variety.REGULAR],
        )

    def _require_client_id(self: DhanProvider) -> str:
        client_id = self._settings.api_key
        if not client_id:
            raise AuthenticationError(
                self.provider_id,
                "Dhan order write requires api_key=<client_id> in ProviderSettings",
            )
        return client_id

    def _resolve_order_instrument(
        self: DhanProvider, order: OrderRequest
    ) -> tuple[str, str, str, ResolvedInstrument | None]:
        """Return (securityId, exchangeSegment, canonical label, resolved_meta)."""
        from bandl.core.contracts import parse_option_symbol
        from bandl.models.market.contract import OptionContract
        from bandl.trade.validation import validate_lot_size, validate_tick_size

        resolved: ResolvedInstrument | None = None

        if order.instrument_id is not None:
            if not order.exchange:
                raise InvalidOrderError(
                    self.provider_id,
                    "instrument_id requires exchange=... (e.g. 'MCX', 'NSE')",
                )
            if (
                order.contract is not None
                and order.exchange.upper() != order.contract.exchange.upper()
            ):
                raise InvalidOrderError(
                    self.provider_id,
                    f"Conflicting order exchange '{order.exchange}' and contract exchange "
                    f"'{order.contract.exchange}'",
                )
            segment = EXCHANGE_SEGMENT.get(order.exchange.upper(), order.exchange.upper())
            label = order.symbol or str(order.instrument_id)
            return str(order.instrument_id), segment, label, None

        if order.contract is not None:
            if order.exchange and order.exchange.upper() != order.contract.exchange.upper():
                raise InvalidOrderError(
                    self.provider_id,
                    f"Conflicting order exchange '{order.exchange}' and contract exchange "
                    f"'{order.contract.exchange}'",
                )
            if isinstance(order.contract, OptionContract):
                resolved = self._scrip.resolve_contract(order.contract)
            else:
                raise InvalidOrderError(
                    self.provider_id,
                    f"Unsupported contract type: {type(order.contract)}",
                )
            validate_lot_size(self.provider_id, order.quantity, resolved.lot_size)
            validate_tick_size(self.provider_id, order.price, resolved.tick_size, "price")
            validate_tick_size(
                self.provider_id, order.trigger_price, resolved.tick_size, "trigger_price"
            )
            canonical = order.contract.canonical()
            return resolved.security_id, resolved.exchange_segment, canonical, resolved

        if order.symbol:
            ex = order.exchange
            if not ex:
                raise InvalidOrderError(
                    self.provider_id,
                    "OrderRequest with symbol requires exchange=... (e.g. 'MCX', 'NSE', 'NFO')",
                )
            # Check if this is an option symbol
            try:
                parsed = parse_option_symbol(order.symbol)
            except Exception:
                parsed = None

            if parsed is not None:
                eff_ex = ex or parsed.exchange
                resolved = self._scrip.resolve_option(
                    parsed.underlying,
                    eff_ex,
                    parsed.strike,
                    parsed.option_type.value,
                    year=parsed.year,
                    month=parsed.month,
                    disallow_ambiguous_month=True,
                )
                validate_lot_size(self.provider_id, order.quantity, resolved.lot_size)
                validate_tick_size(self.provider_id, order.price, resolved.tick_size, "price")
                validate_tick_size(
                    self.provider_id, order.trigger_price, resolved.tick_size, "trigger_price"
                )
                return resolved.security_id, resolved.exchange_segment, order.symbol, resolved

            # Plain equity symbol or other
            oc, label = self._coerce_contract(order.symbol, order.exchange, resolve=True)
            resolved = self._scrip.resolve_contract(oc)
            validate_lot_size(self.provider_id, order.quantity, resolved.lot_size)
            validate_tick_size(self.provider_id, order.price, resolved.tick_size, "price")
            validate_tick_size(
                self.provider_id, order.trigger_price, resolved.tick_size, "trigger_price"
            )
            return resolved.security_id, resolved.exchange_segment, label, resolved

        raise InvalidOrderError(
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
            raise InvalidOrderError(
                self.provider_id,
                f"product={order.product} not writable for dhan (this release)",
            ) from err
        try:
            validity = _VALIDITY_OUT[order.validity]
        except KeyError as err:
            raise InvalidOrderError(
                self.provider_id,
                f"validity={order.validity} not writable for dhan (this release)",
            ) from err
        try:
            order_type = _ORDER_TYPE_OUT[order.order_type]
        except KeyError as err:
            raise InvalidOrderError(
                self.provider_id,
                f"order_type={order.order_type} not writable for dhan (this release)",
            ) from err

        if order.quantity % 1 != 0:
            raise InvalidOrderError(
                self.provider_id,
                f"Dhan requires integer share/lot quantity, got {order.quantity}",
            )

        if order_type in ("LIMIT", "STOP_LOSS") and order.price is None:
            raise InvalidOrderError(self.provider_id, f"{order_type} orders require price")
        if order_type in ("STOP_LOSS", "STOP_LOSS_MARKET") and order.trigger_price is None:
            raise InvalidOrderError(self.provider_id, f"{order_type} orders require trigger_price")

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
            if order.disclosed_quantity % 1 != 0:
                raise InvalidOrderError(
                    self.provider_id,
                    f"Dhan requires integer disclosed_quantity, got {order.disclosed_quantity}",
                )
            body["disclosedQuantity"] = int(order.disclosed_quantity)
        if order.client_order_id:
            if len(order.client_order_id) > 30:
                raise InvalidOrderError(
                    self.provider_id,
                    "Dhan correlationId (client_order_id) length cannot exceed 30 characters, "
                    f"got {len(order.client_order_id)}",
                )
            body["correlationId"] = order.client_order_id
        return body

    def place_order_ack(
        self: DhanProvider, order: OrderRequest, *, account_id: str | None = None
    ) -> OrderAcknowledgement:
        effective_account_id = resolve_account_binding(
            self, account_id=account_id, order_account_id=order.account_id
        )
        validate_broker_order_request(self.provider_id, order)
        client_id = self._require_client_id()
        security_id, segment, _label, _meta = self._resolve_order_instrument(order)
        body = self._build_dhan_order_body(order, client_id, security_id, segment)
        ctx = {
            "operation": "place",
            "securityId": security_id,
            "exchangeSegment": segment,
            "account_id": effective_account_id,
            "client_order_id": order.client_order_id,
        }
        raw = self._http.post_mutation(
            f"{DHAN_API}/orders",
            provider=self.provider_id,
            body=body,
            encoding="json",
            headers=self._auth_headers(),
            context=ctx,
        )
        if not isinstance(raw, dict):
            raise UncertainOutcomeError(
                self.provider_id,
                f"Malformed response payload after order dispatch: {_safe_diagnostic(raw)}",
                operation="place",
                client_order_id=order.client_order_id,
                request_context=ctx,
            )
        if raw.get("orderStatus") == "REJECTED":
            remarks = _redact_text(str(raw.get("remarks") or "Order rejected by broker"))
            r_lower = remarks.lower()
            if "insufficient" in r_lower or "margin" in r_lower or "funds" in r_lower:
                raise InsufficientFundsError(self.provider_id, remarks)
            raise OrderRejectedError(
                self.provider_id,
                remarks,
                order_id=extract_broker_order_id(raw.get("orderId")),
                raw_status="REJECTED",
            )
        oid = extract_broker_order_id(raw.get("orderId"))
        if not oid:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Missing or empty orderId in place order response: {_safe_diagnostic(raw)}",
                operation="place",
                client_order_id=order.client_order_id,
                request_context=ctx,
            )
        native_status = str(raw["orderStatus"]) if raw.get("orderStatus") else None
        return OrderAcknowledgement(
            operation="place",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=oid,
            client_order_id=order.client_order_id,
            status=native_status,
            received_at=datetime.now(timezone.utc),
            provider_native=_redact_dict(raw),
        )

    def place_order(
        self: DhanProvider, order: OrderRequest, *, account_id: str | None = None
    ) -> Order:
        effective_account_id = resolve_account_binding(
            self, account_id=account_id, order_account_id=order.account_id
        )
        ack = self.place_order_ack(order, account_id=effective_account_id)
        if not ack.order_id:
            raise ProviderError(self.provider_id, "No order_id received in acknowledgement")
        try:
            return self.get_order(ack.order_id, account_id=effective_account_id)
        except Exception as err:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Order was accepted by Dhan with ID {ack.order_id}, "
                f"but status retrieval failed: {err}",
                operation="place",
                order_id=ack.order_id,
                client_order_id=order.client_order_id,
                request_context={"account_id": effective_account_id},
            ) from err

    def modify_order_ack(
        self: DhanProvider,
        order_id: str,
        *,
        account_id: str | None = None,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        quantity: Decimal | None = None,
        validity: str | None = None,
    ) -> OrderAcknowledgement:
        verify_account_binding(self, account_id)
        validate_order_modification(
            self.provider_id,
            price=price,
            trigger_price=trigger_price,
            quantity=quantity,
            validity=validity,
        )
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
        ctx = {"operation": "modify", "order_id": order_id, "account_id": account_id}
        raw = self._http.put_mutation(
            f"{DHAN_API}/orders/{order_id}",
            provider=self.provider_id,
            body=body,
            encoding="json",
            headers=self._auth_headers(),
            context=ctx,
        )
        if not isinstance(raw, dict):
            raise UncertainOutcomeError(
                self.provider_id,
                f"Malformed response payload after order modification: {_safe_diagnostic(raw)}",
                operation="modify",
                order_id=order_id,
                request_context=ctx,
            )
        if raw.get("orderStatus") == "REJECTED":
            remarks = _redact_text(
                str(raw.get("remarks") or "Order modification rejected by broker")
            )
            r_lower = remarks.lower()
            if "insufficient" in r_lower or "margin" in r_lower or "funds" in r_lower:
                raise InsufficientFundsError(self.provider_id, remarks)
            raise OrderRejectedError(
                self.provider_id,
                remarks,
                order_id=extract_broker_order_id(raw.get("orderId")) or order_id,
                raw_status="REJECTED",
            )
        oid = extract_broker_order_id(raw.get("orderId"))
        if not oid:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Missing or empty orderId in modify order response: {_safe_diagnostic(raw)}",
                operation="modify",
                order_id=order_id,
                request_context=ctx,
            )
        native_status = str(raw["orderStatus"]) if raw.get("orderStatus") else None
        return OrderAcknowledgement(
            operation="modify",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=oid,
            status=native_status,
            received_at=datetime.now(timezone.utc),
            provider_native=_redact_dict(raw),
        )

    def modify_order(
        self: DhanProvider,
        order_id: str,
        *,
        account_id: str | None = None,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        quantity: Decimal | None = None,
        validity: str | None = None,
    ) -> Order:
        verify_account_binding(self, account_id)
        validate_order_modification(
            self.provider_id,
            price=price,
            trigger_price=trigger_price,
            quantity=quantity,
            validity=validity,
        )
        ack = self.modify_order_ack(
            order_id,
            account_id=account_id,
            price=price,
            trigger_price=trigger_price,
            quantity=quantity,
            validity=validity,
        )
        try:
            return self.get_order(ack.order_id or order_id, account_id=account_id)
        except Exception as err:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Order modification was submitted for {order_id}, "
                f"but status retrieval failed: {err}",
                operation="modify",
                order_id=order_id,
                request_context={"account_id": account_id},
            ) from err

    def cancel_order_ack(
        self: DhanProvider, order_id: str, *, account_id: str | None = None
    ) -> OrderAcknowledgement:
        verify_account_binding(self, account_id)
        ctx = {"operation": "cancel", "order_id": order_id, "account_id": account_id}
        raw = self._http.delete_mutation(
            f"{DHAN_API}/orders/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
            context=ctx,
        )
        if not isinstance(raw, dict):
            raise UncertainOutcomeError(
                self.provider_id,
                f"Malformed response payload after order cancellation: {_safe_diagnostic(raw)}",
                operation="cancel",
                order_id=order_id,
                request_context=ctx,
            )
        if raw.get("orderStatus") == "REJECTED":
            remarks = _redact_text(
                str(raw.get("remarks") or "Order cancellation rejected by broker")
            )
            raise OrderRejectedError(
                self.provider_id,
                remarks,
                order_id=extract_broker_order_id(raw.get("orderId")) or order_id,
                raw_status="REJECTED",
            )
        oid = extract_broker_order_id(raw.get("orderId"))
        if not oid:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Missing or empty orderId in cancel order response: {_safe_diagnostic(raw)}",
                operation="cancel",
                order_id=order_id,
                request_context=ctx,
            )
        oid = str(oid).strip()
        native_status = str(raw["orderStatus"]) if raw.get("orderStatus") else None
        return OrderAcknowledgement(
            operation="cancel",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=oid,
            status=native_status,
            received_at=datetime.now(timezone.utc),
            provider_native=_redact_dict(raw),
        )

    def cancel_order(self: DhanProvider, order_id: str, *, account_id: str | None = None) -> Order:
        verify_account_binding(self, account_id)
        ack = self.cancel_order_ack(order_id, account_id=account_id)
        try:
            return self.get_order(ack.order_id or order_id, account_id=account_id)
        except Exception as err:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Order cancellation was submitted for {order_id}, "
                f"but status retrieval failed: {err}",
                operation="cancel",
                order_id=order_id,
                request_context={"account_id": account_id},
            ) from err

    def get_open_orders(
        self: DhanProvider,
        *,
        symbol: str | None = None,
        account_id: str | None = None,
    ) -> list[Order]:
        verify_account_binding(self, account_id)
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
            order = _dhan_row_to_order(self.provider_id, row, account_id=self.bound_account_id)
            if order.status not in (OrderStatus.OPEN, OrderStatus.PARTIAL):
                continue
            if symbol and symbol.upper() not in order.symbol.upper():
                continue
            out.append(order)
        return out

    def get_orders(
        self: DhanProvider,
        *,
        symbol: str | None = None,
        account_id: str | None = None,
    ) -> list[Order]:
        verify_account_binding(self, account_id)
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
            order = _dhan_row_to_order(self.provider_id, row, account_id=self.bound_account_id)
            if symbol and symbol.upper() not in order.symbol.upper():
                continue
            out.append(order)
        return out

    def get_order(self: DhanProvider, order_id: str, *, account_id: str | None = None) -> Order:
        verify_account_binding(self, account_id)
        raw = self._http.get_json(
            f"{DHAN_API}/orders/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, f"Order {order_id} not found")
        return _dhan_row_to_order(self.provider_id, raw, account_id=self.bound_account_id)

    def get_order_history(
        self: DhanProvider, order_id: str, *, account_id: str | None = None
    ) -> list[Order]:
        verify_account_binding(self, account_id)
        raise UnsupportedCapabilityError(self.provider_id, "order_history")

    def get_trades(
        self: DhanProvider,
        *,
        symbol: str | None = None,
        account_id: str | None = None,
    ) -> list[AccountFill]:
        verify_account_binding(self, account_id)
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
            fill = _dhan_row_to_fill(self.provider_id, row, account_id=self.bound_account_id)
            if symbol and symbol.upper() not in fill.symbol.upper():
                continue
            out.append(fill)
        return out


def _dhan_row_to_order(
    provider_id: str, row: dict[str, Any], account_id: str | None = None
) -> Order:
    oid = str(row.get("orderId", ""))
    seg_raw = str(row.get("exchangeSegment", ""))
    exchange = SEGMENT_TO_EXCHANGE.get(seg_raw.upper(), seg_raw)
    tsym = str(row.get("tradingSymbol", ""))
    sym = f"{exchange}:{tsym}" if exchange and tsym else tsym
    txn = str(row.get("transactionType", "BUY")).upper()
    side = OrderSide.BUY if txn == "BUY" else OrderSide.SELL
    raw_st = str(row.get("orderStatus", "")).upper()
    status = _STATUS_IN.get(raw_st, OrderStatus.UNKNOWN)
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
        account_id=account_id,
        side=side,
        order_type=order_type,
        product=product,
        validity=validity,
        variety=Variety.REGULAR,
        status=status,
        raw_status=row.get("orderStatus"),
        status_message=row.get("omsErrorDescription") or None,
        quantity=Decimal(str(row.get("quantity", 0))),
        filled_quantity=Decimal(str(row.get("filledQty", 0))),
        pending_quantity=_dec(row.get("remainingQuantity")),
        cancelled_quantity=None,
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
        dedup_key=make_dedup_key(provider_id, "order", oid, account_id=account_id),
    )


def _dhan_row_to_fill(
    provider_id: str, row: dict[str, Any], account_id: str | None = None
) -> AccountFill:
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
        account_id=account_id,
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
        dedup_key=make_dedup_key(provider_id, "fill", fid, account_id=account_id),
    )
