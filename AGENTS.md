# bandl — agent reference

> **Audience:** AI coding agents. Read this file only; do not scan `lib/` unless something is missing here.
> **Humans:** use [README.md](README.md).

### How agents get this doc (not via PyPI)

`AGENTS.md` lives in the **Git repository only** — it is **not** installed by `pip install bandl`. Users point their agent at a stable GitHub URL; the agent reads the doc, then uses the installed package.

| What | Action |
|------|--------|
| **Library** | `pip install bandl` (PyPI) or `pip install git+https://github.com/stockalgo/bandl.git` |
| **Agent instructions** | Attach or paste one link below (pin a tag/branch for reproducibility) |

**Stable links (replace `master` with a tag, e.g. `v0.4.0`, when you need a fixed version):**

- Browse: `https://github.com/stockalgo/bandl/blob/master/AGENTS.md`
- Raw (fetch): `https://raw.githubusercontent.com/stockalgo/bandl/master/AGENTS.md`

**Example user prompt to an agent:**

> Use bandl for this task. Follow the API and recipes in:
> https://github.com/stockalgo/bandl/blob/master/AGENTS.md
> Install with `pip install bandl` if needed.

In Cursor / similar IDEs you can also `@AGENTS.md` from a cloned repo, or add the raw URL to project rules.

---

## When to use bandl

Use **bandl** for **historical OHLCV** and **live trading/portfolio** from one sync Python client with normalized models and pandas output:

- **Crypto spot/perp** (Binance, CoinDCX)
- **Indian equities & indices** (Zerodha)
- **Options** — NSE/BSE F&O and MCX commodities, **including expired contracts** (Dhan)
- **Broker account history** — orders, fills, ledger, PnL (CoinDCX, Zerodha)
- **Live trading & portfolio** — place/modify/cancel orders, live order state, positions, holdings, balances, margin (Zerodha, Dhan)

bandl is **sync HTTP only** — no WebSockets, no async client.

**Supported domains:**

| Domain | bandl surface | Providers |
|--------|---------------|-----------|
| Crypto spot/perp OHLCV | `client.crypto.*` | `binance` (default), `coindcx` |
| Indian equity/index OHLCV | `client.equity.*` | `zerodha` (auth) |
| Option OHLCV / chain / expiries | `client.derivatives.*` | `dhan` (auth) |
| Account orders/fills/ledger/PnL (history) | `client.account.*` | `coindcx`, `zerodha` (auth) |
| Live order write/read | `client.trade.*` | `zerodha`, `dhan` (auth) |
| Live positions/holdings/balances/margin | `client.portfolio.*` | `zerodha`, `dhan` (auth) |
| Symbol discovery | `client.list_symbols(source=...)` | per provider |

