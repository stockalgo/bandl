"""Dhan HQ provider — derivatives (options) OHLCV, expiries, and option chain."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from bandl.config import BandlConfig, ProviderSettings
from bandl.core.contracts import parse_option_symbol
from bandl.core.http import HttpClient
from bandl.core.time import ensure_utc
from bandl.exceptions import AuthenticationError, ProviderError
from bandl.models.market import OHLCV, OptionChainEntry, OptionContract, OptionQuote
from bandl.models.market.types import Interval
from bandl.providers.dhan.common import (
    DHAN_API,
    EXCHANGE_SEGMENT,
    INTERVAL_TO_MINUTES,
    INTRADAY_INTERVALS,
    OPTION_INSTRUMENT,
)
from bandl.providers.dhan.scrip import ScripMaster


def _epoch_to_utc(epoch: float) -> datetime:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


class DhanProvider:
    """Dhan HQ adapter. Spans MCX commodity, NSE/BSE F&O, equity."""

    provider_id = "dhan"

    def __init__(self, config: BandlConfig, settings: ProviderSettings | None = None) -> None:
        self._config = config
        self._settings = settings or config.providers.get("dhan") or ProviderSettings()
        self._http = HttpClient(config)
        self._scrip = ScripMaster(self._http, self.provider_id)

    # -- auth -----------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        tok = self._settings.access_token
        if not tok:
            raise AuthenticationError(
                self.provider_id,
                "Dhan requires access_token (JWT); set api_key to your client_id",
            )
        headers = {"access-token": tok, "Content-Type": "application/json"}
        if self._settings.api_key:
            headers["client-id"] = self._settings.api_key
        return headers

    # -- contract coercion ----------------------------------------------------

    def _coerce_contract(
        self,
        contract: str | OptionContract,
        exchange: str | None,
        *,
        resolve: bool = True,
    ) -> tuple[OptionContract, str]:
        """Return a concrete ``OptionContract`` plus the canonical symbol label.

        Strings are parsed; when ``resolve`` is true the exact expiry date is
        looked up from the scrip master (monthly symbols encode only year +
        month). With ``resolve=False`` the expiry day falls back to the 1st —
        ``canonical()`` only uses year + month, so the label is unaffected. This
        lets ``instrument_id`` callers skip scrip lookup for contracts Dhan has
        dropped from the published master.
        """
        if isinstance(contract, OptionContract):
            return contract, contract.canonical()

        parsed = parse_option_symbol(contract)
        ex = exchange or parsed.exchange
        if not ex:
            raise ProviderError(
                self.provider_id,
                f"exchange required to resolve {contract!r} (e.g. exchange='MCX')",
            )
        expiry = date(parsed.year, parsed.month, 1)
        lot_size = None
        if resolve:
            resolved = self._scrip.resolve_option(
                parsed.underlying,
                ex,
                parsed.strike,
                parsed.option_type.value,
                year=parsed.year,
                month=parsed.month,
            )
            expiry = resolved.expiry or expiry
            lot_size = resolved.lot_size
        oc = OptionContract(
            underlying=parsed.underlying,
            expiry=expiry,
            strike=parsed.strike,
            option_type=parsed.option_type,
            exchange=ex,
            lot_size=lot_size,
        )
        return oc, oc.canonical()

    # -- OHLCV ----------------------------------------------------------------

    def get_option_ohlcv(
        self,
        contract: str | OptionContract,
        interval: Interval | int,
        start: datetime,
        end: datetime,
        *,
        exchange: str | None = None,
        instrument_id: str | None = None,
    ) -> list[OHLCV]:
        """Intraday OHLCV for an option contract.

        ``instrument_id`` is the generic native instrument id (Dhan securityId);
        when given the scrip-master lookup is skipped — useful for expired
        contracts dropped from the published scrip master.
        """
        oc, label = self._coerce_contract(
            contract,
            exchange,
            resolve=instrument_id is None,
        )
        ex = exchange or oc.exchange

        if instrument_id is not None:
            security_id = str(instrument_id)
            segment = EXCHANGE_SEGMENT.get(ex.upper(), ex)
            instrument = OPTION_INSTRUMENT.get(ex.upper(), "OPTIDX")
        else:
            resolved = self._scrip.resolve_contract(oc)
            security_id = resolved.security_id
            segment = resolved.exchange_segment
            instrument = resolved.instrument_type

        interval_int, interval_label = _normalize_interval(interval)

        body = {
            "securityId": security_id,
            "exchangeSegment": segment,
            "instrument": instrument,
            "interval": interval_int,
            "fromDate": ensure_utc(start).date().isoformat(),
            "toDate": ensure_utc(end).date().isoformat(),
        }
        payload = self._http.post_json(
            f"{DHAN_API}/charts/intraday",
            provider=self.provider_id,
            body=body,
            headers=self._auth_headers(),
        )
        return self._parse_candles(payload, symbol=label, interval=interval_label)

    def _parse_candles(self, payload: Any, *, symbol: str, interval: str) -> list[OHLCV]:
        if not isinstance(payload, dict):
            raise ProviderError(self.provider_id, f"Unexpected candle payload: {payload!r}")
        timestamps = payload.get("timestamp") or []
        opens = payload.get("open") or []
        highs = payload.get("high") or []
        lows = payload.get("low") or []
        closes = payload.get("close") or []
        volumes = payload.get("volume") or []
        ois = payload.get("open_interest") or payload.get("oi") or []
        out: list[OHLCV] = []
        for i, ts in enumerate(timestamps):
            try:
                out.append(
                    OHLCV(
                        timestamp=_epoch_to_utc(ts),
                        open=Decimal(str(opens[i])),
                        high=Decimal(str(highs[i])),
                        low=Decimal(str(lows[i])),
                        close=Decimal(str(closes[i])),
                        volume=Decimal(str(volumes[i])),
                        open_interest=_dec(ois[i]) if i < len(ois) else None,
                        symbol=symbol,
                        interval=interval,
                        source=self.provider_id,
                    ),
                )
            except (IndexError, TypeError, ValueError, ArithmeticError):
                continue
        return out

    # -- expiries / chain -----------------------------------------------------

    def list_expiries(
        self,
        underlying: str,
        *,
        exchange: str,
        segment: str | None = None,
    ) -> list[date]:
        """Distinct option expiry dates for an underlying (from the scrip master)."""
        return self._scrip.list_expiries(underlying, exchange)

    def get_option_chain(
        self,
        underlying: str,
        *,
        expiry: date,
        exchange: str,
        segment: str | None = None,
    ) -> list[OptionChainEntry]:
        """Live option chain for one expiry via POST /optionchain."""
        und_id, und_seg = self._resolve_underlying(underlying, exchange)
        body = {
            "UnderlyingScrip": int(und_id),
            "UnderlyingSeg": segment or und_seg,
            "Expiry": expiry.isoformat(),
        }
        payload = self._http.post_json(
            f"{DHAN_API}/optionchain",
            provider=self.provider_id,
            body=body,
            headers=self._auth_headers(),
        )
        return self._parse_chain(payload)

    def _resolve_underlying(self, underlying: str, exchange: str) -> tuple[str, str]:
        """Find a security id + segment for the underlying (nearest FUT row)."""
        ex = exchange.upper()
        self._scrip.load()
        fut_types = {"FUTCOM", "FUTIDX", "FUTSTK", "FUTCUR"}
        rows = [
            r
            for r in self._scrip.rows
            if r.get("SEM_EXM_EXCH_ID", "").upper() == ex
            and r.get("SM_SYMBOL_NAME", "").upper() == underlying.upper()
            and r.get("SEM_INSTRUMENT_NAME", "").upper() in fut_types
        ]
        if not rows:
            raise ProviderError(
                self.provider_id,
                f"No underlying instrument for {underlying} on {ex}",
            )
        row = rows[0]
        seg = EXCHANGE_SEGMENT.get(ex, ex)
        return row["SEM_SMST_SECURITY_ID"], seg

    def _parse_chain(self, payload: Any) -> list[OptionChainEntry]:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        oc_map = data.get("oc") if isinstance(data, dict) else None
        if not isinstance(oc_map, dict):
            return []
        out: list[OptionChainEntry] = []
        for strike_str, legs in oc_map.items():
            strike = _dec(strike_str)
            if strike is None or not isinstance(legs, dict):
                continue
            out.append(
                OptionChainEntry(
                    strike=strike,
                    ce=_parse_leg(legs.get("ce")),
                    pe=_parse_leg(legs.get("pe")),
                ),
            )
        out.sort(key=lambda e: e.strike)
        return out


def _normalize_interval(interval: Interval | int) -> tuple[int, str]:
    if isinstance(interval, Interval):
        iv = INTERVAL_TO_MINUTES.get(interval)
        if iv is None:
            supported = ", ".join(i.value for i in INTERVAL_TO_MINUTES)
            raise ProviderError("dhan", f"Unsupported interval {interval.value}; use {supported}")
        return iv, interval.value
    if interval not in INTRADAY_INTERVALS:
        raise ProviderError(
            "dhan",
            f"Interval {interval} not supported; use one of {sorted(INTRADAY_INTERVALS)}",
        )
    return interval, f"{interval}m"


def _parse_leg(leg: Any) -> OptionQuote | None:
    if not isinstance(leg, dict):
        return None
    greeks = leg.get("greeks") if isinstance(leg.get("greeks"), dict) else {}
    return OptionQuote(
        ltp=_dec(leg.get("last_price")),
        oi=_dec(leg.get("oi")),
        iv=_dec(leg.get("implied_volatility")),
        volume=_dec(leg.get("volume")),
        delta=_dec(greeks.get("delta")),
        theta=_dec(greeks.get("theta")),
        gamma=_dec(greeks.get("gamma")),
        vega=_dec(greeks.get("vega")),
    )
