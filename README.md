<p align="center">
  <a href="https://bandl.io" target="_blank">
    <img src="https://raw.githubusercontent.com/stockalgo/bandl/master/img/logo.svg" alt="bandl" width="200">
  </a>
</p>

<p align="center">
  <strong>One Python client for market data — crypto, Indian equities & options.</strong><br>
  Same call everywhere. Get a pandas <code>DataFrame</code> or typed bars in three lines.
</p>

<p align="center">
  <a href="https://pypi.org/project/bandl/"><img src="https://img.shields.io/pypi/v/bandl.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/bandl/"><img src="https://img.shields.io/pypi/pyversions/bandl.svg" alt="Python"></a>
  <a href="https://github.com/stockalgo/bandl/blob/master/LICENSE"><img src="https://img.shields.io/github/license/stockalgo/bandl.svg" alt="License"></a>
</p>

---

```python
from bandl import Bandl, Interval

df = Bandl().crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1)   # no API key needed
```

One client, one API. Switch markets by changing the symbol — not your code.

- 🟢 **Zero-config crypto** — Binance & CoinDCX public data, no keys.
- 🇮🇳 **Indian equities & indices** — `RELIANCE`, `NIFTY 50`, `BANKNIFTY` via Zerodha.
- 📈 **Options, incl. expired contracts** — NSE/BSE F&O + MCX commodities via Dhan.
- 🐼 **pandas or typed models** — `get_ohlcv_dataframe(...)` or `get_ohlcv(...) -> list[OHLCV]`.
- ⏱️ **Normalized everywhere** — UTC timestamps, `Decimal` prices, one `Interval` enum.
- 🤖 **Agent-ready** — a dedicated [AGENTS.md](AGENTS.md) reference for LLM tools.

<p align="center">
  <a href="https://bandl.io" target="_blank">
    <img src="https://raw.githubusercontent.com/stockalgo/bandl/master/img/demo.gif" alt="bandl demo" width="760">
  </a>
</p>

---

## Install

```bash
pip install bandl
```

Python **3.10+**. Dev setup: `pip install -e ".[dev]"` ([CONTRIBUTING.md](CONTRIBUTING.md)).

---

## 60-second start

No API key required — crypto works out of the box:

```python
from bandl import Bandl, Interval

client = Bandl()

df = client.crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1)
print(df.tail())
#            timestamp     open     high      low    close       volume
#  2025-01-10 00:00:00  94000.1  95200.0  92800.5  94850.2   12930.4451
```

Want a window? Pass `start` / `end` (UTC). Want raw bars instead of pandas? Call
`get_ohlcv(...)` — same arguments, returns `list[OHLCV]`.

```python
from datetime import datetime, timedelta, timezone

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
bars = client.crypto.get_ohlcv("ETHUSDT", Interval.H1, start, end)
print(bars[-1].close, bars[-1].source)
```

---

## One API, every market

| Facet | Provider | Auth | Example symbols |
|-------|----------|------|-----------------|
| `client.crypto` | `binance` | None | `BTC/USDT`, `ETHUSDT` |
| `client.crypto` | `coindcx` | None | `BTCUSDT`, `ETHUSDT` |
| `client.equity` | `zerodha` | Kite key + token | `RELIANCE`, `NIFTY 50`, `BANKNIFTY` |
| `client.derivatives` | `dhan` | Dhan id + JWT | `GOLDM26JUN145000CE`, `NIFTY26JAN24000PE` |

Every facet exposes the **same two calls** — `get_ohlcv(...)` and
`get_ohlcv_dataframe(...)`. Pick a provider with `source="..."`, or rely on each
facet's default.

---

## Recipes

### Indian equities & indices (Zerodha)

