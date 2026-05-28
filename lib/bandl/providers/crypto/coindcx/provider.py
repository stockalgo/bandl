"""CoinDCX public REST adapter (spot candles)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.http import HttpClient
from bandl.core.intervals import map_interval
from bandl.core.resolver import resolve_symbol
from bandl.core.time import ensure_utc
from bandl.exceptions import DataNotAvailableError, ProviderError, SymbolNotFoundError
from bandl.models.market import OHLCV, SymbolInfo
from bandl.models.market.types import AssetType, Interval
from bandl.providers.crypto.coindcx.account import CoinDCXAccountMixin
from bandl.providers.crypto.coindcx.constants import (
    COINDCX_API,
    COINDCX_PUBLIC,
    canonical_to_coindcx_pair,
    pair_to_canonical,
)
from bandl.providers.crypto.coindcx.futures import CoinDCXFuturesMixin
from bandl.providers.crypto.common import is_crypto_asset, is_crypto_futures

_INTERVAL_COINDCX: dict[Interval, str] = {
    Interval.M1: "1m",
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


def _candle_time_ms(candle: dict[str, Any], *, provider_id: str) -> int:
    try:
        return int(candle["time"])
    except (KeyError, TypeError, ValueError) as err:
        raise ProviderError(
            provider_id,
            "Invalid candle payload: missing or non-numeric 'time'",
        ) from err


class CoinDCXProvider(CoinDCXAccountMixin, CoinDCXFuturesMixin):
    provider_id = "coindcx"

    def __init__(self, config: BandlConfig, settings: ProviderSettings | None = None) -> None:
        self._config = config
        self._settings = settings or config.providers.get("coindcx") or ProviderSettings()
        self._http = HttpClient(config)

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
        if is_crypto_futures(at):
            return self.get_futures_market_ohlcv(symbol, interval, start, end)
        resolved = resolve_symbol(symbol, asset_type=at)
        if not is_crypto_asset(resolved.asset_type):
            raise SymbolNotFoundError(f"Symbol {symbol} is not a crypto pair for CoinDCX")
        if not resolved.quote:
            raise SymbolNotFoundError(f"Cannot map {resolved.canonical} to CoinDCX pair")
        pair = canonical_to_coindcx_pair(resolved.base, resolved.quote)
        iv = map_interval(interval, _INTERVAL_COINDCX, "coindcx")
        start_ms = int(ensure_utc(start).timestamp() * 1000)
        end_ms = int(ensure_utc(end).timestamp() * 1000)

        # CoinDCX returns [] when both startTime and endTime are set; paginate with endTime only.
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
        all_times_ms: list[int] = []
        cursor_end = end_ms
        safety = 0
        while cursor_end >= start_ms and safety < 50:
            safety += 1
            params: dict[str, Any] = {
                "pair": pair,
                "interval": iv,
                "endTime": cursor_end,
                "limit": 1000,
            }
            chunk = self._http.get_json(
                f"{COINDCX_PUBLIC}/market_data/candles",
                provider=self.provider_id,
                params=params,
            )
            if not isinstance(chunk, list):
                raise ProviderError(self.provider_id, "Unexpected candles payload")
            if not chunk:
                break
            normalized = [c for c in chunk if isinstance(c, dict)]
            if not normalized:
                break
            times: list[int] = []
            for c in normalized:
                t = _candle_time_ms(c, provider_id=self.provider_id)
                times.append(t)
                all_times_ms.append(t)
                if start_ms <= t <= end_ms and t not in seen:
                    seen.add(t)
                    rows.append(c)
            oldest = min(times)
            if oldest >= cursor_end:
                break
            cursor_end = oldest - 1
            if len(normalized) < 1000:
                break

        if not rows and all_times_ms:
            latest_ms = max(all_times_ms)
            earliest_ms = min(all_times_ms)
            latest_dt = datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc)
            earliest_dt = datetime.fromtimestamp(earliest_ms / 1000, tz=timezone.utc)
            req_start = ensure_utc(start)
            req_end = ensure_utc(end)
            raise DataNotAvailableError(
                f"CoinDCX returned candles for {pair} but none fall in the requested window "
                f"({req_start.date()} to {req_end.date()}). "
                f"Available span from this pagination: {earliest_dt.date()} to {latest_dt.date()}. "
                f"The public candles feed may lag behind real time; try an earlier end date "
                f"(e.g. end={latest_dt.date().isoformat()}) or another provider where available.",
            )

        interval_label: str = interval.value if isinstance(interval, Interval) else str(interval)
        out: list[OHLCV] = []
        for item in sorted(rows, key=lambda x: _candle_time_ms(x, provider_id=self.provider_id)):
            t = _candle_time_ms(item, provider_id=self.provider_id)
            ts = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
            out.append(
                OHLCV(
                    timestamp=ts,
                    open=Decimal(str(item["open"])),
                    high=Decimal(str(item["high"])),
                    low=Decimal(str(item["low"])),
                    close=Decimal(str(item["close"])),
                    volume=Decimal(str(item["volume"])),
                    quote_volume=None,
                    trades=None,
                    symbol=resolved.canonical,
                    interval=interval_label,
                    source=self.provider_id,
                ),
            )
        return out

    def list_symbols(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
        asset_type: AssetType | None = None,
        margin_currencies: list[str] | None = None,
    ) -> list[SymbolInfo]:
        if is_crypto_futures(asset_type):
            return self.list_futures_market_symbols(
                search=search,
                limit=limit,
                margin_currencies=margin_currencies,
            )
        data = self._http.get_json(
            f"{COINDCX_API}/exchange/v1/markets",
            provider=self.provider_id,
        )
        if not isinstance(data, list):
            raise ProviderError(self.provider_id, "markets payload error")
        out: list[SymbolInfo] = []
        for m in data:
            if not isinstance(m, str):
                continue
            if not m.upper().startswith("B-"):
                continue
            canon = pair_to_canonical(m)
            if search and search.upper() not in canon:
                continue
            p = m.upper().removeprefix("B-")
            if "_" in p:
                b, q = p.split("_", 1)
            else:
                b, q = p, ""
            out.append(
                SymbolInfo(
                    canonical=canon,
                    base=b,
                    quote=q or None,
                    asset_type=AssetType.CRYPTO_SPOT,
                    provider_symbol=m,
                ),
            )
            if limit is not None and len(out) >= limit:
                break
        return out
