"""ICICI Direct Breeze API constants, URLs, and mapping tables."""

from __future__ import annotations

from bandl.models.market.types import Interval

BREEZE_API_V1 = "https://api.icicidirect.com/breezeapi/api/v1"
BREEZE_API_V2 = "https://breezeapi.icicidirect.com/api/v2"

# Interval mappings for Breeze API v2 historical charts:
# Supported in v2: '1second', '1minute', '5minute', '30minute', '1day'
INTERVAL_TO_BREEZE: dict[Interval, str] = {
    Interval.M1: "1minute",
    Interval.M5: "5minute",
    Interval.M30: "30minute",
    Interval.D1: "1day",
}

# Native interval strings supported by Breeze
SUPPORTED_BREEZE_INTERVALS: frozenset[str] = frozenset(
    {
        "1second",
        "1minute",
        "5minute",
        "30minute",
        "1day",
    }
)

# bandl exchange code -> Breeze exchange_code (lowercase)
EXCHANGE_CODE_MAP: dict[str, str] = {
    "NSE": "nse",
    "BSE": "bse",
    "NFO": "nfo",
    "MCX": "mcx",
    "CDS": "cds",
    "NDX": "ndx",
}

# Commodity underlying alias map to Breeze stock_code
MCX_STOCK_CODES: dict[str, str] = {
    "CRUDEOIL": "CRUDE",
    "CRUDE": "CRUDE",
    "CRUDEOILM": "CRUDMI",
    "CRUDMI": "CRUDMI",
    "NATURALGAS": "NATGAS",
    "NATGAS": "NATGAS",
    "NATGASM": "NATGMI",
    "NATGMI": "NATGMI",
    "GOLD": "GOLD",
    "GOLDM": "GOLDMI",
    "GOLDMI": "GOLDMI",
    "SILVER": "SILVER",
    "SILVERM": "SILMIN",
    "SILMIN": "SILMIN",
    "COPPER": "COPPER",
    "ZINC": "ZINC",
}
