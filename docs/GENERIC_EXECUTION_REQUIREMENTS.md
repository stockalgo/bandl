# Generic multi-broker execution requirements

Date: 2026-09-13 · Status: proposed requirements · Baseline: `b8af0db`

## Objective and current state

Expose one typed, broker-independent Python interface for equities, options, futures, crypto spot and perpetuals. Stolgo and other applications should switch supported brokers/exchanges through configuration, without implementing provider HTTP calls. Generic means shared contracts with explicit capabilities, not identical features across every market.

Bandl already exposes `client.trade` and `client.portfolio`, with regular-order implementations for Zerodha and Dhan. Extend and harden these surfaces; do not introduce a competing execution facet. This document supplements [LIVE_EXECUTION_DESIGN.md](LIVE_EXECUTION_DESIGN.md); its acknowledgement and retry requirements revise the earlier design's mutation semantics. Existing implementations are not evidence of production readiness.

### Findings from this checkout

| Existing code | Gap to address |
|---|---|
| [Provider contracts](../lib/bandl/core/provider.py) and [client](../lib/bandl/client.py) | Trading/portfolio protocols exist, but client construction/configuration uses built-in provider classes. Expose documented custom-provider injection/registration. |
| [Order models](../lib/bandl/models/trading/order.py) | Decimal quantities exist; explicit spot/perpetual market identity, quantity denomination, position side and acknowledgements do not. Exactly-one instrument selection is documented but not enforced by a model validator. |
| [Portfolio models](../lib/bandl/models/trading/portfolio.py) and [entity base](../lib/bandl/models/account/base.py) | INR defaults and product-centric net positions need cross-asset treatment. Dedup keys contain provider/entity/native ID, without explicit account or market scope. |
| [Fill model](../lib/bandl/models/account/fill.py) | Fee currency and maker flag already exist; reuse them. |
| [HTTP transport](../lib/bandl/core/http.py) and [Zerodha trading](../lib/bandl/providers/equity/zerodha/trading.py) | Placement uses retrying POST then a required status GET; quantity/tag truncation and collapsed pending statuses need correction. |
| [Capabilities](../lib/bandl/core/capabilities.py) | Operation-level support exists; detailed market/order constraints, preview and stream capabilities need expansion. |

## Responsibility boundary

**Bandl owns:** provider contracts, authentication, instrument mapping, request validation/encoding, transport, normalized acknowledgements/orders/fills, account snapshots, capabilities, and optional streams.

**Stolgo owns:** strategy decisions, sizing, portfolio risk, execution sequencing, multi-leg coordination, protective-order supervision, durable journals, reconciliation decisions and restart recovery. Bandl supplies the reads and identifiers needed for reconciliation. It does not autonomously resubmit, flatten, or change strategy exposure.

## Required capabilities

| ID | Requirement |
|---|---|
| R1 | **Provider interface:** extend existing contracts with public custom-provider registration/injection. Optional services must not require providers to implement unrelated features. Require explicit broker/account binding for mutations; allow separate clients for multiple accounts at one broker. Scope identifiers/deduplication by account and market where required. No automatic broker fallback. |
| R2 | **Typed commands:** placement, modification and cancellation requests; reuse Decimal prices/quantities and extend enums where needed. Validate exactly one instrument identity, finite positive quantities, required limit/trigger fields, declared quantity units, increments, product and validity. Reject invalid values rather than silently truncating or changing them. |
| R3 | **Exact instruments:** resolve identities to native symbols/IDs using broker metadata, including venue, market type, segment and exact derivative expiry/strike/right. Distinguish spot and perpetual contracts even when both use `BTCUSDT`. Expose metadata version/time and constraints. Reject ambiguous contracts; broker IDs are not portable across providers. |
| R4 | **Immediate acknowledgements:** return a typed mutation acknowledgement containing operation, broker/account identity, correlation ID, available order ID and receive time. Acknowledgement is separate from order state and fills; no required follow-up GET before exposing it. |
| R5 | **Lossless state:** normalized order status plus raw status/reason, requested/filled/pending/cancelled quantities, average fill price, native IDs, product and timestamps. Preserve trigger/modify/cancel pending states. Fill records carry stable broker trade identifiers, quantities, prices and available charges; unavailable values stay unknown. |
| R6 | **Recovery reads:** expose all orders for the available session/range, including terminal orders; single-order state/history; fills by session/order; positions, holdings, balances and margin. Declare pagination, retention, completeness, snapshot timestamps and day/net scope. Open orders alone are insufficient. |
| R7 | **Safe transport:** use provider-correct encoding and bounded timeouts. Never blindly retry place/modify/cancel on timeouts, connection failures or ambiguous server errors. Return structured uncertain-outcome errors with known IDs and request context. Reads may retry with bounded backoff; do not infer safety from HTTP verb alone. |
| R8 | **Correlation and idempotency:** preserve caller identifiers; validate provider length/character constraints without silent truncation. Explicitly distinguish broker-enforced idempotency from correlation-only tags, including scope and retention. Do not promise exactly-once execution. |
| R9 | **Capabilities:** declare support by operation, segment, order type, product, validity and modification transition. Include native conditional/reduce-only features, idempotency, streams, retention and rate limits. Unsupported combinations fail before submission; provider-specific options must be validated and documented. |
| R10 | **Execution context:** add order/basket margin preview with currency, timestamp, assumptions and available interim/final margin detail. Keep fresh bid/ask/depth snapshots in market-data facets. Broker/account eligibility checks must report verified, unsupported or unknown status explicitly. |
| R11 | **Optional streaming:** normalize order/fill updates and quotes while retaining native IDs, event/receive times, sequence information where available, and disconnect/gap events. Reconnect behavior must be explicit; REST snapshots remain available. Preserve the existing synchronous HTTP installation path. |
| R12 | **Errors and observability:** distinguish validation, authentication, unsupported capability, rejection, rate limit and uncertain outcome. Expose safe diagnostics, retry-after and timing hooks; redact credentials. Configure per-account rate controls without claiming coordination across independent processes; Stolgo's gateway owns that coordination. |

