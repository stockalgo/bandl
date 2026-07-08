from __future__ import annotations

from enum import Enum


class ProductType(str, Enum):
    DELIVERY = "delivery"  # zerodha CNC / dhan CNC
    INTRADAY = "intraday"  # zerodha MIS / dhan INTRADAY
    NORMAL = "normal"  # zerodha NRML (F&O carryforward)
    MARGIN = "margin"  # dhan MARGIN (F&O carryforward)
    MTF = "mtf"  # margin trading facility (both)
    COVER = "cover"  # zerodha CO / dhan CO (read-only in this release)
    BRACKET = "bracket"  # zerodha BO / dhan BO (read-only in this release)
    OTHER = "other"


class Validity(str, Enum):
    DAY = "day"
    IOC = "ioc"
    TTL = "ttl"  # zerodha (validity_ttl minutes) — not yet writable
    GTC = "gtc"  # crypto — not yet writable
    FOK = "fok"  # crypto — not yet writable
    OTHER = "other"


class Variety(str, Enum):
    """Order variety. Only REGULAR is accepted on write in this release;
    the rest exist so live order books containing other varieties parse losslessly."""

    REGULAR = "regular"
    AMO = "amo"
    COVER = "cover"
    BRACKET = "bracket"
    ICEBERG = "iceberg"
    AUCTION = "auction"
    GTT = "gtt"
    FOREVER = "forever"
    OCO = "oco"
    OTHER = "other"
