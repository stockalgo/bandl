from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from bandl.models.account.base import AccountEntityBase


class LedgerEntry(AccountEntityBase):
    entry_id: str
    entry_type: str
    amount: Decimal
    asset: str | None = None
    quantity: Decimal | None = None
    related_fill_id: str | None = None
    related_order_id: str | None = None
    description: str | None = None
    posted_at: datetime
