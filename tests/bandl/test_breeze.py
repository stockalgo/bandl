from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from bandl.config import BandlConfig, ProviderSettings
from bandl.exceptions import AuthenticationError, InsufficientFundsError, OrderRejectedError, ProviderError
from bandl.models.account.types import OrderSide, OrderType
from bandl.models.market import OptionContract, OptionType
from bandl.models.market.types import Interval
from bandl.models.trading import OrderRequest, ProductType, Validity
from bandl.providers.breeze import BreezeProvider

_SAMPLE_CANDLES_RESPONSE = {
    "Success": [
        {
            "datetime": "2026-09-01 09:15:00",
            "open": "2450.50",
            "high": "2460.00",
            "low": "2448.25",
            "close": "2458.75",
            "volume": "12500",
            "open_interest": "350000",
        },
        {
            "datetime": "2026-09-01 09:16:00",
            "open": "2458.75",
            "high": "2462.10",
            "low": "2457.00",
            "close": "2461.30",
            "volume": "8300",
            "open_interest": "351200",
        },
    ],
    "Status": 200,
    "Error": None,
}


def _breeze_provider() -> BreezeProvider:
    cfg = BandlConfig()
    settings = ProviderSettings(
        api_key="test_api_key",
        api_secret="test_secret_key",
        access_token="test_session_token",
        account_id="USER123",
    )
    return BreezeProvider(cfg, settings)


def test_requires_credentials() -> None:
    prov = BreezeProvider(BandlConfig(), ProviderSettings())
    with pytest.raises(AuthenticationError):
        prov.get_ohlcv(
            "RELIANCE",
            Interval.M1,
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 2, tzinfo=timezone.utc),
        )


def test_get_ohlcv_equity() -> None:
    prov = _breeze_provider()
    prov._http.get_json = MagicMock(return_value=_SAMPLE_CANDLES_RESPONSE)

    bars = prov.get_ohlcv(
        "RELIANCE",
        Interval.M1,
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    assert len(bars) == 2
    assert bars[0].symbol == "RELIANCE"
    assert bars[0].open == Decimal("2450.50")
    assert bars[0].high == Decimal("2460.00")
    assert bars[0].low == Decimal("2448.25")
    assert bars[0].close == Decimal("2458.75")
    assert bars[0].volume == Decimal("12500")
    assert bars[0].open_interest == Decimal("350000")
    assert bars[0].source == "breeze"

    call_params = prov._http.get_json.call_args.kwargs["params"]
    assert call_params["stock_code"] == "RELIANCE"
    assert call_params["exch_code"] == "nse"
    assert call_params["interval"] == "1minute"


def test_get_option_ohlcv_mcx() -> None:
    prov = _breeze_provider()
    prov._http.get_json = MagicMock(return_value=_SAMPLE_CANDLES_RESPONSE)

    contract = OptionContract(
        underlying="CRUDEOIL",
        expiry=date(2026, 9, 15),
        strike=Decimal("6200"),
        option_type=OptionType.CALL,
        exchange="MCX",
    )

    bars = prov.get_option_ohlcv(
        contract,
        Interval.M5,
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    assert len(bars) == 2
    assert bars[0].symbol == "CRUDEOIL26SEP6200CE"
    call_params = prov._http.get_json.call_args.kwargs["params"]
    assert call_params["stock_code"] == "CRUDE"  # Mapped via MCX_STOCK_CODES
    assert call_params["exch_code"] == "mcx"
    assert call_params["product_type"] == "options"
    assert call_params["interval"] == "5minute"
    assert call_params["strike_price"] == "6200"
    assert call_params["right"] == "call"


def test_portfolio_holdings_and_funds() -> None:
    prov = _breeze_provider()
    prov._request_v1 = MagicMock(
        side_effect=lambda method, endpoint, body=None: {
            "dematholdings": {
                "Success": [
                    {
                        "stock_code": "ZAGPRE",
                        "stock_ISIN": "INE07K301024",
                        "quantity": "10",
                        "blocked_quantity": "0",
                    }
                ],
                "Status": 200,
                "Error": None,
            },
            "funds": {
                "Success": {
                    "unallocated_balance": "15420.50",
                    "allocated_equity": "2000.00",
                    "allocated_fno": "0.0",
                    "allocated_commodity": "0.0",
                    "allocated_currency": "0.0",
                    "block_by_trade_balance": "500.0",
                },
                "Status": 200,
                "Error": None,
            },
        }.get(endpoint, {})
    )

    holdings = prov.get_holdings()
    assert len(holdings) == 1
    assert holdings[0].symbol == "NSE:ZAGPRE"
    assert holdings[0].quantity == Decimal("10")
    assert holdings[0].isin == "INE07K301024"

    balances = prov.get_balances()
    assert len(balances) == 1
    assert balances[0].available == Decimal("15420.50")
    assert balances[0].used == Decimal("2500.00")
    assert balances[0].total == Decimal("17920.50")

    margin = prov.get_margin()
    assert margin.available == Decimal("15420.50")
    assert margin.total == Decimal("17920.50")


def test_trading_place_and_cancel_order() -> None:
    prov = _breeze_provider()
    prov._request_v1 = MagicMock(
        side_effect=lambda method, endpoint, body=None: {
            "order": {
                "Success": {"order_id": "20260927000123"},
                "Status": 200,
                "Error": None,
            }
        }.get(endpoint, {})
    )

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("2450.00"),
        product=ProductType.DELIVERY,
        validity=Validity.DAY,
    )

    ack = prov.place_order(req)
    assert ack.order_id == "20260927000123"
    assert ack.operation == "place"
    assert ack.provider_id == "breeze"

    cancel_ack = prov.cancel_order("20260927000123", exchange="NSE")
    assert cancel_ack.order_id == "20260927000123"
    assert cancel_ack.operation == "cancel"


def test_trading_insufficient_funds() -> None:
    prov = _breeze_provider()
    prov._request_v1 = MagicMock(
        return_value={
            "Success": None,
            "Status": 500,
            "Error": "Insufficient funds / limit available to execute order",
        }
    )

    req = OrderRequest(
        symbol="TCS",
        exchange="NSE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
    )

    with pytest.raises(InsufficientFundsError):
        prov.place_order(req)
