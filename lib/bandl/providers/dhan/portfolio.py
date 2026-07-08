"""Dhan v2 live portfolio (positions/holdings/funds)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.capabilities import CapabilityDetail, PortfolioCapabilities
from bandl.exceptions import ProviderError
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import OrderSide, Segment
from bandl.models.trading import Balance, Holding, MarginInfo, Position, ProductType
from bandl.providers.dhan.common import DHAN_API, SEGMENT_TO_EXCHANGE
from bandl.providers.dhan.trading import _PRODUCT_IN, _bandl_segment

if TYPE_CHECKING:
    from bandl.providers.dhan.provider import DhanProvider


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


class DhanPortfolioMixin:
    """Live positions/holdings/funds mixed into DhanProvider."""

    def portfolio_capabilities(self: DhanProvider) -> PortfolioCapabilities:
        return PortfolioCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.EQUITY_CASH, Segment.EQUITY_FNO, Segment.COMMODITY],
            positions=CapabilityDetail(supported=True),
            holdings=CapabilityDetail(supported=True),
            balances=CapabilityDetail(
                supported=True,
                notes=["GET /fundlimit — single account-level balance, not per-segment"],
            ),
            margin=CapabilityDetail(
                supported=True,
                notes=["span/exposure not available (order-level margincalculator not wired)"],
            ),
        )

    def get_positions(self: DhanProvider) -> list[Position]:
        raw = self._http.get_json(
            f"{DHAN_API}/positions",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        if not isinstance(raw, list):
            raise ProviderError(self.provider_id, "Unexpected positions payload")
        out: list[Position] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            net_qty = _dec(row.get("netQty")) or Decimal(0)
            position_type = str(row.get("positionType", "")).upper()
            if position_type == "CLOSED" and net_qty == 0:
                continue
            side = OrderSide.SELL if position_type == "SHORT" else OrderSide.BUY
            seg_raw = str(row.get("exchangeSegment", ""))
            exchange = SEGMENT_TO_EXCHANGE.get(seg_raw.upper(), seg_raw)
            tsym = str(row.get("tradingSymbol", ""))
            product = str(row.get("productType", "")).upper()
            realized = _dec(row.get("realizedProfit"))
            unrealized = _dec(row.get("unrealizedProfit"))
            pnl = None
            if realized is not None or unrealized is not None:
                pnl = (realized or Decimal(0)) + (unrealized or Decimal(0))
            out.append(
                Position(
                    side=side,
                    quantity=net_qty,
                    average_price=_dec(row.get("costPrice")) or Decimal(0),
                    last_price=None,
                    close_price=None,
                    product=_PRODUCT_IN.get(product, ProductType.OTHER),
                    multiplier=_dec(row.get("multiplier")),
                    buy_quantity=_dec(row.get("buyQty")),
                    sell_quantity=_dec(row.get("sellQty")),
                    realized_pnl=realized,
                    unrealized_pnl=unrealized,
                    pnl=pnl,
                    source=self.provider_id,
                    segment=_bandl_segment(seg_raw),
                    symbol=f"{exchange}:{tsym}" if exchange and tsym else tsym,
                    symbol_native=tsym,
                    instrument_id=str(row["securityId"]) if row.get("securityId") else None,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(
                        self.provider_id,
                        "position",
                        f"{seg_raw}:{tsym}:{product}",
                    ),
                ),
            )
        return out

    def get_holdings(self: DhanProvider) -> list[Holding]:
        try:
            raw = self._http.get_json(
                f"{DHAN_API}/holdings",
                provider=self.provider_id,
                headers=self._auth_headers(),
            )
        except ProviderError as err:
            # Dhan returns HTTP 500 DH-1111 "No holdings available" instead of []
            # when the demat account simply has zero equity holdings.
            if "DH-1111" in str(err) or "No holdings available" in str(err):
                return []
            raise
        if not isinstance(raw, list):
            raise ProviderError(self.provider_id, "Unexpected holdings payload")
        out: list[Holding] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            exchange = str(row.get("exchange", "NSE"))
            tsym = str(row.get("tradingSymbol", ""))
            out.append(
                Holding(
                    quantity=_dec(row.get("totalQty")) or Decimal(0),
                    t1_quantity=_dec(row.get("t1Qty")),
                    average_price=_dec(row.get("avgCostPrice")),
                    last_price=None,
                    close_price=None,
                    pnl=None,
                    day_change=None,
                    day_change_pct=None,
                    collateral_quantity=_dec(row.get("collateralQty")),
                    collateral_type=None,
                    isin=row.get("isin") or None,
                    source=self.provider_id,
                    segment=Segment.EQUITY_CASH,
                    symbol=f"{exchange}:{tsym}" if tsym else tsym,
                    symbol_native=tsym,
                    instrument_id=str(row["securityId"]) if row.get("securityId") else None,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(self.provider_id, "holding", f"{exchange}:{tsym}"),
                ),
            )
        return out

    def _fund_limit(self: DhanProvider) -> dict[str, Any]:
        raw = self._http.get_json(
            f"{DHAN_API}/fundlimit",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, "Unexpected fundlimit payload")
        return raw

    def get_balances(self: DhanProvider) -> list[Balance]:
        raw = self._fund_limit()
        available = _dec(raw.get("availabelBalance")) or Decimal(0)
        used = _dec(raw.get("utilizedAmount")) or Decimal(0)
        return [
            Balance(
                source=self.provider_id,
                segment=None,
                currency="INR",
                available=available,
                used=used,
                total=available + used,
                provider_native=raw,
            ),
        ]

    def get_margin(self: DhanProvider) -> MarginInfo:
        raw = self._fund_limit()
        available = _dec(raw.get("availabelBalance")) or Decimal(0)
        used = _dec(raw.get("utilizedAmount")) or Decimal(0)
        return MarginInfo(
            source=self.provider_id,
            currency="INR",
            available=available,
            used=used,
            total=available + used,
            span=None,
            exposure=None,
            provider_native=raw,
        )
