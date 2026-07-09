from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from bandl.models.account.base import AccountEntityBase
from bandl.models.account.types import PnLConfidence, PnLSourceType

PnLScope = Literal["day", "net", "holding"]


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

    # Which broker "book" this row's economics come from. ``None`` for
    # computed/FIFO rows and aggregates, which have no book ambiguity.
    # Callers must not blend "day" rows with "net"/"holding" rows in a sum —
    # a Kite day-book row for a position closed today is costed against a
    # zero average price and can show a fabricated sign-inverted number.
    scope: PnLScope | None = None
    # True when this row's economics are anchored to a zero average price
    # because the underlying position was fully squared off intraday
    # (Kite's day-book convention) — a strong signal not to sum it in with
    # net/holding pnl.
    zero_avg_price_artifact: bool = False
