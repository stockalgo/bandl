"""Zerodha live-portfolio tests (mocked HTTP)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from bandl.config import BandlConfig, ProviderSettings
from bandl.providers.equity.zerodha import ZerodhaProvider


def _provider() -> ZerodhaProvider:
    return ZerodhaProvider(
        BandlConfig(),
        ProviderSettings(api_key="k", access_token="t"),
    )


def test_get_positions_net_book() -> None:
    prov = _provider()
    prov._http.get_json = MagicMock(
        return_value={
            "status": "success",
            "data": {
                "net": [
                    {
                        "tradingsymbol": "RELIANCE",
                        "exchange": "NSE",
                        "product": "MIS",
                        "quantity": -5,
                        "average_price": 2500.0,
                        "last_price": 2490.0,
                        "close_price": 2495.0,
                        "multiplier": 1,
                        "buy_quantity": 0,
                        "sell_quantity": 5,
                        "unrealised": 50.0,
                        "realised": 0,
                        "pnl": 50.0,
                    },
                    {
                        "tradingsymbol": "FLAT",
                        "exchange": "NSE",
                        "product": "MIS",
                        "quantity": 0,
                    },
                ],
                "day": [],
            },
        },
    )
    positions = prov.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NSE:RELIANCE"
    assert positions[0].side == "sell"
    assert positions[0].quantity == Decimal("-5")


def test_get_holdings() -> None:
    prov = _provider()
    prov._http.get_json = MagicMock(
        return_value={
            "status": "success",
            "data": [
                {
                    "tradingsymbol": "INFY",
                    "exchange": "NSE",
                    "isin": "INE009A01021",
                    "quantity": 10,
                    "t1_quantity": 0,
                    "average_price": 1400.0,
                    "last_price": 1450.0,
                    "pnl": 500.0,
                    "collateral_quantity": 0,
                },
            ],
        },
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
            "status": "success",
            "data": {
                "equity": {
                    "enabled": True,
                    "net": 50000.0,
                    "available": {"cash": 40000.0},
                    "utilised": {"debits": 10000.0, "span": 2000.0, "exposure": 500.0},
                },
                "commodity": {
                    "enabled": True,
                    "net": 1000.0,
                    "available": {"cash": 1000.0},
                    "utilised": {"debits": 0.0},
                },
            },
        },
    )
    balances = prov.get_balances()
    assert {b.segment for b in balances} == {"equity_cash", "commodity"}

    margin = prov.get_margin()
    assert margin.available == Decimal("50000.0")
    assert margin.used == Decimal("10000.0")
    assert margin.span == Decimal("2000.0")
