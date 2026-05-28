"""CoinDCX account history (authenticated)."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.account.pnl import compute_pnl_from_fills
from bandl.core.account_filters import AccountFilters
from bandl.core.auth import coindcx_signature
from bandl.core.capabilities import AccountCapabilities, CapabilityDetail
from bandl.core.time import parse_epoch_ms, to_epoch_ms
from bandl.exceptions import AuthenticationError, ProviderError
from bandl.models.account import AccountFill, AccountOrder, LedgerEntry, PnLRecord
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import (
    LedgerEntryType,
    OrderSide,
    OrderStatus,
    OrderType,
    PnLGranularity,
    Segment,
)
from bandl.providers.account_helpers import require_capability
from bandl.providers.crypto.coindcx.constants import COINDCX_API, FUTURES_TRANSACTIONS

if TYPE_CHECKING:
    from bandl.providers.crypto.coindcx.provider import CoinDCXProvider


def _symbol_to_canonical(symbol: str) -> str:
    s = symbol.upper()
    if len(s) > 3 and s.endswith(("BTC", "INR", "USDT", "ETH")):
        for quote in ("USDT", "INR", "BTC", "ETH"):
            if s.endswith(quote) and len(s) > len(quote):
                return f"{s[: -len(quote)]}{quote}"
    return s


class CoinDCXAccountMixin:
    """Account history methods mixed into CoinDCXProvider."""

    def _coindcx_auth_headers(self: CoinDCXProvider, body: dict[str, Any]) -> dict[str, str]:
        key = self._settings.api_key
        secret = self._settings.api_secret
        if not key or not secret:
            raise AuthenticationError(
                self.provider_id,
                "CoinDCX account APIs require api_key and api_secret in "
                "BandlConfig.providers['coindcx']",
            )
        sig = coindcx_signature(body, secret)
        return {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": key,
            "X-AUTH-SIGNATURE": sig,
        }

    def account_capabilities(self: CoinDCXProvider) -> AccountCapabilities:
        return AccountCapabilities(
            provider_id=self.provider_id,
            segments=[Segment.SPOT_CRYPTO, Segment.CRYPTO_FNO],
            orders=CapabilityDetail(
                supported=True,
                pagination="status_lookup",
                notes=[
                    "Spot: active_orders; Futures: POST /derivatives/futures/orders",
                ],
            ),
            fills=CapabilityDetail(
                supported=True,
                max_history_days=None,
                pagination="spot:from_id; futures:pair+date",
                notes=[
                    "Spot: POST /exchange/v1/orders/trade_history",
                    "Futures USDT: POST /derivatives/futures/trades (from_date/to_date per pair)",
                ],
            ),
            ledger=CapabilityDetail(
                supported=True,
                notes=["Futures: POST /derivatives/futures/positions/transactions"],
            ),
            pnl_broker=CapabilityDetail(
                supported=True,
                notes=[
                    "Futures: sum of transaction amount (broker-reported PnL per trade)",
                    "Spot: no broker PnL API",
                ],
            ),
            pnl_computed=CapabilityDetail(
                supported=True,
                notes=["FIFO from spot + futures fills when broker path unavailable"],
            ),
        )

    def get_orders(self: CoinDCXProvider, filters: AccountFilters) -> list[AccountOrder]:
        require_capability(self.provider_id, "orders", True)
        body: dict[str, Any] = {"timestamp": int(time.time())}
        payload = self._http.post_json(
            f"{COINDCX_API}/exchange/v1/orders/active_orders",
            provider=self.provider_id,
            body=body,
            headers=self._coindcx_auth_headers(body),
        )
        if not isinstance(payload, list):
            raise ProviderError(self.provider_id, "Unexpected active_orders payload")
        out: list[AccountOrder] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            oid = str(row.get("id") or row.get("order_id", ""))
            if not oid:
                continue
            sym_native = str(row.get("market", row.get("symbol", "")))
            sym = _symbol_to_canonical(sym_native) if sym_native else ""
            if filters.symbol and filters.symbol.upper() not in sym.upper():
                continue
            side_raw = str(row.get("side", "")).lower()
            created = parse_epoch_ms(row.get("created_at", row.get("timestamp", time.time())))
            if filters.start and created < filters.start:
                continue
            if filters.end and created > filters.end:
                continue
            out.append(
                AccountOrder(
                    order_id=oid,
                    side=side_raw if side_raw in ("buy", "sell") else OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    status=OrderStatus.OPEN,
                    quantity=Decimal(str(row.get("total_quantity", row.get("quantity", 0)))),
                    filled_quantity=Decimal(str(row.get("filled_quantity", 0))),
                    limit_price=(
                        Decimal(str(row["price"])) if row.get("price") is not None else None
                    ),
                    created_at=created,
                    source=self.provider_id,
                    segment=Segment.SPOT_CRYPTO,
                    symbol=sym,
                    symbol_native=sym_native,
                    currency="INR",
                    provider_native=row,
                    dedup_key=make_dedup_key(self.provider_id, "order", oid),
                ),
            )
        if filters.limit is not None:
            return out[: filters.limit]
        return out

    def _get_spot_fills(self: CoinDCXProvider, filters: AccountFilters) -> list[AccountFill]:
        if not filters.start or not filters.end:
            raise ProviderError(self.provider_id, "get_fills requires start and end on filters")
        all_rows: list[AccountFill] = []
        from_id: int | None = None
        safety = 0
        while safety < 200:
            safety += 1
            body: dict[str, Any] = {
                "timestamp": int(time.time()),
                "from_timestamp": to_epoch_ms(filters.start),
                "to_timestamp": to_epoch_ms(filters.end),
                "sort": "asc",
                "limit": min(filters.limit or 500, 500),
            }
            if from_id is not None:
                body["from_id"] = from_id
            if filters.symbol:
                body["symbol"] = filters.symbol.replace("/", "").upper()
            payload = self._http.post_json(
                f"{COINDCX_API}/exchange/v1/orders/trade_history",
                provider=self.provider_id,
                body=body,
                headers=self._coindcx_auth_headers(body),
            )
            if not isinstance(payload, list):
                raise ProviderError(self.provider_id, "Unexpected trade_history payload")
            if not payload:
                break
            for row in payload:
                if not isinstance(row, dict):
                    continue
                fill = self._map_coindcx_fill(row)
                if filters.side and fill.side != filters.side.lower():
                    continue
                if filters.order_id and fill.order_id != filters.order_id:
                    continue
                all_rows.append(fill)
            last_id = payload[-1].get("id") if isinstance(payload[-1], dict) else None
            if last_id is None:
                break
            from_id = int(last_id)
            if len(payload) < body["limit"]:
                break
        if filters.limit is not None:
            return all_rows[: filters.limit]
        return all_rows

    def get_fills(self: CoinDCXProvider, filters: AccountFilters) -> list[AccountFill]:
        require_capability(
            self.provider_id,
            "fills",
            self.account_capabilities().fills.supported,
        )
        if not filters.start or not filters.end:
            raise ProviderError(self.provider_id, "get_fills requires start and end on filters")
        seg = (filters.segment or "").lower()
        out: list[AccountFill] = []
        if seg in ("", Segment.SPOT_CRYPTO, Segment.SPOT_CRYPTO.value):
            out.extend(self._get_spot_fills(filters))
        if seg in ("", Segment.CRYPTO_FNO, Segment.CRYPTO_FNO.value):
            out.extend(
                self.get_futures_fills(
                    filters.start,
                    filters.end,
                    symbol=filters.symbol,
                ),
            )
        if filters.limit is not None:
            return out[: filters.limit]
        return out

    def _map_coindcx_fill(self: CoinDCXProvider, row: dict[str, Any]) -> AccountFill:
        fid = str(row["id"])
        sym_native = str(row.get("symbol", ""))
        sym = _symbol_to_canonical(sym_native)
        executed = parse_epoch_ms(row["timestamp"])
        side = str(row.get("side", "buy")).lower()
        qty = Decimal(str(row["quantity"]))
        price = Decimal(str(row["price"]))
        fee = Decimal(str(row["fee_amount"])) if row.get("fee_amount") is not None else None
        return AccountFill(
            fill_id=fid,
            order_id=str(row.get("order_id")) if row.get("order_id") else None,
            side=side,
            quantity=qty,
            price=price,
            quote_quantity=qty * price,
            fee=fee,
            fee_currency="INR",
            executed_at=executed,
            is_maker=None,
            source=self.provider_id,
            segment=Segment.SPOT_CRYPTO,
            symbol=sym,
            symbol_native=sym_native,
            currency="INR",
            provider_native=row,
            dedup_key=make_dedup_key(self.provider_id, "fill", fid),
        )

    def get_ledger_entries(self: CoinDCXProvider, filters: AccountFilters) -> list[LedgerEntry]:
        require_capability(
            self.provider_id,
            "ledger",
            self.account_capabilities().ledger.supported,
        )
        if not filters.start or not filters.end:
            raise ProviderError(self.provider_id, "get_ledger_entries requires start and end")
        from bandl.models.account.ledger import LedgerEntry as LE

        rows: list[LedgerEntry] = []
        page = 1
        while page <= 200:
            body: dict[str, Any] = {
                "timestamp": int(time.time() * 1000),
                "stage": "all",
                "page": str(page),
                "size": "100",
                "margin_currency_short_name": ["USDT", "INR"],
            }
            chunk = self._futures_post(FUTURES_TRANSACTIONS, body)
            if not isinstance(chunk, list) or not chunk:
                break
            for row in chunk:
                if not isinstance(row, dict):
                    continue
                posted = parse_epoch_ms(row.get("created_at", 0))
                if posted < filters.start or posted >= filters.end:
                    continue
                eid = str(row.get("parent_id", row.get("position_id", page)))
                rows.append(
                    LE(
                        entry_id=eid,
                        entry_type=LedgerEntryType.FEE
                        if row.get("fee_amount")
                        else LedgerEntryType.OTHER,
                        amount=Decimal(str(row.get("amount", 0))),
                        related_order_id=str(row.get("parent_id"))
                        if row.get("parent_id")
                        else None,
                        description=str(row.get("stage", "futures")),
                        posted_at=posted,
                        source=self.provider_id,
                        segment=Segment.CRYPTO_FNO,
                        symbol=_symbol_to_canonical(str(row.get("pair", ""))),
                        symbol_native=str(row.get("pair", "")),
                        currency=str(row.get("margin_currency_short_name", "USDT")),
                        provider_native=row,
                        dedup_key=make_dedup_key(self.provider_id, "ledger", eid),
                    ),
                )
            if len(chunk) < 100:
                break
            page += 1
        return rows

    def get_pnl(
        self: CoinDCXProvider,
        filters: AccountFilters,
        *,
        granularity: str = PnLGranularity.SYMBOL,
        prefer: str = "auto",
        reconcile: bool = False,
    ) -> list[PnLRecord]:
        if not filters.start or not filters.end:
            raise ProviderError(self.provider_id, "get_pnl requires start and end on filters")
        caps = self.account_capabilities()
        seg = (filters.segment or "").lower()
        rows: list[PnLRecord] = []

        want_fno = seg in ("", Segment.CRYPTO_FNO, Segment.CRYPTO_FNO.value)
        want_spot = seg in ("", Segment.SPOT_CRYPTO, Segment.SPOT_CRYPTO.value)

        if want_fno and prefer in ("auto", "broker", "hybrid") and caps.pnl_broker.supported:
            rows.extend(
                self.get_futures_pnl_from_transactions(
                    filters.start,
                    filters.end,
                    granularity=granularity,
                ),
            )

        if want_spot or (want_fno and prefer in ("computed", "hybrid", "auto") and not rows):
            fills = self.get_fills(filters)
            spot_fills = [f for f in fills if f.segment == Segment.SPOT_CRYPTO]
            fno_fills = [f for f in fills if f.segment == Segment.CRYPTO_FNO]
            if spot_fills and want_spot:
                rows.extend(
                    compute_pnl_from_fills(
                        spot_fills,
                        source=self.provider_id,
                        granularity=granularity,
                        warnings=["Spot FIFO from trade_history"],
                    ),
                )
            if fno_fills and want_fno and prefer in ("computed", "hybrid", "auto"):
                rows.extend(
                    compute_pnl_from_fills(
                        fno_fills,
                        source=self.provider_id,
                        granularity=granularity,
                        warnings=["Futures FIFO from derivatives/futures/trades"],
                    ),
                )

        if not rows:
            return []
        return rows
