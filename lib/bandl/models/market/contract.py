"""Derivative contract models (options)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

_MONTHS_ABBR: tuple[str, ...] = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


class OptionType(str, Enum):
    """Call / put. Value is the common broker code (CE/PE)."""

    CALL = "CE"
    PUT = "PE"

    @classmethod
    def from_str(cls, raw: str) -> OptionType:
        s = raw.strip().upper()
        if s in ("CE", "CALL", "C"):
            return cls.CALL
        if s in ("PE", "PUT", "P"):
            return cls.PUT
        raise ValueError(f"Unrecognized option type: {raw!r}")


def _format_strike(strike: Decimal) -> str:
    """Render strike without a trailing ``.0`` for whole numbers (145000 not 145000.0)."""
    if strike == strike.to_integral_value():
        return str(int(strike))
    return str(strike.normalize())


class OptionContract(BaseModel):
    """Broker-agnostic option contract identity."""

    model_config = {"extra": "forbid", "frozen": True}

    underlying: str
    expiry: date
    strike: Decimal
    option_type: OptionType
    exchange: str
    segment: str | None = None
    lot_size: Decimal | None = None

    def canonical(self) -> str:
        """``{UNDERLYING}{YY}{MMM}{STRIKE}{CE|PE}`` e.g. ``GOLDM26JUN145000CE``."""
        yy = f"{self.expiry.year % 100:02d}"
        mmm = _MONTHS_ABBR[self.expiry.month - 1]
        return (
            f"{self.underlying.upper()}{yy}{mmm}"
            f"{_format_strike(self.strike)}{self.option_type.value}"
        )


class OptionQuote(BaseModel):
    """One leg (CE or PE) of an option-chain strike."""

    model_config = {"extra": "forbid"}

    ltp: Decimal | None = None
    oi: Decimal | None = None
    iv: Decimal | None = None
    volume: Decimal | None = None
    delta: Decimal | None = None
    theta: Decimal | None = None
    gamma: Decimal | None = None
    vega: Decimal | None = None


class OptionChainEntry(BaseModel):
    """A single strike row in an option chain."""

    model_config = {"extra": "forbid"}

    strike: Decimal
    ce: OptionQuote | None = None
    pe: OptionQuote | None = None
