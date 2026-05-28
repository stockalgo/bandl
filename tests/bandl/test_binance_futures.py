from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from bandl.config import BandlConfig
from bandl.models.market.types import AssetType, Interval
from bandl.providers.crypto.binance import BinanceProvider


def test_binance_futures_get_ohlcv_uses_fapi() -> None:
    cfg = BandlConfig()
    prov = BinanceProvider(cfg)
    sample = [
        [
            1_700_000_000_000,
            "1.0",
            "2.0",
            "0.5",
            "1.5",
            "100",
            1_700_000_060_000,
            "150",
            10,
            "1",
            "2",
            "0",
        ],
    ]
    prov._http.get_json = MagicMock(return_value=sample)  # type: ignore[method-assign]
    start = datetime(2023, 11, 1, tzinfo=timezone.utc)
    end = datetime(2023, 11, 2, tzinfo=timezone.utc)
    rows = prov.get_ohlcv(
        "BTCUSDT",
        Interval.D1,
        start,
        end,
        asset_type=AssetType.CRYPTO_PERP,
    )
    assert len(rows) == 1
    assert rows[0].symbol == "BTCUSDT"
    url = prov._http.get_json.call_args[0][0]
    assert "fapi.binance.com" in url


def test_binance_futures_list_symbols() -> None:
    cfg = BandlConfig()
    prov = BinanceProvider(cfg)
    prov._http.get_json = MagicMock(  # type: ignore[method-assign]
        return_value={
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "pair": "BTCUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                },
                {
                    "symbol": "BTCUSDT_240628",
                    "contractType": "CURRENT_QUARTER",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                },
            ],
        },
    )
    syms = prov.list_symbols(search="BTC", asset_type=AssetType.CRYPTO_FUTURE)
    assert len(syms) == 1
    assert syms[0].asset_type == AssetType.CRYPTO_PERP
    assert syms[0].canonical == "BTCUSDT"
