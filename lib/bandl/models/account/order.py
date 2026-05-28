from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from bandl.models.account.base import AccountEntityBase


class AccountOrder(AccountEntityBase):
    order_id: str
    client_order_id: str | None = None
    side: str
    order_type: str
    status: str
    quantity: Decimal
    filled_quantity: Decimal | None = None
    limit_price: Decimal | None = None
    average_fill_price: Decimal | None = None
    created_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
