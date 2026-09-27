"""Provider protocols and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from bandl.core.account_filters import AccountFilters
from bandl.core.capabilities import AccountCapabilities, PortfolioCapabilities, TradeCapabilities
from bandl.models.account import AccountFill, AccountOrder, LedgerEntry, PnLRecord
from bandl.models.market import OHLCV, SymbolInfo
from bandl.models.market.types import Interval
from bandl.models.trading import (
    Balance,
    Holding,
    MarginInfo,
    Order,
    OrderAcknowledgement,
    OrderRequest,
    Position,
)


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
        scope: str | None = None,
    ) -> list[PnLRecord]: ...


@runtime_checkable
class TradingProvider(Protocol):
    """Base trading provider protocol for capability discovery."""

    provider_id: str

    def trade_capabilities(self) -> TradeCapabilities: ...


@runtime_checkable
class FullTradingProvider(TradingProvider, Protocol):
    """Full-featured trading provider supporting the complete set of trade operations."""

    bound_account_id: str | None

    def place_order(self, order: OrderRequest, *, account_id: str | None = None) -> Order: ...

    def place_order_ack(
        self, order: OrderRequest, *, account_id: str | None = None
    ) -> OrderAcknowledgement: ...

    def modify_order(
        self,
        order_id: str,
        *,
        account_id: str | None = None,
        price: Any = None,
        trigger_price: Any = None,
        quantity: Any = None,
        validity: Any = None,
    ) -> Order: ...

    def modify_order_ack(
        self,
        order_id: str,
        *,
        account_id: str | None = None,
        price: Any = None,
        trigger_price: Any = None,
        quantity: Any = None,
        validity: Any = None,
    ) -> OrderAcknowledgement: ...

    def cancel_order(self, order_id: str, *, account_id: str | None = None) -> Order: ...

    def cancel_order_ack(
        self, order_id: str, *, account_id: str | None = None
    ) -> OrderAcknowledgement: ...

    def get_open_orders(
        self, *, symbol: str | None = None, account_id: str | None = None
    ) -> list[Order]: ...

    def get_orders(
        self, *, symbol: str | None = None, account_id: str | None = None
    ) -> list[Order]: ...

    def get_order(self, order_id: str, *, account_id: str | None = None) -> Order: ...

    def get_order_history(self, order_id: str, *, account_id: str | None = None) -> list[Order]: ...

    def get_trades(
        self, *, symbol: str | None = None, account_id: str | None = None
    ) -> list[AccountFill]: ...


@runtime_checkable
class PortfolioProvider(Protocol):
    """Base portfolio provider protocol for capability discovery."""

    provider_id: str

    def portfolio_capabilities(self) -> PortfolioCapabilities: ...


@runtime_checkable
class FullPortfolioProvider(PortfolioProvider, Protocol):
    """Full-featured portfolio provider supporting all portfolio reads."""

    bound_account_id: str | None

    def get_positions(self, *, account_id: str | None = None) -> list[Position]: ...

    def get_holdings(self, *, account_id: str | None = None) -> list[Holding]: ...

    def get_balances(self, *, account_id: str | None = None) -> list[Balance]: ...

    def get_margin(self, *, account_id: str | None = None) -> MarginInfo: ...
