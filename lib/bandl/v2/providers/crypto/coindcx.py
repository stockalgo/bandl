"""CoinDCX public REST adapter (spot candles)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bandl.v2.config import BandlConfig, ProviderSettings
from bandl.v2.core.http import HttpClient
from bandl.v2.core.resolver import ResolvedSymbol, resolve_symbol
from bandl.v2.exceptions import ProviderError, SymbolNotFoundError
from bandl.v2.models import OHLCV, SymbolInfo
from bandl.v2.models.types import AssetType, Interval

COINDCX_PUBLIC = "https://public.coindcx.com"
COINDCX_API = "https://api.coindcx.com"

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


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coindcx_interval(interval: Interval | str) -> str:
    if isinstance(interval, Interval):
        if interval not in _INTERVAL_COINDCX:
            raise ProviderError("coindcx", f"Unsupported interval: {interval}")
        return _INTERVAL_COINDCX[interval]
    s = str(interval)
    if s in set(_INTERVAL_COINDCX.values()):
        return s
    raise ProviderError("coindcx", f"Unsupported interval: {interval}")


def _canonical_to_pair(resolved: ResolvedSymbol) -> str:
    """BTCUSDT components -> B-BTC_USDT (spot convention)."""
    if not resolved.quote:
        raise SymbolNotFoundError(f"Cannot map {resolved.canonical} to CoinDCX pair")
    return f"B-{resolved.base}_{resolved.quote}"


def _pair_to_canonical(pair: str) -> str:
    p = pair.strip().upper()
    if p.startswith("B-"):
        p = p[2:]
    if "_" not in p:
        return p
    base, quote = p.split("_", 1)
    return f"{base}{quote}"


def _candle_time_ms(candle: dict[str, Any], *, provider_id: str) -> int:
    try:
        return int(candle["time"])
    except (KeyError, TypeError, ValueError) as err:
        raise ProviderError(
            provider_id,
            "Invalid candle payload: missing or non-numeric 'time'",
        ) from err


class CoinDCXProvider:
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
        resolved = resolve_symbol(symbol, asset_type=asset_type or AssetType.CRYPTO_SPOT)
        if resolved.asset_type not in (
            AssetType.CRYPTO_SPOT,
            AssetType.CRYPTO_PERP,
            AssetType.CRYPTO_FUTURE,
        ):
            raise SymbolNotFoundError(f"Symbol {symbol} is not a crypto pair for CoinDCX")
        pair = _canonical_to_pair(resolved)
        iv = _coindcx_interval(interval)
        start_ms = int(_ensure_utc(start).timestamp() * 1000)
        end_ms = int(_ensure_utc(end).timestamp() * 1000)

        # CoinDCX returns [] when both startTime and endTime are set; paginate with endTime only.
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
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
                if start_ms <= t <= end_ms and t not in seen:
                    seen.add(t)
                    rows.append(c)
            oldest = min(times)
            if oldest >= cursor_end:
                break
            cursor_end = oldest - 1
            if len(normalized) < 1000:
                break

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
    ) -> list[SymbolInfo]:
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
            canon = _pair_to_canonical(m)
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
