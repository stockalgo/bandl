"""Provider protocols and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from bandl.v2.models import OHLCV, SymbolInfo
from bandl.v2.models.types import Interval


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
