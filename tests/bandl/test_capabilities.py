"""Capability and unsupported-feature tests."""

from __future__ import annotations

import pytest

from bandl import Bandl
from bandl.config import BandlConfig
from bandl.core.capabilities import AccountCapabilities
from bandl.exceptions import ConfigurationError
from bandl.providers.crypto.binance import BinanceProvider


def test_binance_not_account_provider() -> None:
    prov = BinanceProvider(BandlConfig())
    assert not hasattr(prov, "account_capabilities")


def test_account_fills_binance_raises() -> None:
    client = Bandl()
    with pytest.raises(ConfigurationError, match="account history"):
        client.account.get_fills(source="binance")


def test_account_capabilities_has_no_vestigial_positions_field() -> None:
    """AccountCapabilities.positions predated PortfolioCapabilities.positions (the
    real one, backing client.portfolio.get_positions), was never set True by any
    provider, and was never read anywhere — removed rather than fixed to avoid
    implying a get_positions() method that AccountHistoryProvider doesn't have."""
    assert "positions" not in AccountCapabilities.model_fields
