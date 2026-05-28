#!/usr/bin/env python3
"""
Client-facing demo: historical OHLCV from Binance (public) and Zerodha (Kite auth).

Usage (from repo root):

  cp examples/.env.example .env
  # Edit `.env` with your values (see examples/.env.example for all variables).

  python examples/main.py

  # Or set shell variables (they take precedence over `.env`):
  export ZERODHA_API_KEY=your_key
  export ZERODHA_ACCESS_TOKEN=your_access_token
  python examples/main.py

Requires a venv with V2 dependencies: ``pip install -r requirements.txt`` or ``pip install -e .``
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.join(_REPO_ROOT, "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)

from bandl import Bandl, BandlConfig, Interval, ProviderSettings
from bandl.exceptions import AuthenticationError, SymbolNotFoundError


def _load_env_file(path: str) -> None:
    """Populate os.environ from a ``.env`` file (KEY=VALUE). Do not override existing vars."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[key] = value


def load_dotenv_files() -> None:
    """Load ``.env`` from repo root, then ``examples/.env`` (later file fills missing keys only)."""
    _load_env_file(os.path.join(_REPO_ROOT, ".env"))
    _load_env_file(os.path.join(_EXAMPLES_DIR, ".env"))


def run_binance(client: Bandl) -> None:
    print("\n=== Binance (public) ===")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    df = client.crypto.get_ohlcv_dataframe(
        "BTC/USDT",
        Interval.D1,
        start,
        end,
        source="binance",
    )
    print(f"Rows: {len(df)}")
    if len(df) > 0:
        print(df.tail(3).to_string(index=False))


def run_zerodha(client: Bandl) -> None:
    print("\n=== Zerodha (Kite — requires API key + access token) ===")
    api_key = os.environ.get("ZERODHA_API_KEY")
    access_token = os.environ.get("ZERODHA_ACCESS_TOKEN")
    if not api_key or not access_token:
        print(
            "Skip: set ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN in `.env` "
            "(see examples/.env.example) or export them in your shell.",
        )
        return

    # Credentials are already on the client when present in `.env` / config.
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)

    try:
        df_eq = client.equity.get_ohlcv_dataframe(
            "RELIANCE",
            Interval.D1,
            start,
            end,
            source="zerodha",
        )
    except AuthenticationError as err:
        print(err)
        print(
            "Zerodha returned 401/403: renew Kite access_token (expires daily), "
            "ensure ZERODHA_API_KEY matches the app that minted the token, and "
            "check Historical API / Connect permissions on https://kite.trade/connect/apps.",
        )
        return

    print(f"RELIANCE daily rows: {len(df_eq)}")
    if len(df_eq) > 0:
        print(df_eq.tail(30).to_string(index=False))

    try:
        df_ix = client.equity.get_ohlcv_dataframe(
            "NIFTY 50",
            Interval.D1,
            start,
            end,
            source="zerodha",
        )
    except SymbolNotFoundError as err:
        print(f"Skip NIFTY 50 demo (symbol lookup): {err}")
    except AuthenticationError as err:
        print(f"Skip NIFTY 50 demo (auth): {err}")
    else:
        print(f"NIFTY 50 index daily rows: {len(df_ix)}")
        if len(df_ix) > 0:
            print(df_ix.tail(3).to_string(index=False))


def _provider_settings_from_env() -> dict[str, ProviderSettings]:
    """Build provider settings from environment (after ``load_dotenv_files()``)."""
    prov: dict[str, ProviderSettings] = {}
    z_k = os.environ.get("ZERODHA_API_KEY")
    z_t = os.environ.get("ZERODHA_ACCESS_TOKEN")
    if z_k and z_t:
        prov["zerodha"] = ProviderSettings(api_key=z_k, access_token=z_t)
    b_k = os.environ.get("BINANCE_API_KEY")
    if b_k:
        prov["binance"] = ProviderSettings(
            api_key=b_k,
            api_secret=os.environ.get("BINANCE_API_SECRET"),
        )
    c_k = os.environ.get("COINDCX_API_KEY")
    if c_k:
        prov["coindcx"] = ProviderSettings(
            api_key=c_k,
            api_secret=os.environ.get("COINDCX_API_SECRET"),
        )
    return prov


def main() -> None:
    load_dotenv_files()
    prov = _provider_settings_from_env()
    config = BandlConfig(providers=prov) if prov else BandlConfig()
    client = Bandl(config)

    run_binance(client)
    run_zerodha(client)

    print("\nDone.")


if __name__ == "__main__":
    main()
