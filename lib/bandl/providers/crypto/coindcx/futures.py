"""CoinDCX USDT/INR futures: public market data + authenticated account APIs."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from bandl.core.auth import coindcx_signature
from bandl.core.intervals import map_interval
from bandl.core.resolver import resolve_symbol
from bandl.core.time import ensure_utc, parse_epoch_ms
from bandl.exceptions import AuthenticationError, DataNotAvailableError, ProviderError
from bandl.models.account import AccountFill, PnLProvenance, PnLRecord
from bandl.models.account.base import make_dedup_key
from bandl.models.account.types import (
    OrderSide,
    PnLConfidence,
    PnLGranularity,
    PnLSourceType,
    Segment,
)
from bandl.models.market import OHLCV, SymbolInfo, Ticker
from bandl.models.market.types import AssetType, Interval
from bandl.providers.crypto.coindcx.constants import (
    FUTURES_ACTIVE_INSTRUMENTS,
    FUTURES_CANDLESTICKS,
    FUTURES_CURRENT_PRICES_RT,
    FUTURES_ORDERS,
    FUTURES_POSITIONS,
    FUTURES_TRADES,
    FUTURES_TRANSACTIONS,
    INTERVAL_FUTURES_CANDLES,
    MAX_FUTURES_PAGE,
    canonical_to_coindcx_pair,
    pair_to_canonical,
)

if TYPE_CHECKING:
    from bandl.providers.crypto.coindcx.provider import CoinDCXProvider


def _ts_ms() -> int:
    return int(time.time() * 1000)


class CoinDCXFuturesMixin:
    """Futures market data and account history for CoinDCXProvider."""

    def list_futures_market_symbols(
        self: CoinDCXProvider,
        *,
        search: str | None = None,
        limit: int | None = None,
        margin_currencies: list[str] | None = None,
    ) -> list[SymbolInfo]:
        margins = margin_currencies or ["USDT"]
        seen: set[str] = set()
        out: list[SymbolInfo] = []
        for margin in margins:
            data = self._http.get_json(
                FUTURES_ACTIVE_INSTRUMENTS,
                provider=self.provider_id,
                params={"margin_currency_short_name[]": margin},
            )
            if not isinstance(data, list):
                raise ProviderError(self.provider_id, "active_instruments payload error")
            for pair in data:
                if not isinstance(pair, str):
                    continue
                p = pair.upper()
                if p in seen:
                    continue
                seen.add(p)
                canon = pair_to_canonical(p)
                if search and search.upper() not in canon:
                    continue
                if "_" in p.removeprefix("B-"):
                    b, q = p.removeprefix("B-").split("_", 1)
                else:
                    b, q = p, ""
                out.append(
                    SymbolInfo(
                        canonical=canon,
                        base=b,
                        quote=q or None,
                        asset_type=AssetType.CRYPTO_PERP,
                        provider_symbol=p,
                    ),
                )
                if limit is not None and len(out) >= limit:
                    return out
        return out

    def get_futures_market_ohlcv(
        self: CoinDCXProvider,
        symbol: str,
        interval: Interval | str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCV]:
        resolved = resolve_symbol(symbol, asset_type=AssetType.CRYPTO_PERP)
        if not resolved.quote:
            raise ProviderError(self.provider_id, f"Cannot map {symbol} to CoinDCX futures pair")
        pair = canonical_to_coindcx_pair(resolved.base, resolved.quote)
        resolution = map_interval(interval, INTERVAL_FUTURES_CANDLES, "coindcx")
        start_sec = int(ensure_utc(start).timestamp())
        end_sec = int(ensure_utc(end).timestamp())
        payload = self._http.get_json(
            FUTURES_CANDLESTICKS,
            provider=self.provider_id,
            params={
                "pair": pair,
                "from": start_sec,
                "to": end_sec,
                "resolution": resolution,
                "pcode": "f",
            },
        )
        if not isinstance(payload, dict):
            raise ProviderError(self.provider_id, "Unexpected futures candlesticks payload")
        if payload.get("s") == "no_data":
            raise DataNotAvailableError(
                f"CoinDCX futures returned no_data for {pair} ({resolution}) "
                f"between {start.date()} and {end.date()}",
            )
        if payload.get("s") != "ok":
            raise ProviderError(
                self.provider_id,
                f"Futures candlesticks error: {payload.get('s', payload)}",
            )
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError(self.provider_id, "Futures candlesticks missing data array")

        interval_label = interval.value if isinstance(interval, Interval) else str(interval)
        out: list[OHLCV] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            ts = parse_epoch_ms(item["time"])
            if ts < ensure_utc(start) or ts >= ensure_utc(end):
                continue
            out.append(
                OHLCV(
                    timestamp=ts,
                    open=Decimal(str(item["open"])),
                    high=Decimal(str(item["high"])),
                    low=Decimal(str(item["low"])),
                    close=Decimal(str(item["close"])),
                    volume=Decimal(str(item["volume"])),
                    symbol=resolved.canonical,
                    interval=interval_label,
                    source=self.provider_id,
                ),
            )
        out.sort(key=lambda b: b.timestamp)
        return out

    def get_futures_24hr_tickers(
        self: CoinDCXProvider,
        *,
        margin_currencies: list[str] | None = None,
    ) -> list[Ticker]:
        """
        Rolling 24h futures stats (public ``market_data/v3/current_prices/futures/rt``).

        Each instrument includes ``pc`` (24h % change), ``ls`` (last), ``h``/``l``, ``v``.
        Only **active** instruments from ``active_instruments`` are included (matches the app).
        """
        margins = margin_currencies or ["USDT"]
        active_pairs = {
            s.provider_symbol.upper()
            for s in self.list_futures_market_symbols(margin_currencies=margins)
            if s.provider_symbol
        }
        data = self._http.get_json(
            FUTURES_CURRENT_PRICES_RT,
            provider=self.provider_id,
        )
        if not isinstance(data, dict):
            raise ProviderError(self.provider_id, "Unexpected futures current_prices payload")
        prices = data.get("prices")
        if not isinstance(prices, dict):
            raise ProviderError(self.provider_id, "futures current_prices missing prices map")
        ts_raw = data.get("ts")
        if ts_raw is not None:
            ts = parse_epoch_ms(ts_raw)
        else:
            ts = ensure_utc(datetime.now(timezone.utc))

        out: list[Ticker] = []
        for pair, row in prices.items():
            if not isinstance(row, dict):
                continue
            if pair.upper() not in active_pairs:
                continue
            sym = pair_to_canonical(str(pair))
            pc = row.get("pc")
            out.append(
                Ticker(
                    timestamp=ts,
                    last_price=Decimal(str(row.get("ls", row.get("mp", 0)))),
                    high_24h=Decimal(str(row["h"])) if row.get("h") is not None else None,
                    low_24h=Decimal(str(row["l"])) if row.get("l") is not None else None,
                    volume_24h=Decimal(str(row["v"])) if row.get("v") is not None else None,
                    change_24h=Decimal(str(pc)) if pc is not None else None,
                    symbol=sym,
                    source=self.provider_id,
                ),
            )
        return out

    def _futures_headers(self: CoinDCXProvider, body: dict[str, Any]) -> dict[str, str]:
        key = self._settings.api_key
        secret = self._settings.api_secret
        if not key or not secret:
            raise AuthenticationError(
                self.provider_id,
                "CoinDCX futures APIs require api_key and api_secret",
            )
        return {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": key,
            "X-AUTH-SIGNATURE": coindcx_signature(body, secret),
        }

    def _futures_post(self: CoinDCXProvider, url: str, body: dict[str, Any]) -> Any:
        payload = self._http.post_json(
            url,
            provider=self.provider_id,
            body=body,
            headers=self._futures_headers(body),
        )
        if isinstance(payload, dict):
            if payload.get("status") == "error":
                raise ProviderError(
                    self.provider_id,
                    str(payload.get("message", payload)),
                )
            if "data" in payload:
                return payload["data"]
        return payload

    def _futures_margin_currencies(self: CoinDCXProvider) -> list[str]:
        return ["USDT", "INR"]

    def _discover_futures_pairs_from_orders(
        self: CoinDCXProvider,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> set[str]:
        """Pairs with filled futures orders (paginated), optionally filtered by time."""
        pairs: set[str] = set()
        for side in ("buy", "sell"):
            page = 1
            for _ in range(50):
                body: dict[str, Any] = {
                    "timestamp": _ts_ms(),
                    "status": "filled,partially_filled",
                    "side": side,
                    "page": str(page),
                    "size": str(MAX_FUTURES_PAGE),
                    "margin_currency_short_name": self._futures_margin_currencies(),
                }
                chunk = self._futures_post(FUTURES_ORDERS, body)
                if not isinstance(chunk, list) or not chunk:
                    break
                for row in chunk:
                    if not isinstance(row, dict) or not row.get("pair"):
                        continue
                    if start is not None and end is not None:
                        created = parse_epoch_ms(row.get("created_at", 0))
                        if created < start or created >= end:
                            continue
                    pairs.add(str(row["pair"]))
                if len(chunk) < MAX_FUTURES_PAGE:
                    break
                page += 1
        return pairs

    def _pairs_from_transactions(
        self: CoinDCXProvider,
        start: datetime,
        end: datetime,
    ) -> set[str]:
        pairs: set[str] = set()
        page = 1
        while page <= 30:
            body: dict[str, Any] = {
                "timestamp": _ts_ms(),
                "stage": "all",
                "page": str(page),
                "size": str(MAX_FUTURES_PAGE),
                "margin_currency_short_name": self._futures_margin_currencies(),
            }
            chunk = self._futures_post(FUTURES_TRANSACTIONS, body)
            if not isinstance(chunk, list) or not chunk:
                break
            for row in chunk:
                if not isinstance(row, dict) or not row.get("pair"):
                    continue
                created = parse_epoch_ms(row.get("created_at", 0))
                if start <= created < end:
                    pairs.add(str(row["pair"]))
            if len(chunk) < MAX_FUTURES_PAGE:
                break
            page += 1
        return pairs

    def _fetch_futures_trades_for_pair(
        self: CoinDCXProvider,
        pair: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while page <= 100:
            body: dict[str, Any] = {
                "timestamp": _ts_ms(),
                "pair": pair,
                "from_date": from_date,
                "to_date": to_date,
                "page": str(page),
                "size": str(MAX_FUTURES_PAGE),
                "margin_currency_short_name": self._futures_margin_currencies(),
            }
            try:
                chunk = self._futures_post(FUTURES_TRADES, body)
            except ProviderError:
                break
            if not isinstance(chunk, list) or not chunk:
                break
            rows.extend([r for r in chunk if isinstance(r, dict)])
            if len(chunk) < MAX_FUTURES_PAGE:
                break
            page += 1
        return rows

    def get_futures_fills(
        self: CoinDCXProvider,
        start: datetime,
        end: datetime,
        *,
        symbol: str | None = None,
        pairs: set[str] | None = None,
    ) -> list[AccountFill]:
        from_date = start.astimezone(timezone.utc).strftime("%Y-%m-%d")
        to_date = (end.astimezone(timezone.utc)).strftime("%Y-%m-%d")
        if pairs is None:
            if symbol:
                p = symbol.upper().replace("/", "_")
                if not p.startswith("B-"):
                    p = f"B-{p[:-4]}_{p[-4:]}" if len(p) > 4 else f"B-{p}"
                pairs = {p}
            else:
                pairs = self._discover_futures_pairs_from_orders(start, end)
                if not pairs:
                    pairs = self._pairs_from_transactions(start, end)
        out: list[AccountFill] = []
        for pair in sorted(pairs):
            for row in self._fetch_futures_trades_for_pair(pair, from_date, to_date):
                fill = self._map_futures_fill(row)
                if fill.executed_at < start or fill.executed_at >= end:
                    continue
                if symbol and symbol.upper() not in fill.symbol.upper():
                    continue
                out.append(fill)
        return out

    def _map_futures_fill(self: CoinDCXProvider, row: dict[str, Any]) -> AccountFill:
        ts = row.get("timestamp", _ts_ms())
        executed = parse_epoch_ms(ts)
        side = str(row.get("side", "buy")).lower()
        qty = Decimal(str(row["quantity"]))
        price = Decimal(str(row["price"]))
        pair = str(row.get("pair", ""))
        sym = pair_to_canonical(pair)
        fee = Decimal(str(row["fee_amount"])) if row.get("fee_amount") is not None else None
        margin = str(row.get("margin_currency_short_name", "USDT"))
        order_id = str(row["order_id"]) if row.get("order_id") else None
        fid = f"{order_id}:{executed.timestamp()}" if order_id else str(ts)
        return AccountFill(
            fill_id=fid,
            order_id=order_id,
            side=side if side in ("buy", "sell") else OrderSide.BUY,
            quantity=qty,
            price=price,
            quote_quantity=qty * price,
            fee=fee,
            fee_currency=margin,
            executed_at=executed,
            is_maker=bool(row.get("is_maker")) if row.get("is_maker") is not None else None,
            source=self.provider_id,
            segment=Segment.CRYPTO_FNO,
            symbol=sym,
            symbol_native=pair,
            currency=margin,
            provider_native=row,
            dedup_key=make_dedup_key(self.provider_id, "fill:fno", fid),
        )

    def get_futures_pnl_from_transactions(
        self: CoinDCXProvider,
        start: datetime,
        end: datetime,
        *,
        granularity: str = PnLGranularity.PORTFOLIO,
    ) -> list[PnLRecord]:
        """Broker-reported PnL from futures position transactions (``amount`` field)."""
        total = Decimal("0")
        fees = Decimal("0")
        by_pair: dict[str, Decimal] = {}
        page = 1
        while page <= 200:
            body: dict[str, Any] = {
                "timestamp": _ts_ms(),
                "stage": "all",
                "page": str(page),
                "size": str(MAX_FUTURES_PAGE),
                "margin_currency_short_name": self._futures_margin_currencies(),
            }
            chunk = self._futures_post(FUTURES_TRANSACTIONS, body)
            if not isinstance(chunk, list) or not chunk:
                break
            for row in chunk:
                if not isinstance(row, dict):
                    continue
                created = parse_epoch_ms(row.get("created_at", 0))
                if created < start or created >= end:
                    continue
                amt = Decimal(str(row.get("amount", 0)))
                total += amt
                if row.get("fee_amount") is not None:
                    fees += Decimal(str(row["fee_amount"]))
                pair = str(row.get("pair", "*"))
                by_pair[pair] = by_pair.get(pair, Decimal("0")) + amt
            if len(chunk) < MAX_FUTURES_PAGE:
                break
            page += 1

        now = datetime.now(timezone.utc)
        warns = [
            "Futures PnL from POST /derivatives/futures/positions/transactions (amount field)",
        ]
        if granularity == PnLGranularity.SYMBOL:
            return [
                PnLRecord(
                    pnl_id=f"broker:fno:{pair}",
                    granularity=PnLGranularity.SYMBOL,
                    realized_pnl=pnl,
                    total_pnl=pnl,
                    currency="USDT",
                    symbol=pair_to_canonical(pair),
                    as_of=now,
                    provenance=PnLProvenance(
                        source_type=PnLSourceType.BROKER,
                        includes_fees=True,
                        confidence=PnLConfidence.HIGH,
                        warnings=warns,
                    ),
                    source=self.provider_id,
                    segment=Segment.CRYPTO_FNO,
                    symbol_native=pair,
                    provider_native={"pair": pair},
                    dedup_key=make_dedup_key(self.provider_id, "pnl:fno", pair),
                )
                for pair, pnl in by_pair.items()
            ]

        return [
            PnLRecord(
                pnl_id="broker:fno:portfolio",
                granularity=PnLGranularity.PORTFOLIO,
                realized_pnl=total,
                total_pnl=total,
                currency="USDT",
                as_of=now,
                provenance=PnLProvenance(
                    source_type=PnLSourceType.BROKER,
                    includes_fees=True,
                    confidence=PnLConfidence.HIGH,
                    warnings=warns + [f"Total fees in window: {fees}"],
                ),
                source=self.provider_id,
                segment=Segment.CRYPTO_FNO,
                symbol="*",
                symbol_native="*",
                provider_native={"transaction_count": len(by_pair)},
                dedup_key=make_dedup_key(self.provider_id, "pnl:fno", "portfolio"),
            ),
        ]

    def get_futures_open_positions_pnl(
        self: CoinDCXProvider,
    ) -> list[PnLRecord]:
        """Unrealized PnL snapshot from open futures positions (if API exposes it)."""
        body: dict[str, Any] = {
            "timestamp": _ts_ms(),
            "page": "1",
            "size": "100",
            "margin_currency_short_name": ["USDT"],
        }
        chunk = self._futures_post(FUTURES_POSITIONS, body)
        if not isinstance(chunk, list):
            return []
        now = datetime.now(timezone.utc)
        out: list[PnLRecord] = []
        for row in chunk:
            if not isinstance(row, dict):
                continue
            active = Decimal(str(row.get("active_pos", 0)))
            if active == 0:
                continue
            pair = str(row.get("pair", ""))
            sym = pair_to_canonical(pair)
            out.append(
                PnLRecord(
                    pnl_id=f"broker:fno:pos:{pair}",
                    granularity=PnLGranularity.SYMBOL,
                    unrealized_pnl=None,
                    total_pnl=None,
                    currency=str(row.get("margin_currency_short_name", "USDT")),
                    symbol=sym,
                    as_of=now,
                    provenance=PnLProvenance(
                        source_type=PnLSourceType.BROKER,
                        confidence=PnLConfidence.MEDIUM,
                        warnings=["Open position snapshot; closed PnL use transactions"],
                    ),
                    source=self.provider_id,
                    segment=Segment.CRYPTO_FNO,
                    symbol_native=pair,
                    provider_native=row,
                    dedup_key=make_dedup_key(self.provider_id, "pnl:fno:pos", pair),
                ),
            )
        return out
