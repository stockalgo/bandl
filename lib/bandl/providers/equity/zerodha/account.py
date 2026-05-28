"""Zerodha Kite account history (day-scoped orders/trades)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from bandl.account.pnl import compute_pnl_from_fills, reconcile_pnl
from bandl.core.account_filters import AccountFilters
from bandl.core.capabilities import AccountCapabilities, CapabilityDetail
from bandl.exceptions import ProviderError, UnsupportedCapabilityError
from bandl.models.account import AccountFill, AccountOrder, LedgerEntry, PnLProvenance, PnLRecord
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import (
    LedgerEntryType,
    OrderSide,
    PnLConfidence,
    PnLGranularity,
    PnLSourceType,
    Segment,
)
from bandl.providers.account_helpers import map_kite_order_type, map_kite_status, require_capability
from bandl.providers.equity.zerodha.common import (
    KITE_API,
    kite_unwrap,
)
from bandl.providers.equity.zerodha.common import (
    parse_kite_timestamp as _parse_kite_timestamp,
)

if TYPE_CHECKING:
    from bandl.providers.equity.zerodha.provider import ZerodhaProvider


def _kite_segment(exchange: str, product: str) -> str:
    ex = exchange.upper()
    if ex == "MCX":
        return Segment.COMMODITY
    if ex in ("NFO", "BFO", "CDS"):
        return Segment.EQUITY_FNO
    return Segment.EQUITY_CASH


def _canonical_symbol(exchange: str, tradingsymbol: str) -> str:
    return f"{exchange.upper()}:{tradingsymbol}"


class ZerodhaAccountMixin:
    """Account history methods mixed into ZerodhaProvider."""

    def account_capabilities(self: ZerodhaProvider) -> AccountCapabilities:
        return AccountCapabilities(
            provider_id=self.provider_id,
            segments=[
                Segment.EQUITY_CASH,
                Segment.EQUITY_FNO,
                Segment.COMMODITY,
            ],
            orders=CapabilityDetail(
                supported=True,
                max_history_days=1,
                pagination="day_scoped",
                notes=["GET /orders returns current trading session only"],
            ),
            fills=CapabilityDetail(
                supported=True,
                max_history_days=1,
                pagination="day_scoped",
                notes=["GET /trades returns current session executions (Kite 'trades')"],
            ),
            ledger=CapabilityDetail(
                supported=True,
                max_history_days=1,
                pagination="per_order",
                notes=["POST order.contract_note for charges on given order ids"],
            ),
            pnl_broker=CapabilityDetail(
                supported=True,
                max_history_days=1,
                pagination="snapshot",
                notes=["GET /portfolio/positions unrealized/realized fields (day snapshot)"],
            ),
            pnl_computed=CapabilityDetail(
                supported=True,
                notes=["FIFO from session fills when broker PnL incomplete"],
            ),
        )

    def get_orders(self: ZerodhaProvider, filters: AccountFilters) -> list[AccountOrder]:
        require_capability(
            self.provider_id,
            "orders",
            self.account_capabilities().orders.supported,
        )
        raw = self._http.get_json(
            f"{KITE_API}/orders",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list):
            raise ProviderError(self.provider_id, "Unexpected orders payload")
        out: list[AccountOrder] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            oid = str(row.get("order_id", ""))
            if not oid:
                continue
            exchange = str(row.get("exchange", "NSE"))
            tsym = str(row.get("tradingsymbol", ""))
            sym = _canonical_symbol(exchange, tsym)
            if filters.symbol and filters.symbol.upper() not in sym.upper():
                continue
            created = _parse_kite_timestamp(str(row.get("order_timestamp", "")))
            if filters.start and created < filters.start:
                continue
            if filters.end and created > filters.end:
                continue
            txn = str(row.get("transaction_type", "BUY")).upper()
            side = OrderSide.BUY if txn == "BUY" else OrderSide.SELL
            if filters.side and side != filters.side.lower():
                continue
            status = map_kite_status(str(row.get("status", "")))
            if filters.status and status != filters.status.lower():
                continue
            if filters.order_id and oid != filters.order_id:
                continue
            out.append(
                AccountOrder(
                    order_id=oid,
                    client_order_id=str(row["tag"]) if row.get("tag") else None,
                    side=side,
                    order_type=map_kite_order_type(str(row.get("order_type", ""))),
                    status=status,
                    quantity=Decimal(str(row.get("quantity", 0))),
                    filled_quantity=Decimal(str(row.get("filled_quantity", 0))),
                    limit_price=Decimal(str(row["price"])) if row.get("price") else None,
                    average_fill_price=Decimal(str(row["average_price"]))
                    if row.get("average_price")
                    else None,
                    created_at=created,
                    updated_at=_parse_kite_timestamp(str(row["exchange_update_timestamp"]))
                    if row.get("exchange_update_timestamp")
                    else None,
                    source=self.provider_id,
                    segment=_kite_segment(exchange, str(row.get("product", ""))),
                    symbol=sym,
                    symbol_native=tsym,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(self.provider_id, "order", oid),
                    metadata={"product": row.get("product"), "variety": row.get("variety")},
                ),
            )
        if filters.limit is not None:
            return out[: filters.limit]
        return out

    def get_fills(self: ZerodhaProvider, filters: AccountFilters) -> list[AccountFill]:
        require_capability(
            self.provider_id,
            "fills",
            self.account_capabilities().fills.supported,
        )
        raw = self._http.get_json(
            f"{KITE_API}/trades",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list):
            raise ProviderError(self.provider_id, "Unexpected trades payload")
        out: list[AccountFill] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            fid = str(row.get("trade_id", ""))
            if not fid:
                continue
            exchange = str(row.get("exchange", "NSE"))
            tsym = str(row.get("tradingsymbol", ""))
            sym = _canonical_symbol(exchange, tsym)
            if filters.symbol and filters.symbol.upper() not in sym.upper():
                continue
            executed = _parse_kite_timestamp(str(row.get("fill_timestamp", "")))
            if filters.start and executed < filters.start:
                continue
            if filters.end and executed > filters.end:
                continue
            txn = str(row.get("transaction_type", "BUY")).upper()
            side = OrderSide.BUY if txn == "BUY" else OrderSide.SELL
            if filters.side and side != filters.side.lower():
                continue
            oid = str(row.get("order_id", ""))
            if filters.order_id and oid != filters.order_id:
                continue
            qty = Decimal(str(row.get("quantity", 0)))
            price = Decimal(str(row.get("average_price", row.get("price", 0))))
            out.append(
                AccountFill(
                    fill_id=fid,
                    order_id=oid or None,
                    side=side,
                    quantity=qty,
                    price=price,
                    quote_quantity=qty * price,
                    fee=None,
                    executed_at=executed,
                    source=self.provider_id,
                    segment=_kite_segment(exchange, str(row.get("product", ""))),
                    symbol=sym,
                    symbol_native=tsym,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(self.provider_id, "fill", fid),
                ),
            )
        if filters.limit is not None:
            return out[: filters.limit]
        return out

    def get_ledger_entries(self: ZerodhaProvider, filters: AccountFilters) -> list[LedgerEntry]:
        require_capability(
            self.provider_id,
            "ledger",
            self.account_capabilities().ledger.supported,
        )
        orders = self.get_orders(filters)
        if not orders:
            return []
        order_ids = [o.order_id for o in orders]
        if filters.order_id:
            order_ids = [filters.order_id]
        body = [{"order_id": oid} for oid in order_ids]
        raw = self._http.post_json(
            f"{KITE_API}/charges/orders",
            provider=self.provider_id,
            body=body,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list):
            raise ProviderError(self.provider_id, "Unexpected contract note payload")
        out: list[LedgerEntry] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            oid = str(row.get("order_id", ""))
            charges = row.get("charges", row)
            if isinstance(charges, dict):
                total = charges.get("total", charges.get("transaction_tax", 0))
            else:
                total = row.get("total", 0)
            amount = -abs(Decimal(str(total)))
            eid = f"charges:{oid}"
            posted = datetime.now(timezone.utc)
            out.append(
                LedgerEntry(
                    entry_id=eid,
                    entry_type=LedgerEntryType.FEE,
                    amount=amount,
                    related_order_id=oid,
                    description="Kite virtual contract note charges",
                    posted_at=posted,
                    source=self.provider_id,
                    segment=Segment.EQUITY_CASH,
                    symbol="",
                    symbol_native="",
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(self.provider_id, "ledger", eid),
                ),
            )
        return out

    def get_pnl(
        self: ZerodhaProvider,
        filters: AccountFilters,
        *,
        granularity: str = PnLGranularity.SYMBOL,
        prefer: str = "auto",
        reconcile: bool = False,
    ) -> list[PnLRecord]:
        caps = self.account_capabilities()
        broker_rows: list[PnLRecord] = []
        seg_filter = (filters.segment or "").lower() if filters.segment else ""

        if prefer in ("auto", "broker", "hybrid") and caps.pnl_broker.supported:
            now = datetime.now(timezone.utc)

            if not seg_filter or seg_filter in (Segment.EQUITY_CASH, Segment.EQUITY_CASH.value):
                hold_raw = self._http.get_json(
                    f"{KITE_API}/portfolio/holdings",
                    provider=self.provider_id,
                    headers=self._auth_headers(),
                )
                holdings = kite_unwrap(hold_raw, provider_id=self.provider_id)
                if isinstance(holdings, list):
                    for row in holdings:
                        if not isinstance(row, dict):
                            continue
                        tsym = str(row.get("tradingsymbol", ""))
                        sym = _canonical_symbol("NSE", tsym)
                        if filters.symbol and filters.symbol.upper() not in sym.upper():
                            continue
                        pnl_val = row.get("pnl")
                        broker_rows.append(
                            PnLRecord(
                                pnl_id=f"broker:holding:{sym}",
                                granularity=granularity,
                                total_pnl=Decimal(str(pnl_val)) if pnl_val is not None else None,
                                currency="INR",
                                symbol=sym,
                                as_of=now,
                                provenance=PnLProvenance(
                                    source_type=PnLSourceType.BROKER,
                                    includes_fees=False,
                                    confidence=PnLConfidence.MEDIUM,
                                    warnings=[
                                        "Holdings PnL is cumulative (not limited to date window); "
                                        "Kite has no historical trade API for past months",
                                    ],
                                ),
                                source=self.provider_id,
                                segment=Segment.EQUITY_CASH,
                                symbol_native=tsym,
                                provider_native=row,
                                dedup_key=make_dedup_key(self.provider_id, "pnl", f"holding:{sym}"),
                            ),
                        )

            if not seg_filter or seg_filter in (
                Segment.EQUITY_CASH,
                Segment.EQUITY_CASH.value,
                Segment.EQUITY_FNO,
                Segment.EQUITY_FNO.value,
                Segment.COMMODITY,
                Segment.COMMODITY.value,
            ):
                raw = self._http.get_json(
                    f"{KITE_API}/portfolio/positions",
                    provider=self.provider_id,
                    headers=self._auth_headers(),
                )
                payload = kite_unwrap(raw, provider_id=self.provider_id)
                if isinstance(payload, dict):
                    for book in ("net", "day"):
                        book_rows = payload.get(book, [])
                        if not isinstance(book_rows, list):
                            continue
                        for row in book_rows:
                            if not isinstance(row, dict):
                                continue
                            qty = Decimal(str(row.get("quantity", 0)))
                            if qty == 0 and book == "net":
                                continue
                            tsym = str(row.get("tradingsymbol", ""))
                            exchange = str(row.get("exchange", "NSE"))
                            seg = _kite_segment(exchange, str(row.get("product", "")))
                            if seg_filter and seg_filter != seg:
                                continue
                            sym = _canonical_symbol(exchange, tsym)
                            if filters.symbol and filters.symbol.upper() not in sym.upper():
                                continue
                            unreal = row.get("unrealised")
                            real = row.get("realised")
                            total = row.get("pnl")
                            broker_rows.append(
                                PnLRecord(
                                    pnl_id=f"broker:pos:{book}:{sym}",
                                    granularity=granularity,
                                    realized_pnl=Decimal(str(real)) if real is not None else None,
                                    unrealized_pnl=Decimal(str(unreal))
                                    if unreal is not None
                                    else None,
                                    total_pnl=Decimal(str(total)) if total is not None else None,
                                    currency="INR",
                                    symbol=sym,
                                    as_of=now,
                                    provenance=PnLProvenance(
                                        source_type=PnLSourceType.BROKER,
                                        includes_fees=False,
                                        confidence=PnLConfidence.MEDIUM,
                                        warnings=[
                                            f"Snapshot from /portfolio/positions ({book}); "
                                            "session/day scope — not full calendar-month history",
                                        ],
                                    ),
                                    source=self.provider_id,
                                    segment=seg,
                                    symbol_native=tsym,
                                    provider_native=row,
                                    dedup_key=make_dedup_key(
                                        self.provider_id,
                                        "pnl",
                                        f"broker:{book}:{sym}",
                                    ),
                                ),
                            )

        computed_rows: list[PnLRecord] = []
        if prefer in ("auto", "computed", "hybrid") and caps.pnl_computed.supported:
            fills = self.get_fills(filters)
            ledger = []
            try:
                ledger = self.get_ledger_entries(filters)
            except UnsupportedCapabilityError:
                pass
            computed_rows = compute_pnl_from_fills(
                fills,
                ledger=ledger,
                source=self.provider_id,
                granularity=granularity,
                warnings=["Session-limited fills; historical PnL may be incomplete"],
            )

        if broker_rows and computed_rows and reconcile:
            merged: list[PnLRecord] = []
            comp_by_sym = {r.symbol: r for r in computed_rows}
            for br in broker_rows:
                cr = comp_by_sym.get(br.symbol)
                merged.append(reconcile_pnl(br, cr) if cr else br)
            return merged
        if prefer == "broker" and broker_rows:
            return broker_rows
        if prefer == "computed" and computed_rows:
            return computed_rows
        if broker_rows:
            return broker_rows
        if computed_rows:
            return computed_rows
        return []
