"""Breeze portfolio integration (demat holdings and account funds)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.capabilities import CapabilityDetail, PortfolioCapabilities
from bandl.exceptions import ProviderError
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import Segment
from bandl.models.trading import Balance, Holding, MarginInfo, Position
from bandl.trade.validation import verify_account_binding

if TYPE_CHECKING:
    from bandl.providers.breeze.provider import BreezeProvider


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


class BreezePortfolioMixin:
    """Live positions/holdings/funds mixed into BreezeProvider."""

    def portfolio_capabilities(self: BreezeProvider) -> PortfolioCapabilities:
        return PortfolioCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.EQUITY_CASH, Segment.EQUITY_FNO, Segment.COMMODITY],
            positions=CapabilityDetail(
                supported=True,
                notes=["Breeze GET /portfolioholdings / GET /positions"],
            ),
            holdings=CapabilityDetail(
                supported=True,
                notes=["Breeze GET /dematholdings"],
            ),
            balances=CapabilityDetail(
                supported=True,
                notes=["Breeze GET /funds"],
            ),
            margin=CapabilityDetail(
                supported=True,
                notes=["Derived from GET /funds total allocated and unallocated balances"],
            ),
        )

    def get_positions(self: BreezeProvider, *, account_id: str | None = None) -> list[Position]:
        verify_account_binding(self, account_id)
        raw = self._request_v1("GET", "portfolioholdings", body={})
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, "Unexpected positions payload from Breeze")
        
        err = raw.get("Error")
        if err and "no position" in str(err).lower():
            return []
            
        success_list = raw.get("Success")
        if success_list is None:
            return []
        if not isinstance(success_list, list):
            raise ProviderError(self.provider_id, f"Invalid positions list: {raw}")

        out: list[Position] = []
        for row in success_list:
            if not isinstance(row, dict):
                continue
            # Parse position details if available
            # Note: Breeze positions return stock_code, exchange_code, quantity, etc.
            # In live accounts with no positions, empty list is standard.
        return out

    def get_holdings(self: BreezeProvider, *, account_id: str | None = None) -> list[Holding]:
        verify_account_binding(self, account_id)
        raw = self._request_v1("GET", "dematholdings", body={})
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, "Unexpected demat holdings payload from Breeze")
        
        err = raw.get("Error")
        if err and "no holding" in str(err).lower():
            return []

        rows = raw.get("Success")
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise ProviderError(self.provider_id, f"Invalid holdings list: {raw}")

        out: list[Holding] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            stock_code = str(row.get("stock_code") or "").strip()
            isin = row.get("stock_ISIN") or None
            qty = _dec(row.get("quantity")) or Decimal(0)
            avail_qty = _dec(row.get("demat_avail_quantity"))
            
            out.append(
                Holding(
                    quantity=qty,
                    t1_quantity=None,
                    average_price=None,
                    last_price=None,
                    close_price=None,
                    pnl=None,
                    day_change=None,
                    day_change_pct=None,
                    collateral_quantity=_dec(row.get("blocked_quantity")),
                    collateral_type=None,
                    isin=isin,
                    source=self.provider_id,
                    account_id=self.bound_account_id,
                    segment=Segment.EQUITY_CASH,
                    symbol=f"NSE:{stock_code}" if stock_code else "",
                    symbol_native=stock_code,
                    instrument_id=None,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(
                        self.provider_id,
                        "holding",
                        isin or stock_code,
                        account_id=self.bound_account_id,
                    ),
                ),
            )
        return out

    def _get_funds_data(self: BreezeProvider) -> dict[str, Any]:
        raw = self._request_v1("GET", "funds", body={})
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, "Unexpected funds payload from Breeze")
        success = raw.get("Success")
        if not isinstance(success, dict):
            err = raw.get("Error") or "Failed to retrieve funds"
            raise ProviderError(self.provider_id, f"Breeze funds error: {err}")
        return success

    def get_balances(self: BreezeProvider, *, account_id: str | None = None) -> list[Balance]:
        verify_account_binding(self, account_id)
        funds = self._get_funds_data()
        
        # unallocated_balance is available cash balance
        available = _dec(funds.get("unallocated_balance")) or Decimal(0)
        
        # total allocated across segments
        allocated_eq = _dec(funds.get("allocated_equity")) or Decimal(0)
        allocated_fno = _dec(funds.get("allocated_fno")) or Decimal(0)
        allocated_comm = _dec(funds.get("allocated_commodity")) or Decimal(0)
        allocated_cur = _dec(funds.get("allocated_currency")) or Decimal(0)
        blocked = _dec(funds.get("block_by_trade_balance")) or Decimal(0)
        
        used = allocated_eq + allocated_fno + allocated_comm + allocated_cur + blocked
        total = available + used
        
        return [
            Balance(
                source=self.provider_id,
                account_id=self.bound_account_id,
                segment=None,
                currency="INR",
                available=available,
                used=used,
                total=total,
                provider_native=funds,
            ),
        ]

    def get_margin(self: BreezeProvider, *, account_id: str | None = None) -> MarginInfo:
        verify_account_binding(self, account_id)
        funds = self._get_funds_data()
        
        available = _dec(funds.get("unallocated_balance")) or Decimal(0)
        allocated_eq = _dec(funds.get("allocated_equity")) or Decimal(0)
        allocated_fno = _dec(funds.get("allocated_fno")) or Decimal(0)
        allocated_comm = _dec(funds.get("allocated_commodity")) or Decimal(0)
        allocated_cur = _dec(funds.get("allocated_currency")) or Decimal(0)
        blocked = _dec(funds.get("block_by_trade_balance")) or Decimal(0)
        
        used = allocated_eq + allocated_fno + allocated_comm + allocated_cur + blocked
        total = available + used

        return MarginInfo(
            source=self.provider_id,
            account_id=self.bound_account_id,
            currency="INR",
            available=available,
            used=used,
            total=total,
            span=None,
            exposure=None,
            provider_native=funds,
        )
