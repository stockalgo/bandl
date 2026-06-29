from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bandl.core.contracts import parse_option_symbol
from bandl.models.market import OptionContract, OptionType


def test_parse_monthly_symbol() -> None:
    p = parse_option_symbol("GOLDM26JUN145000CE")
    assert p.underlying == "GOLDM"
    assert p.year == 2026
    assert p.month == 6
    assert p.strike == Decimal("145000")
    assert p.option_type is OptionType.CALL
    assert p.exchange is None


def test_parse_with_exchange_prefix_and_put() -> None:
    p = parse_option_symbol("MCX:GOLDM26JUN143500PE")
    assert p.exchange == "MCX"
    assert p.option_type is OptionType.PUT
    assert p.strike == Decimal("143500")


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_option_symbol("NOTANOPTION")


def test_option_type_from_str() -> None:
    assert OptionType.from_str("call") is OptionType.CALL
    assert OptionType.from_str("C") is OptionType.CALL
    assert OptionType.from_str("pe") is OptionType.PUT
    with pytest.raises(ValueError):
        OptionType.from_str("xx")


def test_contract_canonical_roundtrip() -> None:
    c = OptionContract(
        underlying="GOLDM",
        expiry=date(2026, 6, 26),
        strike=Decimal("145000"),
        option_type=OptionType.CALL,
        exchange="MCX",
    )
    canon = c.canonical()
    assert canon == "GOLDM26JUN145000CE"
    p = parse_option_symbol(canon)
    assert (p.underlying, p.year, p.month, p.strike, p.option_type) == (
        "GOLDM",
        2026,
        6,
        Decimal("145000"),
        OptionType.CALL,
    )


def test_contract_canonical_strips_trailing_zero() -> None:
    c = OptionContract(
        underlying="NIFTY",
        expiry=date(2026, 1, 29),
        strike=Decimal("24000.0"),
        option_type=OptionType.PUT,
        exchange="NFO",
    )
    assert c.canonical() == "NIFTY26JAN24000PE"
