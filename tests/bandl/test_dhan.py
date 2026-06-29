from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from bandl.config import BandlConfig, ProviderSettings
from bandl.exceptions import AuthenticationError, ProviderError
from bandl.models.market import OptionContract, OptionType
from bandl.models.market.types import Interval
from bandl.providers.dhan import DhanProvider
from bandl.providers.dhan.scrip import ResolvedInstrument

_CANDLES = {
    "timestamp": [1782099000, 1782099060],
    "open": [20.7, 20.3],
    "high": [21.0, 20.7],
    "low": [20.1, 20.3],
    "close": [20.3, 20.4],
    "volume": [175, 202],
    "open_interest": [1500, 1520],
}


def _provider() -> DhanProvider:
    cfg = BandlConfig()
    return DhanProvider(cfg, ProviderSettings(api_key="cid", access_token="jwt"))


def test_requires_access_token() -> None:
    prov = DhanProvider(BandlConfig(), ProviderSettings())
    with pytest.raises(AuthenticationError):
        prov.get_option_ohlcv(
            "GOLDM26JUN145000CE",
            Interval.M1,
            datetime(2026, 6, 26, tzinfo=timezone.utc),
            datetime(2026, 6, 27, tzinfo=timezone.utc),
            exchange="MCX",
            instrument_id="570850",
        )


def test_instrument_id_bypasses_scrip() -> None:
    prov = _provider()
    prov._http.post_json = MagicMock(return_value=_CANDLES)
    # Scrip lookup must NOT be called when instrument_id is given.
    prov._scrip.resolve_contract = MagicMock(side_effect=AssertionError("scrip used"))

    rows = prov.get_option_ohlcv(
        "GOLDM26JUN143500CE",
        Interval.M1,
        datetime(2026, 6, 26, tzinfo=timezone.utc),
        datetime(2026, 6, 27, tzinfo=timezone.utc),
        exchange="MCX",
        instrument_id="570800",
    )
    assert len(rows) == 2
    assert rows[0].symbol == "GOLDM26JUN143500CE"
    assert rows[0].source == "dhan"
    assert rows[0].open_interest == Decimal("1500")
    body = prov._http.post_json.call_args.kwargs["body"]
    assert body["securityId"] == "570800"
    assert body["exchangeSegment"] == "MCX_COMM"
    assert body["instrument"] == "OPTFUT"
    assert body["interval"] == 1


def test_scrip_resolution_path() -> None:
    prov = _provider()
    prov._http.post_json = MagicMock(return_value=_CANDLES)
    prov._scrip.resolve_contract = MagicMock(
        return_value=ResolvedInstrument(
            security_id="571463",
            exchange_segment="MCX_COMM",
            instrument_type="OPTFUT",
            expiry=date(2026, 7, 29),
            lot_size=Decimal("1"),
        ),
    )
    contract = OptionContract(
        underlying="GOLDM",
        expiry=date(2026, 7, 29),
        strike=Decimal("145000"),
        option_type=OptionType.CALL,
        exchange="MCX",
    )
    rows = prov.get_option_ohlcv(
        contract,
        Interval.M5,
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    prov._scrip.resolve_contract.assert_called_once()
    body = prov._http.post_json.call_args.kwargs["body"]
    assert body["securityId"] == "571463"
    assert body["interval"] == 5
    assert rows[0].symbol == "GOLDM26JUL145000CE"


def test_unsupported_interval() -> None:
    prov = _provider()
    with pytest.raises(ProviderError):
        prov.get_option_ohlcv(
            "GOLDM26JUN145000CE",
            Interval.M3,  # not supported by Dhan intraday
            datetime(2026, 6, 26, tzinfo=timezone.utc),
            datetime(2026, 6, 27, tzinfo=timezone.utc),
            exchange="MCX",
            instrument_id="570800",
        )


def test_parse_chain() -> None:
    prov = _provider()
    payload = {
        "data": {
            "oc": {
                "145000.000000": {
                    "ce": {
                        "last_price": 5.5,
                        "oi": 1200,
                        "implied_volatility": 18.2,
                        "volume": 300,
                        "greeks": {"delta": 0.45, "theta": -1.2, "gamma": 0.01, "vega": 3.3},
                    },
                    "pe": {"last_price": 2.1, "oi": 800},
                },
            },
        },
    }
    rows = prov._parse_chain(payload)
    assert len(rows) == 1
    e = rows[0]
    assert e.strike == Decimal("145000.000000")
    assert e.ce is not None and e.ce.ltp == Decimal("5.5")
    assert e.ce.delta == Decimal("0.45")
    assert e.pe is not None and e.pe.oi == Decimal("800")
    assert e.pe.iv is None
