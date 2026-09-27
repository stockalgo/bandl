"""Reusable offline contract test suite for execution requirements (R1-R9, R12).

Tests Zerodha and Dhan adapters along with a cross-asset fake provider against:
1. Typed commands, strict request validation & non-truncation (R2, R3, R8).
2. Immediate acknowledgements & uncertain outcome handling (R4, R7).
3. Lossless state mapping & pending status preservation (R5).
4. Recovery reads (all session orders, order history, trades) (R6).
5. Safe transport with zero mutation retries and credential redaction (R7, R12).
6. Capabilities and pre-submission gating (R9).
7. Account isolation and dedup key scoping (R1).
8. Cross-asset fake provider (fractional crypto, quote notional, hedge mode, 3rd asset fees).
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from bandl import Bandl
from bandl.config import BandlConfig, ProviderSettings
from bandl.core.capabilities import CapabilityDetail, PortfolioCapabilities, TradeCapabilities
from bandl.core.http import HttpClient, _redact_dict
from bandl.exceptions import (
    AuthenticationError,
    ConfigurationError,
    InsufficientFundsError,
    InvalidOrderError,
    OrderRejectedError,
    ProviderError,
    RateLimitError,
    SymbolNotFoundError,
    UncertainOutcomeError,
    UnsupportedCapabilityError,
)
from bandl.models.account import AccountFill, AccountOrder
from bandl.models.account.types import OrderSide, OrderStatus, OrderType, Segment
from bandl.models.market import OptionContract, OptionType
from bandl.models.trading import (
    Balance,
    Holding,
    MarginInfo,
    Order,
    OrderAcknowledgement,
    OrderRequest,
    Position,
    PositionSide,
    ProductType,
    QuantityUnit,
    Validity,
    Variety,
)
from bandl.providers.dhan import DhanProvider
from bandl.providers.equity.zerodha import ZerodhaProvider

# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

_KITE_ORDER_ROW = {
    "order_id": "151220000000001",
    "exchange": "NSE",
    "tradingsymbol": "INFY",
    "transaction_type": "BUY",
    "order_type": "LIMIT",
    "product": "CNC",
    "validity": "DAY",
    "variety": "regular",
    "status": "OPEN",
    "quantity": 10,
    "filled_quantity": 0,
    "pending_quantity": 10,
    "cancelled_quantity": 0,
    "price": 1500.0,
    "trigger_price": 0,
    "average_price": 0,
    "order_timestamp": "2026-09-13 10:00:00+05:30",
    "exchange_update_timestamp": None,
    "exchange_timestamp": None,
    "tag": "my-tag-123",
}

_DHAN_ORDER_ROW = {
    "orderId": "1122334455",
    "dhanClientId": "cid123",
    "orderStatus": "PENDING",
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "CNC",
    "orderType": "LIMIT",
    "validity": "DAY",
    "tradingSymbol": "INFY",
    "securityId": "1594",
    "quantity": 10,
    "disclosedQuantity": 0,
    "price": 1500.0,
    "triggerPrice": 0,
    "remainingQuantity": 10,
    "averageTradedPrice": 0,
    "filledQty": 0,
    "createTime": "2026-09-13 10:00:00",
    "updateTime": "2026-09-13 10:00:00",
    "exchangeTime": "2026-09-13 10:00:00",
    "correlationId": "corr-456",
}


def _zerodha_prov() -> ZerodhaProvider:
    return ZerodhaProvider(BandlConfig(), ProviderSettings(api_key="k", access_token="t"))


def _dhan_prov() -> DhanProvider:
    return DhanProvider(BandlConfig(), ProviderSettings(api_key="cid123", access_token="jwt"))


# ===========================================================================
# 1. Typed Commands, Validation & Non-Truncation (R2, R3, R8)
# ===========================================================================


def test_order_request_enforces_exactly_one_instrument_identity() -> None:
    # 0 identities -> error
    with pytest.raises(ValueError, match="OrderRequest requires exactly one of"):
        OrderRequest(side=OrderSide.BUY, quantity=Decimal(1))

    # Multiple identities -> error
    c = OptionContract(
        underlying="GOLDM",
        expiry=date(2026, 7, 29),
        strike=Decimal("145000"),
        option_type=OptionType.CALL,
        exchange="MCX",
    )
    with pytest.raises(ValueError, match="OrderRequest requires exactly one of"):
        OrderRequest(symbol="RELIANCE", contract=c, side=OrderSide.BUY, quantity=Decimal(1))

    with pytest.raises(ValueError, match="OrderRequest requires exactly one of"):
        OrderRequest(
            symbol="RELIANCE", instrument_id="123", side=OrderSide.BUY, quantity=Decimal(1)
        )


def test_order_request_enforces_finite_positive_quantity() -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        OrderRequest(symbol="RELIANCE", side=OrderSide.BUY, quantity=Decimal(0))

    with pytest.raises(ValueError, match="finite and positive"):
        OrderRequest(symbol="RELIANCE", side=OrderSide.BUY, quantity=Decimal(-5))

    with pytest.raises(ValueError, match="(finite and positive|finite number)"):
        OrderRequest(symbol="RELIANCE", side=OrderSide.BUY, quantity=Decimal("NaN"))


def test_zerodha_rejects_fractional_shares() -> None:
    prov = _zerodha_prov()
    with pytest.raises(InvalidOrderError, match="requires integer share/lot quantity"):
        prov.place_order(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal(2500),
                quantity=Decimal("1.5"),
            )
        )


def test_dhan_rejects_fractional_shares() -> None:
    prov = _dhan_prov()
    with pytest.raises(InvalidOrderError, match="requires integer share/lot quantity"):
        prov.place_order(
            OrderRequest(
                instrument_id="1594",
                exchange="NSE",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal(500),
                quantity=Decimal("2.5"),
            )
        )


def test_zerodha_rejects_tag_exceeding_20_chars_without_truncation() -> None:
    prov = _zerodha_prov()
    oversized_tag = "tag_longer_than_twenty_characters"
    with pytest.raises(InvalidOrderError, match="length cannot exceed 20 characters"):
        prov.place_order(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal(2500),
                quantity=Decimal(10),
                client_order_id=oversized_tag,
            )
        )


def test_dhan_rejects_correlation_id_exceeding_30_chars_without_truncation() -> None:
    prov = _dhan_prov()
    oversized_id = "correlation_id_longer_than_thirty_characters_12345"
    with pytest.raises(InvalidOrderError, match="length cannot exceed 30 characters"):
        prov.place_order(
            OrderRequest(
                instrument_id="1594",
                exchange="NSE",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal(500),
                quantity=Decimal(10),
                client_order_id=oversized_id,
            )
        )


def test_limit_order_requires_price() -> None:
    prov = _zerodha_prov()
    with pytest.raises(InvalidOrderError, match="LIMIT orders require price"):
        prov.place_order(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(10),
                price=None,
            )
        )


def test_stop_orders_require_trigger_price() -> None:
    prov = _zerodha_prov()
    with pytest.raises(InvalidOrderError, match="orders require trigger_price"):
        prov.place_order(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                order_type=OrderType.STOP,
                quantity=Decimal(10),
                trigger_price=None,
            )
        )


def test_order_request_rejects_empty_or_whitespace_identities() -> None:
    with pytest.raises(ValueError, match="symbol cannot be empty or whitespace-only"):
        OrderRequest(symbol="", side=OrderSide.BUY, quantity=Decimal(1))

    with pytest.raises(ValueError, match="symbol cannot be empty or whitespace-only"):
        OrderRequest(symbol="   ", side=OrderSide.BUY, quantity=Decimal(1))

    with pytest.raises(ValueError, match="instrument_id cannot be empty or whitespace-only"):
        OrderRequest(instrument_id="", side=OrderSide.BUY, quantity=Decimal(1))

    with pytest.raises(ValueError, match="instrument_id cannot be empty or whitespace-only"):
        OrderRequest(instrument_id="   ", side=OrderSide.BUY, quantity=Decimal(1))


def test_order_request_validates_prices_and_disclosed_quantity() -> None:
    with pytest.raises(ValueError, match="price must be finite and positive"):
        OrderRequest(symbol="RELIANCE", side=OrderSide.BUY, quantity=Decimal(1), price=Decimal(0))

    with pytest.raises(ValueError, match="price must be finite and positive"):
        OrderRequest(symbol="RELIANCE", side=OrderSide.BUY, quantity=Decimal(1), price=Decimal(-5))

    with pytest.raises(ValueError, match="trigger_price must be finite and positive"):
        OrderRequest(
            symbol="RELIANCE", side=OrderSide.BUY, quantity=Decimal(1), trigger_price=Decimal(0)
        )

    with pytest.raises(ValueError, match=r"disclosed_quantity.*cannot exceed"):
        OrderRequest(
            symbol="RELIANCE",
            side=OrderSide.BUY,
            quantity=Decimal(10),
            disclosed_quantity=Decimal(15),
        )


@pytest.fixture(params=["zerodha", "dhan"])
def trading_provider_with_req(request: pytest.FixtureRequest):
    if request.param == "zerodha":
        prov = _zerodha_prov()
        prov._http.post_mutation = MagicMock()
        prov._http.put_mutation = MagicMock()
        prov._http.delete_mutation = MagicMock()
        req = OrderRequest(
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal(2500),
            quantity=Decimal(10),
        )
        return prov, req
    else:
        prov = _dhan_prov()
        prov._http.post_mutation = MagicMock()
        prov._http.put_mutation = MagicMock()
        prov._http.delete_mutation = MagicMock()
        req = OrderRequest(
            instrument_id="1594",
            exchange="NSE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal(500),
            quantity=Decimal(10),
        )
        return prov, req


def test_adapters_reject_quote_and_contracts_quantity(trading_provider_with_req) -> None:
    prov, base_req = trading_provider_with_req

    for unit in (QuantityUnit.QUOTE, QuantityUnit.CONTRACTS):
        req = base_req.model_copy(update={"quantity_unit": unit})
        with pytest.raises(UnsupportedCapabilityError):
            prov.place_order(req)
        prov._http.post_mutation.assert_not_called()


def test_adapters_reject_unsupported_flags(trading_provider_with_req) -> None:
    prov, base_req = trading_provider_with_req

    # reduce_only
    with pytest.raises(UnsupportedCapabilityError):
        prov.place_order(base_req.model_copy(update={"reduce_only": True}))
    prov._http.post_mutation.assert_not_called()

    # post_only
    with pytest.raises(UnsupportedCapabilityError):
        prov.place_order(base_req.model_copy(update={"post_only": True}))
    prov._http.post_mutation.assert_not_called()

    # position_side
    with pytest.raises(UnsupportedCapabilityError):
        prov.place_order(base_req.model_copy(update={"position_side": PositionSide.LONG}))
    prov._http.post_mutation.assert_not_called()

    # extra non-empty
    with pytest.raises(UnsupportedCapabilityError):
        prov.place_order(base_req.model_copy(update={"extra": {"custom": "flag"}}))
    prov._http.post_mutation.assert_not_called()


def test_adapters_reject_unsupported_market(trading_provider_with_req) -> None:
    prov, base_req = trading_provider_with_req
    with pytest.raises(UnsupportedCapabilityError):
        prov.place_order(base_req.model_copy(update={"market": "crypto"}))
    prov._http.post_mutation.assert_not_called()


def test_adapters_reject_empty_modification(trading_provider_with_req) -> None:
    prov, _ = trading_provider_with_req
    with pytest.raises(InvalidOrderError, match="requires at least one parameter"):
        prov.modify_order_ack("12345")
    prov._http.put_mutation.assert_not_called()


def test_adapters_reject_invalid_modification_fields(trading_provider_with_req) -> None:
    prov, _ = trading_provider_with_req

    # Zero / negative quantity
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", quantity=Decimal(0))
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", quantity=Decimal(-5))
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", quantity=Decimal("1.5"))

    # Zero / negative price
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", price=Decimal(0))
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", price=Decimal(-100))

    # Zero / negative trigger price
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", trigger_price=Decimal(0))
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", trigger_price=Decimal(-100))

    # Unsupported validity
    with pytest.raises(InvalidOrderError):
        prov.modify_order_ack("12345", validity="unsupported_validity")

    prov._http.put_mutation.assert_not_called()


def test_correlation_id_boundaries() -> None:
    # Zerodha tag: exactly 20 chars allowed, 21 rejected
    zprov = _zerodha_prov()
    zprov._http.post_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "111"}}
    )
    zprov.place_order_ack(
        OrderRequest(
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal(2500),
            quantity=Decimal(10),
            client_order_id="12345678901234567890",  # 20 chars
        )
    )
    assert zprov._http.post_mutation.call_count == 1

    with pytest.raises(InvalidOrderError, match="cannot exceed 20 characters"):
        zprov.place_order_ack(
            OrderRequest(
                symbol="RELIANCE",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal(2500),
                quantity=Decimal(10),
                client_order_id="123456789012345678901",  # 21 chars
            )
        )

    # Dhan correlationId: exactly 30 chars allowed, 31 rejected
    dprov = _dhan_prov()
    dprov._http.post_mutation = MagicMock(return_value={"orderId": "222"})
    dprov.place_order_ack(
        OrderRequest(
            instrument_id="1594",
            exchange="NSE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal(500),
            quantity=Decimal(10),
            client_order_id="123456789012345678901234567890",  # 30 chars
        )
    )
    assert dprov._http.post_mutation.call_count == 1

    with pytest.raises(InvalidOrderError, match="cannot exceed 30 characters"):
        dprov.place_order_ack(
            OrderRequest(
                instrument_id="1594",
                exchange="NSE",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal(500),
                quantity=Decimal(10),
                client_order_id="1234567890123456789012345678901",  # 31 chars
            )
        )


# ===========================================================================
# 2. Immediate Acknowledgements & Lost Response Handling (R4, R7)
# ===========================================================================


def test_zerodha_place_order_ack_returns_immediately_without_get() -> None:
    prov = _zerodha_prov()
    prov._http.post_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "151220000000001"}}
    )
    prov._http.get_json = MagicMock()

    ack = prov.place_order_ack(
        OrderRequest(
            symbol="INFY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(10),
            price=Decimal(1500),
            client_order_id="tag1",
        )
    )
    assert isinstance(ack, OrderAcknowledgement)
    assert ack.operation == "place"
    assert ack.order_id == "151220000000001"
    assert ack.client_order_id == "tag1"
    assert ack.provider_id == "zerodha"
    # Verify no follow-up GET was executed
    prov._http.get_json.assert_not_called()


def test_dhan_place_order_ack_returns_immediately_without_get() -> None:
    prov = _dhan_prov()
    prov._http.post_mutation = MagicMock(
        return_value={"orderId": "1122334455", "orderStatus": "PENDING"}
    )
    prov._http.get_json = MagicMock()

    ack = prov.place_order_ack(
        OrderRequest(
            instrument_id="1594",
            exchange="NSE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(10),
            price=Decimal(1500),
            client_order_id="corr1",
        )
    )
    assert isinstance(ack, OrderAcknowledgement)
    assert ack.operation == "place"
    assert ack.order_id == "1122334455"
    assert ack.client_order_id == "corr1"
    assert ack.provider_id == "dhan"
    prov._http.get_json.assert_not_called()


def test_accepted_mutation_with_lost_get_raises_uncertain_outcome_preserving_id() -> None:
    prov = _zerodha_prov()
    prov._http.post_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "151220000000001"}}
    )
    # GET fails with network timeout/server error
    prov._http.get_json = MagicMock(side_effect=ProviderError("zerodha", "Gateway timeout 504"))

    with pytest.raises(UncertainOutcomeError) as exc_info:
        prov.place_order(
            OrderRequest(
                symbol="INFY",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(10),
                price=Decimal(1500),
                client_order_id="tag1",
            )
        )
    err = exc_info.value
    # Crucial: Order ID is preserved in the exception!
    assert err.order_id == "151220000000001"
    assert err.client_order_id == "tag1"
    assert "status retrieval failed" in str(err)
    # Mutation must have been called strictly ONCE
    prov._http.post_mutation.assert_called_once()


def test_mutation_network_failure_raises_uncertain_outcome_with_no_retries() -> None:
    http = HttpClient(BandlConfig())
    req = httpx.Request("POST", "https://api.example.com/orders")

    # Mock _client.post to fail with RequestError
    http._client.post = MagicMock(
        side_effect=httpx.ConnectTimeout("Connection timed out", request=req)
    )

    with pytest.raises(UncertainOutcomeError) as exc_info:
        http.post_mutation(
            "https://api.example.com/orders",
            provider="test",
            body={"qty": 10},
            context={"order": "123"},
        )
    assert "outcome uncertain" in str(exc_info.value)
    # Exactly 1 call made; NO automatic retries on mutation
    assert http._client.post.call_count == 1


# ===========================================================================
# 2b. Separate Acknowledgement from Order State (T5)
# ===========================================================================


def test_order_acknowledgement_operation_literal_validation() -> None:
    # Valid operations: place, modify, cancel
    for op in ("place", "modify", "cancel"):
        ack = OrderAcknowledgement(
            operation=op,  # type: ignore[arg-type]
            provider_id="test",
            order_id="123",
            received_at=datetime.now(timezone.utc),
        )
        assert ack.operation == op

    # Invalid operation rejected by Pydantic
    with pytest.raises(ValidationError):
        OrderAcknowledgement(
            operation="execute",  # type: ignore[arg-type]
            provider_id="test",
            received_at=datetime.now(timezone.utc),
        )


def test_zerodha_acknowledgements_have_no_fabricated_status() -> None:
    prov = _zerodha_prov()
    prov._http.get_json = MagicMock()

    # Place ack
    prov._http.post_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "z_place_1"}}
    )
    p_ack = prov.place_order_ack(
        OrderRequest(
            symbol="INFY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(10),
            price=Decimal(1500),
        )
    )
    assert p_ack.order_id == "z_place_1"
    assert p_ack.status is None
    assert p_ack.received_at.tzinfo is not None

    # Modify ack
    prov._http.put_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "z_place_1"}}
    )
    m_ack = prov.modify_order_ack("z_place_1", price=Decimal(1550))
    assert m_ack.order_id == "z_place_1"
    assert m_ack.status is None
    assert m_ack.received_at.tzinfo is not None

    # Cancel ack
    prov._http.delete_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "z_place_1"}}
    )
    c_ack = prov.cancel_order_ack("z_place_1")
    assert c_ack.order_id == "z_place_1"
    assert c_ack.status is None
    assert c_ack.received_at.tzinfo is not None

    # Ensure zero GET requests were made across all 3 acknowledgement calls
    prov._http.get_json.assert_not_called()


def test_dhan_acknowledgements_preserve_native_status() -> None:
    prov = _dhan_prov()
    prov._http.get_json = MagicMock()

    # Place ack preserves PENDING
    prov._http.post_mutation = MagicMock(
        return_value={"orderId": "d_101", "orderStatus": "PENDING"}
    )
    p_ack = prov.place_order_ack(
        OrderRequest(
            instrument_id="1333",
            exchange="NSE",
            side=OrderSide.BUY,
            quantity=Decimal(10),
            price=Decimal(100),
        )
    )
    assert p_ack.order_id == "d_101"
    assert p_ack.status == "PENDING"
    assert p_ack.received_at.tzinfo is not None

    # Modify ack preserves PENDING
    prov._http.put_mutation = MagicMock(return_value={"orderId": "d_101", "orderStatus": "PENDING"})
    m_ack = prov.modify_order_ack("d_101", price=Decimal(105))
    assert m_ack.order_id == "d_101"
    assert m_ack.status == "PENDING"
    assert m_ack.received_at.tzinfo is not None

    # Cancel ack preserves CANCELLED (or whatever native status Dhan returns)
    prov._http.delete_mutation = MagicMock(
        return_value={"orderId": "d_101", "orderStatus": "CANCELLED"}
    )
    c_ack = prov.cancel_order_ack("d_101")
    assert c_ack.order_id == "d_101"
    assert c_ack.status == "CANCELLED"
    assert c_ack.received_at.tzinfo is not None

    prov._http.get_json.assert_not_called()


def test_cancel_order_followed_by_complete_reflects_fill_winning_race() -> None:
    # Test that legacy cancel_order reflects the true terminal order state (e.g. COMPLETE)
    # when an order gets filled before cancellation is processed
    prov = _zerodha_prov()
    prov._http.delete_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "z_race_1"}}
    )
    prov._http.get_json = MagicMock(
        return_value={
            "status": "success",
            "data": [
                {
                    "order_id": "z_race_1",
                    "status": "COMPLETE",
                    "filled_quantity": 10,
                    "pending_quantity": 0,
                    "quantity": 10,
                    "tradingsymbol": "INFY",
                    "exchange": "NSE",
                    "transaction_type": "BUY",
                    "order_type": "LIMIT",
                    "product": "CNC",
                    "validity": "DAY",
                    "variety": "regular",
                    "order_timestamp": "2024-01-01 10:00:00",
                }
            ],
        }
    )

    cancelled_order = prov.cancel_order("z_race_1")
    assert cancelled_order.order_id == "z_race_1"
    # Order state is COMPLETE, correctly showing the fill won the race against cancel
    assert cancelled_order.status == OrderStatus.COMPLETE


def test_acknowledgement_succeeds_when_separate_status_get_fails() -> None:
    prov = _zerodha_prov()
    prov._http.post_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "z_ok_1"}}
    )
    prov._http.get_json = MagicMock(side_effect=ProviderError("zerodha", "500 Internal Error"))

    # place_order_ack succeeds despite get_json being broken
    ack = prov.place_order_ack(
        OrderRequest(
            symbol="INFY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(10),
            price=Decimal(1500),
        )
    )
    assert ack.order_id == "z_ok_1"
    # get_json was never called by ack
    prov._http.get_json.assert_not_called()


# ===========================================================================
# 3. Lossless State & Pending Status Preservation (R5)
# ===========================================================================


def test_zerodha_preserves_distinct_pending_statuses_and_raw_status() -> None:
    prov = _zerodha_prov()

    trigger_row = dict(_KITE_ORDER_ROW, order_id="101", status="TRIGGER PENDING")
    modify_row = dict(_KITE_ORDER_ROW, order_id="102", status="MODIFY PENDING")
    cancel_row = dict(_KITE_ORDER_ROW, order_id="103", status="CANCEL PENDING")

    prov._http.get_json = MagicMock(
        return_value={"status": "success", "data": [trigger_row, modify_row, cancel_row]}
    )

    orders = prov.get_orders()
    assert len(orders) == 3

    assert orders[0].status == OrderStatus.TRIGGER_PENDING
    assert orders[0].raw_status == "TRIGGER PENDING"

    assert orders[1].status == OrderStatus.MODIFY_PENDING
    assert orders[1].raw_status == "MODIFY PENDING"

    assert orders[2].status == OrderStatus.CANCEL_PENDING
    assert orders[2].raw_status == "CANCEL PENDING"


def test_dhan_preserves_raw_status() -> None:
    prov = _dhan_prov()
    prov._http.get_json = MagicMock(return_value=[_DHAN_ORDER_ROW])

    orders = prov.get_orders()
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.OPEN
    assert orders[0].raw_status == "PENDING"


# ===========================================================================
# 4. Recovery Reads: All Orders & Order History (R6)
# ===========================================================================


def test_get_orders_returns_both_open_and_terminal_orders() -> None:
    prov = _zerodha_prov()
    open_row = dict(_KITE_ORDER_ROW, order_id="1", status="OPEN")
    complete_row = dict(_KITE_ORDER_ROW, order_id="2", status="COMPLETE")
    cancelled_row = dict(_KITE_ORDER_ROW, order_id="3", status="CANCELLED")
    rejected_row = dict(_KITE_ORDER_ROW, order_id="4", status="REJECTED")

    prov._http.get_json = MagicMock(
        return_value={
            "status": "success",
            "data": [open_row, complete_row, cancelled_row, rejected_row],
        }
    )

    # get_open_orders returns only non-terminal orders
    open_orders = prov.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].order_id == "1"

    # get_orders returns all session orders including terminal states
    all_orders = prov.get_orders()
    assert len(all_orders) == 4
    statuses = {o.status for o in all_orders}
    assert statuses == {
        OrderStatus.OPEN,
        OrderStatus.COMPLETE,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
    }


def test_zerodha_get_order_history_returns_state_transitions() -> None:
    prov = _zerodha_prov()
    step1 = dict(_KITE_ORDER_ROW, status="VALIDATION PENDING")
    step2 = dict(_KITE_ORDER_ROW, status="OPEN")
    step3 = dict(_KITE_ORDER_ROW, status="COMPLETE", filled_quantity=10, pending_quantity=0)

    prov._http.get_json = MagicMock(
        return_value={"status": "success", "data": [step1, step2, step3]}
    )

    history = prov.get_order_history("151220000000001")
    assert len(history) == 3
    assert history[0].status == OrderStatus.OPEN  # validation pending maps to open
    assert history[0].raw_status == "VALIDATION PENDING"
    assert history[2].status == OrderStatus.COMPLETE
    assert history[2].filled_quantity == Decimal(10)


# ===========================================================================
# 4b. Honest Capability & Recovery Contracts (T6)
# ===========================================================================


class _MinimalPlaceCustomProvider:
    provider_id = "minimal_place"
    bound_account_id = None

    def trade_capabilities(self) -> TradeCapabilities:
        return TradeCapabilities(
            provider_id="minimal_place",
            place=CapabilityDetail(supported=True),
            modify=CapabilityDetail(supported=False),
            cancel=CapabilityDetail(supported=False),
            get_open_orders=CapabilityDetail(supported=False),
            get_orders=CapabilityDetail(supported=False),
            get_order=CapabilityDetail(supported=False),
            get_order_history=CapabilityDetail(supported=False),
            get_trades=CapabilityDetail(supported=False),
        )

    def place_order(self, order: OrderRequest, *, account_id: str | None = None) -> Order:
        sym = order.symbol or "TEST"
        return Order(
            order_id="m_123",
            symbol=sym,
            symbol_native=sym,
            segment=Segment.EQUITY_CASH,
            side=order.side,
            order_type=order.order_type.value,
            product=ProductType.DELIVERY,
            validity=Validity.DAY,
            status=OrderStatus.OPEN,
            quantity=order.quantity,
            filled_quantity=Decimal(0),
            source=self.provider_id,
            created_at=datetime.now(timezone.utc),
            dedup_key=f"{self.provider_id}:order:m_123",
        )


def test_minimal_custom_provider_place_only_works_and_rejects_other_operations() -> None:
    client = Bandl()
    custom = _MinimalPlaceCustomProvider()
    client.register_provider("minimal_place", custom)

    order_req = OrderRequest(
        symbol="INFY",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(1500),
        quantity=Decimal(10),
    )
    # Place order succeeds
    res = client.trade.place_order(order_req, source="minimal_place")
    assert res.order_id == "m_123"

    # Place ack raises UnsupportedCapabilityError because provider lacks place_order_ack
    with pytest.raises(UnsupportedCapabilityError, match="place_order_ack"):
        client.trade.place_order_ack(order_req, source="minimal_place")

    # Unsupported operations raise UnsupportedCapabilityError
    with pytest.raises(UnsupportedCapabilityError, match="modify"):
        client.trade.modify_order("m_123", price=Decimal(1600), source="minimal_place")

    with pytest.raises(UnsupportedCapabilityError, match="cancel"):
        client.trade.cancel_order("m_123", source="minimal_place")

    with pytest.raises(UnsupportedCapabilityError, match="get_orders"):
        client.trade.get_orders(source="minimal_place")

    with pytest.raises(UnsupportedCapabilityError, match="get_open_orders"):
        client.trade.get_open_orders(source="minimal_place")

    with pytest.raises(UnsupportedCapabilityError, match="order_history"):
        client.trade.get_order_history("m_123", source="minimal_place")


def test_capability_false_despite_method_existing_raises_unsupported() -> None:
    class _ProviderWithMethodButCapabilityFalse:
        provider_id = "false_cap"
        bound_account_id = None

        def trade_capabilities(self) -> TradeCapabilities:
            return TradeCapabilities(
                provider_id="false_cap",
                modify=CapabilityDetail(supported=False),
            )

        def modify_order(self, order_id: str, **kwargs: Any) -> Order:
            raise RuntimeError("Should never be called")

    client = Bandl()
    client.register_provider("false_cap", _ProviderWithMethodButCapabilityFalse())

    with pytest.raises(UnsupportedCapabilityError):
        client.trade.modify_order("123", source="false_cap")


def test_dhan_order_history_unsupported_and_single_order_supported() -> None:
    prov = _dhan_prov()
    caps = prov.trade_capabilities()
    assert caps.get_order_history.supported is False

    with pytest.raises(UnsupportedCapabilityError, match="order_history"):
        prov.get_order_history("123")

    client = Bandl(
        BandlConfig(providers={"dhan": ProviderSettings(api_key="cid123", access_token="tok")})
    )
    with pytest.raises(UnsupportedCapabilityError, match="order_history"):
        client.trade.get_order_history("123", source="dhan")

    # Single order state remains available
    prov._http.get_json = MagicMock(return_value=_DHAN_ORDER_ROW)
    client.register_provider("dhan", prov)
    ord_state = client.trade.get_order("123", source="dhan")
    assert ord_state.order_id == "1122334455"


def test_trade_get_orders_does_not_fall_back_to_get_open_orders() -> None:
    class _OnlyOpenOrdersProvider:
        provider_id = "only_open"
        bound_account_id = None

        def trade_capabilities(self) -> TradeCapabilities:
            return TradeCapabilities(
                provider_id="only_open",
                get_open_orders=CapabilityDetail(supported=True),
                get_orders=CapabilityDetail(supported=False),
            )

        def get_open_orders(self, **kwargs: Any) -> list[Order]:
            return []

    client = Bandl()
    client.register_provider("only_open", _OnlyOpenOrdersProvider())

    with pytest.raises(UnsupportedCapabilityError, match="get_orders"):
        client.trade.get_orders(source="only_open")


def test_portfolio_facet_raises_unsupported_when_not_supported() -> None:
    class _PartialPortfolioProvider:
        provider_id = "partial_port"
        bound_account_id = None

        def portfolio_capabilities(self) -> PortfolioCapabilities:
            return PortfolioCapabilities(
                provider_id="partial_port",
                positions=CapabilityDetail(supported=False),
                holdings=CapabilityDetail(supported=False),
                balances=CapabilityDetail(supported=False),
                margin=CapabilityDetail(supported=False),
            )

    client = Bandl()
    client.register_provider("partial_port", _PartialPortfolioProvider())

    with pytest.raises(UnsupportedCapabilityError, match="positions"):
        client.portfolio.get_positions(source="partial_port")

    with pytest.raises(UnsupportedCapabilityError, match="holdings"):
        client.portfolio.get_holdings(source="partial_port")

    with pytest.raises(UnsupportedCapabilityError, match="balances"):
        client.portfolio.get_balances(source="partial_port")

    with pytest.raises(UnsupportedCapabilityError, match="margin"):
        client.portfolio.get_margin(source="partial_port")


def test_unknown_raw_statuses_preserved_as_unknown() -> None:
    z_prov = _zerodha_prov()
    mystery_z = dict(_KITE_ORDER_ROW, status="PENDING_APPROVAL")
    z_prov._http.get_json = MagicMock(return_value={"status": "success", "data": [mystery_z]})
    z_orders = z_prov.get_orders()
    assert len(z_orders) == 1
    assert z_orders[0].status == OrderStatus.UNKNOWN
    assert z_orders[0].raw_status == "PENDING_APPROVAL"

    d_prov = _dhan_prov()
    mystery_d = dict(_DHAN_ORDER_ROW, orderStatus="INVESTIGATING")
    d_prov._http.get_json = MagicMock(return_value=[mystery_d])
    d_orders = d_prov.get_orders()
    assert len(d_orders) == 1
    assert d_orders[0].status == OrderStatus.UNKNOWN
    assert d_orders[0].raw_status == "INVESTIGATING"


def test_partial_fills_mapped_and_included_in_open_orders() -> None:
    z_prov = _zerodha_prov()
    partial_z = dict(
        _KITE_ORDER_ROW,
        status="OPEN",
        quantity=10,
        filled_quantity=4,
        pending_quantity=6,
    )
    z_prov._http.get_json = MagicMock(return_value={"status": "success", "data": [partial_z]})
    z_open = z_prov.get_open_orders()
    assert len(z_open) == 1
    assert z_open[0].status == OrderStatus.PARTIAL
    assert z_open[0].filled_quantity == Decimal(4)
    assert z_open[0].pending_quantity == Decimal(6)

    d_prov = _dhan_prov()
    partial_d = dict(
        _DHAN_ORDER_ROW,
        orderStatus="PART_TRADED",
        quantity=10,
        filledQty=4,
        remainingQuantity=6,
    )
    d_prov._http.get_json = MagicMock(return_value=[partial_d])
    d_open = d_prov.get_open_orders()
    assert len(d_open) == 1
    assert d_open[0].status == OrderStatus.PARTIAL
    assert d_open[0].filled_quantity == Decimal(4)
    assert d_open[0].pending_quantity == Decimal(6)


def test_zerodha_account_history_versus_trade_order_dispatch_through_bandl() -> None:
    client = Bandl(
        BandlConfig(providers={"zerodha": ProviderSettings(api_key="k", access_token="t")})
    )
    kite_mock_rows = [
        dict(_KITE_ORDER_ROW, order_id="ord_hist_1", status="COMPLETE", filled_quantity=10)
    ]
    client._get_provider("zerodha")._http.get_json = MagicMock(
        return_value={"status": "success", "data": kite_mock_rows}
    )

    # Account history facet returns list[AccountOrder]
    acc_orders = client.account.get_orders(source="zerodha")
    assert len(acc_orders) == 1
    assert isinstance(acc_orders[0], AccountOrder)
    assert acc_orders[0].order_id == "ord_hist_1"

    # Trade facet returns list[Order]
    trade_orders = client.trade.get_orders(source="zerodha")
    assert len(trade_orders) == 1
    assert isinstance(trade_orders[0], Order)
    assert trade_orders[0].order_id == "ord_hist_1"


def test_market_only_provider_rejects_trade_and_portfolio_facets() -> None:
    class _MarketOnlyProvider:
        provider_id = "market_only"

    client = Bandl()
    client.register_provider("market_only", _MarketOnlyProvider())

    order_req = OrderRequest(
        symbol="INFY",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(1500),
        quantity=Decimal(10),
    )
    with pytest.raises(ConfigurationError, match="does not support trading"):
        client.trade.place_order(order_req, source="market_only")

    with pytest.raises(ConfigurationError, match="does not support portfolio"):
        client.portfolio.get_positions(source="market_only")


# ===========================================================================
# 5. Account Isolation & Credential Redaction (R1, R12)
# ===========================================================================


def test_account_id_scoping_in_orders_and_dedup_keys() -> None:
    prov = _dhan_prov()
    prov._http.get_json = MagicMock(return_value=[_DHAN_ORDER_ROW])

    orders = prov.get_orders(account_id="cid123")
    assert len(orders) == 1
    assert orders[0].account_id == "cid123"
    assert "acc:cid123" in orders[0].dedup_key


def test_dhan_mismatched_account_rejected_zero_requests() -> None:
    prov = _dhan_prov()
    prov._http.post_mutation = MagicMock()
    prov._http.get_json = MagicMock()

    order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
    )
    with pytest.raises(ConfigurationError, match="does not match bound account"):
        prov.place_order(order, account_id="wrong_account")
    prov._http.post_mutation.assert_not_called()

    with pytest.raises(ConfigurationError, match="does not match bound account"):
        prov.get_orders(account_id="wrong_account")
    prov._http.get_json.assert_not_called()


def test_zerodha_unverified_account_rejected_zero_requests() -> None:
    prov = _zerodha_prov()
    prov._http.post_mutation = MagicMock()
    prov._http.get_json = MagicMock()

    order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
    )
    with pytest.raises(ConfigurationError, match="no known bound account"):
        prov.place_order(order, account_id="sub-acc-99")
    prov._http.post_mutation.assert_not_called()

    with pytest.raises(ConfigurationError, match="no known bound account"):
        prov.get_orders(account_id="sub-acc-99")
    prov._http.get_json.assert_not_called()


def test_zerodha_unverified_account_never_reflected_back() -> None:
    prov = _zerodha_prov()
    prov._http.get_json = MagicMock(return_value={"status": "success", "data": [_KITE_ORDER_ROW]})

    orders = prov.get_orders()
    assert len(orders) == 1
    assert orders[0].account_id is None
    assert "acc:" not in orders[0].dedup_key


def test_trade_facet_does_not_mutate_order_request_account_id() -> None:
    from bandl import Bandl
    from bandl.config import BandlConfig, ProviderSettings

    cfg = BandlConfig(
        providers={
            "dhan": ProviderSettings(api_key="cid123", access_token="jwt"),
        }
    )
    client = Bandl(config=cfg)
    prov = client._get_provider("dhan")
    prov._http.post_mutation = MagicMock(
        return_value={"orderId": "112111182198", "orderStatus": "TRANSIT"}
    )
    prov._http.get_json = MagicMock(return_value=_DHAN_ORDER_ROW)
    prov._scrip.resolve_symbol = MagicMock(return_value=1333)

    req = OrderRequest(
        instrument_id="1333",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(15),
        price=Decimal("150.00"),
        account_id=None,
    )
    client.trade.place_order(req, source="dhan", account_id="cid123")
    assert req.account_id is None

    req_with_acc = OrderRequest(
        instrument_id="1333",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(15),
        price=Decimal("150.00"),
        account_id="cid123",
    )
    client.trade.place_order(req_with_acc, source="dhan")
    assert req_with_acc.account_id == "cid123"


def test_portfolio_facet_account_binding_verification() -> None:
    from bandl import Bandl
    from bandl.config import BandlConfig, ProviderSettings

    cfg = BandlConfig(
        providers={
            "dhan": ProviderSettings(api_key="cid123", access_token="jwt"),
            "zerodha": ProviderSettings(api_key="key", access_token="token"),
        }
    )
    client = Bandl(config=cfg)
    dprov = client._get_provider("dhan")
    dprov._http.get_json = MagicMock(return_value=[])

    zprov = client._get_provider("zerodha")
    zprov._http.get_json = MagicMock(return_value={"status": "success", "data": {"net": []}})

    with pytest.raises(ConfigurationError, match="does not match bound account"):
        client.portfolio.get_positions(source="dhan", account_id="wrong_id")
    dprov._http.get_json.assert_not_called()

    with pytest.raises(ConfigurationError, match="no known bound account"):
        client.portfolio.get_positions(source="zerodha", account_id="sub-acc-99")
    zprov._http.get_json.assert_not_called()


def test_account_binding_contract_comprehensive() -> None:
    from bandl import Bandl
    from bandl.config import BandlConfig, ProviderSettings

    # 1. Conflicting Dhan config (settings.account_id != settings.api_key) raises ConfigurationError
    with pytest.raises(ConfigurationError, match="Conflicting Dhan account_id"):
        BandlConfig(
            providers={
                "dhan": ProviderSettings(
                    api_key="cid123", access_token="jwt", account_id="different_acc"
                ),
            }
        )
        DhanProvider(
            BandlConfig(),
            ProviderSettings(api_key="cid123", access_token="jwt", account_id="different_acc"),
        )

    # 2. request A + argument B fails before HTTP
    cfg = BandlConfig(
        providers={
            "dhan": ProviderSettings(api_key="cid123", access_token="jwt"),
        }
    )
    client = Bandl(config=cfg)
    prov = client._get_provider("dhan")
    prov._http.post_mutation = MagicMock()

    req_a = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
        account_id="accA",
    )
    with pytest.raises(ConfigurationError, match="Conflicting account_id"):
        client.trade.place_order(req_a, source="dhan", account_id="accB")
    prov._http.post_mutation.assert_not_called()

    # 3. request A + provider B fails before HTTP
    with pytest.raises(ConfigurationError, match="does not match bound account"):
        client.trade.place_order(req_a, source="dhan")
    prov._http.post_mutation.assert_not_called()

    # 4. explicit A + unknown binding fails
    zcfg = BandlConfig(
        providers={
            "zerodha": ProviderSettings(api_key="key", access_token="jwt"),
        }
    )
    zclient = Bandl(config=zcfg)
    zprov = zclient._get_provider("zerodha")
    zprov._http.post_mutation = MagicMock()

    with pytest.raises(ConfigurationError, match="no known bound account"):
        zclient.trade.place_order(req_a, source="zerodha")
    zprov._http.post_mutation.assert_not_called()

    # 5. bound A + omitted argument returns A in orders, balances, margin
    prov._http.get_json = MagicMock(return_value=[_DHAN_ORDER_ROW])
    prov._fund_limit = MagicMock(return_value={"availabelBalance": 10000, "utilizedAmount": 2000})

    orders = client.trade.get_orders(source="dhan")
    assert orders[0].account_id == "cid123"
    assert "acc:cid123" in orders[0].dedup_key

    balances = client.portfolio.get_balances(source="dhan")
    assert balances[0].account_id == "cid123"

    margin = client.portfolio.get_margin(source="dhan")
    assert margin.account_id == "cid123"

    # 6. omitted/unbound retains None for unconfigured Zerodha
    zprov._http.get_json = MagicMock(return_value={"status": "success", "data": [_KITE_ORDER_ROW]})
    zprov._margins = MagicMock(return_value={"equity": {"net": 5000, "utilised": {"debits": 500}}})
    zorders = zclient.trade.get_orders(source="zerodha")
    assert zorders[0].account_id is None
    assert "acc:" not in zorders[0].dedup_key

    zbalances = zclient.portfolio.get_balances(source="zerodha")
    assert zbalances[0].account_id is None

    zmargin = zclient.portfolio.get_margin(source="zerodha")
    assert zmargin.account_id is None

    # 7. Two separately configured fake clients yield distinct account-scoped keys
    c1 = Bandl(
        config=BandlConfig(
            providers={"dhan": ProviderSettings(api_key="ACC_1", access_token="jwt")}
        )
    )
    c2 = Bandl(
        config=BandlConfig(
            providers={"dhan": ProviderSettings(api_key="ACC_2", access_token="jwt")}
        )
    )
    p1 = c1._get_provider("dhan")
    p2 = c2._get_provider("dhan")
    p1._http.get_json = MagicMock(return_value=[_DHAN_ORDER_ROW])
    p2._http.get_json = MagicMock(return_value=[_DHAN_ORDER_ROW])

    o1 = c1.trade.get_orders(source="dhan")[0]
    o2 = c2.trade.get_orders(source="dhan")[0]
    assert o1.order_id == o2.order_id
    assert o1.account_id == "ACC_1"
    assert o2.account_id == "ACC_2"
    assert o1.dedup_key != o2.dedup_key
    assert "acc:ACC_1" in o1.dedup_key
    assert "acc:ACC_2" in o2.dedup_key

    # 8. Provider TypeError is NOT caught or retried in portfolio facet
    class BrokenPortfolioProvider:
        provider_id = "broken"
        bound_account_id = None

        def portfolio_capabilities(self):
            from bandl.core.capabilities import CapabilityDetail, PortfolioCapabilities

            return PortfolioCapabilities(
                provider_id="broken",
                positions=CapabilityDetail(supported=True),
            )

        def get_positions(self, *, account_id: str | None = None):
            raise TypeError("Real internal bug inside provider get_positions")

        def get_holdings(self, *, account_id: str | None = None):
            return []

        def get_balances(self, *, account_id: str | None = None):
            return []

        def get_margin(self, *, account_id: str | None = None):
            raise NotImplementedError()

    broken_client = Bandl(custom_providers={"broken": BrokenPortfolioProvider()})
    with pytest.raises(TypeError, match="Real internal bug inside provider get_positions"):
        broken_client.portfolio.get_positions(source="broken")


def test_redact_dict_protects_sensitive_tokens() -> None:
    raw = {
        "api-key": "secret123",
        "Authorization": "Bearer supersecretjwt",
        "access_token": "tokenABC",
        "symbol": "BTCUSDT",
        "quantity": 1,
    }
    redacted = _redact_dict(raw)
    assert redacted["api-key"] == "[REDACTED]"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["symbol"] == "BTCUSDT"
    assert redacted["quantity"] == 1


# ===========================================================================
# 5b. Safe Transport Encoding & Single-Attempt Mutations (T3, R7)
# ===========================================================================


def test_zerodha_place_and_modify_use_form_encoding() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.path.endswith("/orders/regular"):
            return httpx.Response(
                200, json={"status": "success", "data": {"order_id": "2401010001"}}
            )
        if "/orders/regular/" in request.url.path:
            return httpx.Response(
                200, json={"status": "success", "data": {"order_id": "2401010001"}}
            )
        return httpx.Response(404, json={})

    prov = _zerodha_prov()
    prov._http._client = httpx.Client(transport=httpx.MockTransport(handler))

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
    )
    ack = prov.place_order_ack(req)
    assert ack.order_id == "2401010001"
    assert len(captured_requests) == 1
    place_req = captured_requests[0]
    assert "application/x-www-form-urlencoded" in place_req.headers.get("content-type", "")
    parsed_body = urllib.parse.parse_qs(place_req.content.decode("utf-8"))
    assert parsed_body["tradingsymbol"] == ["RELIANCE"]
    assert parsed_body["quantity"] == ["10"]
    assert parsed_body["price"] == ["2500.00"]
    assert parsed_body["transaction_type"] == ["BUY"]

    # Modify
    mod_ack = prov.modify_order_ack("2401010001", price=Decimal("2510.00"), quantity=Decimal(20))
    assert mod_ack.order_id == "2401010001"
    assert len(captured_requests) == 2
    mod_req = captured_requests[1]
    assert mod_req.method == "PUT"
    assert "application/x-www-form-urlencoded" in mod_req.headers.get("content-type", "")
    parsed_mod_body = urllib.parse.parse_qs(mod_req.content.decode("utf-8"))
    assert parsed_mod_body["price"] == ["2510.00"]
    assert parsed_mod_body["quantity"] == ["20"]


def test_dhan_place_and_modify_use_json_encoding() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.path.endswith("/orders"):
            return httpx.Response(200, json={"orderId": "112111182198", "orderStatus": "TRANSIT"})
        if "/orders/" in request.url.path:
            return httpx.Response(200, json={"orderId": "112111182198", "orderStatus": "TRANSIT"})
        return httpx.Response(404, json={})

    prov = _dhan_prov()
    prov._http._client = httpx.Client(transport=httpx.MockTransport(handler))

    req = OrderRequest(
        instrument_id="1333",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
    )
    ack = prov.place_order_ack(req)
    assert ack.order_id == "112111182198"
    assert len(captured_requests) == 1
    place_req = captured_requests[0]
    assert "application/json" in place_req.headers.get("content-type", "")
    parsed_body = json.loads(place_req.content.decode("utf-8"))
    assert parsed_body["securityId"] == "1333"
    assert parsed_body["quantity"] == 10
    assert parsed_body["price"] == 2500.0

    # Modify
    mod_ack = prov.modify_order_ack("112111182198", price=Decimal("2510.00"), quantity=Decimal(20))
    assert mod_ack.order_id == "112111182198"
    assert len(captured_requests) == 2
    mod_req = captured_requests[1]
    assert mod_req.method == "PUT"
    assert "application/json" in mod_req.headers.get("content-type", "")
    parsed_mod_body = json.loads(mod_req.content.decode("utf-8"))
    assert parsed_mod_body["price"] == 2510.0
    assert parsed_mod_body["quantity"] == 20


def test_cancel_url_and_method() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if "kite.trade" in str(request.url):
            return httpx.Response(200, json={"status": "success", "data": {"order_id": "z_123"}})
        return httpx.Response(200, json={"orderId": "d_123", "orderStatus": "CANCELLED"})

    zprov = _zerodha_prov()
    zprov._http._client = httpx.Client(transport=httpx.MockTransport(handler))
    zack = zprov.cancel_order_ack("z_123")
    assert zack.order_id == "z_123"
    assert captured[0].method == "DELETE"
    assert captured[0].url.path == "/orders/regular/z_123"

    dprov = _dhan_prov()
    dprov._http._client = httpx.Client(transport=httpx.MockTransport(handler))
    dack = dprov.cancel_order_ack("d_123")
    assert dack.order_id == "d_123"
    assert captured[1].method == "DELETE"
    assert captured[1].url.path == "/v2/orders/d_123"


def test_mutation_methods_send_once_on_timeout_and_503() -> None:
    calls = 0

    def fail_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls % 2 == 1:
            raise httpx.ConnectTimeout("Network timed out")
        return httpx.Response(503, text="Service Unavailable")

    cfg = BandlConfig()
    http = HttpClient(cfg)
    http._client = httpx.Client(transport=httpx.MockTransport(fail_handler))

    # POST mutation on timeout -> exactly 1 attempt
    calls = 0
    with pytest.raises(UncertainOutcomeError, match="Network failure during mutation"):
        http.post_mutation("https://api.example.com/orders", provider="test", body={"a": 1})
    assert calls == 1

    # POST mutation on 503 -> exactly 1 attempt
    calls = 1  # will trigger 503
    with pytest.raises(UncertainOutcomeError, match="Server error 503 during mutation"):
        http.post_mutation("https://api.example.com/orders", provider="test", body={"a": 1})
    assert calls == 2

    # PUT mutation on timeout -> exactly 1 attempt
    calls = 0
    with pytest.raises(UncertainOutcomeError, match="Network failure during modify mutation"):
        http.put_mutation("https://api.example.com/orders/1", provider="test", body={"a": 1})
    assert calls == 1

    # PUT mutation on 503 -> exactly 1 attempt
    calls = 1
    with pytest.raises(UncertainOutcomeError, match="Server error 503 during modify mutation"):
        http.put_mutation("https://api.example.com/orders/1", provider="test", body={"a": 1})
    assert calls == 2

    # DELETE mutation on timeout -> exactly 1 attempt
    calls = 0
    with pytest.raises(UncertainOutcomeError, match="Network failure during cancel mutation"):
        http.delete_mutation("https://api.example.com/orders/1", provider="test")
    assert calls == 1

    # DELETE mutation on 503 -> exactly 1 attempt
    calls = 1
    with pytest.raises(UncertainOutcomeError, match="Server error 503 during cancel mutation"):
        http.delete_mutation("https://api.example.com/orders/1", provider="test")
    assert calls == 2


def test_read_retries_still_work_with_backoff_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    import bandl.core.http as http_mod

    monkeypatch.setattr(http_mod, "_sleep_backoff", lambda attempt: None)

    calls = 0

    def flaky_read(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, text="Temporary error")
        return httpx.Response(200, json={"data": "ok"})

    cfg = BandlConfig(max_http_retries=3)
    client = HttpClient(cfg)
    client._client = httpx.Client(transport=httpx.MockTransport(flaky_read))

    res = client.get_json("https://api.example.com/read", provider="test")
    assert res == {"data": "ok"}
    assert calls == 3


def test_legacy_place_order_through_mock_transport() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "POST":
            return httpx.Response(
                200, json={"status": "success", "data": {"order_id": "2401010001"}}
            )
        if request.method == "GET":
            row = dict(_KITE_ORDER_ROW)
            row["order_id"] = "2401010001"
            return httpx.Response(200, json={"status": "success", "data": [row]})
        return httpx.Response(404, json={})

    prov = _zerodha_prov()
    prov._http._client = httpx.Client(transport=httpx.MockTransport(handler))

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
    )
    order = prov.place_order(req)
    assert order.order_id == "2401010001"
    assert len(captured) == 2
    assert captured[0].method == "POST"
    assert "application/x-www-form-urlencoded" in captured[0].headers.get("content-type", "")
    assert captured[1].method == "GET"
    assert captured[1].url.path == "/orders/2401010001"


# ===========================================================================
# 5c. Complete uncertain-outcome errors and safe diagnostics (T4)
# ===========================================================================


def test_redaction_recursive_mappings_sequences_and_normalized_keys() -> None:
    raw_ctx = {
        "operation": "place",
        "nested": {
            "api_key": "super_secret_1",
            "access-token": "super_secret_2",
            "regular_field": 123,
        },
        "sequence": [
            {"apiKey": "super_secret_3", "clean": "ok"},
            {"PASSWORD": "secret_pass", "nested_list": ["auth_token_here"]},
        ],
        "Authorization": "Bearer tok_12345",
        "secret": "confidential",
    }
    redacted = _redact_dict(raw_ctx)

    assert redacted["operation"] == "place"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["access-token"] == "[REDACTED]"
    assert redacted["nested"]["regular_field"] == 123
    assert redacted["sequence"][0]["apiKey"] == "[REDACTED]"
    assert redacted["sequence"][0]["clean"] == "ok"
    assert redacted["sequence"][1]["PASSWORD"] == "[REDACTED]"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["secret"] == "[REDACTED]"

    # Verify no sentinel secret leaked into json or str representations
    dumped = json.dumps(redacted)
    assert "super_secret" not in dumped
    assert "secret_pass" not in dumped
    assert "tok_12345" not in dumped
    assert "confidential" not in dumped


def test_safe_url_and_bounded_sanitized_error_diagnostics() -> None:
    from bandl.core.http import _provider_http_error

    request = httpx.Request(
        "GET",
        "https://api.kite.trade/orders?api_key=SECRET_KITE_KEY&access_token=SECRET_TOK",
    )
    long_body = "x" * 2500
    response = httpx.Response(
        500,
        text=long_body,
        request=request,
    )
    err = httpx.HTTPStatusError("500 Server Error", request=request, response=response)
    p_err = _provider_http_error("zerodha", err)

    err_str = str(p_err)
    assert "SECRET_KITE_KEY" not in err_str
    assert "SECRET_TOK" not in err_str
    assert "https://api.kite.trade/orders" in err_str
    assert "?" not in err_str.split("orders")[1].split(" ")[0]
    # Bounded detail length
    assert len(err_str) < 1600


def test_429_rate_limit_preserves_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "12.5"},
            text="Too Many Requests",
        )

    cfg = BandlConfig()
    client = HttpClient(cfg)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(RateLimitError) as exc_info:
        client.get_json("https://api.example.com/test", provider="test")

    assert exc_info.value.code == "429"
    assert exc_info.value.retry_after == 12.5
    assert exc_info.value.retryable is True


def test_mutation_malformed_json_raises_uncertain_outcome() -> None:
    def bad_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="NOT_VALID_JSON{{{")

    cfg = BandlConfig()
    client = HttpClient(cfg)
    client._client = httpx.Client(transport=httpx.MockTransport(bad_json_handler))

    with pytest.raises(UncertainOutcomeError) as exc_info:
        client.post_mutation(
            "https://api.example.com/orders",
            provider="zerodha",
            body={"test": 1},
            context={"operation": "place", "client_order_id": "c_999"},
        )
    assert exc_info.value.operation == "place"
    assert exc_info.value.client_order_id == "c_999"
    assert "invalid JSON" in str(exc_info.value)


def test_missing_or_null_or_empty_id_raises_uncertain_outcome() -> None:
    # Zerodha returns 200 with null order_id
    def z_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"order_id": None}})

    zprov = _zerodha_prov()
    zprov._http._client = httpx.Client(transport=httpx.MockTransport(z_handler))

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
        client_order_id="correl_123",
    )
    with pytest.raises(UncertainOutcomeError) as exc_info:
        zprov.place_order_ack(req)
    assert exc_info.value.operation == "place"
    assert exc_info.value.client_order_id == "correl_123"
    assert "Missing or empty order_id" in str(exc_info.value)

    # Dhan returns 200 with empty orderId
    def d_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"orderId": "", "orderStatus": "TRANSIT"})

    dprov = _dhan_prov()
    dprov._http._client = httpx.Client(transport=httpx.MockTransport(d_handler))
    dreq = OrderRequest(
        instrument_id="1333",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
        client_order_id="correl_456",
    )
    with pytest.raises(UncertainOutcomeError) as exc_info:
        dprov.place_order_ack(dreq)
    assert exc_info.value.operation == "place"
    assert exc_info.value.client_order_id == "correl_456"
    assert "Missing or empty orderId" in str(exc_info.value)


def test_successful_mutation_then_failed_get_preserves_order_id_no_retry() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"status": "success", "data": {"order_id": "oid_777"}})
        if request.method == "GET":
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(404, json={})

    zprov = _zerodha_prov()
    zprov._http._client = httpx.Client(transport=httpx.MockTransport(handler))

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
        client_order_id="correl_777",
    )
    with pytest.raises(UncertainOutcomeError) as exc_info:
        zprov.place_order(req)

    assert exc_info.value.order_id == "oid_777"
    assert exc_info.value.client_order_id == "correl_777"
    # Exactly one POST was made — mutation was NEVER retried!
    post_calls = [c for c in calls if c.method == "POST"]
    assert len(post_calls) == 1


def test_documented_rejection_and_insufficient_funds_classification() -> None:
    # Zerodha margin exceeded (HTTP 400 with Kite OrderException body)
    def z_margin_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "status": "error",
                "message": "RMS:Margin Exceeded: Required 50000, Available 12000",
                "error_type": "OrderException",
                "data": None,
            },
        )

    zprov = _zerodha_prov()
    zprov._http._client = httpx.Client(transport=httpx.MockTransport(z_margin_handler))
    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
    )
    with pytest.raises(InsufficientFundsError, match="Margin Exceeded"):
        zprov.place_order_ack(req)

    # Zerodha generic order rejection (HTTP 400 with Kite OrderException)
    def z_reject_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "status": "error",
                "message": "Order rejected: Market is closed",
                "error_type": "OrderException",
                "data": None,
            },
        )

    zprov._http._client = httpx.Client(transport=httpx.MockTransport(z_reject_handler))
    with pytest.raises(OrderRejectedError, match="Market is closed"):
        zprov.place_order_ack(req)

    # Dhan 200 with orderStatus: "REJECTED" and insufficient funds in remarks
    def d_margin_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "orderId": "112111182198",
                "orderStatus": "REJECTED",
                "remarks": "Insufficient balance to place order",
            },
        )

    dprov = _dhan_prov()
    dprov._http._client = httpx.Client(transport=httpx.MockTransport(d_margin_handler))
    dreq = OrderRequest(
        instrument_id="1333",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        price=Decimal("2500.00"),
    )
    with pytest.raises(InsufficientFundsError, match="Insufficient balance"):
        dprov.place_order_ack(dreq)

    # Dhan 200 with orderStatus: "REJECTED" and generic rejection
    def d_reject_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "orderId": "112111182198",
                "orderStatus": "REJECTED",
                "remarks": "Security is blocked for trading",
            },
        )

    dprov._http._client = httpx.Client(transport=httpx.MockTransport(d_reject_handler))
    with pytest.raises(OrderRejectedError, match="Security is blocked"):
        dprov.place_order_ack(dreq)

    # Dhan 400 Input_Exception -> InvalidOrderError
    def d_invalid_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "errorCode": "DH-905",
                "errorType": "Input_Exception",
                "errorMessage": "orderType is required",
            },
        )

    dprov._http._client = httpx.Client(transport=httpx.MockTransport(d_invalid_handler))
    with pytest.raises(InvalidOrderError, match="orderType is required"):
        dprov.place_order_ack(dreq)

    # Zerodha 403 TokenException -> AuthenticationError
    def z_auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "status": "error",
                "message": "Token is invalid or expired",
                "error_type": "TokenException",
                "data": None,
            },
        )

    zprov._http._client = httpx.Client(transport=httpx.MockTransport(z_auth_handler))
    with pytest.raises(AuthenticationError, match="Token is invalid"):
        zprov.place_order_ack(req)


def test_dhan_monthly_symbol_rejects_ambiguous_expiries() -> None:
    from bandl.models.market.contract import OptionType

    dprov = _dhan_prov()
    # Mock scrip rows with two distinct weekly expiries in the same month
    dprov._scrip._rows = [
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SM_SYMBOL_NAME": "NIFTY",
            "SEM_TRADING_SYMBOL": "NIFTY-10Oct2024-25000-CE",
            "SEM_CUSTOM_SYMBOL": "NIFTY 10 OCT 25000 CE",
            "SEM_OPTION_TYPE": "CE",
            "SEM_STRIKE_PRICE": "25000",
            "SEM_EXPIRY_DATE": "2024-10-10 15:30:00",
            "SEM_SMST_SECURITY_ID": "1001",
            "SEM_INSTRUMENT_NAME": "OPTIDX",
            "SEM_LOT_UNITS": "25",
            "SEM_TICK_SIZE": "0.05",
        },
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SM_SYMBOL_NAME": "NIFTY",
            "SEM_TRADING_SYMBOL": "NIFTY-17Oct2024-25000-CE",
            "SEM_CUSTOM_SYMBOL": "NIFTY 17 OCT 25000 CE",
            "SEM_OPTION_TYPE": "CE",
            "SEM_STRIKE_PRICE": "25000",
            "SEM_EXPIRY_DATE": "2024-10-17 15:30:00",
            "SEM_SMST_SECURITY_ID": "1002",
            "SEM_INSTRUMENT_NAME": "OPTIDX",
            "SEM_LOT_UNITS": "25",
            "SEM_TICK_SIZE": "0.05",
        },
    ]

    # Placing order using naive monthly symbol must fail due to ambiguity
    order_ambig = OrderRequest(
        symbol="NIFTY24OCT25000CE",
        exchange="NSE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(25),
        price=Decimal("150.05"),
    )
    with pytest.raises(InvalidOrderError, match="Ambiguous option expiry"):
        dprov.place_order_ack(order_ambig)

    # But placing with exact structured contract succeeds
    dprov._http.post_mutation = MagicMock(
        return_value={"orderId": "d_1001", "orderStatus": "TRANSIT"}
    )
    exact_contract = OptionContract(
        underlying="NIFTY",
        expiry=date(2024, 10, 10),
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
        exchange="NSE",
    )
    order_exact = OrderRequest(
        contract=exact_contract,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(25),
        price=Decimal("150.05"),
    )
    ack = dprov.place_order_ack(order_exact)
    assert ack.order_id == "d_1001"


def test_dhan_lot_size_and_tick_size_constraints() -> None:
    from bandl.models.market.contract import OptionContract, OptionType

    dprov = _dhan_prov()
    dprov._scrip._rows = [
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SM_SYMBOL_NAME": "NIFTY",
            "SEM_TRADING_SYMBOL": "NIFTY-10Oct2024-25000-CE",
            "SEM_CUSTOM_SYMBOL": "NIFTY 10 OCT 25000 CE",
            "SEM_OPTION_TYPE": "CE",
            "SEM_STRIKE_PRICE": "25000",
            "SEM_EXPIRY_DATE": "2024-10-10 15:30:00",
            "SEM_SMST_SECURITY_ID": "1001",
            "SEM_INSTRUMENT_NAME": "OPTIDX",
            "SEM_LOT_UNITS": "25",
            "SEM_TICK_SIZE": "0.05",
        }
    ]

    exact_contract = OptionContract(
        underlying="NIFTY",
        expiry=date(2024, 10, 10),
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
        exchange="NSE",
    )

    # Quantity not multiple of lot size (25)
    with pytest.raises(InvalidOrderError, match="must be a multiple of lot size 25"):
        dprov.place_order_ack(
            OrderRequest(
                contract=exact_contract,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(30),  # Not a multiple of 25
                price=Decimal("150.05"),
            )
        )

    # Price not multiple of tick size (0.05)
    with pytest.raises(InvalidOrderError, match="must be a multiple of tick size 0.05"):
        dprov.place_order_ack(
            OrderRequest(
                contract=exact_contract,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(25),
                price=Decimal("150.03"),  # Invalid tick
            )
        )

    # Trigger price not multiple of tick size (0.05)
    with pytest.raises(InvalidOrderError, match="must be a multiple of tick size 0.05"):
        dprov.place_order_ack(
            OrderRequest(
                contract=exact_contract,
                side=OrderSide.BUY,
                order_type=OrderType.STOP_LIMIT,
                quantity=Decimal(25),
                price=Decimal("150.05"),
                trigger_price=Decimal("149.02"),  # Invalid tick
            )
        )


def test_zerodha_exact_weekly_contract_resolution_and_constraints() -> None:
    from bandl.models.market.contract import OptionContract, OptionType

    zprov = _zerodha_prov()
    # Cache instruments for NFO
    zprov._instrument_cache["NFO"] = [
        {
            "instrument_token": "10011",
            "exchange_token": "10011",
            "tradingsymbol": "NIFTY24OCT25000CE",
            "name": "NIFTY",
            "last_price": "120.0",
            "expiry": "2024-10-10",
            "strike": "25000",
            "tick_size": "0.05",
            "lot_size": "25",
            "instrument_type": "CE",
            "segment": "NFO-OPT",
            "exchange": "NFO",
        },
        {
            "instrument_token": "10012",
            "exchange_token": "10012",
            "tradingsymbol": "NIFTY24O1725000CE",
            "name": "NIFTY",
            "last_price": "95.0",
            "expiry": "2024-10-17",
            "strike": "25000",
            "tick_size": "0.05",
            "lot_size": "25",
            "instrument_type": "CE",
            "segment": "NFO-OPT",
            "exchange": "NFO",
        },
    ]

    # Resolve exact weekly option contract
    oct17_contract = OptionContract(
        underlying="NIFTY",
        expiry=date(2024, 10, 17),
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
        exchange="NFO",
    )

    zprov._http.post_mutation = MagicMock(
        return_value={"status": "success", "data": {"order_id": "z_oct17"}}
    )
    ack = zprov.place_order_ack(
        OrderRequest(
            contract=oct17_contract,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(25),
            price=Decimal("95.05"),
        )
    )
    assert ack.order_id == "z_oct17"
    call_kwargs = zprov._http.post_mutation.call_args[1]
    assert call_kwargs["body"]["tradingsymbol"] == "NIFTY24O1725000CE"

    # Contract with conflicting exchange
    with pytest.raises(InvalidOrderError, match="Conflicting order exchange"):
        zprov.place_order_ack(
            OrderRequest(
                contract=oct17_contract,
                exchange="MCX",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(25),
                price=Decimal("95.05"),
            )
        )

    # Missing contract in instruments master
    missing_contract = OptionContract(
        underlying="NIFTY",
        expiry=date(2024, 10, 24),
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
        exchange="NFO",
    )
    with pytest.raises(SymbolNotFoundError, match="No Zerodha NFO option found"):
        zprov.place_order_ack(
            OrderRequest(
                contract=missing_contract,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(25),
                price=Decimal("95.05"),
            )
        )

    # Zerodha lot size multiple check
    with pytest.raises(InvalidOrderError, match="must be a multiple of lot size 25"):
        zprov.place_order_ack(
            OrderRequest(
                contract=oct17_contract,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(35),  # Not a multiple of 25
                price=Decimal("95.05"),
            )
        )

    # Zerodha tick size multiple check
    with pytest.raises(InvalidOrderError, match="must be a multiple of tick size 0.05"):
        zprov.place_order_ack(
            OrderRequest(
                contract=oct17_contract,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(25),
                price=Decimal("95.02"),  # Invalid tick
            )
        )


# ===========================================================================
# 6. Capabilities Declaration & Pre-submission Gate (R9)
# ===========================================================================


def test_capabilities_declare_supported_types_and_operations() -> None:
    prov = _zerodha_prov()
    caps = prov.trade_capabilities()
    assert caps.place.supported
    assert caps.get_orders.supported
    assert caps.get_order_history.supported
    assert caps.idempotency.supported is False  # Explicitly declares broker idempotency is false
    assert OrderType.MARKET in caps.order_types
    assert ProductType.DELIVERY in caps.products


# ===========================================================================
# 7. Cross-Asset Fake Provider Suite (Spot Crypto & Derivatives)
# ===========================================================================


class FakeCryptoTradingProvider:
    """Fake provider modeling crypto spot & perpetual trading behavior."""

    provider_id = "fake_crypto"
    bound_account_id: str | None = None

    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self.balances: list[Balance] = [
            Balance(
                source="fake_crypto",
                currency="USDT",
                available=Decimal("10000"),
                used=Decimal(0),
                total=Decimal("10000"),
            ),
            Balance(
                source="fake_crypto",
                currency="BTC",
                available=Decimal("1.5"),
                used=Decimal(0),
                total=Decimal("1.5"),
            ),
        ]
        self.positions: list[Position] = []

    def trade_capabilities(self) -> TradeCapabilities:
        return TradeCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.SPOT_CRYPTO, Segment.CRYPTO_FNO],
            place=CapabilityDetail(supported=True),
            modify=CapabilityDetail(supported=True),
            cancel=CapabilityDetail(supported=True),
            get_open_orders=CapabilityDetail(supported=True),
            get_orders=CapabilityDetail(supported=True),
            get_order=CapabilityDetail(supported=True),
            get_trades=CapabilityDetail(supported=True),
            idempotency=CapabilityDetail(
                supported=True,
                notes=["clientOrderId enforced natively by fake exchange"],
            ),
            order_types=[OrderType.MARKET, OrderType.LIMIT, OrderType.STOP],
            products=[ProductType.DELIVERY, ProductType.MARGIN],
            validities=[Validity.DAY, Validity.GTC, Validity.IOC],
        )

    def portfolio_capabilities(self) -> PortfolioCapabilities:
        return PortfolioCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.SPOT_CRYPTO, Segment.CRYPTO_FNO],
            positions=CapabilityDetail(supported=True),
            holdings=CapabilityDetail(supported=True),
            balances=CapabilityDetail(supported=True),
            margin=CapabilityDetail(supported=True),
        )

    def place_order(self, order: OrderRequest, *, account_id: str | None = None) -> Order:
        ack = self.place_order_ack(order, account_id=account_id)
        return self.get_order(ack.order_id or "fake-oid", account_id=account_id)

    def place_order_ack(
        self, order: OrderRequest, *, account_id: str | None = None
    ) -> OrderAcknowledgement:
        # Cross-asset validation: spot cannot accept reduce_only
        if order.product == ProductType.DELIVERY and order.reduce_only:
            raise UnsupportedCapabilityError(self.provider_id, "reduce_only on spot delivery")

        oid = f"crypto-oid-{len(self.orders) + 1}"
        new_order = Order(
            order_id=oid,
            client_order_id=order.client_order_id,
            account_id=account_id,
            side=order.side,
            position_side=order.position_side,
            order_type=order.order_type.value,
            product=order.product.value,
            validity=order.validity.value,
            variety=Variety.REGULAR,
            status=OrderStatus.OPEN,
            raw_status="NEW",
            quantity=order.quantity,
            price=order.price,
            trigger_price=order.trigger_price,
            created_at=datetime.now(timezone.utc),
            source=self.provider_id,
            segment=Segment.SPOT_CRYPTO
            if order.product == ProductType.DELIVERY
            else Segment.CRYPTO_FNO,
            symbol=order.symbol or "BTCUSDT",
            symbol_native=order.symbol or "BTCUSDT",
            currency="USDT",
            dedup_key=f"{self.provider_id}:order:{oid}",
        )
        self.orders[oid] = new_order
        return OrderAcknowledgement(
            operation="place",
            provider_id=self.provider_id,
            account_id=account_id,
            order_id=oid,
            client_order_id=order.client_order_id,
            status=OrderStatus.OPEN,
            received_at=datetime.now(timezone.utc),
        )

    def get_open_orders(
        self, *, symbol: str | None = None, account_id: str | None = None
    ) -> list[Order]:
        return [o for o in self.orders.values() if o.status == OrderStatus.OPEN]

    def get_orders(
        self, *, symbol: str | None = None, account_id: str | None = None
    ) -> list[Order]:
        return list(self.orders.values())

    def get_order(self, order_id: str, *, account_id: str | None = None) -> Order:
        if order_id not in self.orders:
            raise ProviderError(self.provider_id, f"Order {order_id} not found")
        return self.orders[order_id]

    def modify_order(self, order_id: str, *, account_id: str | None = None, **kwargs) -> Order:
        order = self.get_order(order_id)
        return order

    def modify_order_ack(
        self, order_id: str, *, account_id: str | None = None, **kwargs
    ) -> OrderAcknowledgement:
        order = self.get_order(order_id)
        return OrderAcknowledgement(
            operation="modify",
            provider_id=self.provider_id,
            account_id=account_id,
            order_id=order_id,
            status=order.status,
            received_at=datetime.now(timezone.utc),
        )

    def cancel_order(self, order_id: str, *, account_id: str | None = None) -> Order:
        order = self.get_order(order_id)
        order.status = OrderStatus.CANCELLED
        order.raw_status = "CANCELED"
        return order

    def cancel_order_ack(
        self, order_id: str, *, account_id: str | None = None
    ) -> OrderAcknowledgement:
        order = self.cancel_order(order_id, account_id=account_id)
        return OrderAcknowledgement(
            operation="cancel",
            provider_id=self.provider_id,
            account_id=account_id,
            order_id=order_id,
            status=order.status,
            received_at=datetime.now(timezone.utc),
        )

    def get_order_history(self, order_id: str, *, account_id: str | None = None) -> list[Order]:
        return [self.get_order(order_id, account_id=account_id)]

    def get_trades(
        self, *, symbol: str | None = None, account_id: str | None = None
    ) -> list[AccountFill]:
        # Third asset fee example (fee in BNB for BTCUSDT trade)
        return [
            AccountFill(
                fill_id="trade-1",
                order_id="crypto-oid-1",
                side="buy",
                quantity=Decimal("0.00543"),
                price=Decimal("60000"),
                quote_quantity=Decimal("325.8"),
                fee=Decimal("0.001"),
                fee_currency="BNB",
                executed_at=datetime.now(timezone.utc),
                source=self.provider_id,
                segment=Segment.SPOT_CRYPTO,
                symbol="BTCUSDT",
                symbol_native="BTCUSDT",
                currency="USDT",
                dedup_key="fake_crypto:fill:trade-1",
            )
        ]

    def get_positions(self, *, account_id: str | None = None) -> list[Position]:
        return self.positions

    def get_holdings(self, *, account_id: str | None = None) -> list[Holding]:
        return []

    def get_balances(self, *, account_id: str | None = None) -> list[Balance]:
        return self.balances

    def get_margin(self, *, account_id: str | None = None) -> MarginInfo:
        return MarginInfo(
            source=self.provider_id,
            currency="USDT",
            available=Decimal("10000"),
            used=Decimal(0),
            total=Decimal("10000"),
        )


def test_custom_provider_injection_and_crypto_cross_asset_execution() -> None:
    fake = FakeCryptoTradingProvider()
    client = Bandl(custom_providers={"fake_crypto": fake})

    # Verify custom provider registered and wired into trade & portfolio facets
    assert "fake_crypto" in client.list_providers()
    caps = client.trade.capabilities("fake_crypto")
    assert caps.place.supported
    assert caps.idempotency.supported is True

    # 1. Test fractional crypto spot order
    order = client.trade.place_order(
        OrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00543"),  # Fractional spot quantity
            quantity_unit=QuantityUnit.BASE,
            price=Decimal("60000"),
            product=ProductType.DELIVERY,
        ),
        source="fake_crypto",
    )
    assert order.order_id == "crypto-oid-1"
    assert order.quantity == Decimal("0.00543")

    # 2. Test hedge mode position side (LONG & SHORT positions)
    perp_long = client.trade.place_order(
        OrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            position_side=PositionSide.LONG,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
            product=ProductType.MARGIN,
        ),
        source="fake_crypto",
    )
    assert perp_long.position_side == PositionSide.LONG

    # 3. Test reduce_only gating on spot
    with pytest.raises(UnsupportedCapabilityError):
        client.trade.place_order(
            OrderRequest(
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.01"),
                product=ProductType.DELIVERY,
                reduce_only=True,
            ),
            source="fake_crypto",
        )

    # 4. Test third-asset fee in trades
    trades = client.trade.get_trades(source="fake_crypto")
    assert len(trades) == 1
    assert trades[0].fee_currency == "BNB"
    assert trades[0].fee == Decimal("0.001")


# ---------------------------------------------------------------------------
# Regression tests for Execution Hardening Production Review Blockers
# ---------------------------------------------------------------------------


def test_malformed_mutation_responses_raise_uncertain_outcome_zerodha() -> None:
    """Issue 1: Zerodha modify/cancel returning [] or missing ID raises UncertainOutcome."""
    # 1. Modify order with [] response
    zprov = _zerodha_prov()
    zprov._http._client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[]))
    )
    with pytest.raises(UncertainOutcomeError) as exc_mod:
        zprov.modify_order_ack("z_ord_1", price=Decimal("100"))
    assert exc_mod.value.order_id == "z_ord_1"
    assert "Malformed" in str(exc_mod.value)

    # 2. Cancel order with [] response
    with pytest.raises(UncertainOutcomeError) as exc_can:
        zprov.cancel_order_ack("z_ord_2")
    assert exc_can.value.order_id == "z_ord_2"
    assert "Malformed" in str(exc_can.value)

    # 3. Modify order with data missing order_id
    zprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"status": "success", "data": {"order_id": ""}})
        )
    )
    with pytest.raises(UncertainOutcomeError) as exc_empty:
        zprov.modify_order_ack("z_ord_3", price=Decimal("100"))
    assert exc_empty.value.order_id == "z_ord_3"
    assert "Missing or empty order_id" in str(exc_empty.value)


def test_malformed_mutation_responses_raise_uncertain_outcome_dhan() -> None:
    """Issue 1: Dhan modify/cancel returning [] or missing orderId raises UncertainOutcomeError."""
    # 1. Modify order with [] response
    dprov = _dhan_prov()
    dprov._http._client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[]))
    )
    with pytest.raises(UncertainOutcomeError) as exc_mod:
        dprov.modify_order_ack("d_ord_1", price=Decimal("100"))
    assert exc_mod.value.order_id == "d_ord_1"
    assert "Malformed" in str(exc_mod.value)

    # 2. Cancel order with [] response
    with pytest.raises(UncertainOutcomeError) as exc_can:
        dprov.cancel_order_ack("d_ord_2")
    assert exc_can.value.order_id == "d_ord_2"
    assert "Malformed" in str(exc_can.value)

    # 3. Modify order with empty orderId
    dprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"orderId": "   ", "orderStatus": "TRANSIT"})
        )
    )
    with pytest.raises(UncertainOutcomeError) as exc_empty:
        dprov.modify_order_ack("d_ord_3", price=Decimal("100"))
    assert exc_empty.value.order_id == "d_ord_3"
    assert "Missing or empty orderId" in str(exc_empty.value)

    # 4. Modify order rejected by broker
    dprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "orderId": "d_ord_4",
                    "orderStatus": "REJECTED",
                    "remarks": "Insufficient funds",
                },
            )
        )
    )
    with pytest.raises(InsufficientFundsError):
        dprov.modify_order_ack("d_ord_4", price=Decimal("100"))


def test_http_diagnostics_credential_redaction() -> None:
    """Issue 2: HTTP error bodies and mutation exceptions redact credentials and query strings."""
    from bandl.core.http import _redact_text, _safe_exception_str

    # Redact URL query strings in text
    leak_url = "Request failed at https://api.broker.com/order?api_key=SECRET123&token=TOK456"
    redacted = _redact_text(leak_url)
    assert "SECRET123" not in redacted
    assert "TOK456" not in redacted
    assert "https://api.broker.com/order" in redacted

    # Redact JSON sensitive keys
    leak_json = '{"error": "rejected", "api_key": "SECRET123", "password": "PW"}'
    redacted_json = _redact_text(leak_json)
    assert "SECRET123" not in redacted_json
    assert "PW" not in redacted_json
    assert "[REDACTED]" in redacted_json

    # Safe exception formatting for HTTPStatusError
    req = httpx.Request("POST", "https://api.broker.com/mutation?secret=TOPSECRET")
    resp = httpx.Response(500, request=req)
    err = httpx.HTTPStatusError("500 Server Error", request=req, response=resp)
    safe_err = _safe_exception_str(err)
    assert "TOPSECRET" not in safe_err
    assert "secret=" not in safe_err
    assert "500" in safe_err


def test_redact_text_sanitizes_json_string_values_recursively() -> None:
    """_redact_text recursively sanitizes string values inside JSON bodies."""
    from bandl.core.http import _redact_text

    # JSON with Bearer token, URL query param, and Authorization token in string values
    payload = json.dumps(
        {
            "message": "Authorization: token key_123:sec_456 failed",
            "detail": "Bearer my_jwt_token_789",
            "url": "https://api.kite.trade/orders?api_key=SECRET_KITE_KEY",
            "nested": json.dumps({"token": "SECRET_NESTED_TOK"}),
            "safe_key": "safe_value",
        }
    )
    redacted = _redact_text(payload)
    data = json.loads(redacted)

    assert "sec_456" not in redacted
    assert "my_jwt_token_789" not in redacted
    assert "SECRET_KITE_KEY" not in redacted
    assert "SECRET_NESTED_TOK" not in redacted
    assert "safe_value" in redacted
    assert data["message"] == "Authorization: token [REDACTED] failed"
    assert data["detail"] == "Bearer [REDACTED]"
    assert data["url"] == "https://api.kite.trade/orders"
    assert "[REDACTED]" in data["nested"]


def test_safe_diagnostic_redacts_authorization_token() -> None:
    """_safe_diagnostic and _redact_text completely redact Authorization: token credentials."""
    from bandl.core.http import _redact_text, _safe_diagnostic

    # Diagnostic on dict containing Authorization token in value
    d1 = {"error": "Invalid auth header: Authorization: token kite_api_key:kite_access_token"}
    res1 = _safe_diagnostic(d1)
    assert "kite_access_token" not in res1
    assert "kite_api_key:kite_access_token" not in res1
    assert "[REDACTED]" in res1

    # Diagnostic on string
    s2 = "Header dump: Authorization: token single_token_secret_123"
    res2 = _safe_diagnostic(s2)
    assert "single_token_secret_123" not in res2
    assert "[REDACTED]" in res2

    # Direct _redact_text on unquoted and quoted authorization headers
    raw_header = "Authorization: token my_secret_token_abc"
    assert "my_secret_token_abc" not in _redact_text(raw_header)
    assert "token [REDACTED]" in _redact_text(raw_header)

    repr_header = "{'Authorization': 'token my_secret_token_def'}"
    assert "my_secret_token_def" not in _redact_text(repr_header)
    assert "'token [REDACTED]'" in _redact_text(repr_header)


def test_dhan_rejection_remarks_sanitizes_credentials() -> None:
    """Dhan rejection remarks across order place/modify/cancel sanitize credentials."""
    dprov = _dhan_prov()

    # Place order rejected with sensitive remarks
    dprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "orderId": "d_ord_leak_1",
                    "orderStatus": "REJECTED",
                    "remarks": "Rejected: Authorization: token dhan_sec_111 expired",
                },
            )
        )
    )
    req = OrderRequest(
        instrument_id="1333",
        exchange="NSE",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        price=Decimal("100"),
    )
    with pytest.raises(OrderRejectedError) as exc_place:
        dprov.place_order_ack(req)
    assert "dhan_sec_111" not in str(exc_place.value)
    assert "[REDACTED]" in str(exc_place.value)

    # Modify order rejected with insufficient funds and secret in remarks
    dprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "orderId": "d_ord_leak_2",
                    "orderStatus": "REJECTED",
                    "remarks": "Insufficient funds at https://dhan.co/deposit?token=SECRET_TOK_222",
                },
            )
        )
    )
    with pytest.raises(InsufficientFundsError) as exc_mod:
        dprov.modify_order_ack("d_ord_leak_2", price=Decimal("100"))
    assert "SECRET_TOK_222" not in str(exc_mod.value)
    assert "https://dhan.co/deposit" in str(exc_mod.value)

    # Cancel order rejected with sensitive remarks
    dprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "orderId": "d_ord_leak_3",
                    "orderStatus": "REJECTED",
                    "remarks": "Order cancel rejected: password=SECRET_PASS_333",
                },
            )
        )
    )
    with pytest.raises(OrderRejectedError) as exc_can:
        dprov.cancel_order_ack("d_ord_leak_3")
    assert "SECRET_PASS_333" not in str(exc_can.value)
    assert "[REDACTED]" in str(exc_can.value)


def test_direct_provider_calls_reject_conflicting_account_assertions() -> None:
    """Issue 3: Direct provider calls with conflicting accounts raise ConfigurationError."""
    # Zerodha
    zprov = _zerodha_prov()
    object.__setattr__(zprov._settings, "account_id", "ACC_MAIN")

    order_conflict = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(2500),
        quantity=Decimal(1),
        account_id="ACC_OTHER",
    )
    with pytest.raises(ConfigurationError):
        zprov.place_order_ack(order_conflict, account_id="ACC_MAIN")

    with pytest.raises(ConfigurationError):
        zprov.place_order(order_conflict, account_id="ACC_MAIN")

    # Dhan
    dprov = _dhan_prov()
    object.__setattr__(dprov._settings, "account_id", "ACC_MAIN")

    with pytest.raises(ConfigurationError):
        dprov.place_order_ack(order_conflict, account_id="ACC_MAIN")

    with pytest.raises(ConfigurationError):
        dprov.place_order(order_conflict, account_id="ACC_MAIN")


def test_dhan_scrip_resolution_rejects_ambiguous_instruments() -> None:
    """Issue 4: Dhan scrip resolution rejects multiple distinct security IDs for the same expiry."""
    from bandl.providers.dhan.scrip import ScripMaster

    csv_data = (
        "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_INSTRUMENT_NAME,SEM_SMST_SECURITY_ID,"
        "SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_LOT_UNITS,SEM_TICK_SIZE\n"
        "NSE,FNO,OPTIDX,1001,NIFTY24OCT25000CE,NIFTY 25000 CE,2024-10-17,25000,CE,50,0.05\n"
        "NSE,FNO,OPTIDX,1002,NIFTY24OCT25000CE,NIFTY 25000 CE,2024-10-17,25000,CE,50,0.05\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv_data)

    transport = httpx.MockTransport(handler)
    http = HttpClient(BandlConfig(), transport=transport)
    master = ScripMaster(http, provider_id="dhan")

    with pytest.raises(InvalidOrderError) as exc:
        master.resolve_option("NIFTY", "NSE", Decimal(25000), "CE", expiry=date(2024, 10, 17))
    assert "Ambiguous option resolution" in str(exc.value)
    assert "1001" in str(exc.value) and "1002" in str(exc.value)


class _LegacyMutationsCustomProvider:
    provider_id = "legacy_mutations"
    bound_account_id = None

    def trade_capabilities(self) -> TradeCapabilities:
        return TradeCapabilities(
            provider_id="legacy_mutations",
            place=CapabilityDetail(supported=True),
            modify=CapabilityDetail(supported=True),
            cancel=CapabilityDetail(supported=True),
            get_open_orders=CapabilityDetail(supported=False),
            get_orders=CapabilityDetail(supported=False),
            get_order=CapabilityDetail(supported=False),
            get_order_history=CapabilityDetail(supported=False),
            get_trades=CapabilityDetail(supported=False),
        )

    def place_order(self, order: OrderRequest, *, account_id: str | None = None) -> Order:
        raise NotImplementedError

    def modify_order(self, order_id: str, *, account_id: str | None = None, **kwargs: Any) -> Order:
        raise NotImplementedError

    def cancel_order(self, order_id: str, *, account_id: str | None = None) -> Order:
        raise NotImplementedError


def test_facet_ack_methods_raise_unsupported_without_fallback() -> None:
    """Issue 5: Facet ack methods raise UnsupportedCapabilityError when provider lacks *_ack."""
    client = Bandl()
    custom = _LegacyMutationsCustomProvider()
    client.register_provider("legacy_mutations", custom)

    order_req = OrderRequest(
        symbol="INFY",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(1500),
        quantity=Decimal(10),
    )

    with pytest.raises(UnsupportedCapabilityError) as exc_place:
        client.trade.place_order_ack(order_req, source="legacy_mutations")
    assert "place_order_ack" in str(exc_place.value)

    with pytest.raises(UnsupportedCapabilityError) as exc_mod:
        client.trade.modify_order_ack("ord_1", price=Decimal(1600), source="legacy_mutations")
    assert "modify_order_ack" in str(exc_mod.value)

    with pytest.raises(UnsupportedCapabilityError) as exc_can:
        client.trade.cancel_order_ack("ord_1", source="legacy_mutations")
    assert "cancel_order_ack" in str(exc_can.value)


def test_quantity_unit_validation_contracts() -> None:
    """Issue 6: QuantityUnit.BASE is supported; non-BASE units raise UnsupportedCapabilityError."""
    from bandl.models.trading.order import QuantityUnit
    from bandl.trade.validation import validate_broker_order_request

    req_base = OrderRequest(
        symbol="INFY",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(1500),
        quantity=Decimal(10),
        quantity_unit=QuantityUnit.BASE,
    )
    validate_broker_order_request("zerodha", req_base)

    req_quote = req_base.model_copy(update={"quantity_unit": QuantityUnit.QUOTE})
    with pytest.raises(UnsupportedCapabilityError):
        validate_broker_order_request("zerodha", req_quote)

    req_contracts = req_base.model_copy(update={"quantity_unit": QuantityUnit.CONTRACTS})
    with pytest.raises(UnsupportedCapabilityError):
        validate_broker_order_request("zerodha", req_contracts)


def test_recovery_recipe_disambiguation_logic() -> None:
    """Issue 7: Recovery recipe handles known order_id, unique client ID, and ambiguous tags."""
    now = datetime.now(timezone.utc)

    def make_order(order_id: str, tag: str | None) -> Order:
        return Order(
            order_id=order_id,
            account_id="acc1",
            symbol="INFY",
            symbol_native="INFY",
            segment=Segment.EQUITY_CASH,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT.value,
            product=ProductType.DELIVERY,
            validity=Validity.DAY,
            quantity=Decimal(10),
            filled_quantity=Decimal(0),
            price=Decimal(1500),
            status=OrderStatus.OPEN,
            source="zerodha",
            created_at=now,
            dedup_key=f"zerodha:{order_id}",
            client_order_id=tag,
        )

    session_orders = [
        make_order("broker_101", "tag_unique"),
        make_order("broker_102", "tag_dup"),
        make_order("broker_103", "tag_dup"),
    ]

    def recover(err: UncertainOutcomeError) -> tuple[str, Order | None]:
        # Step 1: Known broker order_id
        if err.order_id:
            for o in session_orders:
                if o.order_id == err.order_id:
                    return "recovered_by_order_id", o
        # Step 2: Non-empty client_order_id
        if err.client_order_id and str(err.client_order_id).strip():
            matching = [o for o in session_orders if o.client_order_id == err.client_order_id]
            if len(matching) == 1:
                return "recovered_by_client_id", matching[0]
            if len(matching) > 1:
                return "ambiguous", None
        return "unresolved", None

    # Case A: Recover with broker order_id
    err_a = UncertainOutcomeError("zerodha", "Timeout", order_id="broker_101", client_order_id=None)
    status_a, res_a = recover(err_a)
    assert status_a == "recovered_by_order_id"
    assert res_a is not None and res_a.order_id == "broker_101"

    # Case B: Recover with unique client_order_id
    err_b = UncertainOutcomeError("zerodha", "Timeout", order_id=None, client_order_id="tag_unique")
    status_b, res_b = recover(err_b)
    assert status_b == "recovered_by_client_id"
    assert res_b is not None and res_b.order_id == "broker_101"

    # Case C: Ambiguous client_order_id
    err_c = UncertainOutcomeError("zerodha", "Timeout", order_id=None, client_order_id="tag_dup")
    status_c, res_c = recover(err_c)
    assert status_c == "ambiguous"
    assert res_c is None

    # Case D: None / empty client_order_id does not falsely match untagged orders
    err_d = UncertainOutcomeError("zerodha", "Timeout", order_id=None, client_order_id=None)
    status_d, res_d = recover(err_d)
    assert status_d == "unresolved"
    assert res_d is None


def test_malformed_order_ids_produce_uncertain_outcome() -> None:
    """Issue 8: Booleans, dicts, lists, and sentinel words as order IDs raise
    UncertainOutcomeError.
    """
    # 1. Zerodha place_order_ack with boolean true, dict, or list
    zprov = _zerodha_prov()
    for bad_id in (True, False, {}, [], {"id": 123}, "True", "False", "null", "None", ""):
        zprov._http.post_mutation = MagicMock(
            return_value={"status": "success", "data": {"order_id": bad_id}}
        )
        req = OrderRequest(
            symbol="RELIANCE",
            exchange="NSE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal(2500),
            quantity=Decimal(1),
        )
        with pytest.raises(UncertainOutcomeError) as exc_info:
            zprov.place_order_ack(req)
        assert exc_info.value.operation == "place"
        assert "Missing or empty order_id" in str(exc_info.value)

    # 2. Zerodha modify_order_ack and cancel_order_ack
    for bad_id in (True, {}, []):
        zprov._http.put_mutation = MagicMock(
            return_value={"status": "success", "data": {"order_id": bad_id}}
        )
        with pytest.raises(UncertainOutcomeError) as exc_mod:
            zprov.modify_order_ack("ord_1", price=Decimal(2600))
        assert exc_mod.value.operation == "modify"
        assert exc_mod.value.order_id == "ord_1"

        zprov._http.delete_mutation = MagicMock(
            return_value={"status": "success", "data": {"order_id": bad_id}}
        )
        with pytest.raises(UncertainOutcomeError) as exc_can:
            zprov.cancel_order_ack("ord_1")
        assert exc_can.value.operation == "cancel"
        assert exc_can.value.order_id == "ord_1"

    # 3. Dhan place_order_ack, modify_order_ack, cancel_order_ack
    dprov = _dhan_prov()
    for bad_id in (True, False, {}, [], {"id": 123}, "True", "False", "null", "None", ""):
        dprov._http.post_mutation = MagicMock(
            return_value={"orderId": bad_id, "orderStatus": "TRANSIT"}
        )
        dreq = OrderRequest(
            instrument_id="1333",
            exchange="NSE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal(2500),
            quantity=Decimal(1),
        )
        with pytest.raises(UncertainOutcomeError) as exc_dplace:
            dprov.place_order_ack(dreq)
        assert exc_dplace.value.operation == "place"
        assert "Missing or empty orderId" in str(exc_dplace.value)

    for bad_id in (True, {}, []):
        dprov._http.put_mutation = MagicMock(
            return_value={"orderId": bad_id, "orderStatus": "TRANSIT"}
        )
        with pytest.raises(UncertainOutcomeError) as exc_dmod:
            dprov.modify_order_ack("d_ord_1", price=Decimal(2600))
        assert exc_dmod.value.operation == "modify"
        assert exc_dmod.value.order_id == "d_ord_1"

        dprov._http.delete_mutation = MagicMock(
            return_value={"orderId": bad_id, "orderStatus": "TRANSIT"}
        )
        with pytest.raises(UncertainOutcomeError) as exc_dcan:
            dprov.cancel_order_ack("d_ord_1")
        assert exc_dcan.value.operation == "cancel"
        assert exc_dcan.value.order_id == "d_ord_1"


def test_malformed_response_errors_redact_credentials() -> None:
    """Issue 9: Error messages from malformed responses do not leak sensitive credentials."""
    secret = "SENTINEL_FAKE_SECRET_98765"
    key = "SENTINEL_FAKE_KEY_12345"

    # Dhan place with secret in response payload and invalid orderId
    dprov = _dhan_prov()
    dprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"access_token": secret, "api_key": key, "orderId": None},
            )
        )
    )
    dreq = OrderRequest(
        instrument_id="1333",
        exchange="NSE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(2500),
        quantity=Decimal(1),
    )
    with pytest.raises(UncertainOutcomeError) as exc_d:
        dprov.place_order_ack(dreq)
    err_str_d = str(exc_d.value)
    assert secret not in err_str_d
    assert key not in err_str_d
    assert "[REDACTED]" in err_str_d

    # Zerodha modify with secret in non-dict payload
    zprov = _zerodha_prov()
    zprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"status": "success", "data": {"access_token": secret, "order_id": None}},
            )
        )
    )
    with pytest.raises(UncertainOutcomeError) as exc_z:
        zprov.modify_order_ack("z_ord_1", price=Decimal(100))
    err_str_z = str(exc_z.value)
    assert secret not in err_str_z
    assert "[REDACTED]" in err_str_z


def test_unknown_zerodha_mutation_errors_raise_uncertain_outcome() -> None:
    """Issue 10: Kite HTTP 200 error envelope with unclassified error_type
    raises UncertainOutcomeError.
    """
    zprov = _zerodha_prov()
    # Kite returns 200 with GeneralException
    zprov._http._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "status": "error",
                    "error_type": "GeneralException",
                    "message": "Internal broker error occurred",
                },
            )
        )
    )
    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(2500),
        quantity=Decimal(1),
        client_order_id="my-client-tag",
    )

    # 1. place_order_ack
    with pytest.raises(UncertainOutcomeError) as exc_place:
        zprov.place_order_ack(req)
    assert exc_place.value.operation == "place"
    assert exc_place.value.client_order_id == "my-client-tag"
    assert "GeneralException" in str(exc_place.value) or "Internal broker error" in str(
        exc_place.value
    )

    # 2. modify_order_ack
    with pytest.raises(UncertainOutcomeError) as exc_mod:
        zprov.modify_order_ack("ord_999", price=Decimal(2600))
    assert exc_mod.value.operation == "modify"
    assert exc_mod.value.order_id == "ord_999"

    # 3. cancel_order_ack
    with pytest.raises(UncertainOutcomeError) as exc_can:
        zprov.cancel_order_ack("ord_999")
    assert exc_can.value.operation == "cancel"
    assert exc_can.value.order_id == "ord_999"


def test_auth_classification_scoped_to_provider() -> None:
    """Issue 11: Non-Dhan provider HTTP 400 responses with words containing 'ip'
    (like 'description') do not become AuthenticationError.
    """
    from bandl.core.http import _provider_http_error

    # Binance HTTP 400 with "Invalid description"
    req_binance = httpx.Request("POST", "https://api.binance.com/api/v3/order")
    resp_binance = httpx.Response(
        400,
        request=req_binance,
        json={"code": -1100, "msg": "Invalid description for parameter"},
    )
    err_binance = httpx.HTTPStatusError(
        "400 Bad Request", request=req_binance, response=resp_binance
    )
    classified_b = _provider_http_error("binance", err_binance)
    # Must NOT be AuthenticationError!
    assert not isinstance(classified_b, AuthenticationError)
    assert isinstance(classified_b, ProviderError)

    # Dhan HTTP 400 with IP whitelist error -> must be AuthenticationError
    req_dhan = httpx.Request("POST", "https://api.dhan.co/orders")
    resp_dhan = httpx.Response(
        400,
        request=req_dhan,
        json={"errorCode": "DH-901", "errorMessage": "IP address not whitelisted"},
    )
    err_dhan = httpx.HTTPStatusError("400 Bad Request", request=req_dhan, response=resp_dhan)
    classified_d = _provider_http_error("dhan", err_dhan)
    assert isinstance(classified_d, AuthenticationError)
