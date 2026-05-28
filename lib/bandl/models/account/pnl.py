from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from bandl.models.account.base import AccountEntityBase
from bandl.models.account.types import PnLConfidence, PnLSourceType


class PnLProvenance(BaseModel):
    model_config = {"extra": "forbid"}

    source_type: PnLSourceType | str
    cost_basis_method: str | None = None
    includes_fees: bool = True
    includes_taxes: bool | None = None
    confidence: PnLConfidence | str = PnLConfidence.MEDIUM
    warnings: list[str] = Field(default_factory=list)
    broker_computed: Decimal | None = None
    client_computed: Decimal | None = None
    discrepancy: Decimal | None = None
    discrepancy_note: str | None = None


class PnLRecord(AccountEntityBase):
    pnl_id: str
    granularity: str
    realized_pnl: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    total_pnl: Decimal | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    as_of: datetime
    provenance: PnLProvenance
    metadata: dict[str, Any] = Field(default_factory=dict)
