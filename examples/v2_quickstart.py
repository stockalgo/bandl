#!/usr/bin/env python3
"""Minimal Bandl V2 usage examples (historical OHLCV)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bandl import Bandl, BandlConfig, Interval, ProviderSettings


def main() -> None:
    # Public crypto: Binance (default for facet.crypto)
    client = Bandl()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=14)
    df = client.crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1, start, end)
    print(df.head())

    # CoinDCX (canonical still BTCUSDT; pair mapped to B-BTC_USDT internally)
    df2 = client.crypto.get_ohlcv_dataframe("ETHUSDT", Interval.D1, start, end, source="coindcx")
    print(df2.head())

    # Zerodha — requires Kite Connect api_key + access_token
    # cfg = BandlConfig(
    #     providers={
    #         "zerodha": ProviderSettings(
    #             api_key="your_api_key",
    #             access_token="your_access_token",
    #         ),
    #     },
    # )
    # z = Bandl(cfg)
    # df3 = z.equity.get_ohlcv_dataframe("RELIANCE", Interval.D1, start, end, source="zerodha")
    # df4 = z.equity.get_ohlcv_dataframe("NIFTY 50", Interval.D1, start, end, source="zerodha")
    # print(df3.head(), df4.head())


if __name__ == "__main__":
    main()