**Not in bandl:** live WebSockets, US equities, async client, crypto trading (binance/coindcx `client.trade`/`client.portfolio` not wired). CoinDCX futures candles: no M3/H2/H6. Binance = USDT-M perpetuals only. Dhan option OHLCV intervals: only 1, 5, 15, 60 min. Live trading covers **regular-variety orders only** — no AMO/CO/BO/iceberg/GTT/Forever/slicing/margin-preview/convert-position yet (see "Live trading — what's not yet wired").

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
├── .crypto          → _Facet           (default_source = config.default_crypto_provider, usually "binance")
├── .equity          → _Facet           (default_source = config.default_equity_provider, usually "zerodha")
├── .derivatives     → _DerivativesFacet (default_source = config.default_derivatives_provider, usually "dhan")
├── .account         → AccountFacet     (history: orders/fills/ledger/pnl — read-only, past data)
├── .trade           → TradeFacet       (live: place/modify/cancel + open orders/order/today's trades)
├── .portfolio       → PortfolioFacet   (live: positions/holdings/balances/margin)
├── .get_ohlcv(...)                  # low-level; prefer facets
├── .get_ohlcv_dataframe(...)
├── .get_option_ohlcv(...)           # low-level; prefer client.derivatives
├── .list_expiries(...)
├── .get_option_chain(...)
├── .list_symbols(source=..., search=..., limit=..., asset_type=...)
├── .get_24hr_tickers(source=..., asset_type=...)  # Binance / CoinDCX USDT-M futures
├── .list_providers()         # ["binance", "coindcx", "dhan", "zerodha"]
└── .configure_provider(name, ProviderSettings)
```

**Facet shortcuts** (same signatures; `source` defaults to facet provider):

- `client.crypto.get_ohlcv`, `get_ohlcv_dataframe`, `list_symbols`, `get_24hr_tickers`
- `client.equity.get_ohlcv`, `get_ohlcv_dataframe`, `list_symbols`
- `client.derivatives.get_ohlcv`, `get_ohlcv_dataframe`, `list_expiries`, `get_option_chain`

---

## Decision tree: pick provider

```
USER WANTS MARKET CANDLES?
├─ Crypto (spot)
│  ├─ Try source omitted or "binance" → client.crypto.get_ohlcv_dataframe(...)
│  └─ On GeoRestrictionError (HTTP 451) → source="coindcx"
├─ Crypto futures/perp OHLCV
│  └─ asset_type=AssetType.CRYPTO_PERP (or CRYPTO_FUTURE) on get_ohlcv / list_symbols
│     - binance → fapi.binance.com (USDT-M perpetuals)
│     - coindcx → market_data/candlesticks?pcode=f + active_instruments
├─ Indian stock or index (RELIANCE, NIFTY)
│  └─ source="zerodha" + ZERODHA_API_KEY + ZERODHA_ACCESS_TOKEN
└─ Option contract (GOLDM…CE, NIFTY…PE, F&O or MCX)
   └─ client.derivatives.get_ohlcv(symbol_or_contract, interval, ..., source="dhan", exchange="MCX"|"NFO")
      - DHAN_CLIENT_ID (→ api_key) + DHAN_ACCESS_TOKEN (JWT → access_token)
      - Active contract → symbol string auto-resolves via Dhan scrip master
      - EXPIRED contract dropped from scrip → pass instrument_id="<native securityId>"

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
| **binance** | spot + **USDT-M perp** | `get_ohlcv`, `list_symbols`, `get_24hr_tickers` (futures) | — | none (public) | spot & futures: M1–MO1 (same enum) | `BTCUSDT` | Spot: `api.binance.com`; futures: `fapi.binance.com`. Geo **451** → coindcx |
| **coindcx** | spot + **futures perp** | `get_ohlcv`, `list_symbols`, `get_24hr_tickers` (futures) | orders, fills, ledger, pnl | OHLCV public; account: keys | spot: all intervals; futures: M1,M5,M15,M30,H1,H4,H8,D1,D3,W1,MO1 (**no M3/H2/H6**) | spot `B-BTC_USDT`; futures pair + `pcode=f` | Spot candles lag; futures `from`/`to` in **seconds** |
| **zerodha** | NSE/BSE equity, indices | `get_ohlcv`, `list_symbols` | orders, fills, ledger, pnl | api_key + access_token | M1–M30,H1; H2/H4→60m; D1/W1/MO1→day | `RELIANCE`, `NIFTY50`; index API name `NIFTY 50` | Token expires daily; orders/trades = **session only** |
| **dhan** | **options** (NSE/BSE F&O, MCX commodity) | `get_option_ohlcv`, `list_expiries`, `get_option_chain` | — | api_key (client id) + access_token (JWT) | **M1, M5, M15, H1 only** (1/5/15/60 min) | `GOLDM26JUN145000CE`; or `OptionContract(...)` | Expired contracts leave scrip master → use `instrument_id`; intraday OHLCV omits OI |

### Account capability flags (call `client.account.capabilities(source)`)

| provider | segments | orders | fills | ledger | pnl_broker | pnl_computed |
|----------|----------|--------|-------|--------|------------|--------------|
| coindcx | `spot_crypto`, `crypto_fno` | yes | yes (paginated history) | yes (futures txns) | yes (futures txn amounts) | yes (FIFO from fills) |
| zerodha | `equity_cash`, `equity_fno`, `commodity` | yes (session) | yes (session) | yes (contract notes, session orders) | yes (holdings/positions snapshot) | yes (FIFO from session fills) |
| binance / dhan | — | — | — | — | — | — |

**Account `segment` filter** (kwarg on account methods): `spot_crypto`, `crypto_fno`, `equity_cash`, `equity_fno`, `commodity`.

---

## Live trading & portfolio (`client.trade` / `client.portfolio`)

**Providers:** `zerodha`, `dhan` only (binance/coindcx have no trading provider wired). `source=` is **required** on every call — no multi-provider merge (unlike `client.account`, placing/cancelling only ever targets one broker).

**Scope of this release — regular-variety orders only.** Not yet writable: AMO, cover orders (CO), bracket orders (BO), iceberg, GTT/Forever conditional orders, order slicing over the F&O freeze limit, margin preview, `convert_position`, and crypto leverage/margin-mode. These parse losslessly if they already exist in your account (e.g. an existing CO shows up fine in `get_open_orders`), they just can't be **created** via bandl yet.

### `client.trade`

```python
client.trade.place_order(order: OrderRequest, *, source: str) -> Order
client.trade.modify_order(order_id, *, source, price=None, trigger_price=None, quantity=None, validity=None) -> Order
client.trade.cancel_order(order_id, *, source: str) -> Order
client.trade.get_open_orders(*, source: str, symbol: str | None = None) -> list[Order]
client.trade.get_order(order_id, *, source: str) -> Order
client.trade.get_trades(*, source: str, symbol: str | None = None) -> list[AccountFill]   # today's fills
client.trade.capabilities(source: str) -> TradeCapabilities
client.trade.supports(source: str, capability: str) -> bool
# + get_open_orders_dataframe / get_trades_dataframe
```

`OrderRequest` (from `bandl.models.trading`): pick **one** instrument form —
`contract: OptionContract` (options, most robust) | `instrument_id: str` (native id, e.g. Dhan securityId; skips resolution) | `symbol: str` (+`exchange=`; resolved via scrip master / instruments CSV).
Other fields: `side: OrderSide`, `order_type: OrderType` (`MARKET|LIMIT|STOP_LIMIT|STOP` — `STOP_LIMIT`=SL/STOP_LOSS has a price+trigger, `STOP`=SL-M/STOP_LOSS_MARKET is trigger-only), `quantity`, `price`, `trigger_price` (required for STOP/STOP_LIMIT), `product: ProductType` (`DELIVERY|INTRADAY|NORMAL|MARGIN|MTF`), `validity: Validity` (`DAY|IOC`), `variety` (must be `Variety.REGULAR` — anything else raises `UnsupportedCapabilityError`), `client_order_id` (kite `tag`≤20 / dhan `correlationId`≤30).

```python
from decimal import Decimal
from bandl import Bandl, BandlConfig, ProviderSettings
from bandl.models.account.types import OrderSide, OrderType
from bandl.models.trading import OrderRequest, ProductType

client = Bandl(BandlConfig(providers={
    "zerodha": ProviderSettings(api_key="KEY", access_token="TOKEN"),
}))
order = client.trade.place_order(
    OrderRequest(
        symbol="RELIANCE", side=OrderSide.BUY, order_type=OrderType.LIMIT,
        quantity=Decimal(1), price=Decimal("2500"), product=ProductType.DELIVERY,
    ),
    source="zerodha",
)
open_orders = client.trade.get_open_orders(source="zerodha")
```

Dhan options: pass `contract=OptionContract(...)` or `instrument_id=` (+`exchange=`); Dhan order write additionally **requires static-IP whitelisting** on the account (place/modify/cancel fail with `AuthenticationError`/`ProviderError` otherwise — this is a Dhan account setting, not a bandl bug).

### `client.portfolio`

```python
client.portfolio.get_positions(*, source: str) -> list[Position]   # net book
client.portfolio.get_holdings(*, source: str) -> list[Holding]
client.portfolio.get_balances(*, source: str) -> list[Balance]
client.portfolio.get_margin(*, source: str) -> MarginInfo
client.portfolio.capabilities(source: str) -> PortfolioCapabilities
# + get_positions_dataframe / get_holdings_dataframe / get_balances_dataframe
```

```python
positions = client.portfolio.get_positions(source="zerodha")
margin = client.portfolio.get_margin(source="dhan")
```

**Capability matrix (this release):**

| capability | zerodha | dhan |
|---|---|---|
| place / modify / cancel (regular only) | ✅ | ✅ (static-IP whitelist required) |
| get_open_orders / get_order / get_trades | ✅ | ✅ |
| positions / holdings / balances / margin | ✅ | ✅ |
| Dhan `get_holdings` with zero holdings | — | returns `[]` (Dhan's HTTP 500 `DH-1111` "No holdings available" is treated as empty, not an error) |
| AMO / CO / BO / iceberg / GTT / Forever / slicing / margin preview / convert_position | ❌ not yet | ❌ not yet |
| leverage / margin-mode (crypto) | n/a | n/a |

**Errors:** reuses existing exceptions — `AuthenticationError` (missing/invalid creds, or Dhan static-IP not whitelisted), `UnsupportedCapabilityError` (source has no trading/portfolio provider, or `variety != REGULAR`), `ProviderError` (unsupported `product`/`validity`/`order_type` for that broker this release, missing `trigger_price` on a stop order, upstream failure).

---

## Symbol conventions

| Input examples | Canonical | Provider notes |
|----------------|-----------|----------------|
| `BTC/USDT`, `BTC-USDT`, `btcusdt` | `BTCUSDT` | CoinDCX → `B-BTC_USDT` |
| `ETH`, `BITCOIN` (alias) | `ETHUSDT`, `BTCUSDT` | see `core/aliases.py` |
| `RELIANCE`, `RELIANCE.NS` | `RELIANCE` | Zerodha tradingsymbol `RELIANCE` on NSE |
| `NIFTY 50`, `NIFTY`, `^NSEI` | `NIFTY50` | Zerodha tradingsymbol **`NIFTY 50`** |
| `NIFTY BANK`, `BANKNIFTY` | `BANKNIFTY` | Zerodha tradingsymbol **`NIFTY BANK`** |
| `GOLDM26JUN145000CE`, `MCX:GOLDM26JUN145000CE` | `GOLDM26JUN145000CE` | Dhan option: `{UNDERLYING}{YY}{MMM}{STRIKE}{CE\|PE}` (monthly) |

**Option symbols** (`client.derivatives`): pass the canonical string **or** a structured `OptionContract`. Strings encode only year+month; the exact expiry date is resolved from Dhan's scrip master. Always pass `exchange=` (`"MCX"`, `"NFO"`, `"BFO"`, …) for option calls.

**Equity/crypto heuristics** (`resolve_symbol`, optional `asset_type=`):

- `/` in symbol → crypto spot
- Suffix `.NS`, `:NSE` → Indian equity
- Else: crypto if `BASE+QUOTE` tail matches (USDT, INR, …); else equity/index

**Discovery:**

```python
syms = client.list_symbols(source="binance", search="BTC", limit=10)
# SymbolInfo: canonical, base, quote, asset_type, provider_symbol
exps = client.derivatives.list_expiries("GOLDM", source="dhan", exchange="MCX")  # list[date]
```

Zerodha: pass `exchange="NSE"` via kwargs. Dhan options: pass `exchange="MCX"` (or `"NFO"`).

---

## Intervals

`Interval` enum (`from bandl import Interval`):

| Enum | Value |  | Enum | Value |
|------|-------|--|------|-------|
| M1 | `1m` |  | H2 | `2h` |
| M3 | `3m` |  | H4 | `4h` |
| M5 | `5m` |  | H6 | `6h` |
| M15 | `15m` |  | H8 | `8h` |
| M30 | `30m` |  | D1 | `1d` |
| H1 | `1h` |  | D3 | `3d` |
|  |  |  | W1 | `1w` |
|  |  |  | MO1 | `1M` |

**Gaps:**

| provider | unsupported | mapped (not native) |
|----------|-------------|---------------------|
| coindcx | M3 | — |
| zerodha | H6, H8, D3 | H2, H4 → `60minute`; W1, MO1 → `day` |
| dhan (options) | M3, M30, H2, H4, H6, H8, D1, D3, W1, MO1 | — (only M1, M5, M15, H1) |
| binance | — | all listed supported |

Pass `Interval.H1` or a string like `"1h"`.

---

## API reference (agent format)

### METHOD: `client.crypto.get_ohlcv` / `client.equity.get_ohlcv` / `client.get_ohlcv`

**USE WHEN:** user wants list of OHLCV bars (typed models).

**PARAMS:** `symbol`, `interval=Interval.D1`, `start=None`, `end=None`, `source=None`, `asset_type=None` (`CRYPTO_SPOT` default; use `CRYPTO_PERP` for futures), `**kwargs` (Zerodha: `exchange`, …)

**RETURNS:** `list[OHLCV]` — fields: `timestamp` (UTC), `open`, `high`, `low`, `close`, `volume`, `open_interest?`, `quote_volume?`, `trades?`, `symbol`, `interval`, `source`

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

**RETURNS:** `pandas.DataFrame` — columns from `OHLCV.model_dump()` (`timestamp`, `open`, `high`, `low`, `close`, `volume`, `open_interest`, …)

**EXAMPLE:**

```python
df = client.crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1, start, end)
```

**ERRORS:** same as `get_ohlcv`; empty DataFrame possible if provider returns no in-range candles (CoinDCX lag).

---

### METHOD: `client.derivatives.get_ohlcv` / `get_ohlcv_dataframe` (low-level: `client.get_option_ohlcv`)

**USE WHEN:** user wants option-contract OHLCV (F&O or MCX commodity), active or expired.

**PARAMS:** `contract` (`str` canonical symbol **or** `OptionContract`), `interval=Interval.M1` (1/5/15/60 min only), `start=None`, `end=None`, `source="dhan"`, `exchange=None` (**required** for string symbols, e.g. `"MCX"`, `"NFO"`), `instrument_id=None` (native id; skips scrip lookup — use for expired contracts).

**RETURNS:** `list[OHLCV]` (or DataFrame) — `symbol` is the canonical contract; `open_interest` present when the provider returns it (Dhan intraday omits OI).

**AUTH:** Dhan — `ProviderSettings(api_key=<client_id>, access_token=<jwt>)`.

**EXAMPLE:**

```python
from datetime import date, datetime, timezone
from decimal import Decimal
from bandl import Bandl, BandlConfig, Interval, ProviderSettings
from bandl.models.market import OptionContract, OptionType

client = Bandl(BandlConfig(providers={
    "dhan": ProviderSettings(api_key="DHAN_CLIENT_ID", access_token="DHAN_JWT"),
}))

# A) String symbol (active contract; auto-resolved)
df = client.derivatives.get_ohlcv_dataframe(
    "GOLDM26JUL145000CE", Interval.M5, source="dhan", exchange="MCX",
)

# B) Structured OptionContract
c = OptionContract(underlying="GOLDM", expiry=date(2026, 7, 29),
                   strike=Decimal("145000"), option_type=OptionType.CALL, exchange="MCX")
bars = client.derivatives.get_ohlcv(c, Interval.M1, source="dhan")

# C) Expired contract (dropped from scrip master) → native instrument_id
bars = client.derivatives.get_ohlcv(
    "GOLDM26JUN143500CE", Interval.M1,
    datetime(2026, 6, 26, tzinfo=timezone.utc),
    datetime(2026, 6, 27, tzinfo=timezone.utc),
    source="dhan", exchange="MCX", instrument_id="570800",
)
```

**ERRORS:** `SymbolNotFoundError` → contract not in scrip master (expired? pass `instrument_id=`); `ProviderError` → unsupported interval or upstream failure; `AuthenticationError` → set Dhan token; `UnsupportedCapabilityError` → `source` is not derivatives-capable (only `dhan`).

---

### METHOD: `client.derivatives.list_expiries`

**USE WHEN:** discover available option expiries for an underlying.

**PARAMS:** `underlying: str`, `source="dhan"`, `exchange` (**required**, e.g. `"MCX"`), `segment=None`

**RETURNS:** `list[datetime.date]` (sorted, from Dhan scrip master — no auth network call)

**EXAMPLE:**

```python
expiries = client.derivatives.list_expiries("GOLDM", source="dhan", exchange="MCX")
```

---

### METHOD: `client.derivatives.get_option_chain`

**USE WHEN:** live option chain (strikes with CE/PE quotes + greeks) for one expiry.

**PARAMS:** `underlying: str`, `expiry: date` (**required**), `source="dhan"`, `exchange` (**required**), `segment=None`

**RETURNS:** `list[OptionChainEntry]` — `strike`, `ce: OptionQuote|None`, `pe: OptionQuote|None`; `OptionQuote` = `ltp, oi, iv, volume, delta, theta, gamma, vega` (all `Decimal|None`).

**AUTH:** Dhan credentials. Rate limit ≈ 1 request / 3s (handled via retries).

**EXAMPLE:**

```python
from datetime import date
chain = client.derivatives.get_option_chain(
    "GOLDM", expiry=date(2026, 7, 29), source="dhan", exchange="MCX",
)
```

---

### METHOD: `client.list_symbols`

**USE WHEN:** screening, pair discovery, building symbol loops.

**PARAMS:** `source` (**required**), `search=None`, `limit=None`, `asset_type=None` (`CRYPTO_PERP` for futures universe), `**kwargs` (zerodha: `exchange="NSE"`)

**RETURNS:** `list[SymbolInfo]`

**EXAMPLE:**

```python
pairs = client.list_symbols(source="binance", search="BTC", limit=10)
```

**ERRORS:** `ConfigurationError` unknown provider; `ProviderError` upstream failures

---

### METHOD: `client.list_providers`

**RETURNS:** `["binance", "coindcx", "dhan", "zerodha"]` — **none** required auth to list.

---

### METHOD: `client.configure_provider`

**USE WHEN:** set or rotate API keys after `Bandl()` construction.

**PARAMS:** `name: str`, `settings: ProviderSettings`

**EXAMPLE:**

```python
from bandl import Bandl, ProviderSettings

client = Bandl()
client.configure_provider("dhan", ProviderSettings(api_key="client_id", access_token="jwt"))
```

---

### METHOD: `client.account.capabilities` / `supports`

**USE WHEN:** before account calls; check fills/PnL/segment support.

- `capabilities(source: str | None)` → `AccountCapabilities` (or `dict` if `None`); `.supports("fills")`, `.supports("pnl_broker")`, …
- `supports(source: str, capability: str) -> bool`

```python
caps = client.account.capabilities("coindcx")
assert caps.supports("fills")
```

---

### METHOD: `client.account.get_orders` / `get_fills` / `get_ledger_entries` / `get_pnl` (+ `_dataframe` variants)

**USE WHEN:** order history, executions, fees/funding, PnL.

**COMMON PARAMS:** `start`, `end`, `source=None`, `symbol=`, `segment=`, `side=`, `status=`, `order_id=`, `limit=`. `get_pnl` adds `granularity=` (`trade`|`symbol`|`day`|`portfolio`), `prefer=` (`auto`|`broker`|`computed`|`hybrid`), `reconcile=False`, `scope=` (Zerodha only — see below).

**RETURNS:** `list[AccountOrder]` / `list[AccountFill]` / `list[LedgerEntry]` / `list[PnLRecord]` (or DataFrames)

**AUTH:** coindcx / zerodha credentials

**EXAMPLE:**

```python
fills = client.account.get_fills(start, end, source="coindcx", segment="crypto_fno")
pnl   = client.account.get_pnl(start, end, source="zerodha", prefer="auto")
```

**NOTES:** Zerodha orders/fills = **current session only**; holdings PnL ≈ lifetime snapshot, not arbitrary past months.

**⚠️ Zerodha `get_pnl` day/net/holding scope — do not naively `sum()` without reading this:**
Kite's `/portfolio/positions` returns two books, `net` (true running position economics) and `day` (today's session view — a position squared off intraday is costed against a **zero average price**, which can invert the sign of its reported pnl). `PnLRecord.scope` (`"day"|"net"|"holding"|None`) tags which book a row came from; rows with `zero_avg_price_artifact=True` are exactly the ones a zero-avg-price day-book row can fabricate.

- `get_pnl(..., source="zerodha")` **default** returns `net` + `holding` scope only (day-book excluded) — **safe to `sum()`**.
- Pass `scope="day"` to see Kite's day-book view; `scope="net"` / `scope="holding"` to isolate one book; `scope="all"` for everything.
- **Never** mix `scope="day"` rows into a sum with `net`/`holding` rows — that's the exact bug this default guards against.
- Prefer `client.account.get_pnl_summary(source="zerodha")` over hand-rolling this: it returns **one row per symbol**, already rolled up from the safe (day-excluded) scope — just sum `total_pnl` across the returned rows.

```python
# safe: one number per symbol, no day/net ambiguity to reason about
summary = client.account.get_pnl_summary(source="zerodha")
portfolio_total = sum(r.total_pnl for r in summary if r.total_pnl is not None)
```

---

### METHOD: `client.account.export_analysis_bundle`

**USE WHEN:** one JSON-serializable dump for analysis.

**PARAMS:** `start`, `end`, `sources: list[str] | None`, `include_native=False`, filter kwargs

**RETURNS:** `dict` with keys `manifest`, `capabilities`, `orders`, `fills`, `ledger`, `pnl`

---

## Task recipes (intent → code)

| User says | Do this | Provider | Auth? |
|-----------|---------|----------|-------|
| Daily chart for BTC/USDT | `client.crypto.get_ohlcv_dataframe("BTC/USDT", Interval.D1, start, end)` | binance | No |
| Screen top 10 BTC pairs on 4h | `list_symbols(source="binance", search="BTC", limit=10)` then loop `get_ohlcv_dataframe(..., Interval.H4)` | binance | No |
| Crypto futures daily/weekly | `get_ohlcv_dataframe(..., asset_type=AssetType.CRYPTO_PERP)` | binance/coindcx | No |
| NIFTY 50 last 6 months | `client.equity.get_ohlcv_dataframe("NIFTY 50", Interval.D1, start, end, source="zerodha")` | zerodha | Yes |
| RELIANCE daily bars | `client.equity.get_ohlcv_dataframe("RELIANCE", Interval.D1, start, end)` | zerodha | Yes |
| GOLDM option 5-min candles | `client.derivatives.get_ohlcv_dataframe("GOLDM26JUL145000CE", Interval.M5, source="dhan", exchange="MCX")` | dhan | Yes |
| Expired option minute data | `client.derivatives.get_ohlcv(sym, Interval.M1, start, end, source="dhan", exchange="MCX", instrument_id="<id>")` | dhan | Yes |
| What expiries for an underlying | `client.derivatives.list_expiries("GOLDM", source="dhan", exchange="MCX")` | dhan | Yes |
| Live option chain for a expiry | `client.derivatives.get_option_chain("GOLDM", expiry=date(...), source="dhan", exchange="MCX")` | dhan | Yes |
| My CoinDCX futures PnL last month | `capabilities("coindcx")` then `get_pnl(..., source="coindcx", segment="crypto_fno")` | coindcx | Yes |
| Total Zerodha pnl, safe to sum | `client.account.get_pnl_summary(source="zerodha")` — never sum raw `get_pnl(scope="all")` rows | zerodha | Yes |
| Binance blocked in region | retry with `source="coindcx"` | coindcx | No |
| CoinDCX empty candles | earlier `end`, or read `DataNotAvailableError` span | coindcx | No |
| Compare brokers in one JSON | `export_analysis_bundle(start, end, sources=["coindcx","zerodha"])` | both | Yes |
| Place a live limit order | `client.trade.place_order(OrderRequest(...), source="zerodha")` | zerodha/dhan | Yes |
| Check today's open orders | `client.trade.get_open_orders(source="zerodha")` | zerodha/dhan | Yes |
| Check live positions/holdings/margin | `client.portfolio.get_positions(source=...)` / `get_holdings` / `get_margin` | zerodha/dhan | Yes |
| IST display | convert UTC timestamps (see below) | — | — |

### Recipe: single symbol daily crypto

```python
from datetime import datetime, timedelta, timezone
from bandl import Bandl, Interval

client = Bandl()
end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end)
```

Provider: **binance** | Auth: **no**

### Recipe: option OHLCV (active + expired)

```python
import os
from datetime import datetime, timezone
from bandl import Bandl, BandlConfig, Interval, ProviderSettings

client = Bandl(BandlConfig(providers={
    "dhan": ProviderSettings(
        api_key=os.environ["DHAN_CLIENT_ID"],
        access_token=os.environ["DHAN_ACCESS_TOKEN"],
    ),
}))

# Active monthly contract — string auto-resolves via scrip master
df = client.derivatives.get_ohlcv_dataframe(
    "GOLDM26JUL145000CE", Interval.M5, source="dhan", exchange="MCX",
)

# Expired contract — pass native instrument_id (look up once; scrip master drops it)
bars = client.derivatives.get_ohlcv(
    "GOLDM26JUN143500CE", Interval.M1,
    datetime(2026, 6, 26, tzinfo=timezone.utc),
    datetime(2026, 6, 27, tzinfo=timezone.utc),
    source="dhan", exchange="MCX", instrument_id="570800",
)
```

Provider: **dhan** | Auth: **yes**

### Recipe: Indian equity + index

```python
from bandl import Bandl, BandlConfig, Interval, ProviderSettings

client = Bandl(BandlConfig(providers={
    "zerodha": ProviderSettings(api_key="YOUR_KEY", access_token="YOUR_TOKEN"),
}))
for sym in ("RELIANCE", "NIFTY 50"):
    df = client.equity.get_ohlcv_dataframe(sym, Interval.D1, start, end)
```

Provider: **zerodha** | Auth: **yes** (daily token refresh)

### Recipe: Binance HTTP 451 geo block

```python
from bandl.exceptions import GeoRestrictionError

try:
    df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end)
except GeoRestrictionError:
    df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end, source="coindcx")
```

### Recipe: timezone UTC → IST

```python
import pandas as pd

df = client.crypto.get_ohlcv_dataframe("BTCUSDT", Interval.D1, start, end)
df["timestamp_ist"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
```

All bandl timestamps are **UTC**.

### Recipe: configure from environment

```python
import os
from bandl import Bandl, BandlConfig, ProviderSettings

client = Bandl(BandlConfig(providers={
    "zerodha": ProviderSettings(api_key=os.environ["ZERODHA_API_KEY"],
                                access_token=os.environ["ZERODHA_ACCESS_TOKEN"]),
    "dhan":    ProviderSettings(api_key=os.environ["DHAN_CLIENT_ID"],
                                access_token=os.environ["DHAN_ACCESS_TOKEN"]),
    "coindcx": ProviderSettings(api_key=os.environ["COINDCX_API_KEY"],
                                api_secret=os.environ["COINDCX_API_SECRET"]),
}))
```

---

## Configuration & env vars

### `BandlConfig` fields

| field | default | meaning |
|-------|---------|---------|
| `timeout_seconds` | 30 | HTTP timeout |
| `max_http_retries` | 3 | retry 5xx / network |
| `default_crypto_provider` | `binance` | `client.crypto` default |
| `default_equity_provider` | `zerodha` | `client.equity` default |
| `default_derivatives_provider` | `dhan` | `client.derivatives` default |
| `providers` | `{}` | map of provider id → `ProviderSettings` |

### `ProviderSettings`

| field | repr | notes |
|-------|------|-------|
| `api_key` | hidden | Zerodha key; **Dhan client id**; CoinDCX/Binance key |
| `api_secret` | hidden | CoinDCX, Binance |
| `access_token` | hidden | Zerodha daily token; **Dhan JWT** |
| `base_url` | shown | optional override |

`extra="forbid"` — unknown keys error.

### `.env` keys (`examples/.env.example`)

| variable | used for |
|----------|----------|
| `ZERODHA_API_KEY` / `ZERODHA_ACCESS_TOKEN` | Kite Connect (token expires daily) |
| `DHAN_CLIENT_ID` | Dhan client id → `ProviderSettings.api_key` |
| `DHAN_ACCESS_TOKEN` | Dhan JWT → `ProviderSettings.access_token` |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | optional (public OHLCV needs none) |
| `COINDCX_API_KEY` / `COINDCX_API_SECRET` | account APIs |

bandl does **not** auto-load `.env`; agents must read env and pass `ProviderSettings` (see `examples/main.py` / `examples/dhan_options.py`).

---

## Exception playbook

| exception | meaning | agent action |
|-----------|---------|--------------|
| `AuthenticationError` | missing/invalid credentials (401/403) | set `ProviderSettings`; refresh Zerodha/Dhan token |
| `GeoRestrictionError` | Binance HTTP 451 | `source="coindcx"` for crypto OHLCV |
| `DataNotAvailableError` | range outside available data (CoinDCX lag) | narrow range; read error message for available span |
| `SymbolNotFoundError` | bad symbol for provider | fix symbol; `list_symbols`; Zerodha `tradingsymbol=`/`instrument_token=`; Dhan expired → `instrument_id=` |
| `UnsupportedCapabilityError` | feature not on provider | account: `capabilities()`; derivatives only on `dhan` |
| `RateLimitError` | subclass of `ProviderError` (HTTP 429) | backoff and retry |
| `ProviderError` | upstream failure / unsupported interval | read `[provider]` prefix; 4xx not retried |
| `ConfigurationError` | bad provider name | use `list_providers()` |
| `BandlError` | base / invalid date range | ensure `start < end` UTC |

---

## Not supported / use alternatives

| request | bandl status | alternative |
|---------|--------------|-------------|
| CoinDCX futures **M3 / H2 / H6** candles | **Not supported** | M5, H1, H4, H8, D1, W1 |
| Dhan option OHLCV at **M30 / H2 / H4 / daily** | **Not supported** | M1, M5, M15, H1 only |
| Live WebSockets / streaming | **Not implemented** | poll `get_ohlcv` |
| Async `await` client | **Not implemented** | sync calls only |
| Zerodha **historical** orders/fills for past months | **Not available** | broker statements; holdings snapshot only |
| Equity/index OHLCV via Dhan | **Not wired** (options only) | use `zerodha` for equity/index |
| US equities | **Not implemented** | — |
| Crypto trading (binance/coindcx `client.trade`/`client.portfolio`) | **Not implemented** | market data + account history only for crypto |
| AMO / cover (CO) / bracket (BO) / iceberg orders (write) | **Not implemented** | place a `REGULAR` order; CO/BO/AMO orders already on your account still read fine via `get_open_orders`/`get_order` |
| GTT / Forever conditional orders | **Not implemented** | place/monitor manually via broker app |
| Order slicing over F&O freeze limit | **Not implemented** | split into multiple `REGULAR` orders yourself |
| Margin preview (`preview_margin`) / `convert_position` | **Not implemented** | check margin via broker app before placing |
| Crypto leverage / margin-mode set | **Not implemented** | set via broker app |

---

## Verification

```bash
pip install -e ".[dev]"
pytest tests/bandl/                    # unit tests (default; no network)
ruff check lib/bandl tests/bandl
python examples/main.py                # crypto + Zerodha demo (.env for Kite)
python examples/dhan_options.py        # options demo (.env for Dhan)
```

Package version: see `pyproject.toml` `project.version`.

---

## Quick capability answers (FAQ)

**Q: Option candles, including expired contracts?**
A: `client.derivatives.get_ohlcv_dataframe("GOLDM26JUL145000CE", Interval.M5, source="dhan", exchange="MCX")`. Expired → add `instrument_id="<native securityId>"`. Intervals: 1/5/15/60 min only.

**Q: Default provider for each facet?**
A: `client.crypto`→binance, `client.equity`→zerodha, `client.derivatives`→dhan. Override with `source=` or `BandlConfig.default_*_provider`.

**Q: Crypto futures daily charts?**
A: `get_ohlcv_dataframe("BTCUSDT", Interval.D1, asset_type=AssetType.CRYPTO_PERP, source="binance"|"coindcx")`.

**Q: Multi-provider account merge?**
A: `source=None` merges all account-capable providers with dedup keys; prefer explicit `source=` for deterministic behavior.
