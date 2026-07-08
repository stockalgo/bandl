"""Zerodha live-trading tests (mocked HTTP; no real orders placed)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from bandl.config import BandlConfig, ProviderSettings
from bandl.exceptions import ProviderError, UnsupportedCapabilityError
from bandl.models.account.types import OrderSide, OrderType
from bandl.models.trading import OrderRequest, ProductType, Validity, Variety
from bandl.providers.equity.zerodha import ZerodhaProvider

_ORDER_ROW = {
    "order_id": "151220000000000",
    "exchange": "NSE",
    "tradingsymbol": "RELIANCE",
    "transaction_type": "BUY",
    "order_type": "LIMIT",
    "product": "CNC",
    "validity": "DAY",
    "variety": "regular",
    "status": "OPEN",
    "quantity": 10,
    "filled_quantity": 0,
    "pending_quantity": 10,
    "price": 2500.0,
    "trigger_price": 0,
    "average_price": 0,
    "order_timestamp": "2026-07-08 10:00:00+05:30",
    "exchange_update_timestamp": None,
    "exchange_timestamp": None,
    "tag": None,
}


def _provider() -> ZerodhaProvider:
    return ZerodhaProvider(
        BandlConfig(),
        ProviderSettings(api_key="k", access_token="t"),
    )


def test_place_order_regular_market() -> None:
    prov = _provider()
    prov._http.post_json = MagicMock(
        return_value={"status": "success", "data": {"order_id": "151220000000000"}},
    )
    prov._http.get_json = MagicMock(return_value={"status": "success", "data": [_ORDER_ROW]})

    order = prov.place_order(
        OrderRequest(
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(10),
            price=Decimal("2500"),
            product=ProductType.DELIVERY,
        ),
    )
    assert order.order_id == "151220000000000"
    assert order.symbol == "NSE:RELIANCE"
    assert order.status == "open"
    prov._http.post_json.assert_called_once()
    body = prov._http.post_json.call_args.kwargs["body"]
    assert body["tradingsymbol"] == "RELIANCE"
    assert body["product"] == "CNC"
    assert body["transaction_type"] == "BUY"


def test_place_order_rejects_non_regular_variety() -> None:
    prov = _provider()
    with pytest.raises(UnsupportedCapabilityError):
        prov.place_order(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                quantity=Decimal(1),
                variety=Variety.BRACKET,
            ),
        )


def test_place_order_rejects_unsupported_product() -> None:
    prov = _provider()
    with pytest.raises(ProviderError):
        prov.place_order(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                quantity=Decimal(1),
                product=ProductType.COVER,
            ),
        )


def test_sl_order_requires_trigger_price() -> None:
    prov = _provider()
    with pytest.raises(ProviderError):
        prov.place_order(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                order_type=OrderType.STOP_LIMIT,
                quantity=Decimal(1),
                price=Decimal("2500"),
            ),
        )


def test_modify_order() -> None:
    prov = _provider()
    prov._http.put_json = MagicMock(return_value={"status": "success", "data": {}})
    prov._http.get_json = MagicMock(return_value={"status": "success", "data": [_ORDER_ROW]})

    order = prov.modify_order("151220000000000", price=Decimal("2510"))
    assert order.order_id == "151220000000000"
    body = prov._http.put_json.call_args.kwargs["body"]
    assert body["price"] == "2510"


def test_cancel_order() -> None:
    prov = _provider()
    prov._http.delete_json = MagicMock(return_value={"status": "success", "data": {}})
    prov._http.get_json = MagicMock(return_value={"status": "success", "data": [_ORDER_ROW]})

    order = prov.cancel_order("151220000000000")
    assert order.order_id == "151220000000000"
    prov._http.delete_json.assert_called_once()


def test_get_open_orders_filters_status() -> None:
    prov = _provider()
    complete_row = dict(_ORDER_ROW, order_id="2", status="COMPLETE")
    rows = [_ORDER_ROW, complete_row]
    prov._http.get_json = MagicMock(return_value={"status": "success", "data": rows})

    open_orders = prov.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].order_id == "151220000000000"


def test_get_order_single() -> None:
    prov = _provider()
    prov._http.get_json = MagicMock(return_value={"status": "success", "data": [_ORDER_ROW]})

    order = prov.get_order("151220000000000")
    assert order.status == "open"
    assert order.product == ProductType.DELIVERY
    assert order.validity == Validity.DAY


def test_get_trades_reuses_get_fills() -> None:
    prov = _provider()

    def fake_get(url: str, *, provider: str, params=None, headers=None):
        if url.endswith("/trades"):
            return {
                "status": "success",
                "data": [
                    {
                        "trade_id": "T1",
                        "order_id": "151220000000000",
                        "exchange": "NSE",
                        "tradingsymbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "quantity": 10,
                        "average_price": 2500.0,
                        "fill_timestamp": "2026-07-08 10:00:05+05:30",
                        "product": "CNC",
                    },
                ],
            }
        return {"status": "success", "data": []}

    prov._http.get_json = fake_get
    trades = prov.get_trades()
    assert len(trades) == 1
    assert trades[0].fill_id == "T1"
