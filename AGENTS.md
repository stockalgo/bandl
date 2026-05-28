# bandl — agent reference

> **Audience:** AI coding agents. Read this file only; do not scan `lib/` unless something is missing here.
> **Humans:** use [README.md](README.md).

### How agents get this doc (not via PyPI)

`AGENTS.md` lives in the **Git repository only** — it is **not** installed by `pip install bandl`. Users point their agent at a stable GitHub URL; the agent reads the doc, then uses the installed package.

| What | Action |
|------|--------|
| **Library** | `pip install bandl` (PyPI) or `pip install git+https://github.com/stockalgo/bandl.git` |
| **Agent instructions** | Attach or paste one link below (pin a tag/branch for reproducibility) |

**Stable links (replace `master` with a tag, e.g. `v0.3.0`, when you need a fixed version):**

- Browse: `https://github.com/stockalgo/bandl/blob/master/AGENTS.md`
- Raw (fetch): `https://raw.githubusercontent.com/stockalgo/bandl/master/AGENTS.md`

**Example user prompt to an agent:**

> Use bandl for this task. Follow the API and recipes in:  
> https://github.com/stockalgo/bandl/blob/master/AGENTS.md  
> Install with `pip install bandl` if needed.

In Cursor / similar IDEs you can also `@AGENTS.md` from a cloned repo, or add the raw URL to project rules.

---

## When to use bandl

Use **bandl** when you need **historical OHLCV** (crypto spot, NSE equities/indices) or **broker account history** (orders, fills, ledger, PnL) from a single Python client with normalized models and pandas output. bandl is **sync HTTP only** (no WebSockets, no async client).

**Supported domains:**

| Domain | bandl surface | Providers |
|--------|---------------|-----------|
| Crypto spot OHLCV | `client.crypto.*` | `binance` (default), `coindcx` |
| Indian equity/index OHLCV | `client.equity.*` | `zerodha` (auth) |
| Account orders/fills/ledger/PnL | `client.account.*` | `coindcx`, `zerodha` (auth) |
| Symbol discovery | `client.list_symbols(source=...)` | per provider |

**Not in bandl:** live WebSockets, US equities, NSE options bhavcopy, calendar-month Zerodha trade history via API. CoinDCX futures candles: no M3/H2/H6; Binance = USDT-M perpetuals only.

---

## Install & bootstrap

```bash
pip install bandl
```

- Python **3.10+**
- Default install includes: `httpx`, `pydantic`, `pandas`, `requests`, …

```python
from datetime import datetime, timedelta, timezone

from bandl import Bandl, BandlConfig, Interval, ProviderSettings

client = Bandl()
end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
```

If `start` / `end` omitted on OHLCV or account calls → defaults to **last 30 days** ending now (UTC).

---

## Client shape

```
Bandl(config?: BandlConfig)
├── .crypto          → _Facet (default_source = config.default_crypto_provider, usually "binance")
├── .equity          → _Facet (default_source = config.default_equity_provider, usually "zerodha")
├── .account         → AccountFacet
├── .get_ohlcv(...)           # low-level; prefer facets
├── .get_ohlcv_dataframe(...)
├── .list_symbols(source=..., search=..., limit=..., asset_type=...)
├── .get_24hr_tickers(source=..., asset_type=...)  # Binance / CoinDCX USDT-M futures
├── .list_providers()         # ["binance", "coindcx", "zerodha"]
└── .configure_provider(name, ProviderSettings)
```

**Facet shortcuts** (same signatures; `source` defaults to facet provider):

- `client.crypto.get_ohlcv`, `get_ohlcv_dataframe`, `list_symbols`, `get_24hr_tickers`
- `client.equity.get_ohlcv`, `get_ohlcv_dataframe`, `list_symbols`

---

## Decision tree: pick provider

