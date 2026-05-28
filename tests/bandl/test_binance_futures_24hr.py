from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from bandl.config import BandlConfig
from bandl.providers.crypto.binance import BinanceProvider


def test_binance_futures_24hr_tickers() -> None:
    cfg = BandlConfig()
    prov = BinanceProvider(cfg)
    prov._http.get_json = MagicMock(  # type: ignore[method-assign]
        return_value=[
            {
                "symbol": "BTCUSDT",
                "lastPrice": "90000",
                "priceChangePercent": "2.5",
                "highPrice": "91000",
                "lowPrice": "88000",
                "volume": "1000",
                "closeTime": 1_700_000_000_000,
            },
            {
                "symbol": "ETHUSDT",
                "lastPrice": "3000",
                "priceChangePercent": "-1.2",
                "closeTime": 1_700_000_000_000,
            },
        ],
    )
    tickers = prov.get_futures_24hr_tickers()
    assert len(tickers) == 2
    assert tickers[0].symbol == "BTCUSDT"
    assert tickers[0].change_24h == Decimal("2.5")
