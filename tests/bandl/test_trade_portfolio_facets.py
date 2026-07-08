"""client.trade / client.portfolio facet wiring + capability gating."""

from __future__ import annotations

import pytest

from bandl import Bandl
from bandl.exceptions import ConfigurationError


def test_trade_facet_rejects_non_trading_provider() -> None:
    client = Bandl()
    with pytest.raises(ConfigurationError):
        client.trade.capabilities("binance")


def test_portfolio_facet_rejects_non_portfolio_provider() -> None:
    client = Bandl()
    with pytest.raises(ConfigurationError):
        client.portfolio.capabilities("binance")


def test_trade_facet_wired_for_zerodha_and_dhan() -> None:
    client = Bandl()
    for source in ("zerodha", "dhan"):
        caps = client.trade.capabilities(source)
        assert caps.place.supported
        assert client.trade.supports(source, "place")


def test_portfolio_facet_wired_for_zerodha_and_dhan() -> None:
    client = Bandl()
    for source in ("zerodha", "dhan"):
        caps = client.portfolio.capabilities(source)
        assert caps.positions.supported
        assert client.portfolio.supports(source, "holdings")