```
USER WANTS MARKET CANDLES?
├─ Crypto (spot)
│  ├─ Try source omitted or "binance" → client.crypto.get_ohlcv_dataframe(...)
│  └─ On GeoRestrictionError (HTTP 451) → source="coindcx"
├─ Indian stock or index (RELIANCE, NIFTY)
│  └─ source="zerodha" + ZERODHA_API_KEY + ZERODHA_ACCESS_TOKEN
└─ Crypto futures/perp OHLCV?
   └─ `asset_type=AssetType.CRYPTO_PERP` (or `CRYPTO_FUTURE`) on `get_ohlcv` / `list_symbols`
      - binance → `fapi.binance.com` (USDT-M perpetuals)
      - coindcx → `market_data/candlesticks?pcode=f` + `active_instruments`

USER WANTS ACCOUNT DATA (orders/fills/PnL)?
├─ CoinDCX (spot + USDT futures account)
│  └─ source="coindcx" + COINDCX_API_KEY + COINDCX_API_SECRET
│      → client.account.capabilities("coindcx") first
└─ Zerodha (session orders/trades; holdings/positions snapshots)
   └─ source="zerodha" + Kite api_key + access_token
       → expect session-only fills; NOT full month history via API
```

---

## Provider capability matrix

| provider | asset_types | market methods | account methods | auth | intervals (OHLCV) | symbol format | known limits |
|----------|-------------|----------------|-----------------|------|-------------------|---------------|--------------|
| **binance** | spot + **USDT-M perp** | `get_ohlcv`, `list_symbols`, `get_24hr_tickers` (futures) | — | none (public) | spot & futures: M1–MO1 (same enum) | `BTCUSDT` | Spot: `api.binance.com`; futures: `fapi.binance.com`; 24h %: `/fapi/v1/ticker/24hr`. Geo **451** → coindcx |
| **coindcx** | spot + **futures perp** | `get_ohlcv`, `list_symbols`, `get_24hr_tickers` (futures) | orders, fills, ledger, pnl | OHLCV public; account: keys | spot: all intervals; futures candles: M1,M5,M15,M30,H1,H4,H8,D1,D3,W1,MO1 (**no M3/H2/H6**) | spot `B-BTC_USDT`; futures same pair + `pcode=f` | Spot candles lag; futures `from`/`to` in **seconds**; 24h %: `current_prices/futures/rt` (active USDT instruments only) |
| **zerodha** | NSE/BSE equity, indices | `get_ohlcv`, `list_symbols` | orders, fills, ledger, pnl | api_key + access_token | M1–M30,H1; H2/H4→60m; D1/W1/MO1→day | `RELIANCE`, `NIFTY50`; index API name `NIFTY 50` | Token expires daily; orders/trades = **current session only**; holdings PnL ≈ lifetime snapshot |

### Account capability flags (call `client.account.capabilities(source)`)

| provider | segments | orders | fills | ledger | pnl_broker | pnl_computed |
|----------|----------|--------|-------|--------|------------|--------------|
| coindcx | `spot_crypto`, `crypto_fno` | yes | yes (paginated history) | yes (futures txns) | yes (futures txn amounts) | yes (FIFO from fills) |
| zerodha | `equity_cash`, `equity_fno`, `commodity` | yes (session) | yes (session) | yes (contract notes, session orders) | yes (holdings/positions snapshot) | yes (FIFO from session fills) |
| binance | — | — | — | — | — | — |

**Account `segment` filter** (kwarg on account methods): `spot_crypto`, `crypto_fno`, `equity_cash`, `equity_fno`, `commodity`.

---

## Symbol conventions

| Input examples | Canonical | Provider notes |
|----------------|-------------|----------------|
| `BTC/USDT`, `BTC-USDT`, `btcusdt` | `BTCUSDT` | CoinDCX → `B-BTC_USDT` |
| `ETH`, `BITCOIN` (alias) | `ETHUSDT`, `BTCUSDT` | see `core/aliases.py` |
| `RELIANCE`, `RELIANCE.NS` | `RELIANCE` | Zerodha tradingsymbol `RELIANCE` on NSE |
| `NIFTY 50`, `NIFTY`, `^NSEI` | `NIFTY50` | Zerodha tradingsymbol **`NIFTY 50`** |
| `NIFTY BANK`, `BANKNIFTY` | `BANKNIFTY` | Zerodha tradingsymbol **`NIFTY BANK`** |

