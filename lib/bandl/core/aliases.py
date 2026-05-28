"""Built-in symbol aliases (index names, common crypto shorthand)."""

from __future__ import annotations

SYMBOL_ALIASES: dict[str, str] = {
    "NIFTY": "NIFTY50",
    "NIFTY 50": "NIFTY50",
    "^NSEI": "NIFTY50",
    "NIFTY50": "NIFTY50",
    "BANK NIFTY": "BANKNIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "^NSEBANK": "BANKNIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "S&P 500": "SPX",
    "^GSPC": "SPX",
    "SPX": "SPX",
    "BITCOIN": "BTCUSDT",
    "BTC": "BTCUSDT",
    "ETHEREUM": "ETHUSDT",
    "ETH": "ETHUSDT",
}


def normalize_alias_key(raw: str) -> str:
    """Uppercase and collapse internal whitespace for alias lookup."""
    return " ".join(raw.strip().upper().split())


def resolve_alias(canonical_candidate: str) -> str:
    key = normalize_alias_key(canonical_candidate)
    return SYMBOL_ALIASES.get(key, canonical_candidate)
