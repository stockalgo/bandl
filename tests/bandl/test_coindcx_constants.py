from __future__ import annotations

from bandl.providers.crypto.coindcx.constants import canonical_to_coindcx_pair, pair_to_canonical


def test_pair_to_canonical() -> None:
    assert pair_to_canonical("B-BTC_USDT") == "BTCUSDT"


def test_canonical_to_coindcx_pair() -> None:
    assert canonical_to_coindcx_pair("BTC", "USDT") == "B-BTC_USDT"
