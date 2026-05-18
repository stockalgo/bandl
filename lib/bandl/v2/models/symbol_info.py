from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from bandl.v2.models.types import AssetType


class SymbolInfo(BaseModel):
    model_config = {"extra": "forbid"}

    canonical: str
    base: str
    quote: str | None = None
    asset_type: AssetType
    provider_symbol: str
    display_name: str | None = None
    min_qty: Decimal | None = None
    tick_size: Decimal | None = None
    lot_size: Decimal | None = None
    is_tradable: bool = True
