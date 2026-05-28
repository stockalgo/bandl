"""Deprecated: import from ``bandl`` instead of ``bandl.v2``."""

from __future__ import annotations

import warnings

warnings.warn(
    "bandl.v2 is deprecated; use `from bandl import Bandl` instead",
    DeprecationWarning,
    stacklevel=2,
)

from bandl import (  # noqa: E402
    OHLCV,
    AccountFill,
    AccountOrder,
    AuthenticationError,
    Bandl,
    BandlConfig,
    BandlError,
    ConfigurationError,
    DataNotAvailableError,
    GeoRestrictionError,
    Interval,
    LedgerEntry,
    MarketTrade,  # noqa: E402
    PnLProvenance,
    PnLRecord,
    ProviderError,
    ProviderSettings,
    RateLimitError,
    SymbolInfo,
    SymbolNotFoundError,
    Trade,
    UnsupportedCapabilityError,
)

__all__ = [
    "Bandl",
    "BandlConfig",
    "ProviderSettings",
    "OHLCV",
    "SymbolInfo",
    "Interval",
    "MarketTrade",
    "Trade",
    "AccountOrder",
    "AccountFill",
    "LedgerEntry",
    "PnLRecord",
    "PnLProvenance",
    "BandlError",
    "ProviderError",
    "SymbolNotFoundError",
    "AuthenticationError",
    "RateLimitError",
    "DataNotAvailableError",
    "GeoRestrictionError",
    "ConfigurationError",
    "UnsupportedCapabilityError",
]
