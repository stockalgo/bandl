from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from bandl.config import BandlConfig
from bandl.exceptions import DataNotAvailableError
from bandl.models.market.types import AssetType, Interval
from bandl.providers.crypto.coindcx import CoinDCXProvider


def test_coindcx_futures_candlesticks_parsed() -> None:
    cfg = BandlConfig()
    prov = CoinDCXProvider(cfg)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)
    t_ms = int(datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    prov._http.get_json = MagicMock(  # type: ignore[method-assign]
        return_value={
            "s": "ok",
            "data": [
                {
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 10.0,
                    "time": t_ms,
                },
            ],
        },
    )
    rows = prov.get_ohlcv(
        "BTCUSDT",
        Interval.D1,
        start,
        end,
        asset_type=AssetType.CRYPTO_PERP,
    )
    assert len(rows) == 1
    assert rows[0].close == Decimal("1.5")
    params = prov._http.get_json.call_args[1]["params"]
    assert params["pcode"] == "f"
    assert params["resolution"] == "1D"


def test_coindcx_futures_no_data_raises() -> None:
    cfg = BandlConfig()
    prov = CoinDCXProvider(cfg)
    prov._http.get_json = MagicMock(return_value={"s": "no_data", "data": []})  # type: ignore[method-assign]
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)
    with pytest.raises(DataNotAvailableError, match="no_data"):
        prov.get_ohlcv(
            "BTCUSDT",
            Interval.D1,
            start,
            end,
            asset_type=AssetType.CRYPTO_FUTURE,
        )


def test_coindcx_futures_list_active_instruments() -> None:
    cfg = BandlConfig()
    prov = CoinDCXProvider(cfg)
    prov._http.get_json = MagicMock(  # type: ignore[method-assign]
        return_value=["B-BTC_USDT", "B-ETH_USDT"],
    )
    syms = prov.list_symbols(limit=10, asset_type=AssetType.CRYPTO_PERP)
    assert len(syms) == 2
    assert syms[0].canonical == "BTCUSDT"
    assert syms[0].asset_type == AssetType.CRYPTO_PERP
