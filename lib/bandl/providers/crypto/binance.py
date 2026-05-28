"""Binance Spot public REST adapter (historical klines)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.http import HttpClient
from bandl.core.resolver import resolve_symbol
from bandl.exceptions import ProviderError, SymbolNotFoundError
from bandl.models.market import OHLCV, SymbolInfo
from bandl.models.market.types import AssetType, Interval

BINANCE_BASE = "https://api.binance.com"

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


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _interval_arg(interval: Interval | str) -> str:
    if isinstance(interval, Interval):
        return _INTERVAL_TO_BINANCE.get(interval, interval.value)
    s = str(interval).lower()
    if s in {v for v in _INTERVAL_TO_BINANCE.values()}:
        return s
    raise ProviderError("binance", f"Unsupported interval: {interval}")


class BinanceProvider:
    provider_id = "binance"

    def __init__(self, config: BandlConfig, settings: ProviderSettings | None = None) -> None:
        self._config = config
        self._settings = settings or config.providers.get("binance") or ProviderSettings()
        self._http = HttpClient(config)

    def _to_binance_symbol(self, canonical_crypto: str) -> str:
        return canonical_crypto.upper()

    def get_ohlcv(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime,
        end: datetime,
        *,
        asset_type: AssetType | None = AssetType.CRYPTO_SPOT,
    ) -> list[OHLCV]:
        resolved = resolve_symbol(symbol, asset_type=asset_type or AssetType.CRYPTO_SPOT)
        if resolved.asset_type not in (
            AssetType.CRYPTO_SPOT,
            AssetType.CRYPTO_PERP,
            AssetType.CRYPTO_FUTURE,
        ):
            raise SymbolNotFoundError(
                f"Symbol {symbol} resolved to {resolved.asset_type}, not crypto",
            )
        b_interval = _interval_arg(interval)
        sym = self._to_binance_symbol(resolved.canonical)
        start_ms = int(_ensure_utc(start).timestamp() * 1000)
        end_ms = int(_ensure_utc(end).timestamp() * 1000)

        rows: list[list[Any]] = []
        cursor = start_ms
        while cursor < end_ms:
            params = {
                "symbol": sym,
                "interval": b_interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
            chunk = self._http.get_json(
                f"{BINANCE_BASE}/api/v3/klines",
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

        out: list[OHLCV] = []
        interval_label: str = interval.value if isinstance(interval, Interval) else str(interval)
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
                    symbol=resolved.canonical,
                    interval=interval_label,
                    source=self.provider_id,
                )
            )
        return out

    def list_symbols(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[SymbolInfo]:
        data = self._http.get_json(f"{BINANCE_BASE}/api/v3/exchangeInfo", provider=self.provider_id)
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
