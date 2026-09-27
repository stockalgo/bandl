"""ICICI Direct Breeze API provider adapter.

Supports historical OHLCV candles (NSE, BSE, NFO, MCX), derivatives (options/futures) OHLCV,
expiries, demat holdings, portfolio balances/margins, and live trading.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.contracts import parse_option_symbol
from bandl.core.http import HttpClient
from bandl.core.intervals import map_interval
from bandl.core.resolver import resolve_symbol
from bandl.core.time import ensure_utc
from bandl.exceptions import AuthenticationError, ProviderError
from bandl.models.market import (
    OHLCV,
    OptionContract,
    OptionType,
    SymbolInfo,
)
from bandl.models.market.types import AssetType, Interval
from bandl.providers.breeze.common import (
    BREEZE_API_V1,
    BREEZE_API_V2,
    INTERVAL_TO_BREEZE,
    MCX_STOCK_CODES,
    SUPPORTED_BREEZE_INTERVALS,
)
from bandl.providers.breeze.portfolio import BreezePortfolioMixin
from bandl.providers.breeze.trading import BreezeTradingMixin


def _parse_breeze_timestamp(raw: str) -> datetime:
    """Parse Breeze candle datetime string into UTC datetime.

    Format from historical charts: 'YYYY-MM-DD HH:MM:SS' or ISO.
    Breeze timestamps represent Indian Standard Time (UTC+05:30).
    """
    s = raw.strip()
    # Try ISO
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return ensure_utc(dt)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(s, fmt)
            # Breeze returns IST timestamps without timezone tag
            # Offset IST (UTC+5:30) to UTC
            ts = naive.timestamp() - (5 * 3600 + 30 * 60)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized Breeze datetime string: {raw!r}")


def _to_decimal(val: Any) -> Decimal:
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise ValueError(f"Cannot parse decimal from {val!r}") from err


class BreezeProvider(BreezePortfolioMixin, BreezeTradingMixin):
    provider_id = "breeze"

    def __init__(self, config: BandlConfig, settings: ProviderSettings | None = None) -> None:
        self._config = config
        self._settings = settings or config.providers.get("breeze") or ProviderSettings()
        self._http = HttpClient(config)

    @property
    def bound_account_id(self) -> str | None:
        return self._settings.account_id

    def _resolve_credentials(self) -> tuple[str, str, str, str]:
        """Return (api_key, secret_key, session_token, user_id)."""
        key = self._settings.api_key
        secret = self._settings.api_secret
        token = self._settings.access_token

        # Check account_id as user_id fallback
        user_id = self._settings.account_id or ""

        if not key or not token:
            raise AuthenticationError(
                self.provider_id,
                "Breeze requires api_key and access_token in BandlConfig.providers['breeze']",
            )
        return key, secret or "", token, user_id

    def _get_base64_session_token(self) -> str:
        key, secret, token, user_id = self._resolve_credentials()
        # If user_id is provided, format is user_id:session_token in base64
        # If already base64, return as is; otherwise base64 encode
        if user_id:
            raw = f"{user_id}:{token}".encode("ascii")
            return base64.b64encode(raw).decode("ascii")
        # Otherwise base64 encode token or pass directly
        try:
            # test if already valid base64
            base64.b64decode(token.encode("ascii"))
            return token
        except Exception:
            return base64.b64encode(token.encode("ascii")).decode("ascii")

    def _request_v1(
        self,
        method: str,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated v1 API request using SHA256 checksum signing."""
        key, secret, token, _ = self._resolve_credentials()
        b64_session = self._get_base64_session_token()

        body_str = json.dumps(body or {}, separators=(",", ":"))
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        raw_checksum = timestamp + body_str + secret
        checksum = hashlib.sha256(raw_checksum.encode("utf-8")).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Checksum": f"token {checksum}",
            "X-Timestamp": timestamp,
            "X-AppKey": key,
            "X-SessionToken": b64_session,
        }

        url = f"{BREEZE_API_V1}/{endpoint}"
        if method.upper() == "GET":
            # Breeze v1 GET requests expect JSON payload in body
            # We use HttpClient or custom request
            import httpx

            with httpx.Client(timeout=self._config.timeout_seconds) as client:
                res = client.request("GET", url, content=body_str, headers=headers)
                return res.json()
        elif method.upper() == "POST":
            return self._http.post_json(
                url, body=body or {}, provider=self.provider_id, headers=headers
            )
        elif method.upper() == "PUT":
            import httpx

            with httpx.Client(timeout=self._config.timeout_seconds) as client:
                res = client.request("PUT", url, content=body_str, headers=headers)
                return res.json()
        elif method.upper() == "DELETE":
            import httpx

            with httpx.Client(timeout=self._config.timeout_seconds) as client:
                res = client.request("DELETE", url, content=body_str, headers=headers)
                return res.json()
        else:
            raise ProviderError(self.provider_id, f"Unsupported HTTP method {method}")

    def _request_v2_historical(self, params: dict[str, Any]) -> dict[str, Any]:
        """Query v2 historicalcharts endpoint."""
        key, _, _, _ = self._resolve_credentials()
        b64_session = self._get_base64_session_token()

        headers = {
            "Content-Type": "application/json",
            "X-SessionToken": b64_session,
            "apikey": key,
        }
        url = f"{BREEZE_API_V2}/historicalcharts"
        return self._http.get_json(url, provider=self.provider_id, params=params, headers=headers)

    def get_ohlcv(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime,
        end: datetime,
        *,
        exchange: str = "NSE",
    ) -> list[OHLCV]:
        """Fetch historical equity/index/commodity OHLCV candles."""
        resolved = resolve_symbol(symbol)
        native_interval = self._map_candle_interval(interval)

        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        from_str = start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to_str = end_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Map symbol to Breeze stock_code
        stock_code = resolved.canonical
        ex_code = exchange.lower()
        if ex_code == "mcx" and stock_code.upper() in MCX_STOCK_CODES:
            stock_code = MCX_STOCK_CODES[stock_code.upper()]

        params: dict[str, Any] = {
            "interval": native_interval,
            "from_date": from_str,
            "to_date": to_str,
            "stock_code": stock_code,
            "exch_code": ex_code,
        }

        # For commodities or index futures when requested
        if ex_code in ("mcx", "nfo", "bfo"):
            params["product_type"] = "futures"

        raw = self._request_v2_historical(params)
        return self._parse_candles(raw, symbol=symbol, interval=interval)

    def get_option_ohlcv(
        self,
        contract: OptionContract | str,
        interval: Interval | str,
        start: datetime,
        end: datetime,
        *,
        exchange: str | None = None,
        instrument_id: str | None = None,
    ) -> list[OHLCV]:
        """Fetch historical option OHLCV candles."""
        c = self._coerce_contract(contract, exchange_override=exchange)
        native_interval = self._map_candle_interval(interval)

        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        from_str = start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to_str = end_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        ex_code = (c.exchange or exchange or "NFO").lower()
        underlying = c.underlying.upper()
        stock_code = MCX_STOCK_CODES.get(underlying, underlying) if ex_code == "mcx" else underlying

        expiry_str = c.expiry.strftime("%Y-%m-%dT06:00:00.000Z")
        right_str = "call" if c.option_type.value.lower() in ("call", "ce") else "put"
        strike_str = str(c.strike)

        params: dict[str, Any] = {
            "interval": native_interval,
            "from_date": from_str,
            "to_date": to_str,
            "stock_code": stock_code,
            "exch_code": ex_code,
            "product_type": "options",
            "expiry_date": expiry_str,
            "right": right_str,
            "strike_price": strike_str,
        }

        raw = self._request_v2_historical(params)
        canonical_sym = c.canonical()
        return self._parse_candles(raw, symbol=canonical_sym, interval=interval)

    def _map_candle_interval(self, interval: Interval | str) -> str:
        if isinstance(interval, str) and interval in SUPPORTED_BREEZE_INTERVALS:
            return interval
        try:
            return map_interval(interval, INTERVAL_TO_BREEZE, self.provider_id)
        except Exception as err:
            supported = sorted(SUPPORTED_BREEZE_INTERVALS)
            raise ProviderError(
                self.provider_id,
                f"Unsupported Breeze interval {interval!r}; supported: {supported}",
            ) from err
        supported_keys = sorted(INTERVAL_TO_BREEZE.keys())
        raise ProviderError(
            self.provider_id,
            f"Unsupported Breeze interval {interval!r}; supported: {supported_keys}",
        )

    def _parse_candles(
        self,
        raw: dict[str, Any],
        *,
        symbol: str,
        interval: Interval | str,
    ) -> list[OHLCV]:
        if not isinstance(raw, dict):
            raise ProviderError(self.provider_id, f"Invalid candles payload from Breeze: {raw!r}")

        err = raw.get("Error")
        if err:
            err_lower = str(err).lower()
            if "no data" in err_lower or "data not found" in err_lower:
                return []
            raise ProviderError(self.provider_id, f"Breeze API error: {err}")

        success = raw.get("Success")
        if success is None:
            return []
        if not isinstance(success, list):
            raise ProviderError(
                self.provider_id, f"Expected Success list from Breeze, got {type(success)}"
            )

        out: list[OHLCV] = []
        for row in success:
            if not isinstance(row, dict):
                continue
            ts_str = str(row.get("datetime") or "")
            if not ts_str:
                continue
            try:
                ts = _parse_breeze_timestamp(ts_str)
                open_val = _to_decimal(row["open"])
                high_val = _to_decimal(row["high"])
                low_val = _to_decimal(row["low"])
                close_val = _to_decimal(row["close"])
                vol_val = _to_decimal(row.get("volume") or 0)
                oi = (
                    _to_decimal(row["open_interest"])
                    if "open_interest" in row and row["open_interest"] is not None
                    else None
                )
            except Exception as err:
                raise ProviderError(
                    self.provider_id, f"Failed to parse candle row {row}: {err}"
                ) from err

            out.append(
                OHLCV(
                    timestamp=ts,
                    open=open_val,
                    high=high_val,
                    low=low_val,
                    close=close_val,
                    volume=vol_val,
                    open_interest=oi,
                    symbol=symbol,
                    interval=interval,
                    source=self.provider_id,
                )
            )

        # Sort ascending by timestamp
        out.sort(key=lambda x: x.timestamp)
        return out

    def _coerce_contract(
        self,
        contract: OptionContract | str,
        *,
        exchange_override: str | None = None,
    ) -> OptionContract:
        if isinstance(contract, OptionContract):
            if exchange_override and not contract.exchange:
                return contract.model_copy(update={"exchange": exchange_override})
            return contract

        parsed = parse_option_symbol(contract)
        if not parsed:
            raise ProviderError(self.provider_id, f"Cannot parse option string: {contract!r}")

        ex = exchange_override or "NFO"
        return OptionContract(
            underlying=parsed.underlying,
            expiry=parsed.expiry,
            strike=parsed.strike,
            option_type=OptionType(parsed.option_type),
            exchange=ex,
        )

    def list_symbols(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[SymbolInfo]:
        """List known Breeze symbols / commodities."""
        out: list[SymbolInfo] = []
        for alias, code in MCX_STOCK_CODES.items():
            if search and search.upper() not in alias:
                continue
            out.append(
                SymbolInfo(
                    canonical=alias,
                    base=code,
                    asset_type=AssetType.COMMODITY,
                    provider_symbol=code,
                    display_name=f"{alias} ({code})",
                )
            )
            if limit and len(out) >= limit:
                break
        return out