**Heuristics** (`resolve_symbol`, optional `asset_type=`):

- `/` in symbol → crypto spot
- Suffix `.NS`, `:NSE` → Indian equity
- Else: crypto if `BASE+QUOTE` tail matches (USDT, INR, …); else equity/index

**Discovery:**

```python
syms = client.list_symbols(source="binance", search="BTC", limit=10)
# SymbolInfo: canonical, base, quote, asset_type, provider_symbol
```

Zerodha: pass `exchange="NSE"` via kwargs: `client.list_symbols(source="zerodha", exchange="NSE", search="REL", limit=20)`.

---

## Intervals

`Interval` enum (`bandl.models.market.types` or `from bandl import Interval`):

| Enum | Value |
|------|-------|
| M1 | `1m` |
| M3 | `3m` |
| M5 | `5m` |
| M15 | `15m` |
| M30 | `30m` |
| H1 | `1h` |
| H2 | `2h` |
| H4 | `4h` |
| H6 | `6h` |
| H8 | `8h` |
| D1 | `1d` |
| D3 | `3d` |
| W1 | `1w` |
| MO1 | `1M` |

**Gaps:**

| provider | unsupported | mapped (not native) |
|----------|-------------|---------------------|
| coindcx | M3 | — |
| zerodha | H6, H8, D3 | H2, H4 → `60minute`; W1, MO1 → `day` |
| binance | — | all listed supported |

Pass `Interval.H1` or string `"1h"`.

---

## API reference (agent format)

### METHOD: `client.crypto.get_ohlcv` / `client.equity.get_ohlcv` / `client.get_ohlcv`

**USE WHEN:** user wants list of OHLCV bars (typed models).

**PARAMS:** `symbol`, `interval=Interval.D1`, `start=None`, `end=None`, `source=None`, `asset_type=None` (`CRYPTO_SPOT` default; use `CRYPTO_PERP` for futures), `**kwargs` (Zerodha: `exchange`, …; CoinDCX futures list: `margin_currencies=["USDT"]`)

**RETURNS:** `list[OHLCV]` — fields: `timestamp` (UTC), `open`, `high`, `low`, `close`, `volume`, `quote_volume?`, `trades?`, `symbol`, `interval`, `source`

**AUTH:** none for binance/coindcx public; zerodha requires credentials in config.

**EXAMPLE:**

```python
from datetime import datetime, timedelta, timezone
from bandl import Bandl, Interval

client = Bandl()
end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
bars = client.crypto.get_ohlcv("BTCUSDT", Interval.H1, start, end)
```

**ERRORS:** `GeoRestrictionError` → `source="coindcx"`; `DataNotAvailableError` → narrow date range (CoinDCX lag); `AuthenticationError` → set Zerodha tokens; `SymbolNotFoundError` → fix symbol or pass `tradingsymbol=` / `instrument_token=`

---

### METHOD: `client.crypto.get_ohlcv_dataframe` / `client.equity.get_ohlcv_dataframe` / `client.get_ohlcv_dataframe`

**USE WHEN:** user wants pandas OHLCV (most common).

**PARAMS:** same as `get_ohlcv`

**RETURNS:** `pandas.DataFrame` — columns from `OHLCV.model_dump()` (`timestamp`, `open`, `high`, `low`, `close`, `volume`, …)

**AUTH:** same as `get_ohlcv`

**EXAMPLE:**

```python
df = client.crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1, start, end)
```

**ERRORS:** same as `get_ohlcv`; empty DataFrame possible if provider returns no in-range candles (CoinDCX lag) — may raise `DataNotAvailableError` when candles exist outside window

---

### METHOD: `client.list_symbols`

**USE WHEN:** screening, pair discovery, building symbol loops.

