"""PnL computation tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from bandl.account.pnl import compute_pnl_from_fills, reconcile_pnl
from bandl.models.account import AccountFill, PnLProvenance, PnLRecord
from bandl.models.account.types import PnLGranularity, PnLSourceType, Segment


def _fill(side: str, qty: str, price: str, ts: int) -> AccountFill:
    executed = datetime.fromtimestamp(ts, tz=timezone.utc)
    return AccountFill(
        fill_id=f"{side}-{ts}",
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        executed_at=executed,
        source="test",
        segment=Segment.SPOT_CRYPTO,
        symbol="BTCINR",
        symbol_native="BTCINR",
        currency="INR",
        provider_native={},
        dedup_key=f"test:fill:{side}-{ts}",
    )


def test_fifo_realized_on_sell() -> None:
    fills = [
        _fill("buy", "1", "100", 1),
        _fill("sell", "1", "110", 2),
    ]
    records = compute_pnl_from_fills(
        fills,
        source="test",
        granularity=PnLGranularity.SYMBOL,
    )
    assert len(records) == 1
    assert records[0].realized_pnl == Decimal("10")
    assert records[0].provenance.source_type == PnLSourceType.COMPUTED


def test_reconcile_pnl_discrepancy() -> None:
    broker = PnLRecord(
        pnl_id="b1",
        granularity=PnLGranularity.SYMBOL,
        total_pnl=Decimal("100"),
        currency="INR",
        symbol="NSE:RELIANCE",
        as_of=datetime.now(timezone.utc),
        provenance=PnLProvenance(source_type=PnLSourceType.BROKER, includes_fees=False),
        source="zerodha",
        segment=Segment.EQUITY_CASH,
        symbol_native="RELIANCE",
        provider_native={},
        dedup_key="zerodha:pnl:b1",
    )
    computed = broker.model_copy(
        update={
            "total_pnl": Decimal("90"),
            "provenance": PnLProvenance(source_type=PnLSourceType.COMPUTED, includes_fees=True),
        },
    )
    merged = reconcile_pnl(broker, computed)
    assert merged.provenance.discrepancy == Decimal("10")
