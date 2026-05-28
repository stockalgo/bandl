from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from bandl.models.account.base import AccountEntityBase


class AccountFill(AccountEntityBase):
    fill_id: str
    order_id: str | None = None
    side: str
    quantity: Decimal
    price: Decimal
    quote_quantity: Decimal | None = None
    fee: Decimal | None = None
    fee_currency: str | None = None
    executed_at: datetime
    is_maker: bool | None = None
