from __future__ import annotations

import pytest

from bandl.v2.core.resolver import normalize_crypto_symbol, normalize_equity_or_index_symbol, resolve_symbol
from bandl.v2.models.types import AssetType


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("btc/usdt", "BTCUSDT"),
        ("BTC-USDT", "BTCUSDT"),
        ("btcusdt", "BTCUSDT"),
        ("eth/usd", "ETHUSD"),
    ],
)
def test_normalize_crypto(raw: str, expected: str) -> None:
    assert normalize_crypto_symbol(raw) == expected


def test_resolve_nifty_aliases() -> None:
    r = resolve_symbol("NIFTY 50")
    assert r.canonical == "NIFTY50"
    assert r.asset_type == AssetType.INDEX


def test_resolve_reliance() -> None:
    r = resolve_symbol("RELIANCE.NS")
    assert r.canonical == "RELIANCE"
    assert r.asset_type == AssetType.EQUITY


def test_normalize_equity_strips_suffix() -> None:
    assert normalize_equity_or_index_symbol("reliance.ns") == "RELIANCE"


@pytest.mark.parametrize(
    ("raw", "exp_type"),
    [
        ("BTCUSDT", AssetType.CRYPTO_SPOT),
        ("RELIANCE", AssetType.EQUITY),
    ],
)
def test_resolve_auto_asset(raw: str, exp_type: AssetType) -> None:
    r = resolve_symbol(raw)
    assert r.asset_type == exp_type
