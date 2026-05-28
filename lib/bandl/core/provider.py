"""Provider protocols and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from bandl.core.account_filters import AccountFilters
from bandl.core.capabilities import AccountCapabilities
from bandl.models.account import AccountFill, AccountOrder, LedgerEntry, PnLRecord
from bandl.models.market import OHLCV, SymbolInfo
from bandl.models.market.types import Interval


@runtime_checkable
class HistoricalOHLCVProvider(Protocol):
    provider_id: str

    def get_ohlcv(
        self,
        symbol: str,
        interval: Any,
        start: datetime,
        end: datetime,
    ) -> list[Any]:
        """Return ascending OHLCV bars in UTC."""
        ...

    def list_symbols(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[Any]: ...


class BaseHistoricalProvider(ABC):
    """Optional ABC for type checking; providers may duck-type instead."""

    provider_id: str

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
    ) -> list[OHLCV]:
        raise NotImplementedError

    @abstractmethod
    def list_symbols(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[SymbolInfo]:
        raise NotImplementedError


@runtime_checkable
class AccountHistoryProvider(Protocol):
    provider_id: str

    def account_capabilities(self) -> AccountCapabilities: ...

    def get_orders(self, filters: AccountFilters) -> list[AccountOrder]: ...

    def get_fills(self, filters: AccountFilters) -> list[AccountFill]: ...

    def get_ledger_entries(self, filters: AccountFilters) -> list[LedgerEntry]: ...

    def get_pnl(
        self,
        filters: AccountFilters,
        *,
        granularity: str,
        prefer: str = "auto",
        reconcile: bool = False,
    ) -> list[PnLRecord]: ...