**PARAMS:** `source` (**required**), `search=None`, `limit=None`, `asset_type=None` (`CRYPTO_PERP` for futures universe), `**kwargs` (zerodha: `exchange="NSE"`; coindcx futures: `margin_currencies`)

**RETURNS:** `list[SymbolInfo]`

**AUTH:** none for binance/coindcx; zerodha public instruments CSV (no token for list in adapter — historical still needs token)

**EXAMPLE:**

```python
pairs = client.list_symbols(source="binance", search="BTC", limit=10)
```

**ERRORS:** `ConfigurationError` unknown provider; `ProviderError` upstream failures

---

### METHOD: `client.list_providers`

**USE WHEN:** introspect registered providers.

**RETURNS:** `["binance", "coindcx", "zerodha"]`

**AUTH:** none

---

### METHOD: `client.configure_provider`

**USE WHEN:** set or rotate API keys after `Bandl()` construction.

**PARAMS:** `name: str`, `settings: ProviderSettings`

**RETURNS:** none (re-registers provider instance)

**EXAMPLE:**

```python
from bandl import Bandl, ProviderSettings

client = Bandl()
client.configure_provider("zerodha", ProviderSettings(api_key="k", access_token="t"))
```

---

### METHOD: `client.account.capabilities`

**USE WHEN:** before account calls; check fills/PnL/segment support.

**PARAMS:** `source: str | None` — if `None`, returns `dict[str, AccountCapabilities]`

**RETURNS:** `AccountCapabilities` with `.supports("fills")`, `.supports("pnl_broker")`, etc.

**AUTH:** none for call itself; downstream methods need provider auth.

**EXAMPLE:**

```python
caps = client.account.capabilities("coindcx")
assert caps.supports("fills")
```

---

### METHOD: `client.account.supports`

**USE WHEN:** quick boolean check for one capability on one source.

**PARAMS:** `source: str`, `capability: str` — e.g. `"fills"`, `"ledger"`, `"pnl_broker"`

**RETURNS:** `bool`

---

### METHOD: `client.account.get_orders` / `get_orders_dataframe`

**USE WHEN:** user wants order history.

**PARAMS:** `start`, `end`, `source=None`, `symbol=`, `segment=`, `side=`, `status=`, `order_id=`, `limit=`

**RETURNS:** `list[AccountOrder]` or DataFrame

**AUTH:** coindcx / zerodha credentials

**ERRORS:** `UnsupportedCapabilityError` if provider lacks orders; Zerodha → session orders only

---

### METHOD: `client.account.get_fills` / `get_fills_dataframe`

**USE WHEN:** executions / trade history.

**PARAMS:** same as orders; use `segment="crypto_fno"` for CoinDCX futures fills.

**RETURNS:** `list[AccountFill]`

**AUTH:** coindcx / zerodha credentials

**EXAMPLE:**

```python
fills = client.account.get_fills(start, end, source="coindcx", segment="crypto_fno")
```

---

### METHOD: `client.account.get_ledger_entries` / `get_ledger_entries_dataframe`

**USE WHEN:** fees, funding, wallet-style movements.

**PARAMS:** same date/source filters.

**AUTH:** coindcx (futures transactions) / zerodha (contract notes tied to session orders)

---

### METHOD: `client.account.get_pnl` / `get_pnl_dataframe`

**USE WHEN:** PnL by symbol/day/portfolio.

**PARAMS:** `start`, `end`, `source=`, `granularity=` (`trade`|`symbol`|`day`|`portfolio`), `prefer=` (`auto`|`broker`|`computed`|`hybrid`), `reconcile=False`, plus filter kwargs.

**RETURNS:** `list[PnLRecord]`

**AUTH:** coindcx / zerodha

**EXAMPLE:**

```python
pnl = client.account.get_pnl(start, end, source="coindcx", segment="crypto_fno")
```

**NOTES:** CoinDCX futures PnL often from broker transactions (`pnl_broker`); Zerodha holdings PnL is **not** reliably filtered to arbitrary past months.

---

### METHOD: `client.account.export_analysis_bundle`

