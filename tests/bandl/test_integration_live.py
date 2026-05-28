"""Optional live API checks (run with ``pytest -m integration``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bandl import Bandl, Interval


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
