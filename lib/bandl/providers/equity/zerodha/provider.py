"""Zerodha Kite Connect historical adapter (requires access token)."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.http import HttpClient
from bandl.core.intervals import map_interval
from bandl.core.resolver import ResolvedSymbol, resolve_symbol
from bandl.core.time import ensure_utc
from bandl.exceptions import AuthenticationError, ProviderError, SymbolNotFoundError
from bandl.models.market import OHLCV, SymbolInfo
from bandl.models.market.types import AssetType, Interval
from bandl.providers.equity.zerodha.account import ZerodhaAccountMixin
from bandl.providers.equity.zerodha.common import KITE_API
from bandl.providers.equity.zerodha.common import parse_kite_timestamp as _parse_kite_timestamp

# Kite public instruments CSV paths; reject odd tokens to avoid path injection.
KITE_EXCHANGES: frozenset[str] = frozenset(
    {"NSE", "BSE", "MCX", "NFO", "CDS", "BFO", "BCD"},
)

KITE_INTERVAL: dict[Interval, str] = {
    Interval.M1: "minute",
    Interval.M3: "3minute",
    Interval.M5: "5minute",
    Interval.M15: "15minute",
    Interval.M30: "30minute",
    Interval.H1: "60minute",
    Interval.H2: "60minute",
    Interval.H4: "60minute",
    Interval.D1: "day",
    Interval.W1: "day",
    Interval.MO1: "day",
}

INDEX_TRADINGSYMBOL: dict[str, str] = {
    "NIFTY50": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
}


def _normalize_kite_exchange(exchange: str) -> str:
    ex = exchange.upper().strip()
    if ex not in KITE_EXCHANGES:
        allowed = ", ".join(sorted(KITE_EXCHANGES))
        raise ProviderError(
            "zerodha",
            f"Unsupported exchange {exchange!r}; expected one of: {allowed}",
        )
    return ex


class ZerodhaProvider(ZerodhaAccountMixin):
    provider_id = "zerodha"

    def __init__(self, config: BandlConfig, settings: ProviderSettings | None = None) -> None:
        self._config = config
        self._settings = settings or config.providers.get("zerodha") or ProviderSettings()
        self._http = HttpClient(config)
        self._instrument_cache: dict[str, list[dict[str, str]]] = {}

    def _auth_headers(self) -> dict[str, str]:
        key = self._settings.api_key
        tok = self._settings.access_token
        if not key or not tok:
            raise AuthenticationError(
                self.provider_id,
                "Zerodha requires api_key and access_token in BandlConfig.providers['zerodha']",
            )
        return {
            "Authorization": f"token {key}:{tok}",
            "X-Kite-Version": "3",
        }

    def load_instruments(self, exchange: str = "NSE", *, force: bool = False) -> None:
        ex = _normalize_kite_exchange(exchange)
        if not force and ex in self._instrument_cache:
            return
        text = self._http.get_text(
            f"{KITE_API}/instruments/{ex}",
            provider=self.provider_id,
        )
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(r) for r in reader]
        self._instrument_cache[ex] = rows

    def _pick_tradingsymbol(
        self,
        resolved: ResolvedSymbol,
        *,
        tradingsymbol: str | None,
    ) -> str:
        if tradingsymbol:
            return tradingsymbol
        if resolved.canonical in INDEX_TRADINGSYMBOL:
            return INDEX_TRADINGSYMBOL[resolved.canonical]
        return resolved.canonical

    def _lookup_token(
        self,
        exchange: str,
        tradingsymbol: str,
        asset_type: AssetType,
    ) -> int:
        self.load_instruments(exchange)
        rows = self._instrument_cache[exchange]
        want_types: set[str] = {"INDEX"} if asset_type == AssetType.INDEX else {"EQ"}
        matches = [
            r
            for r in rows
            if r.get("tradingsymbol") == tradingsymbol
            and r.get("exchange") == exchange
            and r.get("instrument_type") in want_types
        ]
        # Some NSE benchmarks are tagged ``EQ`` in the instruments CSV; allow that for indices.
        if not matches and asset_type == AssetType.INDEX:
            want_types = {"INDEX", "EQ"}
            matches = [
                r
                for r in rows
                if r.get("tradingsymbol") == tradingsymbol
                and r.get("exchange") == exchange
                and r.get("instrument_type") in want_types
            ]
        if not matches:
            raise SymbolNotFoundError(
                f"No {exchange} instrument for {tradingsymbol} (type filter {want_types})",
            )
        try:
            return int(matches[0]["instrument_token"])
        except (KeyError, TypeError, ValueError) as err:
            raise ProviderError(
                self.provider_id,
                f"Invalid instrument_token in instruments dump for {tradingsymbol}",
            ) from err

    def get_ohlcv(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime,
        end: datetime,
        *,
        exchange: str | None = None,
        tradingsymbol: str | None = None,
        instrument_token: int | None = None,
        asset_type: AssetType | None = None,
    ) -> list[OHLCV]:
        rs = resolve_symbol(symbol, asset_type=asset_type)
        ex = _normalize_kite_exchange(exchange or "NSE")
        ts = self._pick_tradingsymbol(rs, tradingsymbol=tradingsymbol)
        token = instrument_token
        if token is None:
            at = rs.asset_type if asset_type is None else asset_type
            token = self._lookup_token(ex, ts, at)
        kite_iv = map_interval(interval, KITE_INTERVAL, "zerodha")
        p_from = ensure_utc(start).strftime("%Y-%m-%d %H:%M:%S")
        p_to = ensure_utc(end).strftime("%Y-%m-%d %H:%M:%S")
        url = f"{KITE_API}/instruments/historical/{token}/{kite_iv}"
        payload = self._http.get_json(
            url,
            provider=self.provider_id,
            params={"from": p_from, "to": p_to},
            headers=self._auth_headers(),
        )
        if not isinstance(payload, dict):
            raise ProviderError(self.provider_id, "Unexpected historical payload")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError(
                self.provider_id,
                f"Historical error: {payload.get('message', payload)}",
            )
        candles = data.get("candles")
        if not isinstance(candles, list):
            return []
        interval_label = interval.value if isinstance(interval, Interval) else str(interval)
        out: list[OHLCV] = []
        for row in candles:
            if not isinstance(row, list) or len(row) < 6:
                continue
            ts_parsed = _parse_kite_timestamp(str(row[0]))
            out.append(
                OHLCV(
                    timestamp=ts_parsed,
                    open=Decimal(str(row[1])),
                    high=Decimal(str(row[2])),
                    low=Decimal(str(row[3])),
                    close=Decimal(str(row[4])),
                    volume=Decimal(str(row[5])),
                    symbol=rs.canonical,
                    interval=interval_label,
                    source=self.provider_id,
                ),
            )
        return out

    def list_symbols(
        self,
        *,
        exchange: str = "NSE",
        search: str | None = None,
        limit: int | None = None,
        instrument_types: tuple[str, ...] = ("EQ", "INDEX"),
    ) -> list[SymbolInfo]:
        ex = _normalize_kite_exchange(exchange)
        self.load_instruments(ex)
        out: list[SymbolInfo] = []
        for r in self._instrument_cache[ex]:
            it = r.get("instrument_type", "")
            if it not in instrument_types:
                continue
            ts = r.get("tradingsymbol", "")
            if not ts:
                continue
            canon_key = ts.replace(" ", "").upper() if it == "INDEX" else ts.upper()
            if it == "INDEX":
                for canon, official in INDEX_TRADINGSYMBOL.items():
                    if official == ts:
                        canon_key = canon
                        break
            if search and search.upper() not in canon_key:
                continue
            out.append(
                SymbolInfo(
                    canonical=canon_key,
                    base=canon_key,
                    quote=None,
                    asset_type=AssetType.INDEX if it == "INDEX" else AssetType.EQUITY,
                    provider_symbol=ts,
                ),
            )
            if limit is not None and len(out) >= limit:
                break
        return out
