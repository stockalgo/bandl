# Execution Migration Guide

This document explains the transition to hardened, fail-safe live trading execution semantics in `bandl`.

## 1. Acknowledgements vs Order State

Previously, calling `place_order`, `modify_order`, or `cancel_order` immediately performed a follow-up GET request to inspect and return the full `Order` state. In high-frequency, low-latency, or unreliable network conditions, this post-mutation read had several critical flaws:
1. **Network Failure Ambiguity:** If the mutation succeeded at the broker but the follow-up read timed out, callers received an ambiguous exception.
2. **Fabricated Order Status:** Mocking or synthesizing `OPEN` or `CANCELLED` status immediately upon receiving an acknowledgement misrepresented actual order book state (e.g. an order could be rejected post-acknowledgement, or a cancellation could race with a complete execution fill).

### New Recommended Pattern: Explicit Acknowledgements

Use `*_ack` methods for predictable, low-latency mutation handling:

```python
from decimal import Decimal
from bandl import Bandl, BandlConfig, ProviderSettings
from bandl.models.account.types import OrderSide, OrderType
from bandl.models.trading import OrderRequest, ProductType

client = Bandl(
    BandlConfig(
        providers={
            "zerodha": ProviderSettings(api_key="API_KEY", access_token="TOKEN", account_id="AB1234"),
        }
    )
)

req = OrderRequest(
    symbol="INFY",
    exchange="NSE",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=Decimal(10),
    price=Decimal("1500.00"),
    product=ProductType.DELIVERY,
    client_order_id="my-custom-tag",
)

# Returns OrderAcknowledgement immediately without follow-up GET
ack = client.trade.place_order_ack(req, source="zerodha")
print(f"Dispatched order {ack.order_id} at {ack.received_at}")
```

### Legacy Methods

The legacy methods (`place_order`, `modify_order`, `cancel_order`) remain available for backward compatibility. They dispatch the mutation and perform a subsequent `get_order` read to return the actual broker state (including if a fill won a cancellation race). If the subsequent read fails, an `UncertainOutcomeError` is raised containing the known `order_id` and `client_order_id` so the mutation is never blindly resubmitted.

---

## 2. Uncertain Outcomes & Recovery Pattern

`bandl` enforces a strict **zero blind mutation retry** policy. If an HTTP request times out, drops connection, encounters a 5xx server failure, or receives unparseable JSON after dispatching an order mutation:
- An `UncertainOutcomeError` is raised.
- **Never automatically re-place or re-submit the order.** Automatic resubmission risks placing duplicate orders in volatile markets.

### Recovery Recipe

```python
from bandl.exceptions import UncertainOutcomeError

try:
    ack = client.trade.place_order_ack(req, source="zerodha")
except UncertainOutcomeError as err:
    print(f"Mutation {err.operation} outcome uncertain for order_id={err.order_id}, client_order_id={err.client_order_id}")

    recovered_order = None
    # 1. Prefer querying by known broker order_id first if available
    if err.order_id:
        try:
            recovered_order = client.trade.get_order(err.order_id, source="zerodha")
            print(f"Recovered order {err.order_id} by broker ID: status={recovered_order.status}")
        except Exception:
            recovered_order = None

    # 2. If no broker ID was assigned or lookup failed, reconcile by non-empty client_order_id
    if recovered_order is None and err.client_order_id and str(err.client_order_id).strip():
        session_orders = client.trade.get_orders(source="zerodha")
        matching = [o for o in session_orders if o.client_order_id == err.client_order_id]
        if len(matching) == 1:
            recovered_order = matching[0]
            print(f"Recovered order {recovered_order.order_id} by unique client tag: status={recovered_order.status}")
        elif len(matching) > 1:
            print(f"Ambiguous: found {len(matching)} orders matching client_order_id '{err.client_order_id}'. Manual reconciliation required.")
        else:
            print("Order was not accepted or is pending exchange gateway assignment.")
    elif recovered_order is None:
        print("Cannot reconcile without a broker order_id or client_order_id; manual verification required.")
```

---

## 3. Account Binding & Multi-Account Isolation

To prevent accidental cross-account execution in multi-account environments, credentials can be strictly bound to an account ID. For multiple accounts with the same provider (e.g. Zerodha), create separate `Bandl` client instances:

```python
from bandl import Bandl
from bandl.config import BandlConfig, ProviderSettings

# Dedicated client instance for main account
client_main = Bandl(
    config=BandlConfig(
        providers={
            "zerodha": ProviderSettings(
                api_key="KEY1",
                access_token="TOK1",
                account_id="USER1",
            ),
        }
    )
)

# Dedicated client instance for sub/secondary account
client_sub = Bandl(
    config=BandlConfig(
        providers={
            "zerodha": ProviderSettings(
                api_key="KEY2",
                access_token="TOK2",
                account_id="USER2",
            ),
        }
    )
)
```

- When `ProviderSettings.account_id` is set, any request specifying an incompatible `account_id` raises `ConfigurationError` **before** any network mutation occurs.
- If a caller specifies `account_id="XYZ"` on an unbound provider (where `account_id` was not pre-configured), `ConfigurationError` is raised to enforce explicit account registration.

---

## 4. Exact Option Contracts & Metadata Constraints

1. **Structured `OptionContract` Required for Weekly Expiries:**
   Naive option symbols specifying only month/year (e.g. `NIFTY24OCT25000CE`) are ambiguous when multiple weekly expiries exist in that month. In such cases, Dhan rejects string symbol placement with `InvalidOrderError`. Pass a structured `OptionContract(underlying="NIFTY", expiry=date(2024, 10, 17), strike=Decimal(25000), option_type=OptionType.CALL, exchange="NFO")` or explicit native `instrument_id`.
2. **Lot Size & Tick Size Validation:**
   Quantities must be exact positive integer multiples of the contract's `lot_size`. Limit and trigger prices must align exactly with the instrument's `tick_size`. Invalid multiples are rejected with `InvalidOrderError` before dispatch; `bandl` never rounds prices or quantities.
3. **Quantity Units:**
   All Indian equity and derivative orders operate strictly in native units (`QuantityUnit.BASE`), representing the exact count of shares or derivative contracts. Passing other units such as `QuantityUnit.QUOTE` or `QuantityUnit.CONTRACTS` raises `UnsupportedCapabilityError`.

---

## 5. Broker Support Matrix

| Feature | Zerodha Kite | Dhan v2 |
|---|---|---|
| **Encoding** | `application/x-www-form-urlencoded` | `application/json` |
| **Authentication** | API Key + daily Request Token (headers) | Client ID + JWT (headers, static IP whitelisting required) |
| **Client Tag / Correlation ID** | `tag` (max 20 chars) | `correlationId` (max 30 chars) |
| **Order History** | Full state transition history via `get_order_history` | Not supported by broker API (`UnsupportedCapabilityError`); single `get_order` supported |
| **Session Scope** | Current trading day session only | Current trading day session only |
| **Partial Fills** | Normalized to `OrderStatus.PARTIAL` | Normalized to `OrderStatus.PARTIAL` |
