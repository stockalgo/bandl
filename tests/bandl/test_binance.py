from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from bandl.config import BandlConfig
from bandl.models.market.types import Interval
from bandl.providers.crypto.binance import BinanceProvider


def test_binance_get_ohlcv_parses_klines() -> None:
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
    rows = prov.get_ohlcv("BTC/USDT", Interval.H1, start, end)
    assert len(rows) == 1
    bar = rows[0]
    assert bar.symbol == "BTCUSDT"
    assert bar.open == Decimal("1.0")
    assert bar.high == Decimal("2.0")
    assert bar.low == Decimal("0.5")
    assert bar.close == Decimal("1.5")
    assert bar.volume == Decimal("100")
    assert bar.source == "binance"
    prov._http.get_json.assert_called_once()


def test_binance_list_symbols_maps_exchange_info() -> None:
    cfg = BandlConfig()
    prov = BinanceProvider(cfg)
    prov._http.get_json = MagicMock(  # type: ignore[method-assign]
        return_value={
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "isSpotTradingAllowed": True,
                },
                {
                    "symbol": "FAKE",
                    "status": "BREAK",
                    "baseAsset": "X",
                    "quoteAsset": "Y",
                },
            ],
        },
    )
    syms = prov.list_symbols(search="BTC", limit=10)
    assert len(syms) == 1
    assert syms[0].canonical == "BTCUSDT"
