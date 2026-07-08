# bandl — live execution API design

> **Status:** **core shipped** for zerodha + dhan (2026-07-08) — see `AGENTS.md` § "Live trading & portfolio" for the user-facing surface. This document is the full design; the sections below marked with the release note were trimmed for the first cut.
> **Shipped:** `client.trade` (place/modify/cancel, get_open_orders/get_order/get_trades) and `client.portfolio` (get_positions/get_holdings/get_balances/get_margin) for zerodha + dhan, **regular-variety orders only**. Live-validated read paths against real accounts; place/modify/cancel validated via mocked unit tests only (no real orders placed during validation).
> **Deferred to a later pass:** conditional orders (GTT/Forever/OCO, §7b), order slicing/iceberg, AMO/CO/BO write support, margin preview, `convert_position`, crypto leverage/margin-mode, live quotes (`get_quote`/`get_ltp`), binance/coindcx trading providers, streaming/sockets (Phase 2).
> **Scope:** add live trading + portfolio to bandl, which today is read-only (historical OHLCV + account *history*).
> **Providers in scope:** zerodha (equity/F&O), dhan (options/commodity), binance (crypto spot + USDT-M perp), coindcx (crypto spot + futures).

---

## 1. Goals & non-goals

**Goals**
- One generic, sync surface to place/modify/cancel orders and read live order/position/holding/balance state across stock + crypto + commodity brokers.
- Match existing bandl patterns: facets on the client, pydantic models, `Protocol` providers, capability gating, `_dataframe` variants.
- Enum + provider passthrough for fields that don't normalize cleanly.

**Non-goals (this pass)**
- WebSockets / streaming (order updates, ticks) — Phase 2.
- Strategy/OMS layer, position sizing, risk engine.
- US equities, async client.

---

## 2. Facet layout

Two new facets, decided split:

