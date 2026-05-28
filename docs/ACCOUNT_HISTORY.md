# Account & trading history

bandl provides a unified **account** facet for your own orders, fills, ledger entries, and PnL across configured brokers.

## Terminology

| bandl model | Meaning | Not to confuse with |
|-------------|---------|---------------------|
| `AccountFill` | Your executed trade | Kite `/trades`, CoinDCX `trade_history` |
| `AccountOrder` | Your order intent | Broker order book |
| `MarketTrade` | Public market tape | CoinDCX `market_data/trade_history` |

## Quick start

```python
from datetime import datetime, timezone
from bandl import Bandl, BandlConfig, ProviderSettings

client = Bandl(
    BandlConfig(
        providers={
            "coindcx": ProviderSettings(api_key="...", api_secret="..."),
            "zerodha": ProviderSettings(api_key="...", access_token="..."),
        },
    ),
)

caps = client.account.capabilities("coindcx")
print(caps.fills.supported, caps.fills.notes)

fills = client.account.get_fills(
    datetime(2024, 1, 1, tzinfo=timezone.utc),
    datetime(2024, 2, 1, tzinfo=timezone.utc),
    source="coindcx",
)
df = client.account.get_fills_dataframe(...)

pnl = client.account.get_pnl(..., prefer="auto", reconcile=True)
bundle = client.account.export_analysis_bundle(...)
```

## Capabilities

Call `client.account.capabilities(source)` before fetching. Unsupported features raise `UnsupportedCapabilityError` — not empty lists.

## PnL provenance

Every `PnLRecord` includes `provenance`:

- `source_type`: `broker`, `computed`, or `hybrid`
- `cost_basis_method`: default FIFO for computed paths
- `discrepancy` when broker and computed values differ (`reconcile=True`)

## Provider notes

### CoinDCX

| Domain | Spot | USDT futures |
|--------|------|----------------|
| Fills | `POST /exchange/v1/orders/trade_history` | `POST /exchange/v1/derivatives/futures/trades` (per pair, `from_date`/`to_date`) |
| Orders | `active_orders` | `POST /derivatives/futures/orders` |
| PnL (broker) | FIFO from spot fills | `POST /derivatives/futures/positions/transactions` (`amount` = PnL) |
| Ledger | fees on fills | futures `positions/transactions` |

Futures auth uses **millisecond** `timestamp`; spot uses **seconds**.

### Zerodha (no Kite SDK required — same REST as `kiteconnect`)

We use direct HTTP to `https://api.kite.trade`, not the official SDK. The SDK does not add historical trade APIs.

| Domain | API | Scope |
|--------|-----|--------|
| Orders / fills | `GET /orders`, `GET /trades` | **Current session only** |
| Equity PnL | `GET /portfolio/holdings` (`pnl`) | **Lifetime** on holdings |
| F&O / MCX PnL | `GET /portfolio/positions` (`day` + `net`) | **Session snapshot** |
| Ledger | `POST /charges/orders` | Contract note for today's orders |

**There is no Kite API for calendar-month trade history** (see [pykiteconnect#219](https://github.com/zerodha/pykiteconnect/issues/219)). May 2026 realized PnL requires Console export or third-party reports.

## Adding a provider

Implement `account_capabilities()`, `get_orders`, `get_fills`, `get_ledger_entries`, and `get_pnl` on your adapter; register in `Bandl.__init__`.

See [BANDL.md](BANDL.md) for market data usage.
