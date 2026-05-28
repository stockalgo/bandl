"""Account history facet on the Bandl client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from bandl.core.account_filters import AccountFilters, default_account_range
from bandl.core.capabilities import AccountCapabilities
from bandl.core.provider import AccountHistoryProvider
from bandl.exceptions import BandlError, ConfigurationError, UnsupportedCapabilityError
from bandl.models.account import AccountFill, AccountOrder, LedgerEntry, PnLRecord
from bandl.models.account.types import PnLGranularity


def _to_dataframe(rows: list[Any]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([r.model_dump() for r in rows])


def _merge_by_dedup(rows: list[Any]) -> list[Any]:
    seen: dict[str, Any] = {}
    for row in rows:
        seen[row.dedup_key] = row
    return list(seen.values())


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
        **kwargs: Any,
    ) -> list[PnLRecord]:
        filters = self._filters(start, end, **kwargs)
        rows: list[PnLRecord] = []
        for _, prov in self._providers_for(source):
            rows.extend(
                prov.get_pnl(
                    filters,
                    granularity=granularity,
                    prefer=prefer,
                    reconcile=reconcile,
                ),
            )
        return _merge_by_dedup(rows)

    def get_pnl_dataframe(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return _to_dataframe(self.get_pnl(*args, **kwargs))

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
