"""Shared Zerodha/Kite constants and helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

KITE_API = "https://api.kite.trade"


def kite_unwrap(
    payload: object,
    *,
    provider_id: str = "zerodha",
    context: dict[str, Any] | None = None,
) -> object:
    """Extract ``data`` from a standard Kite Connect envelope."""
    if isinstance(payload, dict):
        status = payload.get("status")
        if status == "error":
            from bandl.core.http import _redact_dict, _redact_text, _safe_diagnostic
            from bandl.exceptions import (
                AuthenticationError,
                InsufficientFundsError,
                InvalidOrderError,
                OrderRejectedError,
                ProviderError,
                UncertainOutcomeError,
            )

            raw_msg = payload.get("message")
            if raw_msg:
                msg = _redact_text(str(raw_msg))
            else:
                msg = _safe_diagnostic(payload)
            err_type = str(payload.get("error_type") or "")
            if err_type == "TokenException":
                raise AuthenticationError(provider_id, f"Kite API error: {msg}")
            if err_type == "OrderException":
                m_lower = msg.lower()
                if "margin" in m_lower or "insufficient" in m_lower or "funds" in m_lower:
                    raise InsufficientFundsError(provider_id, msg)
                raise OrderRejectedError(provider_id, msg, raw_status="REJECTED")
            if err_type == "InputException":
                raise InvalidOrderError(provider_id, msg)
            if context is not None:
                raise UncertainOutcomeError(
                    provider_id,
                    f"Kite API error: {msg}",
                    operation=context.get("operation"),
                    order_id=context.get("order_id"),
                    client_order_id=context.get("client_order_id"),
                    request_context=_redact_dict(context),
                )
            raise ProviderError(provider_id, f"Kite API error: {msg}")
        if "data" in payload:
            return payload["data"]
    return payload


def parse_kite_timestamp(raw: str) -> datetime:
    """Parse Kite timestamp to UTC (handles ``+0530`` style offsets)."""
    s = raw.strip()
    s = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", s)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
