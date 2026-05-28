"""Optional live API checks (run with ``pytest -m integration``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bandl import Bandl, Interval
from bandl.models.market.types import AssetType


@pytest.mark.integration
def test_live_binance_btc_daily() -> None:
    client = Bandl()
    end = datetime(2025, 7, 20, tzinfo=timezone.utc)
    start = end - timedelta(days=14)
    rows = client.crypto.get_ohlcv("BTCUSDT", Interval.D1, start, end, source="binance")
    assert len(rows) >= 1
    assert rows[0].symbol == "BTCUSDT"


@pytest.mark.integration
def test_live_coindcx_btc_daily() -> None:
    client = Bandl()
    end = datetime(2025, 7, 20, tzinfo=timezone.utc)
    start = end - timedelta(days=14)
    rows = client.crypto.get_ohlcv("BTCUSDT", Interval.D1, start, end, source="coindcx")
    assert len(rows) >= 1


@pytest.mark.integration
def test_live_binance_futures_instruments_and_multi_timeframe() -> None:
    """E2E: fapi exchangeInfo + klines for 1d and 1w."""
    client = Bandl()
    syms = client.list_symbols(
        source="binance",
        search="BTC",
        limit=5,
        asset_type=AssetType.CRYPTO_PERP,
    )
    assert any(s.canonical == "BTCUSDT" for s in syms)

    end = datetime.now(timezone.utc) - timedelta(days=2)
    start = end - timedelta(days=60)
    for interval in (Interval.D1, Interval.W1):
        rows = client.crypto.get_ohlcv(
            "BTCUSDT",
            interval,
            start,
            end,
            source="binance",
            asset_type=AssetType.CRYPTO_PERP,
        )
        assert len(rows) >= 2
        assert rows[0].timestamp < rows[-1].timestamp


@pytest.mark.integration
def test_live_coindcx_futures_instruments_and_multi_timeframe() -> None:
    """E2E: active_instruments + candlesticks pcode=f for 1D and 1w."""
    client = Bandl()
    syms = client.list_symbols(
        source="coindcx",
        search="BTC",
        limit=5,
        asset_type=AssetType.CRYPTO_PERP,
    )
    assert any(s.canonical == "BTCUSDT" for s in syms)

    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=45)
    for interval in (Interval.D1, Interval.W1):
        rows = client.crypto.get_ohlcv(
            "BTCUSDT",
            interval,
            start,
            end,
            source="coindcx",
            asset_type=AssetType.CRYPTO_PERP,
        )
        assert len(rows) >= 2
        assert rows[0].timestamp < rows[-1].timestamp
