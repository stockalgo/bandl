"""Account history facet on the Bandl client."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from bandl.core.account_filters import AccountFilters, default_account_range
from bandl.core.capabilities import AccountCapabilities
from bandl.core.dataframe import models_to_dataframe
from bandl.core.provider import AccountHistoryProvider
from bandl.exceptions import BandlError, ConfigurationError, UnsupportedCapabilityError
from bandl.models.account import AccountFill, AccountOrder, LedgerEntry, PnLProvenance, PnLRecord
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import PnLConfidence, PnLGranularity, PnLSourceType


def _to_dataframe(rows: list[Any]) -> pd.DataFrame:
    return models_to_dataframe(rows)


def _merge_by_dedup(rows: list[Any]) -> list[Any]:
    seen: dict[str, Any] = {}
    for row in rows:
        seen[row.dedup_key] = row
    return list(seen.values())


def _sum_optional(values: Iterable[Decimal | None]) -> Decimal | None:
    """Sum non-``None`` values; ``None`` only if every value was ``None``."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present, Decimal(0))


def _effective_total(r: PnLRecord) -> Decimal | None:
    if r.total_pnl is not None:
        return r.total_pnl
    if r.realized_pnl is not None or r.unrealized_pnl is not None:
        return (r.realized_pnl or Decimal(0)) + (r.unrealized_pnl or Decimal(0))
    return None


_CONFIDENCE_RANK: dict[str, int] = {
    PnLConfidence.LOW: 0,
    PnLConfidence.MEDIUM: 1,
    PnLConfidence.HIGH: 2,
}


def _lowest_confidence(confidences: list[Any]) -> str:
    return min(confidences, key=lambda c: _CONFIDENCE_RANK.get(c, 1))


