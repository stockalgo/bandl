"""AccountFacet.get_pnl_summary — sum-safe rollup per symbol."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from bandl import Bandl
from bandl.models.account import PnLProvenance, PnLRecord
from bandl.models.account.types import PnLConfidence, PnLSourceType, Segment


def _row(
    pnl_id: str,
    *,
    symbol: str,
    scope,
    realized=None,
    unrealized=None,
    total=None,
    confidence=PnLConfidence.MEDIUM,
) -> PnLRecord:
    return PnLRecord(
        pnl_id=pnl_id,
        granularity="symbol",
        scope=scope,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=total,
        currency="INR",
        symbol=symbol,
        symbol_native=symbol.split(":")[-1],
        as_of=datetime.now(timezone.utc),
        provenance=PnLProvenance(source_type=PnLSourceType.BROKER, confidence=confidence),
        source="zerodha",
        segment=Segment.EQUITY_FNO,
        provider_native={},
        dedup_key=f"zerodha:pnl:{pnl_id}",
    )


def test_get_pnl_summary_sums_across_scopes_safely() -> None:
    client = Bandl()
    net_row = _row(
        "broker:pos:net:NFO:RELIANCE",
        symbol="NFO:RELIANCE",
        scope="net",
        realized=Decimal(100),
        unrealized=Decimal(-20),
        total=Decimal(80),
    )
    holding_row = _row(
        "broker:holding:NFO:RELIANCE",
        symbol="NFO:RELIANCE",
        scope="holding",
        total=Decimal(30),
        confidence=PnLConfidence.LOW,
    )
    client.account.get_pnl = MagicMock(return_value=[net_row, holding_row])

    summary = client.account.get_pnl_summary(source="zerodha")
    assert len(summary) == 1
    row = summary[0]
    assert row.symbol == "NFO:RELIANCE"
    assert row.realized_pnl == Decimal(100)
    assert row.unrealized_pnl == Decimal(-20)
    assert row.total_pnl == Decimal(110)  # 80 (net) + 30 (holding), never blended with day
    assert row.provenance.confidence == PnLConfidence.LOW  # worst-case of contributing rows
    assert "broker:pos:net:NFO:RELIANCE" in row.metadata["contributing_pnl_ids"]


def test_get_pnl_summary_handles_total_only_rows() -> None:
    client = Bandl()
    row = _row("broker:holding:NSE:INFY", symbol="NSE:INFY", scope="holding", total=Decimal(500))
    client.account.get_pnl = MagicMock(return_value=[row])

    summary = client.account.get_pnl_summary(source="zerodha")
    assert len(summary) == 1
    assert summary[0].total_pnl == Decimal(500)
    assert summary[0].realized_pnl is None
    assert summary[0].unrealized_pnl is None
