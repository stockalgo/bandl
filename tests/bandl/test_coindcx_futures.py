"""CoinDCX futures mapping tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from bandl.config import BandlConfig, ProviderSettings
from bandl.providers.crypto.coindcx import CoinDCXProvider


def test_map_futures_fill() -> None:
    prov = CoinDCXProvider(
        BandlConfig(providers={"coindcx": ProviderSettings(api_key="k", api_secret="s")}),
    )
    row = {
        "price": 0.2962,
        "quantity": 33.0,
        "is_maker": False,
        "fee_amount": 0.00733095,
        "pair": "B-BTC_USDT",
        "side": "buy",
        "timestamp": 1705645534425,
        "order_id": "9b37c924-d8cf-4a0b-8475-cc8a2b14b962",
        "margin_currency_short_name": "USDT",
    }
    fill = prov._map_futures_fill(row)
    assert fill.segment == "crypto_fno"
    assert fill.symbol == "BTCUSDT"
    assert fill.currency == "USDT"
    assert fill.fee == Decimal("0.00733095")


def test_futures_trades_pagination(monkeypatch) -> None:
    prov = CoinDCXProvider(
        BandlConfig(providers={"coindcx": ProviderSettings(api_key="k", api_secret="s")}),
    )
    calls = 0

    def fake_post(url: str, body: dict | None = None, headers=None):
        nonlocal calls
        calls += 1
        if "trades" in url:
            return [
                {
                    "price": 1,
                    "quantity": 1,
                    "side": "buy",
                    "pair": "B-BTC_USDT",
                    "timestamp": int(datetime(2026, 5, 10, tzinfo=timezone.utc).timestamp() * 1000),
                    "order_id": "o1",
                    "fee_amount": 0,
                    "margin_currency_short_name": "USDT",
                },
            ]
        return []

    prov._futures_post = fake_post  # type: ignore[method-assign]
    prov._discover_futures_pairs_from_orders = lambda *a, **k: {"B-BTC_USDT"}  # type: ignore
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fills = prov.get_futures_fills(start, end, pairs={"B-BTC_USDT"})
    assert len(fills) == 1
    assert calls >= 1
