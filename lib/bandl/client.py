"""High-level synchronous Bandl client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from bandl.account.facet import AccountFacet
from bandl.config import BandlConfig, ProviderSettings
from bandl.core.dataframe import models_to_dataframe
from bandl.core.registry import ProviderRegistry
from bandl.core.resolver import ResolvedSymbol, resolve_symbol
from bandl.core.time import default_time_range
from bandl.exceptions import BandlError, ConfigurationError
from bandl.models.market import OHLCV, SymbolInfo, Ticker
from bandl.models.market.types import AssetType, Interval
from bandl.providers.crypto.binance import BinanceProvider
from bandl.providers.crypto.coindcx import CoinDCXProvider
from bandl.providers.crypto.common import is_crypto_futures
from bandl.providers.equity.zerodha import ZerodhaProvider

_PROVIDER_CLASSES: dict[str, type] = {
    "binance": BinanceProvider,
    "coindcx": CoinDCXProvider,
    "zerodha": ZerodhaProvider,
}


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
        asset_type: AssetType | None = None,
        **kwargs: Any,
    ) -> list[SymbolInfo]:
        return self.client.list_symbols(
            source=source or self.default_source,
            search=search,
            limit=limit,
            asset_type=asset_type,
            **kwargs,
        )

    def get_24hr_tickers(
        self,
        *,
        source: str | None = None,
        asset_type: AssetType | None = None,
    ) -> list[Ticker]:
        return self.client.get_24hr_tickers(
            source=source or self.default_source,
            asset_type=asset_type,
        )


class Bandl:
    """Unified market data and account history."""

    def __init__(self, config: BandlConfig | None = None) -> None:
        self._config = config or BandlConfig()
        self._registry = ProviderRegistry()
        self._registry.register("binance", BinanceProvider(self._config))
        self._registry.register("coindcx", CoinDCXProvider(self._config))
        self._registry.register("zerodha", ZerodhaProvider(self._config))
        self.crypto = _Facet(self, self._config.default_crypto_provider)
        self.equity = _Facet(self, self._config.default_equity_provider)
        self.account = AccountFacet(self)

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
        start_dt, end_dt = default_time_range(start, end)
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
        return models_to_dataframe(rows)

    def list_symbols(
        self,
        *,
        source: str,
        search: str | None = None,
        limit: int | None = None,
        asset_type: AssetType | None = None,
        **kwargs: Any,
    ) -> list[SymbolInfo]:
        prov = self._get_provider(source)
        return prov.list_symbols(
            search=search,
            limit=limit,
            asset_type=asset_type,
            **kwargs,
        )

    def get_24hr_tickers(
        self,
        *,
        source: str,
        asset_type: AssetType | None = None,
    ) -> list[Ticker]:
        """Rolling 24h ticker stats (Binance / CoinDCX USDT-M futures)."""
        prov = self._get_provider(source)
        if asset_type is not None and not is_crypto_futures(asset_type):
            raise BandlError(
                f"24hr tickers require crypto futures asset_type, got {asset_type!r}",
            )
        if hasattr(prov, "get_futures_24hr_tickers"):
            return prov.get_futures_24hr_tickers()
        raise BandlError(
            f"24hr tickers not supported for source={source!r} asset_type={asset_type!r}",
        )

    def list_providers(self) -> list[str]:
        return self._registry.list_providers()

    def configure_provider(self, name: str, settings: ProviderSettings) -> None:
        """Replace provider instance using updated settings."""
        self._config.providers[name] = settings
        cls = _PROVIDER_CLASSES.get(name)
        if cls is None:
            raise BandlError(f"Unknown provider '{name}'")
        self._registry.register(name, cls(self._config, settings))
