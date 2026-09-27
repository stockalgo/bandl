"""Zerodha Kite live trading (regular-variety orders only in this release)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.account_filters import AccountFilters
from bandl.core.capabilities import CapabilityDetail, TradeCapabilities
from bandl.core.http import _redact_dict, _safe_diagnostic
from bandl.core.resolver import resolve_symbol
from bandl.exceptions import (
    InvalidOrderError,
    ProviderError,
    SymbolNotFoundError,
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
from bandl.providers.equity.zerodha.account import _canonical_symbol, _kite_segment
from bandl.providers.equity.zerodha.common import KITE_API, kite_unwrap
from bandl.providers.equity.zerodha.common import parse_kite_timestamp as _parse_kite_timestamp
from bandl.trade.validation import (
    extract_broker_order_id,
    resolve_account_binding,
    validate_broker_order_request,
    validate_order_modification,
    verify_account_binding,
)

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
    "TRIGGER PENDING": OrderStatus.TRIGGER_PENDING,
    "OPEN PENDING": OrderStatus.OPEN,
    "VALIDATION PENDING": OrderStatus.OPEN,
    "MODIFY PENDING": OrderStatus.MODIFY_PENDING,
    "MODIFY VALIDATION PENDING": OrderStatus.MODIFY_PENDING,
    "CANCEL PENDING": OrderStatus.CANCEL_PENDING,
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
            get_open_orders=CapabilityDetail(
                supported=True,
                pagination="day_scoped",
                notes=["current trading day open order book"],
            ),
            get_orders=CapabilityDetail(
                supported=True,
                pagination="day_scoped",
                notes=[
                    "current trading day session orders only; "
                    "historical days not available via this endpoint"
                ],
            ),
            get_order=CapabilityDetail(
                supported=True,
                notes=["current trading day single order state"],
            ),
            get_order_history=CapabilityDetail(
                supported=True,
                notes=["intraday order modification and lifecycle trail for current day"],
            ),
            get_trades=CapabilityDetail(
                supported=True,
                pagination="day_scoped",
                notes=["current trading day executions only"],
            ),
            idempotency=CapabilityDetail(
                supported=False,
                notes=[
                    "tag is correlation-only, max 20 chars; "
                    "Zerodha does not enforce broker-side idempotency"
                ],
            ),
            order_types=[OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT],
            products=[
                ProductType.DELIVERY,
                ProductType.INTRADAY,
                ProductType.NORMAL,
                ProductType.MTF,
            ],
            validities=[Validity.DAY, Validity.IOC],
            varieties=[Variety.REGULAR],
        )

    def _resolve_order_instrument(
        self: ZerodhaProvider, order: OrderRequest
    ) -> tuple[str, str, dict[str, Any] | None]:
        # deferred: provider.py imports this mixin, so a top-level import here would cycle.
        from bandl.models.market.contract import OptionContract
        from bandl.providers.equity.zerodha.provider import _normalize_kite_exchange
        from bandl.trade.validation import validate_lot_size, validate_tick_size

        if order.contract is not None:
            if order.exchange and order.exchange.upper() != order.contract.exchange.upper():
                raise InvalidOrderError(
                    self.provider_id,
                    f"Conflicting order exchange '{order.exchange}' and contract exchange "
                    f"'{order.contract.exchange}'",
                )
            ex = _normalize_kite_exchange(order.exchange or order.contract.exchange)
            if isinstance(order.contract, OptionContract):
                self.load_instruments(ex)
                rows = self._instrument_cache.get(ex, [])
                oc = order.contract
                opt_str = oc.option_type.value.upper()
                strike_str = str(oc.strike)
                matches: list[dict[str, str]] = []
                for r in rows:
                    if r.get("instrument_type", "").upper() != opt_str:
                        continue
                    # Match strike
                    r_strike = r.get("strike", "").strip()
                    try:
                        if Decimal(r_strike) != oc.strike:
                            continue
                    except Exception:
                        continue
                    # Match expiry
                    r_exp = r.get("expiry", "").strip()
                    exp_date = None
                    if r_exp:
                        try:
                            exp_date = datetime.strptime(r_exp, "%Y-%m-%d").date()
                        except ValueError:
                            pass
                    if oc.expiry is not None and exp_date != oc.expiry:
                        continue
                    # Match name / tradingsymbol underlying prefix
                    r_name = r.get("name", "").strip().upper()
                    r_ts = r.get("tradingsymbol", "").strip().upper()
                    und = oc.underlying.strip().upper()
                    if r_name == und or r_ts.startswith(und):
                        matches.append(r)

                if not matches:
                    raise SymbolNotFoundError(
                        f"No Zerodha {ex} option found matching contract {oc.canonical()} "
                        f"(strike={strike_str}, expiry={oc.expiry})"
                    )
                if len(matches) > 1:
                    raise InvalidOrderError(
                        self.provider_id,
                        f"Ambiguous instrument match for {oc.canonical()} in Zerodha {ex}: "
                        f"found {len(matches)} matching instruments. Cannot resolve safely.",
                    )
                matched_row = matches[0]
                tsym = matched_row["tradingsymbol"]
                lot_size = None
                tick_size = None
                try:
                    if matched_row.get("lot_size"):
                        lot_size = Decimal(matched_row["lot_size"])
                except Exception:
                    pass
                try:
                    if matched_row.get("tick_size"):
                        tick_size = Decimal(matched_row["tick_size"])
                except Exception:
                    pass

                validate_lot_size(self.provider_id, order.quantity, lot_size)
                validate_tick_size(self.provider_id, order.price, tick_size, "price")
                validate_tick_size(
                    self.provider_id, order.trigger_price, tick_size, "trigger_price"
                )

                meta = {
                    "source": "kite_instruments_csv",
                    "exchange": ex,
                    "tradingsymbol": tsym,
                    "lot_size": lot_size,
                    "tick_size": tick_size,
                }
                return tsym, ex, meta

            return order.contract.canonical(), ex, None

        if order.instrument_id is not None:
            raise InvalidOrderError(
                self.provider_id,
                "Zerodha order placement needs 'symbol' or 'contract' (tradingsymbol), "
                "not instrument_id",
            )
        if not order.symbol:
            raise InvalidOrderError(
                self.provider_id, "OrderRequest requires 'symbol' or 'contract'"
            )
        ex = _normalize_kite_exchange(order.exchange or "NSE")
        rs = resolve_symbol(order.symbol)
        ts = self._pick_tradingsymbol(rs, tradingsymbol=None)

        # Check if instruments dump is cached for ex to validate tick_size and lot_size
        lot_size = None
        tick_size = None
        if ex in self._instrument_cache:
            for r in self._instrument_cache[ex]:
                if r.get("tradingsymbol") == ts:
                    try:
                        if r.get("lot_size"):
                            lot_size = Decimal(r["lot_size"])
                    except Exception:
                        pass
                    try:
                        if r.get("tick_size"):
                            tick_size = Decimal(r["tick_size"])
                    except Exception:
                        pass
                    break

        validate_lot_size(self.provider_id, order.quantity, lot_size)
        validate_tick_size(self.provider_id, order.price, tick_size, "price")
        validate_tick_size(self.provider_id, order.trigger_price, tick_size, "trigger_price")

        meta = {
            "source": "symbol_resolved",
            "exchange": ex,
            "tradingsymbol": ts,
            "lot_size": lot_size,
            "tick_size": tick_size,
        }
        return ts, ex, meta

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
            raise InvalidOrderError(
                self.provider_id,
                f"product={order.product} not writable for zerodha (this release)",
            ) from err
        try:
            validity = _VALIDITY_OUT[order.validity]
        except KeyError as err:
            raise InvalidOrderError(
                self.provider_id,
                f"validity={order.validity} not writable for zerodha (this release)",
            ) from err
        try:
            order_type = _ORDER_TYPE_OUT[order.order_type]
        except KeyError as err:
            raise InvalidOrderError(
                self.provider_id,
                f"order_type={order.order_type} not writable for zerodha (this release)",
            ) from err

        if order.quantity % 1 != 0:
            raise InvalidOrderError(
                self.provider_id,
                f"Zerodha requires integer share/lot quantity, got {order.quantity}",
            )

        if order_type in ("LIMIT", "SL") and order.price is None:
            raise InvalidOrderError(self.provider_id, f"{order_type} orders require price")
        if order_type in ("SL", "SL-M") and order.trigger_price is None:
            raise InvalidOrderError(self.provider_id, f"{order_type} orders require trigger_price")

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
            if order.disclosed_quantity % 1 != 0:
                raise InvalidOrderError(
                    self.provider_id,
                    f"Zerodha requires integer disclosed_quantity, got {order.disclosed_quantity}",
                )
            body["disclosed_quantity"] = str(int(order.disclosed_quantity))
        if order.client_order_id:
            if len(order.client_order_id) > 20:
                raise InvalidOrderError(
                    self.provider_id,
                    "Zerodha tag (client_order_id) length cannot exceed 20 characters, "
                    f"got {len(order.client_order_id)}",
                )
            body["tag"] = order.client_order_id
        return body

    def place_order_ack(
        self: ZerodhaProvider, order: OrderRequest, *, account_id: str | None = None
    ) -> OrderAcknowledgement:
        effective_account_id = resolve_account_binding(
            self, account_id=account_id, order_account_id=order.account_id
        )
        validate_broker_order_request(self.provider_id, order)
        tradingsymbol, exchange, _meta = self._resolve_order_instrument(order)
        body = self._build_kite_order_body(order, tradingsymbol, exchange)
        ctx = {
            "operation": "place",
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "account_id": effective_account_id,
            "client_order_id": order.client_order_id,
        }
        raw = self._http.post_mutation(
            f"{KITE_API}/orders/regular",
            provider=self.provider_id,
            body=body,
            encoding="form",
            headers=self._auth_headers(),
            context=ctx,
        )
        data = kite_unwrap(raw, provider_id=self.provider_id, context=ctx)
        if not isinstance(data, dict):
            raise UncertainOutcomeError(
                self.provider_id,
                f"Malformed response payload after order dispatch: {_safe_diagnostic(data)}",
                operation="place",
                client_order_id=order.client_order_id,
                request_context=ctx,
            )
        oid = extract_broker_order_id(data.get("order_id"))
        if not oid:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Missing or empty order_id in place order response: {_safe_diagnostic(data)}",
                operation="place",
                client_order_id=order.client_order_id,
                request_context=ctx,
            )
        return OrderAcknowledgement(
            operation="place",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=oid,
            client_order_id=order.client_order_id,
            status=None,
            received_at=datetime.now(timezone.utc),
            provider_native=_redact_dict(data),
        )

    def place_order(
        self: ZerodhaProvider, order: OrderRequest, *, account_id: str | None = None
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
                f"Order was accepted by Zerodha with ID {ack.order_id}, "
                f"but status retrieval failed: {err}",
                operation="place",
                order_id=ack.order_id,
                client_order_id=order.client_order_id,
                request_context={"account_id": effective_account_id},
            ) from err

    def modify_order_ack(
        self: ZerodhaProvider,
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
        body: dict[str, Any] = {}
        if price is not None:
            body["price"] = str(price)
        if trigger_price is not None:
            body["trigger_price"] = str(trigger_price)
        if quantity is not None:
            body["quantity"] = str(int(quantity))
        if validity is not None:
            body["validity"] = _VALIDITY_OUT.get(validity, str(validity))
        ctx = {"operation": "modify", "order_id": order_id, "account_id": account_id}
        raw = self._http.put_mutation(
            f"{KITE_API}/orders/regular/{order_id}",
            provider=self.provider_id,
            body=body,
            encoding="form",
            headers=self._auth_headers(),
            context=ctx,
        )
        data = kite_unwrap(raw, provider_id=self.provider_id, context=ctx)
        if not isinstance(data, dict):
            raise UncertainOutcomeError(
                self.provider_id,
                f"Malformed response payload after order modification: {_safe_diagnostic(data)}",
                operation="modify",
                order_id=order_id,
                request_context=ctx,
            )
        oid = extract_broker_order_id(data.get("order_id"))
        if not oid:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Missing or empty order_id in modify order response: {_safe_diagnostic(data)}",
                operation="modify",
                order_id=order_id,
                request_context=ctx,
            )
        return OrderAcknowledgement(
            operation="modify",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=oid,
            status=None,
            received_at=datetime.now(timezone.utc),
            provider_native=_redact_dict(data),
        )

    def modify_order(
        self: ZerodhaProvider,
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
        self: ZerodhaProvider, order_id: str, *, account_id: str | None = None
    ) -> OrderAcknowledgement:
        verify_account_binding(self, account_id)
        ctx = {"operation": "cancel", "order_id": order_id, "account_id": account_id}
        raw = self._http.delete_mutation(
            f"{KITE_API}/orders/regular/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
            context=ctx,
        )
        data = kite_unwrap(raw, provider_id=self.provider_id, context=ctx)
        if not isinstance(data, dict):
            raise UncertainOutcomeError(
                self.provider_id,
                f"Malformed response payload after order cancellation: {_safe_diagnostic(data)}",
                operation="cancel",
                order_id=order_id,
                request_context=ctx,
            )
        oid = extract_broker_order_id(data.get("order_id"))
        if not oid:
            raise UncertainOutcomeError(
                self.provider_id,
                f"Missing or empty order_id in cancel order response: {_safe_diagnostic(data)}",
                operation="cancel",
                order_id=order_id,
                request_context=ctx,
            )
        return OrderAcknowledgement(
            operation="cancel",
            provider_id=self.provider_id,
            account_id=self.bound_account_id,
            order_id=oid,
            status=None,
            received_at=datetime.now(timezone.utc),
            provider_native=_redact_dict(data),
        )

    def cancel_order(
        self: ZerodhaProvider, order_id: str, *, account_id: str | None = None
    ) -> Order:
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
        self: ZerodhaProvider,
        *,
        symbol: str | None = None,
        account_id: str | None = None,
    ) -> list[Order]:
        verify_account_binding(self, account_id)
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
            order = _kite_row_to_order(self.provider_id, row, account_id=self.bound_account_id)
            if order.status not in (
                OrderStatus.OPEN,
                OrderStatus.PARTIAL,
                OrderStatus.TRIGGER_PENDING,
                OrderStatus.MODIFY_PENDING,
                OrderStatus.CANCEL_PENDING,
            ):
                continue
            if symbol and symbol.upper() not in order.symbol.upper():
                continue
            out.append(order)
        return out

    def get_trading_orders(
        self: ZerodhaProvider,
        *,
        symbol: str | None = None,
        account_id: str | None = None,
    ) -> list[Order]:
        verify_account_binding(self, account_id)
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
            order = _kite_row_to_order(self.provider_id, row, account_id=self.bound_account_id)
            if symbol and symbol.upper() not in order.symbol.upper():
                continue
            out.append(order)
        return out

    get_orders = get_trading_orders

    def get_order(self: ZerodhaProvider, order_id: str, *, account_id: str | None = None) -> Order:
        verify_account_binding(self, account_id)
        raw = self._http.get_json(
            f"{KITE_API}/orders/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list) or not payload:
            raise ProviderError(self.provider_id, f"Order {order_id} not found")
        return _kite_row_to_order(self.provider_id, payload[-1], account_id=self.bound_account_id)

    def get_order_history(
        self: ZerodhaProvider, order_id: str, *, account_id: str | None = None
    ) -> list[Order]:
        verify_account_binding(self, account_id)
        raw = self._http.get_json(
            f"{KITE_API}/orders/{order_id}",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list) or not payload:
            raise ProviderError(self.provider_id, f"Order {order_id} not found")
        return [
            _kite_row_to_order(self.provider_id, row, account_id=self.bound_account_id)
            for row in payload
            if isinstance(row, dict)
        ]

    def get_trades(
        self: ZerodhaProvider,
        *,
        symbol: str | None = None,
        account_id: str | None = None,
    ) -> list[AccountFill]:
        verify_account_binding(self, account_id)
        return self.get_fills(AccountFilters(symbol=symbol))


def _kite_row_to_order(
    provider_id: str, row: dict[str, Any], account_id: str | None = None
) -> Order:
    oid = str(row.get("order_id", ""))
    exchange = str(row.get("exchange", "NSE"))
    tsym = str(row.get("tradingsymbol", ""))
    sym = _canonical_symbol(exchange, tsym)
    txn = str(row.get("transaction_type", "BUY")).upper()
    side = OrderSide.BUY if txn == "BUY" else OrderSide.SELL
    raw_st = str(row.get("status", "")).upper()
    status = _STATUS_IN.get(raw_st, OrderStatus.UNKNOWN)
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
    cancelled_qty = (
        Decimal(str(row["cancelled_quantity"]))
        if row.get("cancelled_quantity") is not None
        else None
    )
    qty = Decimal(str(row.get("quantity", 0)))
    filled_qty = Decimal(str(row.get("filled_quantity", 0)))
    pending_qty = (
        Decimal(str(row["pending_quantity"])) if row.get("pending_quantity") is not None else None
    )
    if status == OrderStatus.OPEN and filled_qty > 0 and (pending_qty is None or pending_qty > 0):
        status = OrderStatus.PARTIAL
    return Order(
        order_id=oid,
        client_order_id=str(row["tag"]) if row.get("tag") else None,
        exchange_order_id=str(row["exchange_order_id"]) if row.get("exchange_order_id") else None,
        account_id=account_id,
        side=side,
        order_type=order_type,
        product=product,
        validity=validity,
        variety=variety,
        status=status,
        raw_status=row.get("status"),
        status_message=row.get("status_message") or None,
        quantity=qty,
        filled_quantity=filled_qty,
        pending_quantity=pending_qty,
        cancelled_quantity=cancelled_qty,
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
        dedup_key=make_dedup_key(provider_id, "order", oid, account_id=account_id),
    )
