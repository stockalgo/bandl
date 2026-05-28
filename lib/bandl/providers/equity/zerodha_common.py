"""Shared Zerodha/Kite constants and helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone

KITE_API = "https://api.kite.trade"


def kite_unwrap(payload: object, *, provider_id: str = "zerodha") -> object:
    """Extract ``data`` from a standard Kite Connect envelope."""
    if isinstance(payload, dict):
        status = payload.get("status")
        if status == "error":
            from bandl.exceptions import ProviderError

            msg = payload.get("message", payload)
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
