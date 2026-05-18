"""Symbol normalization and canonical form resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bandl.v2.core.aliases import normalize_alias_key, resolve_alias
from bandl.v2.models.types import AssetType

# Longest-first match for crypto quote leg
_CRYPTO_QUOTES: tuple[str, ...] = (
    "USDT",
    "USDC",
    "BUSD",
    "TUSD",
    "FDUSD",
    "EUR",
    "GBP",
    "AUD",
    "BIDR",
    "USD",
    "INR",
    "BTC",
    "ETH",
    "BNB",
    "DOGE",
)

_EXCHANGE_SUFFIXES: tuple[str, ...] = (
    ".NS",
    ".BO",
    ".NSE",
    ".BSE",
    "-NS",
    "-NSE",
    ":NSE",
    ":BSE",
    ":NS",
)


@dataclass(frozen=True)
class ResolvedSymbol:
    canonical: str
    asset_type: AssetType
    base: str
    quote: str | None


_RE_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def _strip_known_exchange_suffix(upper: str) -> str:
    s = upper.strip()
    for suf in _EXCHANGE_SUFFIXES:
        if s.upper().endswith(suf.upper()):
            return s[: -len(suf)].rstrip(" .:-_/")
    return s


def _split_crypto_pair(token: str) -> tuple[str, str | None]:
    """Split concatenated BASEQUOTE using longest quote suffix match."""
    t = token.upper()
    for q in _CRYPTO_QUOTES:
        if len(t) > len(q) + 1 and t.endswith(q):
            base = t[: -len(q)]
            if base:
                return base, q
    return t, None


def normalize_crypto_symbol(raw: str) -> str:
    """Return canonical crypto symbol like BTCUSDT."""
    s = raw.strip().upper()
    s = s.replace(" ", "")

    # explicit separator form
    for sep in ("/", "-", "_"):
        if sep in s:
            parts = [p for p in s.split(sep) if p]
            if len(parts) == 2:
                base, quote = parts[0].upper(), parts[1].upper()
                return f"{base}{quote}"

    s = _RE_NON_ALNUM.sub("", s)
    if not s:
        return s

    s = resolve_alias(s)
    # split if implicit BTCUSDT-style
    base, quote = _split_crypto_pair(s)
    if quote:
        return f"{base}{quote}"
    return s


def normalize_equity_or_index_symbol(raw: str, *, prefer_index: bool = False) -> str:
    """Return canonical equity/index symbol (no exchange suffix; spaces removed for indices)."""
    s = raw.strip()
    s = _strip_known_exchange_suffix(s.upper())
    s = resolve_alias(s)
    # Remove remaining punctuation except &
    s = s.replace("/", "").replace("-", " ")
    s = " ".join(s.split())
    if prefer_index or s in {
        "NIFTY 50",
        "NIFTY BANK",
    }:
        pass  # keep space forms for alias step
    key = normalize_alias_key(s)
    s = resolve_alias(key)
    # final canonical: no spaces in index tickers (NIFTY50)
    sq = s.replace(" ", "")
    return sq.upper()


def resolve_symbol(
    raw: str,
    *,
    asset_type: AssetType | None = None,
) -> ResolvedSymbol:
    """
    Parse user input into a canonical symbol.

    If ``asset_type`` is omitted, use conservative heuristics:
    separators like ``/`` imply crypto; valid ``BASE+QUOTE`` tails imply crypto;
    exchange suffixes (``.NS``) imply Indian equities; otherwise treat as equity/index.
    """
    work = raw.strip()
    upper = work.upper()

    if asset_type in (AssetType.CRYPTO_SPOT, AssetType.CRYPTO_PERP, AssetType.CRYPTO_FUTURE):
        canon = normalize_crypto_symbol(work)
        base, quote = _split_crypto_pair(canon)
        return ResolvedSymbol(
            canonical=canon,
            asset_type=asset_type,
            base=base,
            quote=quote,
        )

    if asset_type in (AssetType.EQUITY, AssetType.INDEX):
        canon = normalize_equity_or_index_symbol(work)
        idx_names = {"NIFTY50", "BANKNIFTY", "SPX", "MIDCPNIFTY"}
        is_index = asset_type == AssetType.INDEX or canon in idx_names
        at = AssetType.INDEX if is_index else AssetType.EQUITY
        c = canon.replace("^", "")
        return ResolvedSymbol(canonical=c, asset_type=at, base=c, quote=None)

    # --- auto-detect ---
    if any(upper.endswith(suf) for suf in (".NS", ".BO", ":NSE", ":BSE")):
        canon = normalize_equity_or_index_symbol(work)
        idx_names = {"NIFTY50", "BANKNIFTY", "SPX", "MIDCPNIFTY"}
        is_index = canon in idx_names
        at = AssetType.INDEX if is_index else AssetType.EQUITY
        c = canon.replace("^", "")
        return ResolvedSymbol(canonical=c, asset_type=at, base=c, quote=None)

    if "/" in work:
        canon = normalize_crypto_symbol(work)
        base, quote = _split_crypto_pair(canon)
        return ResolvedSymbol(
            canonical=canon,
            asset_type=AssetType.CRYPTO_SPOT,
            base=base,
            quote=quote,
        )

    compact = _RE_NON_ALNUM.sub("", upper)
    _, quote = _split_crypto_pair(compact)
    if quote is not None and len(compact) >= 5:
        canon = normalize_crypto_symbol(work)
        b, q = _split_crypto_pair(canon)
        return ResolvedSymbol(
            canonical=canon,
            asset_type=AssetType.CRYPTO_SPOT,
            base=b,
            quote=q,
        )

    canon = normalize_equity_or_index_symbol(work)
    idx_names = {"NIFTY50", "BANKNIFTY", "SPX", "MIDCPNIFTY"}
    is_index = canon in idx_names or upper.startswith("^")
    at = AssetType.INDEX if is_index else AssetType.EQUITY
    c = canon.replace("^", "")
    return ResolvedSymbol(canonical=c, asset_type=at, base=c, quote=None)
