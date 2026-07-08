"""High-level synchronous Bandl client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from bandl.account.facet import AccountFacet
from bandl.config import BandlConfig, ProviderSettings
from bandl.core.dataframe import models_to_dataframe
from bandl.core.registry import ProviderRegistry
from bandl.core.resolver import ResolvedSymbol, resolve_symbol
from bandl.core.time import default_time_range
from bandl.exceptions import BandlError, ConfigurationError, UnsupportedCapabilityError
from bandl.models.market import (
    OHLCV,
    OptionChainEntry,
    OptionContract,
    SymbolInfo,
    Ticker,
)
from bandl.models.market.types import AssetType, Interval
from bandl.portfolio.facet import PortfolioFacet
from bandl.providers.crypto.binance import BinanceProvider
from bandl.providers.crypto.coindcx import CoinDCXProvider
from bandl.providers.crypto.common import is_crypto_futures
from bandl.providers.dhan import DhanProvider
from bandl.providers.equity.zerodha import ZerodhaProvider
from bandl.trade.facet import TradeFacet

_PROVIDER_CLASSES: dict[str, type] = {
    "binance": BinanceProvider,
    "coindcx": CoinDCXProvider,
    "zerodha": ZerodhaProvider,
    "dhan": DhanProvider,
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


@dataclass
class _DerivativesFacet:
    """Options/futures contract data (Dhan today; other brokers may opt in)."""

    client: Bandl
    default_source: str

    def get_ohlcv(
        self,
        contract: str | OptionContract,
        interval: Interval | int = Interval.M1,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        exchange: str | None = None,
        instrument_id: str | None = None,
    ) -> list[OHLCV]:
        return self.client.get_option_ohlcv(
            contract,
            interval,
            start,
            end,
            source=source or self.default_source,
            exchange=exchange,
            instrument_id=instrument_id,
        )

    def get_ohlcv_dataframe(
        self,
        contract: str | OptionContract,
        interval: Interval | int = Interval.M1,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str | None = None,
        exchange: str | None = None,
        instrument_id: str | None = None,
    ) -> pd.DataFrame:
        rows = self.get_ohlcv(
            contract,
            interval,
            start,
            end,
            source=source,
            exchange=exchange,
            instrument_id=instrument_id,
        )
        return models_to_dataframe(rows)

    def list_expiries(
        self,
        underlying: str,
        *,
        source: str | None = None,
        exchange: str,
        segment: str | None = None,
    ) -> list[date]:
        return self.client.list_expiries(
            underlying,
            source=source or self.default_source,
            exchange=exchange,
            segment=segment,
        )

    def get_option_chain(
        self,
        underlying: str,
        *,
        expiry: date,
        source: str | None = None,
        exchange: str,
        segment: str | None = None,
    ) -> list[OptionChainEntry]:
        return self.client.get_option_chain(
            underlying,
            expiry=expiry,
            source=source or self.default_source,
            exchange=exchange,
            segment=segment,
        )


class Bandl:
    """Unified market data and account history."""

    def __init__(self, config: BandlConfig | None = None) -> None:
        self._config = config or BandlConfig()
        self._registry = ProviderRegistry()
        self._registry.register("binance", BinanceProvider(self._config))
        self._registry.register("coindcx", CoinDCXProvider(self._config))
        self._registry.register("zerodha", ZerodhaProvider(self._config))
        self._registry.register("dhan", DhanProvider(self._config))
        self.crypto = _Facet(self, self._config.default_crypto_provider)
        self.equity = _Facet(self, self._config.default_equity_provider)
        self.derivatives = _DerivativesFacet(self, self._config.default_derivatives_provider)
        self.account = AccountFacet(self)
        self.trade = TradeFacet(self)
        self.portfolio = PortfolioFacet(self)

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

    def get_option_ohlcv(
        self,
        contract: str | OptionContract,
        interval: Interval | int = Interval.M1,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        source: str,
        exchange: str | None = None,
        instrument_id: str | None = None,
    ) -> list[OHLCV]:
        prov = self._get_provider(source)
        if not hasattr(prov, "get_option_ohlcv"):
            raise UnsupportedCapabilityError(source, "get_option_ohlcv")
        start_dt, end_dt = default_time_range(start, end)
        return prov.get_option_ohlcv(
            contract,
            interval,
            start_dt,
            end_dt,
            exchange=exchange,
            instrument_id=instrument_id,
        )

    def list_expiries(
        self,
        underlying: str,
        *,
        source: str,
        exchange: str,
        segment: str | None = None,
    ) -> list[date]:
        prov = self._get_provider(source)
        if not hasattr(prov, "list_expiries"):
            raise UnsupportedCapabilityError(source, "list_expiries")
        return prov.list_expiries(underlying, exchange=exchange, segment=segment)

    def get_option_chain(
        self,
        underlying: str,
        *,
        expiry: date,
        source: str,
        exchange: str,
        segment: str | None = None,
    ) -> list[OptionChainEntry]:
        prov = self._get_provider(source)
        if not hasattr(prov, "get_option_chain"):
            raise UnsupportedCapabilityError(source, "get_option_chain")
        return prov.get_option_chain(
            underlying,
            expiry=expiry,
            exchange=exchange,
            segment=segment,
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
