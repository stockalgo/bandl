<p align="center">
  <a href="https://bandl.io" target="_blank">
    <img src="https://raw.githubusercontent.com/stockalgo/bandl/master/img/logo.svg" alt="bandl" width="200">
  </a>
</p>

<p align="center">
  <strong>Unified market data for Indian equities and crypto</strong><br>
  One client, multiple providers — historical OHLCV as pandas or structured bars.
</p>

<p align="center">
  <a href="https://pypi.org/project/bandl/"><img src="https://img.shields.io/pypi/v/bandl.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/bandl/"><img src="https://img.shields.io/pypi/pyversions/bandl.svg" alt="Python"></a>
  <a href="https://github.com/stockalgo/bandl/blob/master/LICENSE"><img src="https://img.shields.io/github/license/stockalgo/bandl.svg" alt="License"></a>
</p>

---

## Install

```bash
pip install bandl
```

Requires **Python 3.10+**. For development: `pip install -e ".[dev]"` (see [CONTRIBUTING.md](CONTRIBUTING.md)).

---

## Quick start

Import **`bandl.v2`**, create a **`Bandl`** client, and fetch candles. **Binance** and **CoinDCX** public endpoints work without API keys.

```python
from datetime import datetime, timedelta, timezone

from bandl.v2 import Bandl, Interval

client = Bandl()
end = datetime.now(timezone.utc)
start = end - timedelta(days=30)

# Crypto — daily BTC/USDT from Binance (default crypto provider)
df = client.crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1, start, end)
print(df[["timestamp", "open", "high", "low", "close", "volume"]].tail())
```

