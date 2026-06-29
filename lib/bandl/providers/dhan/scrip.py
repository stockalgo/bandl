"""Dhan scrip-master (instrument dump) loading and lookup."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from bandl.core.http import HttpClient
from bandl.exceptions import SymbolNotFoundError
from bandl.models.market.contract import OptionContract
from bandl.providers.dhan.common import DHAN_SCRIP_MASTER_URL


@dataclass(frozen=True)
class ResolvedInstrument:
    security_id: str
    exchange_segment: str
    instrument_type: str
    expiry: date | None
    lot_size: Decimal | None


def _parse_expiry(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


class ScripMaster:
    """Lazily download + index Dhan's public instrument CSV."""

    def __init__(self, http: HttpClient, provider_id: str) -> None:
        self._http = http
        self._provider_id = provider_id
        self._rows: list[dict[str, str]] = []

    def load(self, *, force: bool = False) -> None:
        if self._rows and not force:
            return
        text = self._http.get_text(DHAN_SCRIP_MASTER_URL, provider=self._provider_id)
        reader = csv.DictReader(io.StringIO(text))
        self._rows = [dict(r) for r in reader]

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
            if r.get("SM_SYMBOL_NAME", "").upper() != underlying.upper():
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
        # Earliest matching expiry first (stable for year+month matches).
        matches.sort(key=lambda t: t[0] or date.max)
        exp, row = matches[0]
        return ResolvedInstrument(
            security_id=row["SEM_SMST_SECURITY_ID"],
            exchange_segment=f"{row.get('SEM_EXM_EXCH_ID', ex)}_{_segment_suffix(row)}",
            instrument_type=row.get("SEM_INSTRUMENT_NAME", ""),
            expiry=exp,
            lot_size=_to_decimal(row.get("SEM_LOT_UNITS", "")),
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
            if r.get("SM_SYMBOL_NAME", "").upper() != underlying.upper():
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
