# Bandl — implementation notes

## Layout

- Source lives under [`lib/bandl/v2/`](../lib/bandl/v2/); legacy modules remain in [`lib/bandl/`](../lib/bandl/) (`yfinance.py`, `nse_data.py`, etc.).
- Install with modern metadata via [`pyproject.toml`](../pyproject.toml) (`pip install -e .` or `uv pip install -e .`), or install runtime deps only: `pip install -r requirements.txt`.
- Public imports: `from bandl import Bandl, OHLCV, Interval`.

## Design choices

1. **Public API names** — `get_ohlcv()` returns `list[OHLCV]`; `get_ohlcv_dataframe()` returns a **pandas** `DataFrame` (same parameters). Other entrypoints: `list_symbols`, `list_providers`, `configure_provider`.
2. **Sync-first HTTP** — `httpx` synchronous client keeps the first slice small; streaming/WebSockets can add an async layer later without changing models.
3. **Canonical symbols** — Crypto: concatenated `BTCUSDT`. Equities / indices: `RELIANCE`, `NIFTY50` (see `core/resolver.py` and `core/aliases.py`). Providers map to native symbols internally (e.g. CoinDCX `B-BTC_USDT`, Zerodha instrument tokens).
4. **Zerodha** — Historical API requires `api_key` and `access_token`. Instrument token is resolved by downloading the public NSE instruments CSV from Kite, except when the caller passes `instrument_token=`. Known index tradingsymbols (`NIFTY 50`, `NIFTY BANK`) are mapped from canonical index names.
5. **Kite intervals** — Several normalized `Interval` values (`H2`, `H4`, `W1`, `MO1`) currently map to the closest supported Kite interval (`60minute` or `day`). Refine when sub-day precision matters.
6. **CoinDCX** — The public `market_data/candles` API returns `[]` when both `startTime` and `endTime` are set. The adapter paginates with `endTime` + `limit` and filters to the requested window client-side.
7. **Tests** — Default `pytest` excludes `@pytest.mark.integration` (see `addopts` in `pyproject.toml`). Run network smoke tests with `pytest tests/v2/ -m integration --override-ini="addopts="` (see [CONTRIBUTING.md](../CONTRIBUTING.md)). **CI** (`.github/workflows/ci.yml`) runs unit tests, Ruff, and `build`/`twine check` on pushes and PRs; optional live API smoke tests run weekly or on demand via `integration.yml`.

## Examples and `.env`

- Run `python examples/main.py`; copy [`examples/.env.example`](examples/.env.example) to `.env` at the repo root or `examples/.env`.
- Documented variables: Zerodha, Binance, CoinDCX keys, and optional future `BANDL_*` tuning (reserved).

## Running tests

```bash
uv venv .venv && uv pip install -e '.[dev]'
PYTHONPATH=lib .venv/bin/pytest tests/v2/          # unit tests only (default)
PYTHONPATH=lib .venv/bin/pytest tests/v2/ -m integration  # + network smoke tests
```

## Not yet implemented (vs architecture plan)

- Async API, `WebSocketTransport`, live `Kline` streams.
- Module-level `bandl.crypto` facades on the root `bandl` package (current API is `Bandl.crypto`).
- Full `SymbolInfo` coverage for Binance filters beyond spot listing.
