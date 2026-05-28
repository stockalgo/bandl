from __future__ import annotations

from enum import Enum


class Segment(str, Enum):
    SPOT_CRYPTO = "spot_crypto"
    CRYPTO_FNO = "crypto_fno"
    EQUITY_CASH = "equity_cash"
    EQUITY_FNO = "equity_fno"
    COMMODITY = "commodity"
    UNKNOWN = "unknown"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    OTHER = "other"


class OrderStatus(str, Enum):
    OPEN = "open"
    PARTIAL = "partial"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class LedgerEntryType(str, Enum):
    FEE = "fee"
    TAX = "tax"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    OTHER = "other"


class PnLGranularity(str, Enum):
    TRADE = "trade"
    SYMBOL = "symbol"
    DAY = "day"
    PORTFOLIO = "portfolio"


class PnLSourceType(str, Enum):
    BROKER = "broker"
    COMPUTED = "computed"
    HYBRID = "hybrid"


class PnLConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
