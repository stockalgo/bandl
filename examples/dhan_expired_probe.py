#!/usr/bin/env python3
"""EXPERIMENTAL: discover Dhan securityIds for expired option contracts.

Dhan drops fully-expired contracts from its published scrip master, but their
historical candles remain reachable by native securityId. This helper brute-force
scans a numeric securityId range, querying the intraday endpoint for a target date,
and prints ids that return candles. It is SLOW, rate-limited, and unofficial — it is
deliberately NOT part of the bandl library. Use only to recover an id once, then pass
it to the supported API via ``instrument_id=``.

Usage (from repo root, with DHAN_* in .env):

  python examples/dhan_expired_probe.py --from-id 570000 --to-id 571446 \
      --date 2026-06-26 --exchange MCX

Then fetch real data:

  client.derivatives.get_ohlcv("GOLDM26JUN143500CE", Interval.M1, start, end,
      source="dhan", exchange="MCX", instrument_id="<found id>")
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

from bandl.config import BandlConfig, ProviderSettings
from bandl.providers.dhan.common import DHAN_API, EXCHANGE_SEGMENT, OPTION_INSTRUMENT
from bandl.providers.dhan.provider import DhanProvider

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env() -> None:
    path = os.path.join(_REPO_ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-id", type=int, required=True)
    ap.add_argument("--to-id", type=int, required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD trading day to probe")
    ap.add_argument("--exchange", default="MCX")
    ap.add_argument("--step", type=int, default=25, help="id stride")
    ap.add_argument("--sleep", type=float, default=0.35, help="seconds between calls")
    args = ap.parse_args()

    _load_env()
    cfg = BandlConfig(
        providers={
            "dhan": ProviderSettings(
                api_key=os.environ.get("DHAN_CLIENT_ID"),
                access_token=os.environ.get("DHAN_ACCESS_TOKEN"),
            ),
        },
    )
    prov = DhanProvider(cfg)
    seg = EXCHANGE_SEGMENT.get(args.exchange.upper(), args.exchange)
    instr = OPTION_INSTRUMENT.get(args.exchange.upper(), "OPTIDX")
    headers = prov._auth_headers()

    found: list[int] = []
    for sec_id in range(args.from_id, args.to_id + 1, args.step):
        time.sleep(args.sleep)
        body = {
            "securityId": str(sec_id),
            "exchangeSegment": seg,
            "instrument": instr,
            "interval": 5,
            "fromDate": args.date,
            "toDate": args.date,
        }
        try:
            r = prov._http.post_json(
                f"{DHAN_API}/charts/intraday",
                provider="dhan",
                body=body,
                headers=headers,
            )
        except Exception:  # noqa: BLE001 - probing; ignore 400/invalid token rows
            continue
        ts = r.get("timestamp") or []
        if ts:
            close0 = (r.get("close") or [None])[0]
            t0 = datetime.fromtimestamp(ts[0], tz=timezone.utc).isoformat()
            print(f"id={sec_id}  candles={len(ts)}  first={t0}  close={close0}")
            found.append(sec_id)

    print(f"\nFound {len(found)} ids with candles on {args.date}: {found}")


if __name__ == "__main__":
    main()
