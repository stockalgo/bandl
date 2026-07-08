"""Dhan live-trading tests (mocked HTTP; no real orders placed)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from bandl.config import BandlConfig, ProviderSettings
from bandl.exceptions import AuthenticationError, ProviderError, UnsupportedCapabilityError
from bandl.models.account.types import OrderSide, OrderType
from bandl.models.market import OptionContract, OptionType
from bandl.models.trading import OrderRequest, ProductType, Variety
from bandl.providers.dhan import DhanProvider
from bandl.providers.dhan.scrip import ResolvedInstrument

_ORDER_ROW = {
    "orderId": "112111182198",
    "dhanClientId": "cid",
    "orderStatus": "PENDING",
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "CNC",
    "orderType": "LIMIT",
    "validity": "DAY",
    "tradingSymbol": "SBIN",
    "securityId": "3045",
    "quantity": 10,
    "disclosedQuantity": 0,
    "price": 500.0,
    "triggerPrice": 0,
    "remainingQuantity": 10,
    "averageTradedPrice": 0,
    "filledQty": 0,
    "createTime": "2026-07-08 10:00:00",
    "updateTime": "2026-07-08 10:00:00",
    "exchangeTime": "2026-07-08 10:00:00",
}


def _provider(with_client_id: bool = True) -> DhanProvider:
    settings = ProviderSettings(api_key="cid" if with_client_id else None, access_token="jwt")
    return DhanProvider(BandlConfig(), settings)


def test_place_order_by_instrument_id() -> None:
    prov = _provider()
    prov._http.post_json = MagicMock(
        return_value={"orderId": "112111182198", "orderStatus": "PENDING"},
    )
    prov._http.get_json = MagicMock(return_value=_ORDER_ROW)

    order = prov.place_order(
        OrderRequest(
            instrument_id="3045",
            exchange="NSE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(10),
            price=Decimal("500"),
            product=ProductType.DELIVERY,
        ),
    )
    assert order.order_id == "112111182198"
    assert order.symbol == "NSE:SBIN"
    assert order.status == "open"
    body = prov._http.post_json.call_args.kwargs["body"]
    assert body["securityId"] == "3045"
    assert body["exchangeSegment"] == "NSE_EQ"
    assert body["dhanClientId"] == "cid"


def test_place_order_requires_client_id() -> None:
    prov = _provider(with_client_id=False)
    with pytest.raises(AuthenticationError):
        prov.place_order(
            OrderRequest(
                instrument_id="3045",
                exchange="NSE",
                side=OrderSide.BUY,
                quantity=Decimal(1),
            ),
        )


def test_place_order_rejects_non_regular_variety() -> None:
    prov = _provider()
    with pytest.raises(UnsupportedCapabilityError):
        prov.place_order(
            OrderRequest(
                instrument_id="3045",
                exchange="NSE",
                side=OrderSide.BUY,
                quantity=Decimal(1),
                variety=Variety.BRACKET,
            ),
        )


def test_stop_loss_requires_trigger_price() -> None:
    prov = _provider()
    with pytest.raises(ProviderError):
        prov.place_order(
            OrderRequest(
                instrument_id="3045",
                exchange="NSE",
                side=OrderSide.BUY,
                order_type=OrderType.STOP_LIMIT,
                quantity=Decimal(1),
                price=Decimal("500"),
            ),
        )


def test_place_option_order_via_contract() -> None:
    prov = _provider()
    prov._scrip.resolve_contract = MagicMock(
        return_value=ResolvedInstrument(
            security_id="570850",
            exchange_segment="MCX_COMM",
            instrument_type="OPTFUT",
            expiry=date(2026, 7, 29),
            lot_size=Decimal(100),
        ),
    )
    option_row = dict(_ORDER_ROW, exchangeSegment="MCX_COMM", tradingSymbol="GOLDM26JUL145000CE")
    prov._http.post_json = MagicMock(
        return_value={"orderId": "112111182198", "orderStatus": "PENDING"},
    )
    prov._http.get_json = MagicMock(return_value=option_row)

    contract = OptionContract(
        underlying="GOLDM",
        expiry=date(2026, 7, 29),
        strike=Decimal("145000"),
        option_type=OptionType.CALL,
        exchange="MCX",
    )
    order = prov.place_order(
        OrderRequest(
            contract=contract,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal(100),
            product=ProductType.MARGIN,
        ),
    )
    assert order.symbol == "MCX:GOLDM26JUL145000CE"
    body = prov._http.post_json.call_args.kwargs["body"]
    assert body["securityId"] == "570850"
    assert body["exchangeSegment"] == "MCX_COMM"
    assert body["productType"] == "MARGIN"


def test_modify_order() -> None:
    prov = _provider()
    prov._http.put_json = MagicMock(return_value={})
    prov._http.get_json = MagicMock(return_value=_ORDER_ROW)

    order = prov.modify_order("112111182198", price=Decimal("510"))
    assert order.order_id == "112111182198"
    body = prov._http.put_json.call_args.kwargs["body"]
    assert body["price"] == 510.0


def test_cancel_order() -> None:
    prov = _provider()
    prov._http.delete_json = MagicMock(return_value={})
    prov._http.get_json = MagicMock(return_value=_ORDER_ROW)

    order = prov.cancel_order("112111182198")
    assert order.order_id == "112111182198"
    prov._http.delete_json.assert_called_once()


def test_get_open_orders_filters_status() -> None:
    prov = _provider()
    traded_row = dict(_ORDER_ROW, orderId="2", orderStatus="TRADED")
    prov._http.get_json = MagicMock(return_value=[_ORDER_ROW, traded_row])

    open_orders = prov.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].order_id == "112111182198"


def test_get_trades() -> None:
    prov = _provider()
    prov._http.get_json = MagicMock(
        return_value=[
            {
                "orderId": "112111182198",
                "exchangeTradeId": "T1",
                "exchangeSegment": "NSE_EQ",
                "tradingSymbol": "SBIN",
                "securityId": "3045",
                "transactionType": "BUY",
                "tradedQuantity": 10,
                "tradedPrice": 500.0,
                "exchangeTime": "2026-07-08 10:00:05",
            },
        ],
    )
    trades = prov.get_trades()
    assert len(trades) == 1
    assert trades[0].fill_id == "T1"
    assert trades[0].symbol == "NSE:SBIN"
