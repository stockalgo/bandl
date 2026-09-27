"""Dhan scrip-master (instrument dump) loading and lookup."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from bandl.core.http import HttpClient
from bandl.exceptions import InvalidOrderError, SymbolNotFoundError
from bandl.models.market.contract import OptionContract
from bandl.providers.dhan.common import DHAN_SCRIP_MASTER_URL


@dataclass(frozen=True)
class ResolvedInstrument:
    security_id: str
    exchange_segment: str
    instrument_type: str
    expiry: date | None
    lot_size: Decimal | None
    tick_size: Decimal | None = None
    source: str = "dhan_scrip_master"
    retrieved_at: datetime | None = None


def _parse_expiry(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s or s.startswith("0001-01-01"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            if d.year < 1970:
                return None
            return d
        except ValueError:
            continue
    return None


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _matches_underlying(r: dict[str, str], underlying: str) -> bool:
    und = underlying.strip().upper()
    sm_sym = r.get("SM_SYMBOL_NAME", "").strip().upper()
    if sm_sym == und:
        return True
    trading_sym = r.get("SEM_TRADING_SYMBOL", "").strip().upper()
    custom_sym = r.get("SEM_CUSTOM_SYMBOL", "").strip().upper()
    if und == "NIFTY":
        return trading_sym.startswith("NIFTY-") or custom_sym.startswith("NIFTY ")
    if und == "BANKNIFTY":
        return trading_sym.startswith("BANKNIFTY-") or custom_sym.startswith("BANKNIFTY ")
    if und == "FINNIFTY":
        return trading_sym.startswith("FINNIFTY-") or custom_sym.startswith("FINNIFTY ")
    if und == "MIDCPNIFTY":
        return trading_sym.startswith("MIDCPNIFTY-") or custom_sym.startswith("MIDCPNIFTY ")
    if und == "SENSEX":
        return (
            trading_sym.startswith("SENSEX-")
            or custom_sym.startswith("SENSEX ")
            or sm_sym == "BSXOPT"
        )
    if und == "BANKEX":
        return (
            trading_sym.startswith("BANKEX-")
            or custom_sym.startswith("BANKEX ")
            or sm_sym == "BKXOPT"
        )
    return False


class ScripMaster:
    """Lazily download + index Dhan's public instrument CSV."""

    def __init__(self, http: HttpClient, provider_id: str) -> None:
        self._http = http
        self._provider_id = provider_id
        self._rows: list[dict[str, str]] = []
        self._loaded_at: datetime | None = None

    def load(self, *, force: bool = False) -> None:
        if self._rows and not force:
            return
        text = self._http.get_text(DHAN_SCRIP_MASTER_URL, provider=self._provider_id)
        reader = csv.DictReader(io.StringIO(text))
        self._rows = [dict(r) for r in reader]
        self._loaded_at = datetime.now()

    @property
    def rows(self) -> list[dict[str, str]]:
        self.load()
        return self._rows

    def resolve_option(
        self,
        underlying: str,
        exchange: str,
        strike: Decimal,
        option_type: str,
        *,
        year: int | None = None,
        month: int | None = None,
        expiry: date | None = None,
        disallow_ambiguous_month: bool = False,
    ) -> ResolvedInstrument:
        """Find the option instrument matching underlying/strike/type and expiry.

        Match on exact ``expiry`` date when given, else on ``year``+``month``.
        """
        ex = exchange.upper()
        opt = option_type.upper()
        matches: list[tuple[date | None, dict[str, str]]] = []
        for r in self.rows:
            if r.get("SEM_EXM_EXCH_ID", "").upper() != ex:
                continue
            if not _matches_underlying(r, underlying):
                continue
            if r.get("SEM_OPTION_TYPE", "").upper() != opt:
                continue
            row_strike = _to_decimal(r.get("SEM_STRIKE_PRICE", ""))
            if row_strike is None or row_strike != strike:
                continue
            row_exp = _parse_expiry(r.get("SEM_EXPIRY_DATE", ""))
            if expiry is not None and row_exp != expiry:
                continue
            if (
                expiry is None
                and year is not None
                and month is not None
                and (not row_exp or (row_exp.year, row_exp.month) != (year, month))
            ):
                continue
            matches.append((row_exp, r))

        if not matches:
            raise SymbolNotFoundError(
                f"No Dhan {ex} option for {underlying} {strike} {opt} "
                f"(expiry={expiry or f'{year}-{month}'})",
            )

        if expiry is None and disallow_ambiguous_month:
            # Check unique expiries in the matching rows
            unique_expiries = {m[0] for m in matches if m[0] is not None}
            if len(unique_expiries) > 1:
                exp_list = sorted(unique_expiries)
                raise InvalidOrderError(
                    self._provider_id,
                    f"Ambiguous option expiry for {underlying} {strike} {opt} in month "
                    f"{year}-{month}: found {len(unique_expiries)} expiries {exp_list}. "
                    "Specify an exact structured OptionContract or native instrument_id.",
                )

        # Earliest matching expiry first (stable for year+month matches).
        matches.sort(key=lambda t: t[0] or date.max)
        exp, row = matches[0]

        # Check for ambiguity among rows matching the target expiry
        candidate_ids = {
            r.get("SEM_SMST_SECURITY_ID")
            for row_exp, r in matches
            if row_exp == exp and r.get("SEM_SMST_SECURITY_ID")
        }
        if len(candidate_ids) > 1:
            raise InvalidOrderError(
                self._provider_id,
                f"Ambiguous option resolution for {underlying} {strike} {opt} (expiry={exp}): "
                f"found multiple matching security IDs {sorted(candidate_ids)}. "
                "Specify an exact native instrument_id.",
            )
        return ResolvedInstrument(
            security_id=row["SEM_SMST_SECURITY_ID"],
            exchange_segment=f"{row.get('SEM_EXM_EXCH_ID', ex)}_{_segment_suffix(row)}",
            instrument_type=row.get("SEM_INSTRUMENT_NAME", ""),
            expiry=exp,
            lot_size=_to_decimal(row.get("SEM_LOT_UNITS", "")),
            tick_size=_to_decimal(row.get("SEM_TICK_SIZE", ""))
            or _to_decimal(row.get("SEM_PRICE_TICK", "")),
            source="dhan_scrip_master",
            retrieved_at=self._loaded_at,
        )

    def resolve_contract(self, contract: OptionContract) -> ResolvedInstrument:
        return self.resolve_option(
            contract.underlying,
            contract.exchange,
            contract.strike,
            contract.option_type.value,
            expiry=contract.expiry,
        )

    def list_expiries(
        self,
        underlying: str,
        exchange: str,
        *,
        option_only: bool = True,
    ) -> list[date]:
        ex = exchange.upper()
        out: set[date] = set()
        for r in self.rows:
            if r.get("SEM_EXM_EXCH_ID", "").upper() != ex:
                continue
            if not _matches_underlying(r, underlying):
                continue
            if option_only and not r.get("SEM_OPTION_TYPE", "").strip():
                continue
            exp = _parse_expiry(r.get("SEM_EXPIRY_DATE", ""))
            if exp:
                out.add(exp)
        return sorted(out)


def _segment_suffix(row: dict[str, str]) -> str:
    """Reconstruct the Dhan exchangeSegment suffix from a scrip row's exchange/instrument."""
    ex = row.get("SEM_EXM_EXCH_ID", "").upper()
    instr = row.get("SEM_INSTRUMENT_NAME", "").upper()
    if ex == "MCX":
        return "COMM"
    if ex in ("NSE", "BSE"):
        if instr in ("OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK", "OPTFUT"):
            return "FNO"
        if instr in ("OPTCUR", "FUTCUR"):
            return "CURRENCY"
        return "EQ"
    return "FNO"
