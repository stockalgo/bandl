"""Capability and unsupported-feature tests."""

from __future__ import annotations

import pytest

from bandl import Bandl
from bandl.config import BandlConfig
from bandl.exceptions import ConfigurationError
from bandl.providers.crypto.binance import BinanceProvider


def test_binance_not_account_provider() -> None:
    prov = BinanceProvider(BandlConfig())
    assert not hasattr(prov, "account_capabilities")


def test_account_fills_binance_raises() -> None:
    client = Bandl()
    with pytest.raises(ConfigurationError, match="account history"):
        client.account.get_fills(source="binance")
