from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from bandl.config import BandlConfig, ProviderSettings
from bandl.exceptions import AuthenticationError
from bandl.models.market.types import Interval
from bandl.providers.equity.zerodha import ZerodhaProvider, _parse_kite_timestamp


def test_parse_kite_timestamp_offset() -> None:
    dt = _parse_kite_timestamp("2015-12-01T15:29:00+0530")
    assert dt.tzinfo is not None
    assert dt.hour == 9
    assert dt.minute == 59


def test_zerodha_requires_auth() -> None:
    cfg = BandlConfig()
    prov = ZerodhaProvider(cfg, ProviderSettings())
    with pytest.raises(AuthenticationError):
        prov.get_ohlcv(
            "RELIANCE",
            Interval.D1,
            datetime(2023, 1, 1, tzinfo=timezone.utc),
            datetime(2023, 1, 10, tzinfo=timezone.utc),
            instrument_token=999,
        )


def test_zerodha_historical_with_mock_token() -> None:
    cfg = BandlConfig()
    prov = ZerodhaProvider(
        cfg,
        ProviderSettings(api_key="k", access_token="t"),
    )
    prov._http.get_json = MagicMock(
        return_value={
            "data": {
                "candles": [
                    [
                        "2023-01-03T00:00:00+0530",
                        100,
                        110,
                        90,
                        105,
                        1000,
                    ],
                ],
            },
        },
    )
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2023, 1, 5, tzinfo=timezone.utc)
    rows = prov.get_ohlcv(
        "RELIANCE",
        Interval.D1,
        start,
        end,
        instrument_token=1_234_567,
    )
    assert len(rows) == 1
    assert rows[0].symbol == "RELIANCE"
    assert rows[0].source == "zerodha"
