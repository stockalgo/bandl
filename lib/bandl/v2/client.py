"""High-level synchronous Bandl V2 client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from bandl.v2.config import BandlConfig, ProviderSettings
from bandl.v2.core.registry import ProviderRegistry
from bandl.v2.core.resolver import ResolvedSymbol, resolve_symbol
from bandl.v2.exceptions import BandlError, ConfigurationError
from bandl.v2.models import OHLCV, SymbolInfo
from bandl.v2.models.types import AssetType, Interval
from bandl.v2.providers.crypto.binance import BinanceProvider
from bandl.v2.providers.crypto.coindcx import CoinDCXProvider
from bandl.v2.providers.equity.zerodha import ZerodhaProvider


def _default_range(
    start: datetime | None,
    end: datetime | None,
    *,
    default_days: int = 30,
) -> tuple[datetime, datetime]:
    end_dt = end or datetime.now(timezone.utc)
    if start is None:
        start_dt = end_dt - timedelta(days=default_days)
    else:
        start_dt = start
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if start_dt >= end_dt:
        raise BandlError("start must be before end")
    return start_dt, end_dt


@dataclass
class _Facet:
    client: Bandl
    default_source: str

    def get_ohlcv(
        self,
        symbol: str,
        interval: Interval | str = Interval.D1,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        **kwargs: Any,
    ) -> list[OHLCV]:
        src = source or self.default_source
        return self.client.get_ohlcv(
            symbol,
            interval,
            start,
            end,
            source=src,
            **kwargs,
        )

    def get_ohlcv_dataframe(
        self,
        symbol: str,
        interval: Interval | str = Interval.D1,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        src = source or self.default_source
        return self.client.get_ohlcv_dataframe(
            symbol,
            interval,
            start,
            end,
            source=src,
            **kwargs,
        )

    def list_symbols(
        self,
        *,
        source: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[SymbolInfo]:
        return self.client.list_symbols(
            source=source or self.default_source,
            search=search,
            limit=limit,
        )


class Bandl:
    """Entry point for historical OHLCV.

    Use ``get_ohlcv`` for ``list[OHLCV]`` or ``get_ohlcv_dataframe`` for a pandas
    ``DataFrame``.
    """

    def __init__(self, config: BandlConfig | None = None) -> None:
        self._config = config or BandlConfig()
        self._registry = ProviderRegistry()
        self._registry.register("binance", BinanceProvider(self._config))
        self._registry.register("coindcx", CoinDCXProvider(self._config))
        self._registry.register("zerodha", ZerodhaProvider(self._config))
        self.crypto = _Facet(self, self._config.default_crypto_provider)
        self.equity = _Facet(self, self._config.default_equity_provider)

    def _pick_default_source(self, rs: ResolvedSymbol) -> str:
        if rs.asset_type in (
            AssetType.CRYPTO_SPOT,
            AssetType.CRYPTO_PERP,
            AssetType.CRYPTO_FUTURE,
        ):
            return self._config.default_crypto_provider
        return self._config.default_equity_provider

    def _get_provider(self, source: str) -> Any:
        try:
            return self._registry.get(source)
        except KeyError as err:
            raise ConfigurationError(f"Unknown provider '{source}'") from err

    def get_ohlcv(
        self,
        symbol: str,
        interval: Interval | str = Interval.D1,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        asset_type: AssetType | None = None,
        **kwargs: Any,
    ) -> list[OHLCV]:
        rs = resolve_symbol(symbol, asset_type=asset_type)
        prov_id = source or self._pick_default_source(rs)
        prov = self._get_provider(prov_id)
        start_dt, end_dt = _default_range(start, end)
        return prov.get_ohlcv(
            symbol,
            interval,
            start_dt,
            end_dt,
            asset_type=asset_type,
            **kwargs,
        )

    def get_ohlcv_dataframe(
        self,
        symbol: str,
        interval: Interval | str = Interval.D1,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        asset_type: AssetType | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        rows = self.get_ohlcv(
            symbol,
            interval,
            start,
            end,
            source=source,
            asset_type=asset_type,
            **kwargs,
        )
        rec: list[dict[str, Any]] = []
        for r in rows:
            rec.append(r.model_dump())
        return pd.DataFrame(rec)

    def list_symbols(
        self,
        *,
        source: str,
        search: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> list[SymbolInfo]:
        prov = self._get_provider(source)
        return prov.list_symbols(search=search, limit=limit, **kwargs)

    def list_providers(self) -> list[str]:
        return self._registry.list_providers()

    def configure_provider(self, name: str, settings: ProviderSettings) -> None:
        """Replace provider instance using updated settings."""
        self._config.providers[name] = settings
        if name == "binance":
            self._registry.register(name, BinanceProvider(self._config, settings))
        elif name == "coindcx":
            self._registry.register(name, CoinDCXProvider(self._config, settings))
        elif name == "zerodha":
            self._registry.register(name, ZerodhaProvider(self._config, settings))
        else:
            raise BandlError(f"Unknown provider '{name}'")
