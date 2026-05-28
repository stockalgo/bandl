# Bandl — implementation notes

**AI coding agents:** use [AGENTS.md](../AGENTS.md) for API lookup and task recipes.

## Layout

```
lib/bandl/
  client.py, config.py, exceptions.py
  account/          # AccountFacet + PnL helpers
  core/             # http, resolver, time, intervals, registry, …
  models/           # OHLCV, account models, …
  providers/
    crypto/common.py
    crypto/binance/
    crypto/coindcx/
    equity/zerodha/
```

Install: `pip install -e ".[dev]"` from [pyproject.toml](../pyproject.toml). Public imports: `from bandl import Bandl, OHLCV, Interval`.

## Design choices

1. **Public API** — `get_ohlcv()` → `list[OHLCV]`; `get_ohlcv_dataframe()` → pandas; `list_symbols`, `get_24hr_tickers` (futures), `client.account.*`.
2. **Sync HTTP** — `httpx` only; no WebSockets yet.
3. **Canonical symbols** — Crypto: `BTCUSDT`. Equities: `RELIANCE`, `NIFTY50` (`core/resolver.py`, `core/aliases.py`).
4. **Zerodha** — Kite historical API; instrument token from NSE CSV unless `instrument_token=` is passed.
5. **CoinDCX spot candles** — Paginate with `endTime` only (both bounds returns `[]`).
6. **CoinDCX futures 24h** — `current_prices/futures/rt`, filtered to active USDT instruments.
7. **Tests** — `pytest tests/bandl/` (integration: `-m integration`). CI: `.github/workflows/ci.yml`.

## Examples

```bash
cp examples/.env.example .env
python examples/main.py
python examples/futures_24hr_leaders.py --source coindcx
```

See [ACCOUNT_HISTORY.md](ACCOUNT_HISTORY.md) for `client.account`.

## Running tests

```bash
pytest tests/bandl/
pytest tests/bandl/ -m integration --override-ini="addopts="
```
