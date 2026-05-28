#!/usr/bin/env python3
"""Top 10 futures gainers and losers (rolling 24h) for Binance or CoinDCX."""

from __future__ import annotations

import argparse
import time

from bandl import Bandl
from bandl.models.market.types import AssetType


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("binance", "coindcx"),
        default="binance",
        help="Crypto futures provider (default: binance)",
    )
    args = parser.parse_args()

    client = Bandl()
    t0 = time.perf_counter()
    print(f"Fetching {args.source} futures 24hr tickers...")
    tickers = client.crypto.get_24hr_tickers(
        source=args.source,
        asset_type=AssetType.CRYPTO_PERP,
    )
    print(f"Got {len(tickers)} tickers in {time.perf_counter() - t0:.2f}s\n")

    rows: list[tuple[str, float, str]] = []
    for t in tickers:
        if t.change_24h is None:
            continue
        rows.append((t.symbol, float(t.change_24h), str(t.last_price)))

    rows.sort(key=lambda x: x[1], reverse=True)
    gainers = rows[:10]
    losers = sorted(rows, key=lambda x: x[1])[:10]

    print("Top 10 gainers (24h % change)")
    print(f"{'Symbol':<16} {'24h %':>10} {'Last price':>16}")
    print("-" * 44)
    for sym, pct, price in gainers:
        print(f"{sym:<16} {pct:>+9.2f}% {price:>16}")

    print("\nTop 10 losers (24h % change)")
    print(f"{'Symbol':<16} {'24h %':>10} {'Last price':>16}")
    print("-" * 44)
    for sym, pct, price in losers:
        print(f"{sym:<16} {pct:>+9.2f}% {price:>16}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
