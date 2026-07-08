"""Zerodha Kite live portfolio (positions/holdings/margins)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.capabilities import CapabilityDetail, PortfolioCapabilities
from bandl.exceptions import ProviderError
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import OrderSide, Segment
from bandl.models.trading import Balance, Holding, MarginInfo, Position, ProductType
from bandl.providers.equity.zerodha.account import _canonical_symbol, _kite_segment
from bandl.providers.equity.zerodha.common import KITE_API, kite_unwrap
from bandl.providers.equity.zerodha.trading import _PRODUCT_IN

if TYPE_CHECKING:
    from bandl.providers.equity.zerodha.provider import ZerodhaProvider


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


class ZerodhaPortfolioMixin:
    """Live positions/holdings/margins mixed into ZerodhaProvider."""

    def portfolio_capabilities(self: ZerodhaProvider) -> PortfolioCapabilities:
        return PortfolioCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.EQUITY_CASH, Segment.EQUITY_FNO, Segment.COMMODITY],
            positions=CapabilityDetail(
                supported=True,
                notes=["net book only; day book not exposed"],
            ),
            holdings=CapabilityDetail(supported=True),
            balances=CapabilityDetail(supported=True, notes=["per-segment: equity, commodity"]),
            margin=CapabilityDetail(supported=True, notes=["equity segment"]),
        )

    def get_positions(self: ZerodhaProvider) -> list[Position]:
        raw = self._http.get_json(
            f"{KITE_API}/portfolio/positions",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, dict):
            raise ProviderError(self.provider_id, "Unexpected positions payload")
        rows = payload.get("net", [])
        if not isinstance(rows, list):
            return []
        out: list[Position] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            qty = Decimal(str(row.get("quantity", 0)))
            if qty == 0:
                continue
            exchange = str(row.get("exchange", "NSE"))
            tsym = str(row.get("tradingsymbol", ""))
            product = str(row.get("product", ""))
            out.append(
                Position(
                    side=OrderSide.BUY if qty >= 0 else OrderSide.SELL,
                    quantity=qty,
                    average_price=Decimal(str(row.get("average_price", 0))),
                    last_price=_dec(row.get("last_price")),
                    close_price=_dec(row.get("close_price")),
                    product=_PRODUCT_IN.get(product.upper(), ProductType.OTHER),
                    multiplier=_dec(row.get("multiplier")),
                    buy_quantity=_dec(row.get("buy_quantity")),
                    sell_quantity=_dec(row.get("sell_quantity")),
                    realized_pnl=_dec(row.get("realised")),
                    unrealized_pnl=_dec(row.get("unrealised")),
                    pnl=_dec(row.get("pnl")),
                    source=self.provider_id,
                    segment=_kite_segment(exchange, product),
                    symbol=_canonical_symbol(exchange, tsym),
                    symbol_native=tsym,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(
                        self.provider_id,
                        "position",
                        f"{exchange}:{tsym}:{product}",
                    ),
                ),
            )
        return out

    def get_holdings(self: ZerodhaProvider) -> list[Holding]:
        raw = self._http.get_json(
            f"{KITE_API}/portfolio/holdings",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, list):
            raise ProviderError(self.provider_id, "Unexpected holdings payload")
        out: list[Holding] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            exchange = str(row.get("exchange", "NSE"))
            tsym = str(row.get("tradingsymbol", ""))
            out.append(
                Holding(
                    quantity=Decimal(str(row.get("quantity", 0))),
                    t1_quantity=_dec(row.get("t1_quantity")),
                    average_price=_dec(row.get("average_price")),
                    last_price=_dec(row.get("last_price")),
                    close_price=_dec(row.get("close_price")),
                    pnl=_dec(row.get("pnl")),
                    day_change=_dec(row.get("day_change")),
                    day_change_pct=_dec(row.get("day_change_percentage")),
                    collateral_quantity=_dec(row.get("collateral_quantity")),
                    collateral_type=row.get("collateral_type") or None,
                    isin=row.get("isin") or None,
                    source=self.provider_id,
                    segment=Segment.EQUITY_CASH,
                    symbol=_canonical_symbol(exchange, tsym),
                    symbol_native=tsym,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(self.provider_id, "holding", f"{exchange}:{tsym}"),
                ),
            )
        return out

    def _margins(self: ZerodhaProvider) -> dict[str, Any]:
        raw = self._http.get_json(
            f"{KITE_API}/user/margins",
            provider=self.provider_id,
            headers=self._auth_headers(),
        )
        payload = kite_unwrap(raw, provider_id=self.provider_id)
        if not isinstance(payload, dict):
            raise ProviderError(self.provider_id, "Unexpected margins payload")
        return payload

    def get_balances(self: ZerodhaProvider) -> list[Balance]:
        payload = self._margins()
        out: list[Balance] = []
        for seg_name, seg_row in payload.items():
            if not isinstance(seg_row, dict):
                continue
            utilised = seg_row.get("utilised", {})
            utilised = utilised if isinstance(utilised, dict) else {}
            net = _dec(seg_row.get("net")) or Decimal(0)
            used = _dec(utilised.get("debits")) or Decimal(0)
            segment = Segment.EQUITY_CASH.value if seg_name == "equity" else Segment.COMMODITY.value
            out.append(
                Balance(
                    source=self.provider_id,
                    segment=segment,
                    currency="INR",
                    available=net,
                    used=used,
                    total=net + used,
                    provider_native=seg_row,
                ),
            )
        return out

    def get_margin(self: ZerodhaProvider) -> MarginInfo:
        payload = self._margins()
        seg_row = payload.get("equity")
        if not isinstance(seg_row, dict):
            raise ProviderError(self.provider_id, "Unexpected margins payload (missing 'equity')")
        utilised = seg_row.get("utilised", {})
        utilised = utilised if isinstance(utilised, dict) else {}
        net = _dec(seg_row.get("net")) or Decimal(0)
        used = _dec(utilised.get("debits")) or Decimal(0)
        return MarginInfo(
            source=self.provider_id,
            currency="INR",
            available=net,
            used=used,
            total=net + used,
            span=_dec(utilised.get("span")),
            exposure=_dec(utilised.get("exposure")),
            provider_native=seg_row,
        )
