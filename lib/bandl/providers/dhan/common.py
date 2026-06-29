"""Dhan HQ API constants and enum maps."""

from __future__ import annotations

from bandl.models.market.types import Interval

DHAN_API = "https://api.dhan.co/v2"
DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

# bandl exchange code -> Dhan exchangeSegment enum.
EXCHANGE_SEGMENT: dict[str, str] = {
    "NSE": "NSE_EQ",
    "NFO": "NSE_FNO",
    "BSE": "BSE_EQ",
    "BFO": "BSE_FNO",
    "MCX": "MCX_COMM",
    "CDS": "NSE_CURRENCY",
    "BCD": "BSE_CURRENCY",
}

# Dhan instrument enums for option contracts, keyed by bandl exchange.
OPTION_INSTRUMENT: dict[str, str] = {
    "NFO": "OPTIDX",  # also OPTSTK; resolved per scrip row
    "BFO": "OPTIDX",
    "MCX": "OPTFUT",
    "CDS": "OPTCUR",
}

# Intraday minute intervals supported by Dhan.
INTRADAY_INTERVALS: frozenset[int] = frozenset({1, 5, 15, 25, 60})

INTERVAL_TO_MINUTES: dict[Interval, int] = {
    Interval.M1: 1,
    Interval.M5: 5,
    Interval.M15: 15,
    Interval.H1: 60,
}
