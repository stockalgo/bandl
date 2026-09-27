# Provider Author Guide: Execution & Trading

This guide specifies requirements for implementing a new live trading and portfolio adapter in `bandl`.

## 1. Optional Protocols & Base Capabilities

Providers do not need to implement every facet method. Providers declare capabilities dynamically via:
- `trade_capabilities() -> TradeCapabilities`
- `portfolio_capabilities() -> PortfolioCapabilities`

If a provider only supports placing orders (e.g. an order-routing engine without orderbook queries), set `place=CapabilityDetail(supported=True)` and leave other operations as `supported=False`. The `TradeFacet` gates all public calls against capability flags and method existence, raising `UnsupportedCapabilityError` before making any upstream requests.

## 2. Safe Mutation Transport Rules

All mutations (`place_order_ack`, `modify_order_ack`, `cancel_order_ack`) must obey these transport constraints:

1. **Zero Blind Retries on Mutation:**
   - Use `HttpClient.post_mutation`, `put_mutation`, or `delete_mutation`.
   - Never use read retry helpers (`get_json`) for state mutations.
   - Timeouts, connection errors, and 5xx responses must raise `UncertainOutcomeError`.
2. **Explicit Encodings:**
   - Specify `encoding="form"` for form-urlencoded endpoints (like Kite).
   - Specify `encoding="json"` for JSON payload endpoints (like Dhan).
3. **No Automatic GET in Acknowledgements:**
   - Acknowledgement methods must return immediately with `OrderAcknowledgement`.
   - Do not perform a subsequent GET request inside an acknowledgement method.
   - If the broker returns a success payload without a valid, non-empty order ID, raise `UncertainOutcomeError`.

## 3. Account Binding Verification

Adapters must verify that callers do not dispatch orders to arbitrary accounts without explicit binding:

```python
from bandl.trade.validation import verify_account_binding

def place_order_ack(self, order: OrderRequest, *, account_id: str | None = None) -> OrderAcknowledgement:
    effective_account_id = account_id or order.account_id
    verify_account_binding(self, effective_account_id)
    ...
```

If `self.bound_account_id` does not match `effective_account_id` (or is unset when an explicit ID is passed), `ConfigurationError` is raised.

## 4. Diagnostics & Redaction Contract

All error messages, exception contexts, and log strings must be sanitized using `bandl.core.http._redact_dict` and safe URL helpers:
- Normalize sensitive key names (`api_key`, `access_token`, `authorization`, `secret`, `password`, `jwt`).
- Do not interpolate unfiltered raw HTTP request/response bodies or query strings into exceptions.
- Wrap mutation JSON decoding so invalid JSON surfaces as `UncertainOutcomeError` after dispatch.

## 5. Offline Certification Tests

New provider adapters must include offline tests using `httpx.MockTransport` in `tests/bandl/`:
1. Request body and header assertions (verifying form or JSON encoding and non-truncation).
2. Exactly one mutation call attempt on network timeout or HTTP 503 (zero retries).
3. Proper exception classification (`OrderRejectedError`, `InsufficientFundsError`, `AuthenticationError`, `RateLimitError`).
4. Network isolation verification (no real sockets created).