| Facet | Responsibility |
|---|---|
| `client.trade` | order **write** (place/modify/cancel), live order **state** (open orders, single order, order history, today's trades), risk config (leverage/margin mode) |
| `client.portfolio` | **positions**, **holdings**, **balances**, **margin/funds**, order **margin preview** |

Live **quotes** (`get_quote`, `get_ltp`) are market data → added to existing market facets (`client.crypto`, `client.equity`, `client.derivatives`) as siblings of `get_ohlcv`, **not** in trade/portfolio.

Read-only `client.account` (history: orders/fills/ledger/pnl) is unchanged. `client.trade.get_trades` = **today's session** fills (live); `client.account.get_fills` = historical.

---

## 3. Generic API surface

### `client.trade`

```python
# order write
place_order(order: OrderRequest, *, source: str) -> Order | list[Order]
    # returns list[Order] when order.slice=True (one Order per freeze-limit leg)
modify_order(order_id: str, *, source: str,
             price: Decimal | None = None,
             trigger_price: Decimal | None = None,
             quantity: Decimal | None = None,
             validity: Validity | None = None) -> Order
cancel_order(order_id: str, *, source: str) -> Order
cancel_all(*, source: str, symbol: str | None = None) -> list[Order]

# order read (live / today)
get_open_orders(*, source: str, symbol: str | None = None) -> list[Order]
get_order(order_id: str, *, source: str) -> Order
get_order_history(order_id: str, *, source: str) -> list[Order]   # state transitions
get_trades(*, source: str, symbol: str | None = None) -> list[Fill]  # today's fills

# conditional orders (GTT / Forever / OCO) — see §7b for models
place_conditional / modify_conditional / cancel_conditional
get_conditionals / get_conditional

# risk config (capability-gated; crypto futures)
set_leverage(symbol: str, leverage: int, *, source: str) -> None
set_margin_mode(symbol: str, mode: MarginMode, *, source: str) -> None

capabilities(source: str | None = None) -> TradeCapabilities | dict[str, TradeCapabilities]
supports(source: str, capability: str) -> bool
# + *_dataframe on every list-returning read
```

### `client.portfolio`

```python
get_positions(*, source: str) -> list[Position]
get_holdings(*, source: str) -> list[Holding]
get_balances(*, source: str) -> list[Balance]
get_margin(*, source: str) -> MarginInfo
preview_margin(order: OrderRequest, *, source: str) -> MarginInfo   # capability-gated
convert_position(symbol, *, source, from_product: ProductType,      # capability-gated
                 to_product: ProductType, quantity, position_type="net") -> bool
    # kite PUT /portfolio/positions (NRML<->MIS); dhan has equivalent

capabilities(source: str | None = None) -> PortfolioCapabilities | dict[...]
# + *_dataframe variants
```

### Market facets (new live-snapshot methods)

```python
client.crypto.get_quote(symbol, *, source=None) -> Quote
client.crypto.get_ltp(symbol, *, source=None)   -> Decimal
# same on client.equity, client.derivatives
```

---

## 4. Models

New pydantic models. Live entities share a small base like `AccountEntityBase` (`source, segment, symbol, symbol_native, currency, instrument_id, provider_native`).

```python
# --- input ---
OrderRequest:
    # instrument: pass a flat symbol OR a structured OptionContract (options/F&O).
    symbol: str | None = None               # equity/crypto: "RELIANCE", "BTCUSDT",
                                            #   or canonical option "NIFTY24JUL22000CE"
    contract: OptionContract | None = None   # structured option (reuse existing model)
    instrument_id: str | None = None         # native id (Dhan securityId / kite token)
                                            #   skips scrip lookup; needed for some options
    side: OrderSide
    order_type: OrderType
    quantity: Decimal                        # in UNITS (F&O: must be lot-size multiple)
    price: Decimal | None = None             # limit price
    trigger_price: Decimal | None = None     # SL / SL-M / CO
    product: ProductType = ProductType.DELIVERY
    validity: Validity = Validity.DAY
    validity_ttl: int | None = None          # minutes, when validity=TTL (kite)
    variety: Variety = Variety.REGULAR
    client_order_id: str | None = None       # idempotency: kite tag(<=20) / dhan correlationId(<=30)
                                            #   / crypto clientOrderId
    exchange: str | None = None              # routing: NSE/NFO/BFO/MCX/... ; None for crypto
    reduce_only: bool = False                # crypto futures
    leverage: int | None = None
    disclosed_quantity: Decimal | None = None
    # conditional / bracket / cover legs
    stoploss: Decimal | None = None          # BO/CO SL (kite squareoff/stoploss ; dhan boStopLossValue)
    target: Decimal | None = None            # BO target      (dhan boProfitValue)
    trailing_stoploss: Decimal | None = None
    # slicing over F&O freeze limit
    slice: bool = False                      # dhan /orders/slicing ; kite autoslice
    iceberg_legs: int | None = None          # kite iceberg (2-50)
    iceberg_quantity: Decimal | None = None
    # after-market
    amo: bool = False                        # dhan afterMarketOrder ; kite variety=amo
    amo_time: str | None = None              # PRE_OPEN|OPEN|OPEN_30|OPEN_60 (dhan)
    extra: dict[str, Any] = {}               # provider passthrough (market_protection, auction_number, …)

# --- live order (mutable-state superset of AccountOrder) ---
Order(AccountEntityBase):
    order_id: str
    client_order_id: str | None
    exchange_order_id: str | None
    side: OrderSide
    order_type: OrderType
    product: ProductType
    validity: Validity
    variety: Variety
    status: OrderStatus
    status_message: str | None
    quantity: Decimal
    filled_quantity: Decimal
    pending_quantity: Decimal
    cancelled_quantity: Decimal | None
    price: Decimal | None
    trigger_price: Decimal | None
    average_price: Decimal | None
    created_at: datetime
    updated_at: datetime | None
    exchange_timestamp: datetime | None

Fill(AccountEntityBase):        # reuse/align with AccountFill shape
    trade_id: str
    order_id: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal | None
    timestamp: datetime

Position(AccountEntityBase):
    side: OrderSide             # or net qty sign
    quantity: Decimal           # net
    overnight_quantity: Decimal | None   # kite: carried vs day
    day_quantity: Decimal | None
    average_price: Decimal
    last_price: Decimal | None
    close_price: Decimal | None
    product: ProductType
    multiplier: Decimal | None  # F&O lot size
    value: Decimal | None
    pnl: Decimal | None
    m2m: Decimal | None         # mark-to-market (kite)
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal | None
    buy_quantity: Decimal | None
    sell_quantity: Decimal | None
    liquidation_price: Decimal | None   # crypto futures
    leverage: int | None

Holding(AccountEntityBase):     # equity holdings / crypto spot wallet
    quantity: Decimal           # realised/settled
    t1_quantity: Decimal | None          # kite: not-yet-settled (T+1)
    average_price: Decimal | None
    last_price: Decimal | None
    close_price: Decimal | None
    pnl: Decimal | None
    day_change: Decimal | None
    day_change_pct: Decimal | None
    product: ProductType | None
    collateral_quantity: Decimal | None
    collateral_type: str | None
    isin: str | None

Balance:
    source: str
    currency: str
    available: Decimal
    used: Decimal
    total: Decimal

MarginInfo:
    source: str
    currency: str
    available: Decimal
    used: Decimal
    total: Decimal
    span: Decimal | None
    exposure: Decimal | None
    order_margin: Decimal | None    # populated by preview_margin
    provider_native: dict

Quote:
    symbol: str
    source: str
    ltp: Decimal
    bid: Decimal | None
    ask: Decimal | None
    volume: Decimal | None
    oi: Decimal | None
    ohlc: dict | None               # day open/high/low/close/prev_close
    depth: dict | None              # bids/asks ladder
    timestamp: datetime
```

### Enums

Reuse existing `OrderSide`, `OrderStatus`, `Segment` (`models/account/types.py`).
Extend `OrderType`; add the rest. Values chosen to cover kite + dhan + crypto.

```python
OrderType:    MARKET | LIMIT | SL | SL_M | OTHER
    # kite: MARKET/LIMIT/SL/SL-M ; dhan: MARKET/LIMIT/STOP_LOSS(=SL)/STOP_LOSS_MARKET(=SL_M)
    # crypto: MARKET/LIMIT ; SL/SL_M carry trigger_price
ProductType:  DELIVERY | INTRADAY | NORMAL | MTF | COVER | BRACKET | MARGIN | OTHER
    # kite:  CNC=DELIVERY, MIS=INTRADAY, NRML=NORMAL, MTF
    # dhan:  CNC=DELIVERY, INTRADAY, MARGIN, MTF, CO=COVER, BO=BRACKET
    #        (dhan models CO/BO as productType; kite as variety — see mapping)
    # crypto: spot=DELIVERY, perp=MARGIN
Validity:     DAY | IOC | TTL | GTC | FOK | OTHER
    # kite: DAY/IOC/TTL(+validity_ttl) ; dhan: DAY/IOC ; crypto: GTC/IOC/FOK
Variety:      REGULAR | AMO | COVER | BRACKET | ICEBERG | AUCTION | GTT | FOREVER | OCO | OTHER
    # kite variety (URL path): regular/amo/co/iceberg/auction + GTT (separate endpoint)
    # dhan: regular + Forever/Super Order (separate endpoints)
    # crypto: REGULAR + OCO
MarginMode:   CROSS | ISOLATED
```

**CO/BO placement mismatch:** Dhan sets `productType=CO|BO`; Kite sets `variety=co` (+ bracket via
`squareoff`/`stoploss`/`trailing_stoploss`). bandl accepts `variety=COVER|BRACKET`; each provider maps
to its own field internally. `ProductType.COVER/BRACKET` kept only so Dhan round-trips losslessly.

Unmapped provider values → carried in `OrderRequest.extra` / `provider_native`, never lost.

### Order status mapping → `OrderStatus`

| bandl `OrderStatus` | kite | dhan |
|---|---|---|
| OPEN | OPEN, OPEN PENDING, TRIGGER PENDING, *interim* | PENDING, TRANSIT |
| PARTIAL | (qty-derived) | PART_TRADED |
| COMPLETE | COMPLETE | TRADED |
| CANCELLED | CANCELLED, CANCEL PENDING | CANCELLED |
| REJECTED | REJECTED | REJECTED |
| EXPIRED | — | EXPIRED |

Interim kite states (`VALIDATION PENDING`, `MODIFY PENDING`, …) collapse to `OPEN`; raw string kept in `status_message`.

---

## 5. Provider protocols

Parallel to `AccountHistoryProvider`. Two protocols so a provider can implement one without the other.

```python
@runtime_checkable
class TradingProvider(Protocol):
    provider_id: str
    def trade_capabilities(self) -> TradeCapabilities: ...
    def place_order(self, order: OrderRequest) -> Order: ...
    def modify_order(self, order_id: str, changes: OrderModify) -> Order: ...
    def cancel_order(self, order_id: str) -> Order: ...
    def get_open_orders(self, symbol: str | None) -> list[Order]: ...
    def get_order(self, order_id: str) -> Order: ...
    def get_order_history(self, order_id: str) -> list[Order]: ...
    def get_trades(self, symbol: str | None) -> list[Fill]: ...
    # optional: set_leverage, set_margin_mode, cancel_all

@runtime_checkable
class PortfolioProvider(Protocol):
    provider_id: str
    def portfolio_capabilities(self) -> PortfolioCapabilities: ...
    def get_positions(self) -> list[Position]: ...
    def get_holdings(self) -> list[Holding]: ...
    def get_balances(self) -> list[Balance]: ...
    def get_margin(self) -> MarginInfo: ...
    # optional: preview_margin
```

### Capabilities (extend the `CapabilityDetail` pattern)

```python
TradeCapabilities:
    provider_id, segments
    place, modify, cancel, cancel_all      : CapabilityDetail
    order_history, trades                  : CapabilityDetail
    leverage, margin_mode                  : CapabilityDetail
    variety_stop, variety_bracket,
    variety_cover, gtt, oco                : CapabilityDetail

PortfolioCapabilities:
    provider_id, segments
    positions, holdings, balances,
    margin, margin_preview, convert_position : CapabilityDetail
```

---

## 6. Provider capability matrix

| capability | zerodha | dhan | binance | coindcx |
|---|---|---|---|---|
| place / modify / cancel | ✅ | ✅ | ✅ | ✅ |
| cancel_all | ⚠️ loop | ⚠️ | ✅ `DELETE /openOrders` | ✅ `cancel_all` |
| open orders / order status | ✅ | ✅ | ✅ | ✅ |
| order history (transitions) | ✅ `order_history` | ✅ | ⚠️ `allOrders` (no per-state) | ⚠️ |
| today's trades | ✅ | ✅ | ✅ `myTrades` | ✅ `trade_history` |
| positions | ✅ net/day | ✅ | ✅ futures `positionRisk` | ✅ futures |
| holdings / spot wallet | ✅ `holdings` | ✅ | ✅ `account` balances | ✅ `balances` |
| balances / funds | ✅ `margins` | ✅ `fundlimit` | ✅ | ✅ |
| margin preview | ✅ `margins/orders` | ⚠️ calc | ⚠️ calc | ⚠️ calc |
| convert position (product) | ✅ `PUT /positions` | ✅ | ❌ n/a | ❌ n/a |
| set leverage | ❌ | ❌ | ✅ | ✅ |
| set margin mode | ❌ | ❌ | ✅ isolated/cross | ✅ |
| live quote / ltp | ✅ `quote`/`ltp` | ✅ `marketfeed` | ✅ `ticker`/`depth` | ✅ `ticker` |
| **options / F&O ordering** | ✅ NFO/BFO tradingsymbol | ✅ drv* / securityId | ✅ n/a | ✅ n/a |
| **freeze-limit slicing** | ✅ `autoslice` / iceberg | ✅ `/orders/slicing` | ❌ n/a | ❌ n/a |
| iceberg | ✅ `variety=iceberg` | ⚠️ via slicing | ❌ | ❌ |
| MTF product | ✅ | ✅ | ❌ | ❌ |
| after-market (AMO) | ✅ `variety=amo` | ✅ `afterMarketOrder` | ❌ | ❌ |
| cover order (CO) | ✅ `variety=co` | ✅ `productType=CO` | ❌ | ❌ |
| bracket order (BO) | ⚠️ deprecated | ✅ `productType=BO` | ⚠️ TP/SL pair | ⚠️ |
| GTT / forever (conditional exit) | ✅ GTT single+OCO | ✅ Forever / Super | ✅ OCO | ⚠️ stop |
| super / multi-leg order | ⚠️ basket (separate) | ✅ Super Order | ❌ | ❌ |

Legend: ✅ native · ⚠️ partial / emulated / needs client-side calc · ❌ not offered.

**Ops note (Dhan):** order **place/modify/cancel require static IP whitelisting** on the account.
Surface as a setup precondition; a 4xx from missing whitelist → `AuthenticationError` with a clear message.

---

## 7. Cross-provider mismatches & resolutions

| Concern | Divergence | Resolution |
|---|---|---|
| Product type | equity CNC/MIS/NRML vs crypto spot/margin+reduceOnly | `ProductType` enum; crypto `reduce_only` bool separate |
| Validity | DAY/IOC (equity) vs GTC/FOK/IOC (crypto) | `Validity` enum; provider rejects unsupported via capability |
| Idempotency | `clientOrderId` (crypto) vs `tag` (kite) | generic `client_order_id` |
| Order id type | int (kite) vs string/uuid (crypto) | always `str` |
| Symbol routing | equity needs `exchange`; crypto doesn't | `OrderRequest.exchange` optional; resolver handles native |
| Positions sign | net qty +/- (kite) vs side+size (crypto) | store both `side` + signed `quantity` |
| Conditional orders | GTT/forever/OCO/bracket all differ | `Variety` enum, gated by capability; details in `extra` |
| Margin preview | only kite has a real endpoint | capability flag; others compute or raise `UnsupportedCapabilityError` |

---

## 7b. Options / F&O specifics

Options are first-class for this library (Dhan options is the flagship read path). Ordering an option needs
more than a flat symbol:

1. **Contract identity** — three accepted forms on `OrderRequest`, in priority order:
   - `instrument_id` (native Dhan `securityId` / kite `instrument_token`) — most robust; skips scrip lookup.
   - `contract: OptionContract(underlying, expiry, strike, option_type, exchange)` — reuse existing model
     (`models/market/contract.py`); resolver maps to native (`drvExpiryDate`/`drvOptionType`/`drvStrikePrice`
     for Dhan; `tradingsymbol`+`exchange=NFO/BFO` for kite).
   - `symbol` canonical string (`"NIFTY24JUL22000CE"`) + `exchange` — resolved via scrip master (same path as
     `client.derivatives.get_ohlcv`).
2. **Lot size** — F&O `quantity` is in units and **must be a lot multiple**. bandl reads lot size from the
   scrip master and **validates** on `place_order` (raise `InvalidOrderError` on non-multiple). Optional
   helper: `OrderRequest.lots` sugar → units = `lots * lot_size` at build time.
3. **Freeze limit / slicing** — exchange caps single-order qty (freeze limit). `slice=True` routes to Dhan
   `/orders/slicing` or kite `autoslice`; returns **list[Order]** (one per leg). Capability-gated.
4. **Conditional exits** — options SL/target commonly via GTT (kite) / Forever (dhan). See conditional-order API below.
5. **Greeks in quotes** — option `get_quote` returns `oi, iv, delta, theta, gamma, vega` when the provider
   gives them; single-strike alternative to `client.derivatives.get_option_chain`.
6. **Expired contracts** — not orderable; ordering path only covers live contracts (unlike read path which
   supports expired via `instrument_id`).

### Conditional-order sub-API (GTT / Forever) — capability-gated

Distinct lifecycle from regular orders (rests server-side until triggered), so a separate group under `client.trade`:

```python
client.trade.place_conditional(req: ConditionalOrderRequest, *, source) -> ConditionalOrder
client.trade.modify_conditional(cond_id, *, source, ...)                 -> ConditionalOrder
client.trade.cancel_conditional(cond_id, *, source)                      -> ConditionalOrder
client.trade.get_conditionals(*, source)                                 -> list[ConditionalOrder]
client.trade.get_conditional(cond_id, *, source)                         -> ConditionalOrder
```

```python
ConditionalOrderRequest:
    trigger_type: TriggerType          # SINGLE | TWO_LEG (OCO)
    symbol/contract/instrument_id ...  # same instrument forms as OrderRequest
    exchange: str | None
    last_price: Decimal                # kite GTT requires current LTP
    trigger_values: list[Decimal]      # 1 for SINGLE, 2 for TWO_LEG (SL, target)
    legs: list[OrderRequest]           # order(s) fired on trigger
TriggerType: SINGLE | TWO_LEG
```

Maps to kite `/gtt/triggers` (single + two-leg OCO) and dhan Forever/Super Order. Coindcx/binance OCO
map here too where it fits; otherwise capability `False`.

## 8. Errors (reuse existing exception hierarchy)

Add semantics to existing exceptions; introduce a few:

- `InsufficientFundsError(ProviderError)` — margin/balance rejection.
- `OrderRejectedError(ProviderError)` — carries broker `status_message`.
- `InvalidOrderError(BandlError)` — client-side validation (bad qty/price/tick).
- Reuse: `AuthenticationError`, `RateLimitError`, `UnsupportedCapabilityError`, `SymbolNotFoundError`.

Order write is **not** auto-retried on 5xx (unlike reads) unless the request carries a `client_order_id` the provider dedups on — avoids double-fills.

---

## 9. Open items to confirm before implementation

1. **Idempotency guarantee** — which providers actually dedup on `client_order_id`? Governs retry policy. (Verify per-broker.)
2. **cancel_all** — emulate via loop where no native endpoint (zerodha/dhan)? Risk: partial failure semantics.
3. **preview_margin** — expose only where native (zerodha), or ship a best-effort estimator for others?
4. **Positions granularity** — kite splits net vs day; expose both or just net?
5. **Paper/dry-run mode** — worth a `dry_run=True` on `place_order` mapping to Binance `POST /order/test`? Others have no equivalent → emulate or omit.
6. **Streaming (Phase 2)** — separate `client.stream` facet with a callback/generator API over kite ticker / binance user-data-stream+ws / coindcx socket.io / dhan ws.
7. **CO/BO modeling** — expose as `variety` (uniform) and map to Dhan `productType=CO|BO` vs kite `variety=co`/bracket fields? Confirm the round-trip is lossless.
8. **Slicing return shape** — `place_order(slice=True)` returns `list[Order]`; standardize how a partial-leg failure is reported (raise vs. return mixed list with rejected legs).
9. **Lot-size validation** — validate F&O `quantity` against scrip-master lot size client-side, or defer to broker rejection? Recommend client-side + `OrderRequest.lots` sugar.
10. **F&O GTT/Forever** — confirm kite GTT works for NFO/BFO options (docs only show equity) and Dhan Forever covers options; else mark capability `False` for those segments.
11. **Instrument-form precedence** — lock the resolution order (`instrument_id` > `contract` > `symbol`) and error when two conflict.

---

## 10. Verified endpoint appendix (Dhan v2 + Kite Connect v3)

Confirmed against live docs on 2026-07-08.

### Dhan v2 — `https://dhanhq.co/docs/v2/orders/`
| Method | Path | Purpose |
|---|---|---|
| POST | `/orders` | place |
| PUT | `/orders/{order-id}` | modify |
| DELETE | `/orders/{order-id}` | cancel |
| POST | `/orders/slicing` | slice over F&O freeze limit (same body as place) |
| GET | `/orders` | day orderbook |
| GET | `/orders/{order-id}` | order status |
| GET | `/orders/external/{correlation-id}` | status by correlationId |
| GET | `/trades` / `/trades/{order-id}` | day trades / per-order |

- **Required body:** `dhanClientId, transactionType(BUY|SELL), exchangeSegment, productType, orderType, validity, quantity, price`.
- **Options/F&O body:** `drvExpiryDate, drvOptionType(CALL|PUT), drvStrikePrice`, or `securityId`.
- **productType:** `CNC, INTRADAY, MARGIN, MTF, CO, BO` · **orderType:** `LIMIT, MARKET, STOP_LOSS, STOP_LOSS_MARKET` · **validity:** `DAY, IOC`.
- **BO:** `boProfitValue, boStopLossValue`; legs `ENTRY_LEG/TARGET_LEG/STOP_LOSS_LEG`; modify uses `legName`.
- **AMO:** `afterMarketOrder` + `amoTime(PRE_OPEN|OPEN|OPEN_30|OPEN_60)`.
- **status:** `TRANSIT, PENDING, REJECTED, CANCELLED, PART_TRADED, TRADED, EXPIRED`.
- **idempotency:** `correlationId` (<=30 chars). **Place/modify/cancel require static-IP whitelisting.**
- Super Order / Forever Order / Conditional Trigger = separate endpoints (map to §7b conditional API).

### Kite Connect v3 — `https://kite.trade/docs/connect/v3/orders/` + `/gtt/`
| Method | Path | Purpose |
|---|---|---|
| POST | `/orders/:variety` | place |
| PUT | `/orders/:variety/:order_id` | modify |
| DELETE | `/orders/:variety/:order_id` | cancel |
| GET | `/orders` / `/orders/:order_id` | day orders / order history |
| GET | `/trades` / `/orders/:order_id/trades` | day trades / per-order |
| POST/GET/PUT/DELETE | `/gtt/triggers[/:id]` | GTT single + two-leg OCO |

- **params:** `tradingsymbol, exchange(NSE|BSE|NFO|BFO|CDS|MCX|BCD), transaction_type, order_type(MARKET|LIMIT|SL|SL-M), quantity, product(CNC|NRML|MIS|MTF), validity(DAY|IOC|TTL)`.
- **optional:** `price, trigger_price, disclosed_quantity, validity_ttl, iceberg_legs(2-50), iceberg_quantity, auction_number, market_protection, autoslice, tag(<=20)`.
- **variety:** `regular, amo, co, iceberg, auction` (+ GTT separate). **GTT** = `single` | `two-leg` (OCO); docs show equity examples — **confirm F&O GTT support before relying on it**.

### Kite Connect v3 — `https://kite.trade/docs/connect/v3/portfolio/`
| Method | Path | Purpose |
|---|---|---|
| GET | `/portfolio/holdings` | long-term equity holdings |
| GET | `/portfolio/positions` | positions — returns `net` + `day` datasets |
| PUT | `/portfolio/positions` | convert product (NRML↔MIS): `tradingsymbol, exchange, transaction_type, position_type(overnight|day), quantity, old_product, new_product` → bool |
| GET | `/portfolio/holdings/auctions` | auction holdings |

- **holdings fields:** `tradingsymbol, exchange, instrument_token, isin, product, quantity, t1_quantity, realised_quantity, average_price, last_price, close_price, pnl, day_change, day_change_percentage, collateral_quantity, collateral_type` (+ MTF qty/margin).
- **positions:** `net` = current portfolio, `day` = intraday snapshot. Fields: `quantity, overnight_quantity, multiplier(lot size), average_price, close_price, last_price, pnl, m2m, unrealised, realised, value, buy_*, sell_*, day_buy_*, day_sell_*`. Options/F&O carry `multiplier` + separate buy/sell tracking; holdings are delivery-only.
- **margins:** `/user/margins` (equity+commodity segments), `/margins/orders` (order-margin preview) — **fields still to verify**.

### Still to verify before wiring (not yet fetched)
- Kite `/user/margins`, `/margins/orders` (preview) — response shapes.
- Binance spot `/api/v3/order`, futures `/fapi/v1/{order,positionRisk,leverage,marginType,openOrders}` — current fields.
- CoinDCX spot + futures order/cancel/positions/leverage/balances — response shapes.
- Live-quote endpoints: kite `/quote`,`/quote/ltp`,`/quote/ohlc`; dhan `/marketfeed/*`.
