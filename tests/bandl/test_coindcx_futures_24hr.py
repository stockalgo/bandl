from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from bandl.config import BandlConfig
from bandl.models.market import SymbolInfo
from bandl.models.market.types import AssetType
from bandl.providers.crypto.coindcx import CoinDCXProvider


def test_coindcx_futures_24hr_tickers_active_only() -> None:
    prov = CoinDCXProvider(BandlConfig())
    prov._http = MagicMock()
    prov._http.get_json.return_value = {
        "ts": 1_700_000_000_000,
        "prices": {
            "B-BTC_USDT": {
                "ls": 50000,
                "h": 51000,
                "l": 49000,
                "v": 1000,
                "pc": 2.5,
            },
            "B-ETH_USDT": {
                "ls": 3000,
                "pc": -1.2,
            },
            "B-INACTIVE_USDT": {
                "ls": 1,
                "pc": -99.0,
            },
        },
    }
    prov.list_futures_market_symbols = MagicMock(  # type: ignore[method-assign]
        return_value=[
            SymbolInfo(
                canonical="BTCUSDT",
                base="BTC",
                quote="USDT",
                asset_type=AssetType.CRYPTO_PERP,
                provider_symbol="B-BTC_USDT",
            ),
            SymbolInfo(
                canonical="ETHUSDT",
                base="ETH",
                quote="USDT",
                asset_type=AssetType.CRYPTO_PERP,
                provider_symbol="B-ETH_USDT",
            ),
        ],
    )
    tickers = prov.get_futures_24hr_tickers()
    assert len(tickers) == 2
    by_sym = {t.symbol: t for t in tickers}
    assert by_sym["BTCUSDT"].change_24h == Decimal("2.5")
    assert by_sym["ETHUSDT"].change_24h == Decimal("-1.2")
