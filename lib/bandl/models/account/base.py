from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field


def make_dedup_key(source: str, entity: str, native_id: str) -> str:
    return f"{source}:{entity}:{native_id}"


def make_dedup_key_from_fields(source: str, entity: str, **fields: Any) -> str:
    parts = [source, entity] + [str(fields[k]) for k in sorted(fields)]
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"{source}:{entity}:hash:{digest}"


class AccountEntityBase(BaseModel):
    """Shared fields for normalized account entities."""

    model_config = {"extra": "forbid"}

    source: str
    segment: str
    symbol: str
    symbol_native: str
    currency: str = "INR"
    instrument_id: str | None = None
    provider_native: dict[str, Any] = Field(default_factory=dict)
    dedup_key: str