## Interface direction

- `client.trade`: place/modify/cancel; all/open orders; order state/history; session/order fills; capabilities; optional updates.
- `client.portfolio`: positions/holdings/balances/current margin; order/basket margin preview.
- Market-data facets: instrument resolution/metadata and quote/depth snapshots; optional quote streams.

New method names require API review. Current mutations return `Order`; introduce acknowledgement semantics through an additive method or a versioned breaking change with migration guidance. Keep legacy behavior documented during transition, while removing unsafe automatic mutation retries.

## Cross-asset requirements

| Concern | Required generic behavior |
|---|---|
| Instrument model | Distinguish equity, option, dated future, spot pair and perpetual. Carry base/quote/settlement currencies, contract multiplier, linear/inverse convention and applicable expiry/strike/right. Derivative-only fields remain optional. |
| Order quantity | Declare base units, quote notional or contract count explicitly. Support fractional crypto quantities and integer/lot contracts, min/max quantity, step size and minimum notional. Never assume quantity is an integer or one contract equals one underlying unit. |
| Execution features | Capability-gate post-only, reduce-only, IOC/FOK/GTC, trigger-price reference (last/mark/index), and applicable position side. No silent fallback to a different order type, price reference or time-in-force. |
| Positions and funds | Represent spot free/locked balances separately from derivative positions/collateral. Support one-way and hedge-mode long/short positions, cross/isolated margin, leverage and available funding/liquidation data. Preserve currency and account/product/position-side identity; do not default unknown currencies to INR or require Indian product labels for crypto. |
| Fees and account events | Preserve commission amount and asset, including fees paid in another token; expose available funding, settlement and margin events. Do not silently convert these amounts or invent absent values. |
| Provider settings | Indian product mappings such as MIS/NRML belong in adapters. Crypto leverage/margin/position-mode changes are explicit capability-gated commands, never hidden side effects of placement. Market-data support alone does not imply trading support. |

Bandl reports these semantics and broker values; Stolgo owns valuation, portfolio risk and simulated accounting.

## Delivery and acceptance

**First release:** R1–R9 and R12 for existing Zerodha and Dhan regular-order adapters. Prioritize current POST retry behavior, acknowledgement-hidden-by-GET failures, quantity/tag truncation, exact options mapping and raw order states.

**Next:** R10–R11 for the Stolgo live deployment requirements; implement a crypto spot/perpetual trading adapter through the same contracts (select Binance or CoinDCX after provider validation). Generic multi-leg orchestration, synthetic OCO, paper fills and strategy risk remain outside Bandl.

Acceptance requires one reusable offline contract suite passing against both adapters, covering:

- Correct native request encoding/mapping and rejection of invalid quantities, prices, identities and unsupported features.
- Accepted mutation with lost response; acknowledgement followed by failed GET; no automatic duplicate mutation.
- Partial fills, rejection, cancel/fill races, unknown raw statuses, repeated/out-of-order updates and complete terminal-order retrieval.
- Account isolation, authentication expiry, rate limits, redacted diagnostics and metadata-driven option resolution.
- Cross-asset fake-provider cases for fractional spot quantities, quote-notional orders, contract multipliers, hedge-mode positions, third-asset fees and unsupported reduce-only/trigger modes. Certify a real crypto adapter against this suite before claiming crypto execution support.

Publish a broker capability matrix, adapter-author guide and migration examples. Tests use broker fakes; document live-validation evidence separately from mocked conformance results.

**Audit validation:** 32 focused offline tests passed across trade/portfolio facets, Zerodha/Dhan adapters, HTTP and capabilities. Source findings above describe remaining requirements, not failures covered by that suite. No live orders or implementation changes were made.