@dataclass
class AccountFacet:
    client: Any

    def _providers_for(self, source: str | None) -> list[tuple[str, AccountHistoryProvider]]:
        if source is not None:
            prov = self.client._get_provider(source)
            if not isinstance(prov, AccountHistoryProvider):
                raise ConfigurationError(f"Provider '{source}' does not support account history")
            return [(source, prov)]
        out: list[tuple[str, AccountHistoryProvider]] = []
        for pid in self.client.list_providers():
            prov = self.client._get_provider(pid)
            if isinstance(prov, AccountHistoryProvider):
                out.append((pid, prov))
        if not out:
            raise ConfigurationError("No providers with account history support are configured")
        return out

    def capabilities(
        self, source: str | None = None
    ) -> AccountCapabilities | dict[str, AccountCapabilities]:
        if source is not None:
            prov = self.client._get_provider(source)
            if not isinstance(prov, AccountHistoryProvider):
                raise ConfigurationError(f"Provider '{source}' does not support account history")
            return prov.account_capabilities()
        return {pid: prov.account_capabilities() for pid, prov in self._providers_for(None)}

    def supports(self, source: str, capability: str) -> bool:
        caps = self.capabilities(source)
        if isinstance(caps, dict):
            raise BandlError("supports() requires a single source")
        return caps.supports(capability)

    def _filters(
        self,
        start: datetime | None,
        end: datetime | None,
        **kwargs: Any,
    ) -> AccountFilters:
        start_dt, end_dt = default_account_range(start, end)
        return AccountFilters(start=start_dt, end=end_dt, **kwargs)

    def get_orders(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        **kwargs: Any,
    ) -> list[AccountOrder]:
        filters = self._filters(start, end, **kwargs)
        rows: list[AccountOrder] = []
        for _, prov in self._providers_for(source):
            rows.extend(prov.get_orders(filters))
        return _merge_by_dedup(rows)

    def get_orders_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return _to_dataframe(self.get_orders(*args, **kwargs))

    def get_fills(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        **kwargs: Any,
    ) -> list[AccountFill]:
        filters = self._filters(start, end, **kwargs)
        rows: list[AccountFill] = []
        for _, prov in self._providers_for(source):
            caps = prov.account_capabilities()
            if not caps.fills.supported:
                raise UnsupportedCapabilityError(prov.provider_id, "fills")
            rows.extend(prov.get_fills(filters))
        return _merge_by_dedup(rows)

    def get_fills_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return _to_dataframe(self.get_fills(*args, **kwargs))

    def get_ledger_entries(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        **kwargs: Any,
    ) -> list[LedgerEntry]:
        filters = self._filters(start, end, **kwargs)
        rows: list[LedgerEntry] = []
        for _, prov in self._providers_for(source):
            caps = prov.account_capabilities()
            if not caps.ledger.supported:
                raise UnsupportedCapabilityError(prov.provider_id, "ledger")
            rows.extend(prov.get_ledger_entries(filters))
        return _merge_by_dedup(rows)

    def get_ledger_entries_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return _to_dataframe(self.get_ledger_entries(*args, **kwargs))

    def get_pnl(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        granularity: str = PnLGranularity.SYMBOL,
        prefer: str = "auto",
        reconcile: bool = False,
        scope: str | None = None,
        **kwargs: Any,
    ) -> list[PnLRecord]:
        """``scope``: ``None`` (default) excludes day-book rows — safe to sum.
        Pass ``"day"``/``"net"``/``"holding"`` to isolate one book, or ``"all"``
        for every row. See ``PnLRecord.scope`` / ``zero_avg_price_artifact``.
        """
        filters = self._filters(start, end, **kwargs)
        rows: list[PnLRecord] = []
        for _, prov in self._providers_for(source):
            rows.extend(
                prov.get_pnl(
                    filters,
                    granularity=granularity,
                    prefer=prefer,
                    reconcile=reconcile,
                    scope=scope,
                ),
            )
        return _merge_by_dedup(rows)

    def get_pnl_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return _to_dataframe(self.get_pnl(*args, **kwargs))

    def get_pnl_summary(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        prefer: str = "auto",
        reconcile: bool = True,
        **kwargs: Any,
    ) -> list[PnLRecord]:
        """One row per symbol, safe to ``sum()`` — rolls up whatever ``get_pnl()``'s
        default (day-book-excluded) scope returns, so callers never need to
        hand-roll day/net/holding reconciliation themselves.
        """
        rows = self.get_pnl(
            start,
            end,
            source=source,
            prefer=prefer,
            reconcile=reconcile,
            scope=None,
            **kwargs,
        )
        by_symbol: dict[str, list[PnLRecord]] = {}
        for r in rows:
            by_symbol.setdefault(r.symbol, []).append(r)

        now = datetime.now(timezone.utc)
        summary: list[PnLRecord] = []
        for sym, sym_rows in sorted(by_symbol.items()):
            realized = _sum_optional(r.realized_pnl for r in sym_rows)
            unrealized = _sum_optional(r.unrealized_pnl for r in sym_rows)
            total = _sum_optional(_effective_total(r) for r in sym_rows)
            sources = sorted({r.source for r in sym_rows})
            confidences = [r.provenance.confidence for r in sym_rows]
            summary.append(
                PnLRecord(
                    pnl_id=f"summary:{sym}",
                    granularity=PnLGranularity.SYMBOL,
                    scope=None,
                    realized_pnl=realized,
                    unrealized_pnl=unrealized,
                    total_pnl=total,
                    currency=sym_rows[0].currency,
                    symbol=sym,
                    as_of=now,
                    provenance=PnLProvenance(
                        source_type=PnLSourceType.HYBRID
                        if len({r.provenance.source_type for r in sym_rows}) > 1
                        else sym_rows[0].provenance.source_type,
                        includes_fees=all(r.provenance.includes_fees for r in sym_rows),
                        confidence=_lowest_confidence(confidences),
                        warnings=[
                            f"Rollup of {len(sym_rows)} row(s): "
                            f"{', '.join(sorted({r.pnl_id for r in sym_rows}))}",
                        ],
                    ),
                    source=sources[0] if len(sources) == 1 else "multiple",
                    segment=sym_rows[0].segment,
                    symbol_native=sym_rows[0].symbol_native,
                    provider_native={},
                    dedup_key=make_dedup_key("summary", "pnl", sym),
                    metadata={"contributing_pnl_ids": sorted({r.pnl_id for r in sym_rows})},
                ),
            )
        return summary

    def get_pnl_summary_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return _to_dataframe(self.get_pnl_summary(*args, **kwargs))

    def export_analysis_bundle(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        sources: list[str] | None = None,
        include_native: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Export normalized tables + capability manifest for AI/analysis tools."""
        if sources:
            caps = {s: self.capabilities(s) for s in sources}
            orders: list[AccountOrder] = []
            fills: list[AccountFill] = []
            ledger: list[LedgerEntry] = []
            pnl: list[PnLRecord] = []
            for src in sources:
                orders.extend(self.get_orders(start, end, source=src, **kwargs))
                fills.extend(self.get_fills(start, end, source=src, **kwargs))
                try:
                    ledger.extend(self.get_ledger_entries(start, end, source=src, **kwargs))
                except UnsupportedCapabilityError:
                    pass
                try:
                    pnl.extend(
                        self.get_pnl(
                            start,
                            end,
                            source=src,
                            prefer="auto",
                            reconcile=True,
                            **kwargs,
                        ),
                    )
                except UnsupportedCapabilityError:
                    pass
        else:
            caps = self.capabilities()
            orders = self.get_orders(start, end, **kwargs)
            fills = self.get_fills(start, end, **kwargs)
            ledger = []
            pnl = []
            try:
                ledger = self.get_ledger_entries(start, end, **kwargs)
            except UnsupportedCapabilityError:
                pass
            try:
                pnl = self.get_pnl(start, end, prefer="auto", reconcile=True, **kwargs)
            except UnsupportedCapabilityError:
                pass

        def _dump(rows: list[Any]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for r in rows:
                d = r.model_dump()
                if not include_native:
                    d.pop("provider_native", None)
                out.append(d)
            return out

        caps_dump: Any
        if isinstance(caps, dict):
            caps_dump = {k: v.model_dump() for k, v in caps.items()}
        else:
            caps_dump = caps.model_dump()

        start_dt, end_dt = default_account_range(start, end)
        if sources:
            src_list: list[str] = sources
        elif isinstance(caps, dict):
            src_list = list(caps.keys())
        else:
            src_list = [caps.provider_id]
        return {
            "manifest": {
                "version": "1",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "sources": src_list,
            },
            "capabilities": caps_dump,
            "orders": _dump(orders),
            "fills": _dump(fills),
            "ledger": _dump(ledger),
            "pnl": _dump(pnl),
        }