Add your [Kite Connect](https://kite.trade/docs/connect/v3/) credentials once; the rest
is identical to crypto. Symbol aliases (`NIFTY 50` → `NIFTY50`) are handled for you.

```python
from bandl import Bandl, BandlConfig, Interval, ProviderSettings

client = Bandl(BandlConfig(providers={
    "zerodha": ProviderSettings(api_key="kite_api_key", access_token="daily_token"),
}))

reliance = client.equity.get_ohlcv_dataframe("RELIANCE", Interval.D1, source="zerodha")
nifty    = client.equity.get_ohlcv_dataframe("NIFTY 50", Interval.D1, source="zerodha")
```

### Options & derivatives (Dhan)

`client.derivatives` serves option OHLCV across NSE/BSE F&O and MCX commodities — with
`open_interest` on every bar. Give it a **symbol string** (auto-resolved against Dhan's
scrip master) or a structured **`OptionContract`**.

```python
from datetime import date, datetime, timezone
from decimal import Decimal
from bandl import Bandl, BandlConfig, Interval, ProviderSettings
from bandl.models.market import OptionContract, OptionType

client = Bandl(BandlConfig(providers={
    "dhan": ProviderSettings(api_key="dhan_client_id", access_token="dhan_jwt"),
}))

# 1) Symbol string — easiest
df = client.derivatives.get_ohlcv_dataframe(
    "GOLDM26JUL145000CE", Interval.M5, source="dhan", exchange="MCX",
)

# 2) Structured contract — explicit & unambiguous
contract = OptionContract(
    underlying="GOLDM", expiry=date(2026, 7, 29),
    strike=Decimal("145000"), option_type=OptionType.CALL, exchange="MCX",
)
bars = client.derivatives.get_ohlcv(contract, Interval.M1, source="dhan")

# What expiries exist for an underlying?
expiries = client.derivatives.list_expiries("GOLDM", source="dhan", exchange="MCX")
```

**Need expired contracts?** Most APIs drop them. bandl still fetches their minute
candles — pass the native `instrument_id` once (look it up via Dhan, or the bundled
`examples/dhan_expired_probe.py`):

```python
bars = client.derivatives.get_ohlcv(
    "GOLDM26JUN143500CE", Interval.M1,
    datetime(2026, 6, 26, tzinfo=timezone.utc),
    datetime(2026, 6, 27, tzinfo=timezone.utc),
    source="dhan", exchange="MCX", instrument_id="570800",
)
```

### Typed bars instead of pandas

```python
from bandl import OHLCV

bars: list[OHLCV] = client.crypto.get_ohlcv("BTCUSDT", Interval.H1)
bars[-1].close      # Decimal — no float rounding
bars[-1].timestamp  # tz-aware UTC datetime
```

### List tradable symbols

```python
client.list_symbols(source="binance", search="BTC", limit=20)
client.list_symbols(source="zerodha", exchange="NSE",
                    instrument_types=("EQ",), search="RELI", limit=10)
```

### Intervals & timezones

One enum maps to every provider's native interval. Timestamps come back **UTC**.

```python
from bandl import Interval
Interval.M1, Interval.M5, Interval.H1, Interval.D1   # 1m / 5m / 1h / 1d

df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata")  # → IST for display
```

---

## Configuration

```python
from bandl import BandlConfig, ProviderSettings

config = BandlConfig(
    providers={
        "zerodha": ProviderSettings(api_key="...", access_token="..."),
        "dhan":    ProviderSettings(api_key="client_id", access_token="jwt"),
    },
    timeout_seconds=30,
    default_crypto_provider="binance",       # client.crypto default
    default_equity_provider="zerodha",       # client.equity default
    default_derivatives_provider="dhan",     # client.derivatives default
)
```

| Provider | `api_key` | `access_token` | Notes |
|----------|-----------|----------------|-------|
| `zerodha` | Kite API key | daily token | Tokens **expire daily** — regenerate after login. 403 ⇒ expired/wrong token or no historical-API access. |
| `dhan` | client id | JWT | JWT generated in the Dhan web/app. Expired contracts leave the scrip master — fetch by `instrument_id`. |
| `binance` / `coindcx` | — | — | Public OHLCV needs no keys. |

> **Binance HTTP 451?** Binance blocks some regions/cloud IPs (US, Colab). Use
> `source="coindcx"` — same symbols, no key — or set
> `default_crypto_provider="coindcx"`.
>
> **CoinDCX empty `DataFrame`?** Its public feed can lag by months. A `start`/`end`
> entirely after the feed raises `DataNotAvailableError` with the available span;
> pick an overlapping window.

---

## More

<details>
<summary><strong>Account history</strong> — orders, fills & PnL via <code>client.account</code></summary>

```python
fills  = client.account.get_fills(start, end, source="coindcx")
pnl    = client.account.get_pnl(start, end, source="zerodha", prefer="auto")
bundle = client.account.export_analysis_bundle(start, end)
```

Full guide: [docs/ACCOUNT_HISTORY.md](docs/ACCOUNT_HISTORY.md).
</details>

<details>
<summary><strong>Futures 24h leaders</strong> — rolling ticker stats</summary>

```python
from bandl import AssetType

tickers = client.crypto.get_24hr_tickers(source="coindcx", asset_type=AssetType.CRYPTO_PERP)
```
</details>

<details>
<summary><strong>Runnable demos</strong></summary>

```bash
cp examples/.env.example .env      # add ZERODHA_* / DHAN_* to test authed providers
python examples/main.py
python examples/dhan_options.py
python examples/futures_24hr_leaders.py --source coindcx
```
</details>

---

## For AI agents

**[AGENTS.md](AGENTS.md)** is a purpose-built reference (provider matrix, recipes,
errors) for LLM coding tools. It is **not** shipped in the PyPI wheel — point your
agent at the GitHub link:

`https://github.com/stockalgo/bandl/blob/master/AGENTS.md`

Pin a tag (e.g. `.../blob/v0.4.0/AGENTS.md`) for a fixed version. See
[agents/README.md](agents/README.md).

---

## Docs & development

- [docs/BANDL.md](docs/BANDL.md) — layout & design notes
- [docs/ACCOUNT_HISTORY.md](docs/ACCOUNT_HISTORY.md) — account facet
- [CONTRIBUTING.md](CONTRIBUTING.md) — tests, Ruff, pull requests
- [SECURITY.md](SECURITY.md) — reporting vulnerabilities

```bash
pytest tests/bandl/
ruff check lib/bandl tests/bandl
```

---

## Roadmap

- Live streams / WebSockets
- More brokers & deeper commodity history
- Richer `SymbolInfo` and fundamentals

---

## Contributing

PRs welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) first.

## License

[MIT](LICENSE)
