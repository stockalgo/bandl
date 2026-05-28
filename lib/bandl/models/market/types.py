from __future__ import annotations

from enum import Enum


class AssetType(str, Enum):
    EQUITY = "equity"
    INDEX = "index"
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_PERP = "crypto_perp"
    CRYPTO_FUTURE = "crypto_future"
    COMMODITY = "commodity"
    FOREX = "forex"
    OPTION = "option"


class Interval(str, Enum):
    """Normalized candle intervals (provider adapters map to native strings)."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H6 = "6h"
    H8 = "8h"
    D1 = "1d"
    D3 = "3d"
    W1 = "1w"
    MO1 = "1M"
