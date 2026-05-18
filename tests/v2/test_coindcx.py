from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from bandl.v2.config import BandlConfig
from bandl.v2.models.types import Interval
from bandl.v2.providers.crypto.coindcx import CoinDCXProvider


def test_coindcx_get_ohlcv_desc_sorted() -> None:
    cfg = BandlConfig()
    prov = CoinDCXProvider(cfg)
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2023, 1, 10, tzinfo=timezone.utc)
    t_hi = int(end.timestamp() * 1000) - 86_400_000
    t_lo = t_hi - 86_400_000
    sample = [
        {
            "open": "2",
            "high": "2",
            "low": "2",
            "close": "2",
            "volume": "1",
            "time": t_hi,
        },
        {
            "open": "1",
            "high": "1",
            "low": "1",
            "close": "1",
            "volume": "1",
            "time": t_lo,
        },
    ]
    prov._http.get_json = MagicMock(side_effect=[sample, []])  # type: ignore[method-assign]
    rows = prov.get_ohlcv("BTCUSDT", Interval.M1, start, end)
    assert [r.timestamp for r in rows] == sorted(r.timestamp for r in rows)
    assert rows[0].open == Decimal("1")


def test_coindcx_markets_to_symbol_info() -> None:
    cfg = BandlConfig()
    prov = CoinDCXProvider(cfg)
    prov._http.get_json = MagicMock(return_value=["B-BTC_USDT", "SOMETHING"])  # type: ignore[method-assign]
    rows = prov.list_symbols()
    assert len(rows) == 1
    assert rows[0].canonical == "BTCUSDT"