**Indian equities (Zerodha Kite)** need a [Kite Connect](https://kite.trade/docs/connect/v3/) API key and access token:

```python
from bandl.v2 import Bandl, BandlConfig, Interval, ProviderSettings

client = Bandl(
    BandlConfig(
        providers={
            "zerodha": ProviderSettings(
                api_key="your_kite_api_key",
                access_token="your_daily_access_token",
            ),
        },
    ),
)

df = client.equity.get_ohlcv_dataframe(
    "RELIANCE",
    Interval.D1,
    start,
    end,
    source="zerodha",
)
print(df.tail())
```

**Indices** use the same API (aliases like `NIFTY 50` → `NIFTY50` are handled for you):

```python
nifty = client.equity.get_ohlcv_dataframe(
    "NIFTY 50",
    Interval.D1,
    start,
    end,
    source="zerodha",
)
```

---

## What you can fetch

| Market | Provider | Auth | Example symbols |
|--------|----------|------|-----------------|
| Crypto spot | `binance` | None (public klines) | `BTC/USDT`, `BTCUSDT`, `ETHUSDT` |
| Crypto spot | `coindcx` | None (public candles) | `BTCUSDT`, `ETHUSDT` |
| NSE equities & indices | `zerodha` | Kite API key + access token | `RELIANCE`, `NIFTY 50`, `BANKNIFTY` |

Switch provider with `source="binance"` | `"coindcx"` | `"zerodha"`, or use **`client.crypto`** / **`client.equity`** (defaults per facet).

> **Binance HTTP 451 (restricted location)?** Binance blocks many regions and cloud IPs (e.g. US, Google Colab). Use **CoinDCX** instead — same symbols, no API key:
>
> ```python
> df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end, source="coindcx")
> ```
>
> Or set `BandlConfig(default_crypto_provider="coindcx")`.
>
> **CoinDCX empty `DataFrame`?** The public candles API can **lag** (latest daily bars may end months before “today”). If your `start`/`end` are entirely after the feed, bandl raises **`DataNotAvailableError`** with the available date span. Use a window that overlaps the feed, for example:
>
> ```python
> end = datetime(2025, 7, 20, tzinfo=timezone.utc)
> start = end - timedelta(days=30)
> df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end, source="coindcx")
> ```

---

## Common patterns

### Pandas `DataFrame` (default for analysis)

```python
df = client.crypto.get_ohlcv_dataframe("ETHUSDT", Interval.D1, start, end)
```

### Typed list of bars (no pandas required in your pipeline)

```python
from bandl.v2 import OHLCV

bars: list[OHLCV] = client.crypto.get_ohlcv("BTCUSDT", Interval.H1, start, end)
for bar in bars[-5:]:
    print(bar.timestamp, bar.close, bar.source)
```

### Another crypto exchange

```python
df = client.crypto.get_ohlcv_dataframe(
    "BTCUSDT",
    Interval.D1,
    start,
    end,
    source="coindcx",
)
```

### List tradable symbols

```python
# Crypto (Binance spot, trading status)
symbols = client.list_symbols(source="binance", search="BTC", limit=20)

# NSE equities + indices (Zerodha — requires credentials)
symbols = client.list_symbols(
    source="zerodha",
    exchange="NSE",
    instrument_types=("EQ",),
    search="RELI",
    limit=10,
)
```

### Intervals

Use `Interval` enums or provider-native strings where supported:

```python
from bandl.v2 import Interval

Interval.M1   # 1m
Interval.H1   # 1h
Interval.D1   # 1d
```

Timestamps in responses are **UTC**. Convert for display if you need IST:

```python
df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata")
```

---

## Configuration

| Variable / setting | Purpose |
|--------------------|---------|
| `BandlConfig.providers["zerodha"]` | `api_key`, `access_token` for Kite |
| `BandlConfig.providers["binance"]` | Optional keys for future signed APIs |
| `BandlConfig.timeout_seconds` | HTTP timeout (default 30s) |
| `BandlConfig.default_crypto_provider` | Default for `client.crypto` (`binance`) |
| `BandlConfig.default_equity_provider` | Default for `client.equity` (`zerodha`) |

**Zerodha:** access tokens expire daily — regenerate after login. A 403 on historical data usually means an expired token, wrong API key, or missing historical API access on your Kite app.

Runnable demos:

```bash
cp examples/.env.example .env   # add ZERODHA_* if testing Kite
python examples/main.py
python examples/v2_quickstart.py
```

---

## Demo

<p align="center">
  <a href="https://bandl.io" target="_blank">
    <img src="https://raw.githubusercontent.com/stockalgo/bandl/master/img/demo.gif" alt="bandl demo">
  </a>
</p>

---

## Legacy modules (pre–V2)

Older helpers remain importable for NSE options, Yahoo Finance, legacy Binance wrappers, etc. New projects should prefer **`bandl.v2`**.

<details>
<summary><strong>NSE, Nasdaq, Yahoo, legacy Binance/Coinbase</strong></summary>

### NSE (options & historical)

```python
from bandl.nse_data import NseData

nd = NseData()
strikes = nd.get_oc_strike_prices("NIFTY")
oc_data = nd.get_option_data("NIFTY", strikes=strikes)

df = nd.get_data("RELIANCE", series="EQ", periods=30)
part_oi_df = nd.get_part_oi_df(periods=66)
```

### Nasdaq

```python
from bandl.nasdaq import Nasdaq

dfs = Nasdaq().get_data("AAPL", periods=15)
```

### Yahoo Finance

```python
from bandl.yfinance import Yfinance

yf = Yfinance()
us = yf.get_data("AAPL", is_indian=False)
india = yf.get_data("SBIN", start="21-Jan-2020")
```

### Legacy Binance / Coinbase

```python
from bandl.binance import Binance
from bandl.coinbase import Coinbase

Binance().get_data("ETHBTC", start="21-Jan-2020")
Coinbase().get_data("BTC-USD", start="21-Jan-2020", end="21-Jan-2021")
```

</details>

---

## Documentation & development

- [docs/BANDL_V2.md](docs/BANDL_V2.md) — design notes and provider behavior  
- [docs/PYPI_TRUSTED_PUBLISHING.md](docs/PYPI_TRUSTED_PUBLISHING.md) — release process for maintainers  
- [CONTRIBUTING.md](CONTRIBUTING.md) — tests, Ruff, pull requests  
- [SECURITY.md](SECURITY.md) — reporting vulnerabilities  

```bash
pytest tests/v2/          # unit tests
ruff check lib/bandl/v2 tests/v2
```

---

## Roadmap

- Live streams / WebSockets  
- More brokers and MCX commodity history  
- Broader `SymbolInfo` and fundamentals  

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before opening a pull request.

---

## License

[MIT](LICENSE)
