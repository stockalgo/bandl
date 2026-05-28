#!/usr/bin/env python3
"""May 2026 account fills and PnL — Zerodha (by segment) and CoinDCX (spot + USDT futures)."""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "lib"))

from bandl import Bandl, BandlConfig, ProviderSettings
from bandl.models.account.types import PnLGranularity, Segment

START = datetime(2026, 5, 1, tzinfo=timezone.utc)
END = datetime(2026, 6, 1, tzinfo=timezone.utc)

SEGMENT_LABELS = {
    Segment.EQUITY_CASH: "Equity (cash / holdings)",
    Segment.EQUITY_FNO: "F&O (NFO/BFO/CDS)",
    Segment.COMMODITY: "Commodity (MCX)",
    Segment.SPOT_CRYPTO: "CoinDCX spot",
    Segment.CRYPTO_FNO: "CoinDCX USDT futures",
    Segment.UNKNOWN: "Other",
}


def _load_env(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip("\"'")


def _money(x: Decimal | None) -> str:
    if x is None:
        return "—"
    return f"{x:,.2f}"


def _sum_pnl(rows: list) -> Decimal:
    total = Decimal("0")
    for r in rows:
        if r.total_pnl is not None:
            total += r.total_pnl
        else:
            total += (r.realized_pnl or Decimal("0")) + (r.unrealized_pnl or Decimal("0"))
    return total


def _print_segment_table(title: str, by_seg: dict[str, list]) -> Decimal:
    print(f"\n{title}")
    grand = Decimal("0")
    for seg_key in (
        Segment.EQUITY_CASH.value,
        Segment.EQUITY_FNO.value,
        Segment.COMMODITY.value,
        Segment.SPOT_CRYPTO.value,
        Segment.CRYPTO_FNO.value,
    ):
        rows = by_seg.get(seg_key, [])
        label = SEGMENT_LABELS.get(Segment(seg_key), seg_key)
        t = _sum_pnl(rows)
        grand += t
        print(f"  {label:28} {len(rows):4} rows   total PnL {_money(t)}")
    print(f"  {'Overall':28}        total PnL {_money(grand)}")
    return grand


def main() -> None:
    _load_env(os.path.join(_REPO_ROOT, ".env"))
    providers: dict[str, ProviderSettings] = {}
    if os.environ.get("ZERODHA_API_KEY") and os.environ.get("ZERODHA_ACCESS_TOKEN"):
        providers["zerodha"] = ProviderSettings(
            api_key=os.environ["ZERODHA_API_KEY"],
            access_token=os.environ["ZERODHA_ACCESS_TOKEN"],
        )
    if os.environ.get("COINDCX_API_KEY") and os.environ.get("COINDCX_API_SECRET"):
        providers["coindcx"] = ProviderSettings(
            api_key=os.environ["COINDCX_API_KEY"],
            api_secret=os.environ["COINDCX_API_SECRET"],
        )
    if not providers:
        print("Configure ZERODHA_* and/or COINDCX_* in .env")
        sys.exit(1)

    client = Bandl(BandlConfig(providers=providers))
    print(f"Window: {START.date()} → {END.date()} (UTC)\n")

    if "coindcx" in providers:
        print("=" * 60)
        print("CoinDCX")
        print("=" * 60)
        try:
            spot = client.account.get_fills(START, END, source="coindcx", segment="spot_crypto")
            fno = client.account.get_fills(START, END, source="coindcx", segment="crypto_fno")
            print(f"Spot fills: {len(spot)}   USDT futures fills: {len(fno)}")
            pnl = client.account.get_pnl(
                START,
                END,
                source="coindcx",
                granularity=PnLGranularity.PORTFOLIO,
                prefer="auto",
            )
            by_seg: dict[str, list] = defaultdict(list)
            for r in pnl:
                by_seg[str(r.segment)].append(r)
            _print_segment_table("PnL", by_seg)
        except Exception as e:
            print(f"Error: {e}")

    if "zerodha" in providers:
        print("\n" + "=" * 60)
        print("Zerodha")
        print("=" * 60)
        caps = client.account.capabilities("zerodha")
        print("API limits:", caps.fills.notes[0] if caps.fills.notes else "")
        try:
            fills = client.account.get_fills(START, END, source="zerodha")
            print(f"Session fills in window: {len(fills)}")
        except Exception as e:
            print(f"Fills: {e}")
        try:
            pnl = client.account.get_pnl(
                START,
                END,
                source="zerodha",
                prefer="broker",
                granularity=PnLGranularity.SYMBOL,
            )
            by_seg = defaultdict(list)
            holdings_extra = Decimal("0")
            for r in pnl:
                if "holding" in r.pnl_id:
                    holdings_extra += _sum_pnl([r])
                    continue
                by_seg[str(r.segment)].append(r)
            _print_segment_table("Positions PnL (session snapshot, not full May history)", by_seg)
            if holdings_extra != 0:
                print(f"  Holdings (lifetime, not May-only):     total PnL {_money(holdings_extra)}")
        except Exception as e:
            print(f"PnL: {e}")

    print("\nNote: Kite has no API for calendar-month trade history; CoinDCX futures use")
    print("  POST /derivatives/futures/trades + positions/transactions for USDT F&O.")


if __name__ == "__main__":
    main()