**USE WHEN:** agent needs one JSON-serializable dump for analysis.

**PARAMS:** `start`, `end`, `sources: list[str] | None`, `include_native=False`, filter kwargs

**RETURNS:** `dict` with keys `manifest`, `capabilities`, `orders`, `fills`, `ledger`, `pnl` (lists of dicts; strips `provider_native` unless `include_native=True`)

**AUTH:** per included sources

---

## Task recipes (intent → code)

| User says | Do this | Provider | Auth? |
|-----------|---------|----------|-------|
| Daily chart for BTC/USDT | `client.crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1, start, end)` | binance | No |
| Screen top 10 BTC pairs on 4h | `list_symbols(source="binance", search="BTC", limit=10)` then loop `get_ohlcv_dataframe(..., Interval.H4, ...)` | binance | No |
| Crypto futures daily/weekly charts | `get_ohlcv_dataframe(..., asset_type=AssetType.CRYPTO_PERP)` | binance or coindcx | No |
| My CoinDCX futures PnL last month | `capabilities("coindcx")` then `get_pnl(start, end, source="coindcx", segment="crypto_fno")` | coindcx | Yes |
| NIFTY 50 last 6 months | `get_ohlcv_dataframe("NIFTY 50", Interval.D1, start, end, source="zerodha")` | zerodha | Yes |
| RELIANCE daily bars | `client.equity.get_ohlcv_dataframe("RELIANCE", Interval.D1, start, end)` | zerodha | Yes |
| Binance blocked in region | retry with `source="coindcx"` | coindcx | No |
| CoinDCX empty candles | earlier `end` or `DataNotAvailableError` message dates | coindcx | No |
| CoinDCX futures fills last week | `get_fills(..., source="coindcx", segment="crypto_fno")` | coindcx | Yes |
| Compare brokers in one JSON | `export_analysis_bundle(start, end, sources=["coindcx","zerodha"])` | both | Yes |
| IST display | convert UTC timestamps (see below) | — | — |

### Recipe: single symbol daily crypto

**User says:** "BTC daily candles for 30 days"

```python
from datetime import datetime, timedelta, timezone
from bandl import Bandl, Interval

client = Bandl()
end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end)
```

Provider: **binance** | Auth: **no**

---

### Recipe: futures multi-timeframe screen

**User says:** "Screen BTC USDT perps on 1D and 1W from Binance"

```python
from bandl import Bandl, Interval
from bandl.models.market.types import AssetType

client = Bandl()
syms = client.list_symbols(
    source="binance",
    search="BTC",
    limit=5,
    asset_type=AssetType.CRYPTO_PERP,
)
end = datetime.now(timezone.utc)
start = end - timedelta(days=90)
for info in syms:
    for interval in (Interval.D1, Interval.W1):
        df = client.crypto.get_ohlcv_dataframe(
            info.canonical,
            interval,
            start,
            end,
            source="binance",
            asset_type=AssetType.CRYPTO_PERP,
        )
```

Provider: **binance** `fapi` | Auth: **no**

---

### Recipe: multi-symbol crypto screen

**User says:** "Screen BTC pairs on 4h"

```python
from datetime import datetime, timedelta, timezone
from bandl import Bandl, Interval

client = Bandl()
end = datetime.now(timezone.utc)
start = end - timedelta(days=14)
symbols = client.list_symbols(source="binance", search="BTC", limit=10)
frames = {}
for info in symbols:
    sym = info.canonical
    frames[sym] = client.crypto.get_ohlcv_dataframe(sym, Interval.H4, start, end)
```

Provider: **binance** | Auth: **no**

---

### Recipe: custom interval 15m

**User says:** "ETH 15-minute bars"

```python
df = client.crypto.get_ohlcv_dataframe("ETHUSDT", Interval.M15, start, end)
```

Provider: **binance** or **coindcx** | Auth: **no**

---

### Recipe: Indian equity + index

**User says:** "RELIANCE and NIFTY 50 daily"

