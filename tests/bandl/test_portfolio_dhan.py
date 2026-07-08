"""Dhan live-portfolio tests (mocked HTTP)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from bandl.config import BandlConfig, ProviderSettings
from bandl.providers.dhan import DhanProvider


def _provider() -> DhanProvider:
    return DhanProvider(BandlConfig(), ProviderSettings(api_key="cid", access_token="jwt"))


def test_get_positions() -> None:
    prov = _provider()
    prov._http.get_json = MagicMock(
        return_value=[
            {
                "tradingSymbol": "SBIN",
                "securityId": "3045",
                "positionType": "LONG",
                "exchangeSegment": "NSE_EQ",
                "productType": "INTRADAY",
                "buyAvg": 500.0,
                "buyQty": 10,
                "costPrice": 500.0,
                "sellAvg": 0,
                "sellQty": 0,
                "netQty": 10,
                "realizedProfit": 0,
                "unrealizedProfit": 100.0,
                "multiplier": 1,
            },
            {
                "tradingSymbol": "FLAT",
                "positionType": "CLOSED",
                "exchangeSegment": "NSE_EQ",
                "productType": "INTRADAY",
                "netQty": 0,
            },
        ],
    )
    positions = prov.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NSE:SBIN"
    assert positions[0].side == "buy"
    assert positions[0].unrealized_pnl == Decimal("100.0")


def test_get_holdings() -> None:
    prov = _provider()
    prov._http.get_json = MagicMock(
        return_value=[
            {
                "exchange": "NSE",
                "tradingSymbol": "INFY",
                "securityId": "1594",
                "isin": "INE009A01021",
                "totalQty": 10,
                "dpQty": 10,
                "t1Qty": 0,
                "availableQty": 10,
                "collateralQty": 0,
                "avgCostPrice": 1400.0,
            },
        ],
    )
    holdings = prov.get_holdings()
    assert len(holdings) == 1
    assert holdings[0].symbol == "NSE:INFY"
    assert holdings[0].quantity == Decimal(10)
    assert holdings[0].isin == "INE009A01021"


def test_get_balances_and_margin() -> None:
    prov = _provider()
    prov._http.get_json = MagicMock(
        return_value={
            "dhanClientId": "cid",
            "availabelBalance": 50000.0,
            "sodLimit": 50000.0,
            "collateralAmount": 0,
            "receiveableAmount": 0,
            "utilizedAmount": 10000.0,
            "blockedPayoutAmount": 0,
            "withdrawableBalance": 40000.0,
        },
    )
    balances = prov.get_balances()
    assert len(balances) == 1
    assert balances[0].available == Decimal("50000.0")
    assert balances[0].used == Decimal("10000.0")

    margin = prov.get_margin()
    assert margin.total == Decimal("60000.0")
    assert margin.span is None
