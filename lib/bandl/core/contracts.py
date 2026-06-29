"""Parse option-symbol strings into structured components.

The public :class:`~bandl.models.market.contract.OptionContract` always carries a
concrete ``expiry`` date. Monthly broker symbols (``GOLDM26JUN145000CE``) encode
only year + month, so string parsing yields a :class:`ParsedOption` (year + month,
no day); the resolving provider pins the exact expiry date from its instrument dump.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from bandl.models.market.contract import OptionType

_MONTHS: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

# {UNDERLYING}{YY}{MMM}{STRIKE}{CE|PE} with optional EXCH: prefix.
# e.g. GOLDM26JUN145000CE, MCX:GOLDM26JUN145000CE, NIFTY26JUN24000PE
_RE_MONTHLY = re.compile(
    r"^(?:(?P<exch>[A-Z]+):)?"
    r"(?P<underlying>[A-Z][A-Z0-9]*?)"
    r"(?P<yy>\d{2})"
    r"(?P<mmm>JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"(?P<strike>\d+(?:\.\d+)?)"
    r"(?P<opt>CE|PE)$",
)


@dataclass(frozen=True)
class ParsedOption:
    underlying: str
    year: int
    month: int
    strike: Decimal
    option_type: OptionType
    exchange: str | None = None
    day: int | None = None


def parse_option_symbol(symbol: str) -> ParsedOption:
    """Parse a monthly option symbol into its components.

    Raises ``ValueError`` if the string does not match a known option format.
    """
    s = symbol.strip().upper().replace(" ", "")
    m = _RE_MONTHLY.match(s)
    if not m:
        raise ValueError(f"Unrecognized option symbol: {symbol!r}")
    yy = int(m.group("yy"))
    year = 2000 + yy
    month = _MONTHS[m.group("mmm")]
    return ParsedOption(
        underlying=m.group("underlying"),
        year=year,
        month=month,
        strike=Decimal(m.group("strike")),
        option_type=OptionType.from_str(m.group("opt")),
        exchange=m.group("exch"),
    )