```python
from bandl import Bandl, BandlConfig, Interval, ProviderSettings

cfg = BandlConfig(
    providers={
        "zerodha": ProviderSettings(
            api_key="YOUR_KEY",
            access_token="YOUR_TOKEN",
        ),
    },
)
client = Bandl(cfg)
for sym in ("RELIANCE", "NIFTY 50"):
    df = client.equity.get_ohlcv_dataframe(sym, Interval.D1, start, end)
```

Provider: **zerodha** | Auth: **yes** (daily token refresh)

---

### Recipe: account fills date range

**User says:** "CoinDCX fills last 7 days"

```python
fills = client.account.get_fills(start, end, source="coindcx")
df = client.account.get_fills_dataframe(start, end, source="coindcx")
```

Provider: **coindcx** | Auth: **yes**

---

### Recipe: Binance HTTP 451 geo block

**User says:** "Binance doesn't work on this server"

```python
from bandl.exceptions import GeoRestrictionError

try:
    df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end)
except GeoRestrictionError:
    df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end, source="coindcx")
```

Provider: **coindcx** fallback | Auth: **no** for OHLCV

---

### Recipe: CoinDCX empty or stale feed

**User says:** "CoinDCX returned no rows"

```python
from bandl.exceptions import DataNotAvailableError

try:
    df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end, source="coindcx")
except DataNotAvailableError:
    # Message includes available candle span — set end to latest available date
    raise
if df.empty:
    end2 = end - timedelta(days=3)  # shift end earlier until data appears
    df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end2, source="coindcx")
```

Provider: **coindcx** | Auth: **no**

---

### Recipe: timezone UTC → IST

**User says:** "show times in IST"

```python
import pandas as pd

df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end)
df = df.copy()
df["timestamp_ist"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
```

All bandl timestamps are **UTC**.

---

### Recipe: crypto futures PnL (not charts)

**User says:** "CoinDCX USDT futures PnL last month"

```python
caps = client.account.capabilities("coindcx")
if not caps.supports("pnl_broker"):
    raise RuntimeError("coindcx broker PnL not available")
pnl = client.account.get_pnl(
    start,
    end,
    source="coindcx",
    segment="crypto_fno",
    prefer="auto",
)
```

Provider: **coindcx** | Auth: **yes** | **Not OHLCV**

---

### Recipe: capabilities guard before account call

```python
from bandl.exceptions import UnsupportedCapabilityError

src = "zerodha"
if not client.account.supports(src, "fills"):
    raise UnsupportedCapabilityError(src, "fills")
fills = client.account.get_fills(start, end, source=src)
```

---

### Recipe: configure from environment

```python
import os
from bandl import Bandl, BandlConfig, ProviderSettings

cfg = BandlConfig(
    providers={
        "zerodha": ProviderSettings(
            api_key=os.environ["ZERODHA_API_KEY"],
            access_token=os.environ["ZERODHA_ACCESS_TOKEN"],
        ),
        "coindcx": ProviderSettings(
            api_key=os.environ["COINDCX_API_KEY"],
            api_secret=os.environ["COINDCX_API_SECRET"],
        ),
    },
)
client = Bandl(cfg)
```

---

## Configuration & env vars

### `BandlConfig` fields

| field | default | meaning |
|-------|---------|---------|
| `timeout_seconds` | 30 | HTTP timeout |
| `max_http_retries` | 3 | retry 5xx / network |
| `user_agent` | `bandl/0.3 (...)` | HTTP header |
| `default_crypto_provider` | `binance` | `client.crypto` default |
| `default_equity_provider` | `zerodha` | `client.equity` default |
| `providers` | `{}` | map of provider id → `ProviderSettings` |

### `ProviderSettings`

| field | repr | notes |
|-------|------|-------|
| `api_key` | hidden | Zerodha, CoinDCX, Binance (optional) |
| `api_secret` | hidden | CoinDCX, Binance |
| `access_token` | hidden | Zerodha |
| `base_url` | shown | optional override |

`extra="forbid"` — unknown keys error.

### `.env` keys (`examples/.env.example`)

