"""Binance Spot and USDT-M Futures public REST adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.http import HttpClient
from bandl.core.intervals import map_interval
from bandl.core.resolver import resolve_symbol
from bandl.core.time import ensure_utc
from bandl.exceptions import ProviderError, SymbolNotFoundError
from bandl.models.market import OHLCV, SymbolInfo, Ticker
from bandl.models.market.types import AssetType, Interval
from bandl.providers.crypto.common import is_crypto_asset, is_crypto_futures

BINANCE_SPOT_BASE = "https://api.binance.com"
BINANCE_FAPI_BASE = "https://fapi.binance.com"
BINANCE_SPOT_KLINES = f"{BINANCE_SPOT_BASE}/api/v3/klines"
BINANCE_FAPI_KLINES = f"{BINANCE_FAPI_BASE}/fapi/v1/klines"

_INTERVAL_TO_BINANCE: dict[Interval, str] = {
    Interval.M1: "1m",
    Interval.M3: "3m",
    Interval.M5: "5m",
    Interval.M15: "15m",
    Interval.M30: "30m",
    Interval.H1: "1h",
    Interval.H2: "2h",
    Interval.H4: "4h",
    Interval.H6: "6h",
    Interval.H8: "8h",
    Interval.D1: "1d",
    Interval.D3: "3d",
    Interval.W1: "1w",
    Interval.MO1: "1M",
}


def _parse_kline_rows(
    rows: list[list[Any]],
    *,
    canonical: str,
    interval_label: str,
    source: str,
) -> list[OHLCV]:
    out: list[OHLCV] = []
    for row in rows:
        ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
        out.append(
            OHLCV(
                timestamp=ts,
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
                quote_volume=Decimal(str(row[7])) if len(row) > 7 else None,
                trades=int(row[8]) if len(row) > 8 else None,
                symbol=canonical,
                interval=interval_label,
                source=source,
            ),
        )
    return out


class BinanceProvider:
    """Binance spot (api.binance.com) and USDT-M futures (fapi.binance.com)."""

    provider_id = "binance"

    def __init__(self, config: BandlConfig, settings: ProviderSettings | None = None) -> None:
        self._config = config
        self._settings = settings or config.providers.get("binance") or ProviderSettings()
        self._http = HttpClient(config)

    def _to_binance_symbol(self, canonical_crypto: str) -> str:
        return canonical_crypto.upper()

    def _fetch_klines(
        self,
        *,
        klines_url: str,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[list[Any]]:
        start_ms = int(ensure_utc(start).timestamp() * 1000)
        end_ms = int(ensure_utc(end).timestamp() * 1000)
        rows: list[list[Any]] = []
        cursor = start_ms
        while cursor < end_ms:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
            chunk = self._http.get_json(
                klines_url,
                provider=self.provider_id,
                params=params,
            )
            if not isinstance(chunk, list):
                raise ProviderError(self.provider_id, "Unexpected klines payload")
            if not chunk:
                break
            rows.extend(chunk)
            last_open = int(chunk[-1][0])
            next_cursor = last_open + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(chunk) < 1000:
                break
        return rows

    def get_ohlcv(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime,
        end: datetime,
        *,
        asset_type: AssetType | None = AssetType.CRYPTO_SPOT,
    ) -> list[OHLCV]:
        at = asset_type or AssetType.CRYPTO_SPOT
        resolved = resolve_symbol(symbol, asset_type=at)
        if not is_crypto_asset(resolved.asset_type):
            raise SymbolNotFoundError(
                f"Symbol {symbol} resolved to {resolved.asset_type}, not crypto",
            )
        b_interval = map_interval(
            interval,
            _INTERVAL_TO_BINANCE,
            "binance",
            normalize=str.lower,
        )
        sym = self._to_binance_symbol(resolved.canonical)
        interval_label = interval.value if isinstance(interval, Interval) else str(interval)

        if is_crypto_futures(at):
            raw = self._fetch_klines(
                klines_url=BINANCE_FAPI_KLINES,
                symbol=sym,
                interval=b_interval,
                start=start,
                end=end,
            )
        else:
            raw = self._fetch_klines(
                klines_url=BINANCE_SPOT_KLINES,
                symbol=sym,
                interval=b_interval,
                start=start,
                end=end,
            )
        return _parse_kline_rows(
            raw,
            canonical=resolved.canonical,
            interval_label=interval_label,
            source=self.provider_id,
        )

    def list_symbols(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
        asset_type: AssetType | None = None,
    ) -> list[SymbolInfo]:
        if is_crypto_futures(asset_type):
            return self._list_futures_symbols(search=search, limit=limit)
        return self._list_spot_symbols(search=search, limit=limit)

    def _list_spot_symbols(
        self,
        *,
        search: str | None,
        limit: int | None,
    ) -> list[SymbolInfo]:
        data = self._http.get_json(
            f"{BINANCE_SPOT_BASE}/api/v3/exchangeInfo",
            provider=self.provider_id,
        )
        symbols = data.get("symbols") if isinstance(data, dict) else None
        if not isinstance(symbols, list):
            raise ProviderError(self.provider_id, "exchangeInfo parse error")

        out: list[SymbolInfo] = []
        for s in symbols:
            if not isinstance(s, dict):
                continue
            if s.get("status") != "TRADING":
                continue
            if s.get("isSpotTradingAllowed") is False:
                continue
            sym = str(s.get("symbol", ""))
            base = str(s.get("baseAsset", ""))
            quote = str(s.get("quoteAsset", ""))
            canon = f"{base}{quote}".upper()
            if not canon:
                continue
            if search and search.upper() not in canon:
                continue
            out.append(
                SymbolInfo(
                    canonical=canon,
                    base=base.upper(),
                    quote=quote.upper(),
                    asset_type=AssetType.CRYPTO_SPOT,
                    provider_symbol=sym,
                ),
            )
            if limit is not None and len(out) >= limit:
                break
        return out

    def _list_futures_symbols(
        self,
        *,
        search: str | None,
        limit: int | None,
    ) -> list[SymbolInfo]:
        """USDT-M perpetuals via GET /fapi/v1/exchangeInfo."""
        data = self._http.get_json(
            f"{BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo",
            provider=self.provider_id,
        )
        symbols = data.get("symbols") if isinstance(data, dict) else None
        if not isinstance(symbols, list):
            raise ProviderError(self.provider_id, "fapi exchangeInfo parse error")

        out: list[SymbolInfo] = []
        for s in symbols:
            if not isinstance(s, dict):
                continue
            if s.get("status") != "TRADING":
                continue
            if s.get("contractType") != "PERPETUAL":
                continue
            sym = str(s.get("symbol", ""))
            base = str(s.get("baseAsset", ""))
            quote = str(s.get("quoteAsset", ""))
            canon = f"{base}{quote}".upper()
            if not canon:
                continue
            if search and search.upper() not in canon:
                continue
            out.append(
                SymbolInfo(
                    canonical=canon,
                    base=base.upper(),
                    quote=quote.upper(),
                    asset_type=AssetType.CRYPTO_PERP,
                    provider_symbol=sym,
                    display_name=str(s.get("pair", sym)),
                ),
            )
            if limit is not None and len(out) >= limit:
                break
        return out

    def get_futures_24hr_tickers(self) -> list[Ticker]:
        """
        Rolling 24h stats for all USDT-M futures (GET /fapi/v1/ticker/24hr).

        See: https://developers.binance.com/docs/derivatives/usds-margined-futures/
        market-data/rest-api/24hr-Ticker-Price-Change-Statistics
        """
        data = self._http.get_json(
            f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/24hr",
            provider=self.provider_id,
        )
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        if not rows:
            raise ProviderError(self.provider_id, "Unexpected 24hr ticker payload")

        out: list[Ticker] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol", ""))
            if not sym:
                continue
            close_ms = int(row.get("closeTime", 0))
            ts = (
                datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
                if close_ms
                else ensure_utc(datetime.now(timezone.utc))
            )
            out.append(
                Ticker(
                    timestamp=ts,
                    last_price=Decimal(str(row.get("lastPrice", 0))),
                    high_24h=Decimal(str(row["highPrice"]))
                    if row.get("highPrice") is not None
                    else None,
                    low_24h=Decimal(str(row["lowPrice"]))
                    if row.get("lowPrice") is not None
                    else None,
                    volume_24h=Decimal(str(row["volume"]))
                    if row.get("volume") is not None
                    else None,
                    change_24h=Decimal(str(row["priceChangePercent"]))
                    if row.get("priceChangePercent") is not None
                    else None,
                    symbol=sym.upper(),
                    source=self.provider_id,
                ),
            )
        return out
