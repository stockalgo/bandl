from __future__ import annotations

import pytest

from bandl.exceptions import ProviderError
from bandl.providers.equity.zerodha.common import kite_unwrap


def test_kite_unwrap_list() -> None:
    assert kite_unwrap({"status": "success", "data": [{"a": 1}]}) == [{"a": 1}]


def test_kite_unwrap_error() -> None:
    with pytest.raises(ProviderError, match="Kite API error"):
        kite_unwrap({"status": "error", "message": "bad token"})


def test_kite_unwrap_error_sanitizes_message() -> None:
    payload = {
        "status": "error",
        "error_type": "TokenException",
        "message": "Auth failure: Authorization: token k_key:k_sec & secret=SEC789",
    }
    with pytest.raises(ProviderError) as exc_info:
        kite_unwrap(payload)
    err_str = str(exc_info.value)
    assert "k_key:k_sec" not in err_str
    assert "SEC789" not in err_str
    assert "[REDACTED]" in err_str


def test_kite_unwrap_error_sanitizes_payload_when_message_missing() -> None:
    payload = {
        "status": "error",
        "error_type": "OrderException",
        "api_key": "LEAKED_API_KEY",
        "access_token": "LEAKED_ACCESS_TOKEN",
    }
    with pytest.raises(ProviderError) as exc_info:
        kite_unwrap(payload)
    err_str = str(exc_info.value)
    assert "LEAKED_API_KEY" not in err_str
    assert "LEAKED_ACCESS_TOKEN" not in err_str
    assert "[REDACTED]" in err_str


def test_kite_unwrap_error_sanitizes_context() -> None:
    payload = {
        "status": "error",
        "message": "Gateway timeout",
    }
    ctx = {
        "operation": "place",
        "order_id": "111",
        "api_key": "SECRET_CONTEXT_KEY",
        "Authorization": "token abc:xyz",
    }
    with pytest.raises(ProviderError) as exc_info:
        kite_unwrap(payload, context=ctx)
    rc = getattr(exc_info.value, "request_context", {})
    assert rc.get("api_key") == "[REDACTED]"
    assert rc.get("Authorization") == "[REDACTED]"
    assert "xyz" not in str(rc)