| variable | used for |
|----------|----------|
| `ZERODHA_API_KEY` | Kite Connect |
| `ZERODHA_ACCESS_TOKEN` | expires daily |
| `BINANCE_API_KEY` | optional (public OHLCV needs none) |
| `BINANCE_API_SECRET` | optional |
| `COINDCX_API_KEY` | account APIs |
| `COINDCX_API_SECRET` | account APIs |
| `BANDL_HTTP_TIMEOUT_SECONDS` | reserved |
| `BANDL_MAX_HTTP_RETRIES` | reserved |
| `BANDL_DEFAULT_CRYPTO_PROVIDER` | reserved |
| `BANDL_DEFAULT_EQUITY_PROVIDER` | reserved |

bandl does **not** auto-load `.env`; agents must read env and pass `ProviderSettings` (see `examples/main.py` pattern).

---

## Exception playbook

| exception | meaning | agent action |
|-----------|---------|--------------|
| `AuthenticationError` | missing/invalid credentials (401/403) | set `ProviderSettings`; refresh Zerodha token |
| `GeoRestrictionError` | Binance HTTP 451 | `source="coindcx"` for crypto OHLCV |
| `DataNotAvailableError` | range outside available data (CoinDCX lag) | narrow range; read error message for available span |
| `SymbolNotFoundError` | bad symbol for provider | fix symbol; use `list_symbols`; Zerodha: `tradingsymbol=` / `instrument_token=` |
| `UnsupportedCapabilityError` | account feature not on provider | call `capabilities()`; pick another source or method |
| `RateLimitError` | subclass of `ProviderError` | rare; HTTP 429 → `ProviderError(..., retryable=True)` — backoff and retry |
| `ProviderError` | upstream failure | read `[provider]` prefix; 4xx not retried |
| `ConfigurationError` | bad provider name / no account providers | use `list_providers()` |
| `BandlError` | base / invalid date range | ensure `start < end` UTC |

---

## Not supported / use alternatives

| request | bandl status | alternative |
|---------|--------------|-------------|
| CoinDCX futures **M3 / H2 / H6** candles | **Not supported** on candlesticks API | Use M5, H1, H4, H8, D1, W1, etc. |
| Live WebSockets / streaming | **Not implemented** | poll `get_ohlcv` |
| Async `await` client | **Not implemented** | sync calls only |
| Zerodha **historical** orders/fills for past months | **Not available** (Kite session APIs) | broker statements; holdings snapshot only |
| Binance account/futures in bandl | **Not implemented** | CoinDCX account or native Binance SDK |
| US equities | **Not implemented** | — |
| NSE options chain / bhavcopy | **Not implemented** | — |
| Calendar-month PnL guarantee (Zerodha) | **Unreliable** | use CoinDCX for crypto history; external reports for equity |

Account history details: [docs/ACCOUNT_HISTORY.md](docs/ACCOUNT_HISTORY.md) (human-oriented; facts mirrored above).

---

## Verification

```bash
pip install -e ".[dev]"
pytest tests/bandl/                    # unit tests (default; no network)
pytest tests/bandl/ -m integration    # optional live API smoke
ruff check lib/bandl/account lib/bandl/core lib/bandl/models lib/bandl/providers tests/bandl
python examples/main.py               # needs .env for Zerodha demo
python examples/account_may2026.py    # account demo; needs keys
```

Package version: see `pyproject.toml` `project.version`.

---

## Quick capability answers (FAQ)

**Q: Crypto futures daily charts?**  
A: `client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end, asset_type=AssetType.CRYPTO_PERP, source="binance"|"coindcx")`. List universe: `list_symbols(source=..., asset_type=AssetType.CRYPTO_PERP)`.

**Q: Default provider for `client.crypto.get_ohlcv`?**  
A: `binance` unless `BandlConfig.default_crypto_provider` or `source=` override.

**Q: Multi-provider account merge?**  
A: `source=None` merges all account-capable providers with dedup keys; prefer explicit `source=` for deterministic agent behavior.
