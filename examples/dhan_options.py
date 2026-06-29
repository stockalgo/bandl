#!/usr/bin/env python3
"""Dhan derivatives demo: option OHLCV, expiries, and the expired-contract escape hatch.

Usage (from repo root):

  cp examples/.env.example .env      # then fill DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN
  python examples/dhan_options.py

Dhan serves minute OHLCV for active option contracts (resolved from its public scrip
master) and for *expired* contracts when you pass the native instrument id.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from bandl import Bandl, BandlConfig, Interval, ProviderSettings

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip("\"'")


def _client() -> Bandl:
    _load_env_file(os.path.join(_REPO_ROOT, ".env"))
    cid = os.environ.get("DHAN_CLIENT_ID")
    tok = os.environ.get("DHAN_ACCESS_TOKEN")
    if not tok:
        raise SystemExit("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env first.")
    cfg = BandlConfig(providers={"dhan": ProviderSettings(api_key=cid, access_token=tok)})
    return Bandl(cfg)


def main() -> None:
    client = _client()

    print("=== GOLDM option expiries (MCX, from scrip master) ===")
    expiries = client.derivatives.list_expiries("GOLDM", source="dhan", exchange="MCX")
    print(f"{len(expiries)} expiries; first few: {expiries[:6]}")

    if expiries:
        # Active contract: resolved from the scrip master by underlying/expiry/strike/type.
        nearest = expiries[0]
        symbol = f"GOLDM{nearest.year % 100:02d}{nearest.strftime('%b').upper()}145000CE"
        end = datetime.now(timezone.utc)
        start = datetime(end.year, end.month, max(1, end.day - 5), tzinfo=timezone.utc)
        print(f"\n=== {symbol} 5-min (active, scrip-resolved) ===")
        try:
            df = client.derivatives.get_ohlcv_dataframe(
                symbol,
                Interval.M5,
                start,
                end,
                source="dhan",
                exchange="MCX",
            )
            print(f"rows={len(df)}")
            if len(df):
                print(df.tail(3).to_string(index=False))
        except Exception as err:  # noqa: BLE001 - demo
            print(f"skip ({type(err).__name__}): {err}")

    # Expired contract escape hatch: pass the native instrument id (generic `instrument_id`).
    # Dhan drops fully-expired contracts from the published scrip master, so look up the
    # securityId once (Kite/Dhan web, or examples/dhan_expired_probe.py) and reuse it.
    print("\n=== GOLDM26JUN143500CE 1-min (expired, via instrument_id) ===")
    try:
        rows = client.derivatives.get_ohlcv(
            "GOLDM26JUN143500CE",
            Interval.M1,
            datetime(2026, 6, 26, tzinfo=timezone.utc),
            datetime(2026, 6, 27, tzinfo=timezone.utc),
            source="dhan",
            exchange="MCX",
            instrument_id="570800",  # native Dhan securityId for this expired contract
        )
        print(f"rows={len(rows)}")
        if rows:
            r = rows[-1]
            print(f"last: {r.timestamp.isoformat()} close={r.close} volume={r.volume}")
    except Exception as err:  # noqa: BLE001 - demo
        print(f"skip ({type(err).__name__}): {err}")

    print("\nDone.")


if __name__ == "__main__":
    main()
