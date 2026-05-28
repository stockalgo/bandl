"""Client-side PnL computation from fills and ledger fees (FIFO)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from bandl.models.account import AccountFill, LedgerEntry, PnLProvenance, PnLRecord
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import PnLConfidence, PnLGranularity, PnLSourceType, Segment


def _fifo_realized_for_symbol(
    fills: list[AccountFill],
    fees_by_fill: dict[str, Decimal],
) -> list[tuple[AccountFill, Decimal]]:
    """Return (fill, realized_pnl) for sells that close long lots (simplified FIFO)."""
    sorted_fills = sorted(fills, key=lambda f: f.executed_at)
    lots: list[tuple[Decimal, Decimal]] = []  # (qty, cost_per_unit)
    results: list[tuple[AccountFill, Decimal]] = []

    for fill in sorted_fills:
        qty = fill.quantity
        price = fill.price
        fee = fees_by_fill.get(fill.fill_id, Decimal("0"))
        if fill.side == "buy":
            cost = price * qty + fee
            lots.append((qty, cost / qty if qty else Decimal("0")))
        elif fill.side == "sell":
            remaining = qty
            realized = Decimal("0")
            while remaining > 0 and lots:
                lot_qty, lot_cost = lots[0]
                take = min(remaining, lot_qty)
                realized += (price - lot_cost) * take
                remaining -= take
                new_lot_qty = lot_qty - take
                if new_lot_qty <= 0:
                    lots.pop(0)
                else:
                    lots[0] = (new_lot_qty, lot_cost)
            realized -= fee
            results.append((fill, realized))
    return results


def compute_pnl_from_fills(
    fills: list[AccountFill],
    ledger: list[LedgerEntry] | None = None,
    *,
    source: str,
    granularity: str = PnLGranularity.SYMBOL,
    warnings: list[str] | None = None,
) -> list[PnLRecord]:
    """Compute realized PnL using FIFO per (source, symbol)."""
    warns = list(warnings or [])
    fees_by_fill: dict[str, Decimal] = {}
    if ledger:
        for entry in ledger:
            if entry.related_fill_id and entry.entry_type in ("fee", "tax"):
                fees_by_fill[entry.related_fill_id] = fees_by_fill.get(
                    entry.related_fill_id,
                    Decimal("0"),
                ) + abs(entry.amount)

    by_symbol: dict[str, list[AccountFill]] = defaultdict(list)
    for fill in fills:
        by_symbol[fill.symbol].append(fill)

    now = datetime.now(timezone.utc)
    records: list[PnLRecord] = []

    if granularity == PnLGranularity.TRADE:
        for sym, sym_fills in by_symbol.items():
            for fill, realized in _fifo_realized_for_symbol(sym_fills, fees_by_fill):
                records.append(
                    PnLRecord(
                        pnl_id=f"computed:{fill.fill_id}",
                        granularity=PnLGranularity.TRADE,
                        realized_pnl=realized,
                        total_pnl=realized,
                        currency=fill.currency,
                        symbol=sym,
                        as_of=fill.executed_at,
                        provenance=PnLProvenance(
                            source_type=PnLSourceType.COMPUTED,
                            cost_basis_method="fifo",
                            includes_fees=True,
                            confidence=PnLConfidence.MEDIUM,
                            warnings=warns,
                        ),
                        source=source,
                        segment=fill.segment,
                        symbol_native=fill.symbol_native,
                        provider_native={"fill_id": fill.fill_id},
                        dedup_key=make_dedup_key(source, "pnl", f"trade:{fill.fill_id}"),
                    ),
                )
        return records

    for sym, sym_fills in by_symbol.items():
        trade_pnls = _fifo_realized_for_symbol(sym_fills, fees_by_fill)
        total_realized = sum((p for _, p in trade_pnls), Decimal("0"))
        last = sym_fills[-1] if sym_fills else None
        records.append(
            PnLRecord(
                pnl_id=f"computed:symbol:{sym}",
                granularity=PnLGranularity.SYMBOL,
                realized_pnl=total_realized,
                total_pnl=total_realized,
                currency=last.currency if last else "INR",
                symbol=sym,
                as_of=now,
                provenance=PnLProvenance(
                    source_type=PnLSourceType.COMPUTED,
                    cost_basis_method="fifo",
                    includes_fees=True,
                    confidence=PnLConfidence.MEDIUM,
                    warnings=warns,
                ),
                source=source,
                segment=last.segment if last else Segment.UNKNOWN,
                symbol_native=last.symbol_native if last else sym,
                provider_native={},
                dedup_key=make_dedup_key(source, "pnl", f"symbol:{sym}"),
            ),
        )

    if granularity == PnLGranularity.PORTFOLIO and records:
        currencies = {r.currency for r in records}
        if len(currencies) > 1:
            warns.append("Portfolio PnL not consolidated across currencies")
        total = sum((r.realized_pnl or Decimal("0") for r in records), Decimal("0"))
        records = [
            PnLRecord(
                pnl_id=f"computed:portfolio:{source}",
                granularity=PnLGranularity.PORTFOLIO,
                realized_pnl=total,
                total_pnl=total,
                currency=next(iter(currencies)) if currencies else "INR",
                as_of=now,
                provenance=PnLProvenance(
                    source_type=PnLSourceType.COMPUTED,
                    cost_basis_method="fifo",
                    includes_fees=True,
                    confidence=PnLConfidence.LOW if len(currencies) > 1 else PnLConfidence.MEDIUM,
                    warnings=warns,
                ),
                source=source,
                segment=Segment.UNKNOWN,
                symbol="*",
                symbol_native="*",
                provider_native={},
                dedup_key=make_dedup_key(source, "pnl", "portfolio"),
            ),
        ]

    return records


def reconcile_pnl(
    broker: PnLRecord,
    computed: PnLRecord,
) -> PnLRecord:
    """Attach discrepancy fields when both broker and computed values exist."""
    b_val = broker.total_pnl or broker.realized_pnl or broker.unrealized_pnl
    c_val = computed.total_pnl or computed.realized_pnl
    disc = None
    note = None
    if b_val is not None and c_val is not None:
        disc = abs(b_val - c_val)
        if disc > Decimal("0.01"):
            note = "Broker and computed PnL differ; broker value retained in totals"
    prov = broker.provenance.model_copy(
        update={
            "source_type": PnLSourceType.HYBRID,
            "broker_computed": b_val,
            "client_computed": c_val,
            "discrepancy": disc,
            "discrepancy_note": note,
        },
    )
    return broker.model_copy(update={"provenance": prov})
