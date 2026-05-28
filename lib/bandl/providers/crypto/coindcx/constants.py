"""CoinDCX API URLs, futures paths, and symbol pair helpers (no provider imports)."""

from __future__ import annotations

from bandl.models.market.types import Interval

COINDCX_API = "https://api.coindcx.com"
COINDCX_PUBLIC = "https://public.coindcx.com"

MAX_FUTURES_PAGE = 100  # API returns 422 above ~100 for futures list endpoints

FUTURES_CANDLESTICKS = f"{COINDCX_PUBLIC}/market_data/candlesticks"
FUTURES_CURRENT_PRICES_RT = f"{COINDCX_PUBLIC}/market_data/v3/current_prices/futures/rt"
FUTURES_TRADES = f"{COINDCX_API}/exchange/v1/derivatives/futures/trades"
FUTURES_ORDERS = f"{COINDCX_API}/exchange/v1/derivatives/futures/orders"
FUTURES_POSITIONS = f"{COINDCX_API}/exchange/v1/derivatives/futures/positions"
FUTURES_TRANSACTIONS = f"{COINDCX_API}/exchange/v1/derivatives/futures/positions/transactions"
FUTURES_ACTIVE_INSTRUMENTS = (
    f"{COINDCX_API}/exchange/v1/derivatives/futures/data/active_instruments"
)

# Verified against live API (docs list subset: 1, 5, 60, 1D).
INTERVAL_FUTURES_CANDLES: dict[Interval, str] = {
    Interval.M1: "1",
    Interval.M5: "5",
    Interval.M15: "15",
    Interval.M30: "30",
    Interval.H1: "60",
    Interval.H4: "4h",
    Interval.H8: "8h",
    Interval.D1: "1D",
    Interval.D3: "3d",
    Interval.W1: "1w",
    Interval.MO1: "1M",
}


def pair_to_canonical(pair: str) -> str:
    """``B-BTC_USDT`` → ``BTCUSDT``."""
    p = pair.strip().upper()
    if p.startswith("B-"):
        p = p[2:]
    if "_" in p:
        base, quote = p.split("_", 1)
        return f"{base}{quote}"
    return p


def canonical_to_coindcx_pair(base: str, quote: str) -> str:
    """``BTC``, ``USDT`` → ``B-BTC_USDT`` (spot and futures convention)."""
    return f"B-{base.upper()}_{quote.upper()}"
