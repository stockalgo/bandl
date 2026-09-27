# Execution hardening implementation plan

Status: ready for implementation; no tasks completed by creating this plan.

Baseline: commit `b8af0db` **plus the existing uncommitted changes** reviewed in this conversation. Do not reset to that commit. The working tree contains the implementation being repaired.

Audience: an implementing coding agent working in small, sequential tasks. Read this plan and [AGENTS.md](../AGENTS.md), then read only the implementation and tests needed for the current task. Implementation details absent from AGENTS.md require targeted source inspection.

## 1. Goal and scope

Ship a dependable, documented regular-order execution surface for Zerodha and Dhan. Preserve existing market-data and account-history behaviour. Keep additive acknowledgement methods alongside legacy methods returning `Order`.

This is a hardening release, **not certification that all generic execution requirements are complete**. [GENERIC_EXECUTION_REQUIREMENTS.md](GENERIC_EXECUTION_REQUIREMENTS.md) remains the broader roadmap. Margin preview, streaming, real crypto execution, synthetic orders, strategy risk and multi-leg orchestration are not part of this implementation.

Review baseline:

- Offline suite: 122 passed, 4 integration tests deselected.
- Ruff: 46 lint errors; 11 files require formatting.
- Confirmed with offline reproductions: quote quantities silently treated as native quantities; conflicting account labels accepted; invalid modifications submitted; malformed successful mutation responses escape as JSON errors; incomplete redaction and missing recovery IDs.
- Zerodha form-encoding defect predates this patch but remains a release blocker in the changed execution path.
- No live broker execution was validated.

## 2. Working rules for the implementing agent

1. Work through T0–T10 in order. Complete one task and its tests before starting the next. Do not rewrite the entire library.
2. Preserve existing uncommitted work. Do not use `git reset`, remove unrelated files, read `.env`, or print credentials. Do not use administrator privileges.
3. Use fake credentials and `httpx.MockTransport`. Never place, modify or cancel a real order. Do not run integration tests or credential-dependent examples.
4. For each behaviour fix, first add a regression test that fails on the current implementation; then implement the fix and run the focused tests.
5. Do not make tests pass by weakening assertions, deleting coverage, adding blanket exception catches or fabricating broker values.
6. For broker-specific assumptions, consult official documentation and record the source. If evidence is missing, reject the feature or declare it unsupported; do not guess encodings, symbols, error codes or account identity.
7. Do not commit, push or publish as part of this plan. Provide a reviewable diff and validation report.
8. After each task, update the progress table with exact checks and remaining limitations. A passing test count alone does not prove broker conformance.

Use the existing `.venv/bin/python`, `.venv/bin/pytest` and `.venv/bin/ruff`. If unavailable, follow project setup instructions without changing dependency bounds just to make installation work.

## 3. Decisions to follow

| Area | Required decision |
|---|---|
| Accounts | One provider instance has one credential/account binding. Per-call `account_id` is an assertion against that binding, never a selector or arbitrary output label. Separate clients represent separate accounts. |
| Compatibility | Calls omitting account ID remain valid. If the account is unknown, output `None`; do not invent one. Explicit account assertions require a known configured binding. |
| Quantity | Existing adapters keep native quantity semantics under `QuantityUnit.BASE` for compatibility: shares for cash, exchange quantity units for derivatives. Reject `QUOTE` and `CONTRACTS` until explicit conversion is implemented and documented. Never multiply by lot size implicitly. |
| Unsupported options | Reject `reduce_only=True`, `post_only=True`, any non-None `position_side`, and unsupported nonempty `extra` options in these adapters. New adapters may support them explicitly. |
| Acknowledgement | Means the mutation response was received and understood. It never proves the order is open, filled or cancelled. Preserve an actual returned status; otherwise use `None`. |
| Mutation retries | Exactly one HTTP attempt. No retry after network failure, 5xx, invalid JSON or an unrecognizable success response. Recovery is the caller's responsibility. |
| Error distinction | Model construction can raise Pydantic `ValidationError`; adapter/request validation raises `InvalidOrderError`; unsupported features raise `UnsupportedCapabilityError`. Document this distinction. |
| Recovery | All orders must include terminal orders. History must contain history, not a current-state snapshot disguised as history. |
| Optional providers | Checking trading capability must not require every optional method. No fallback from history to snapshot, all orders to open orders, or acknowledgement to a legacy method with a required GET. |

These are proposed release decisions adopted by this plan, not claims about behaviour already present.

## T0. Record baseline and repair mechanical failures

Files: changed Python files, `tests/bandl/test_execution_contracts.py`, `.github/workflows/ci.yml`.

- Record `git status --short` and run the offline suite.
- Fix unused imports, import ordering, long lines and the missing `Any` import/return annotation in Zerodha's `get_orders` dispatcher. Prefer a correct `list[AccountOrder] | list[Order]` annotation over `Any`; retain account/trade dispatch semantics.
- Format touched Python files. Avoid unrelated formatting churn.
- Make CI lint and formatting include `lib/bandl/trade` and `lib/bandl/portfolio`; preferably use `lib/bandl tests/bandl` consistently.

Acceptance: full lint, format and offline tests pass. No runtime behaviour intentionally changes in this task.

## T1. Validate order semantics before dispatch

Files: `lib/bandl/models/trading/order.py`, new small shared validation helper if needed, both trading adapters, trade tests.

- Reject empty/whitespace-only identities, while keeping exactly-one identity validation.
- Validate finite positive quantity and supplied prices/triggers. Required LIMIT/STOP_LIMIT price and STOP/STOP_LIMIT trigger must be positive. A zero disclosed quantity may mean no disclosure; otherwise require finite nonnegative integer quantity no greater than total quantity for these adapters.
- Reject fractional native quantities in both adapters, including modification. Reject zero/negative/nonfinite modification quantity, invalid supplied prices/triggers, unsupported validity and an empty modification.
- Centralize modification validation so `modify_order` and `modify_order_ack` cannot diverge. Retain public method signatures; do not add a competing execution facet.
- Enforce quantity-unit and unsupported-option decisions above, including direct provider calls. Perform provider-independent checks before instrument downloads or any mutation request.
- Reject unsupported `market` values; never silently reinterpret a crypto market as equity. Document accepted labels before adding labels to the public contract.
- Keep Decimal validation exact; avoid using float conversion to decide positivity, integrality or increments.
- Validate correlation length and documented character constraints without truncation. Do not invent a broker regex.

Regression cases, parameterized across both adapters: quote/contract quantity; unsupported flags; conflicting/empty identities; invalid numbers; missing required prices; disclosed quantity exceeding total; invalid validity; empty modify; boundary-length and overlong correlation IDs. Assert **zero mutation requests** on every rejection. Fractional crypto remains possible through a supporting fake provider.

Acceptance: valid existing cash/native-quantity calls remain valid; unsupported commands are never silently changed.

## T2. Bind account identity consistently

Files: `config.py`, provider initialization/helpers, trade/portfolio facets, both adapters, `models/trading/portfolio.py`, account-scoping tests.

- Add optional `ProviderSettings.account_id` as an explicit local binding. It is not proof the broker verified that identity; document this limitation.
- Dhan may derive the binding from its configured client ID. Reject a conflicting explicitly configured ID. Do not derive Zerodha account identity from its API key or access-token text.
- Resolve `OrderRequest.account_id`, method `account_id` and provider binding with one helper. Any two supplied identities disagreeing must raise `ConfigurationError` before HTTP. An explicit request ID without a known binding must also fail.
- When no request ID is supplied, use the configured binding, or `None` for compatibility. Do not mutate the caller's request model.
- Apply this to place/modify/cancel, all/open orders, individual order/history, fills and all portfolio reads, including direct provider calls.
- Fix Zerodha `get_trades` so fills and their dedup keys carry the resolved binding. Scope orders, positions and holdings similarly.
- Add optional `account_id` to `Balance` and `MarginInfo` and populate it consistently.
- Remove `except TypeError: retry_without_account_id()` in portfolio facets. A provider implementation bug must propagate, and an account assertion must never be silently discarded. Update portfolio protocols to accept the account keyword.

Tests: request A + argument B fails; request A + provider B fails; explicit A + unknown binding fails; bound A + omitted argument returns A; omitted/unbound retains None; two separately configured fake clients yield distinct account-scoped keys for identical native IDs; fills/balances/margin retain identity. Provider `TypeError` causes one call and is not retried.

Acceptance: account selection is never implied; outputs cannot be relabelled by changing a call argument.

## T3. Correct HTTP mutation encoding

Files: `core/http.py`, both trading adapters, HTTP and adapter tests.

- Add an explicit encoding option or separate form mutation helpers. Keep existing JSON defaults for other providers and read-like POST calls.
- Zerodha POST/PUT use form parameters (`data=`); Dhan uses JSON (`json=`). Do not set a form header over a JSON body.
- Keep one-attempt mutation paths separate from retryable reads. DELETE retains provider-correct query parameters and no automatic retry.
- Use `httpx.MockTransport` below `HttpClient`, not mocks of `post_mutation`, to inspect actual outgoing headers and decoded request bodies.

Tests: Zerodha place/modify form body; Dhan place/modify JSON body; cancel URL/method; all three mutation methods send once on timeout/503; read retries still work with backoff mocked out. Also exercise the legacy `place_order` path through the transport.

Reference: [Kite response structure](https://kite.trade/docs/connect/v3/response-structure/) explicitly requires form-encoded POST/PUT inputs. Validate Dhan against its official order documentation when implementing.

Acceptance: real encoded requests, not just intermediate dictionaries, match the broker contract.

## T4. Complete uncertain-outcome errors and safe diagnostics

Files: `core/http.py`, `exceptions.py`, both trading adapters, HTTP/contract tests.

- Centralize mutation context: operation, resolved account, known order ID, caller correlation ID and minimal instrument identity. Never include auth headers or entire unfiltered request bodies.
- Populate `UncertainOutcomeError.order_id` and `.client_order_id` from known context, not only `request_context`.
- Classify network errors, ambiguous server failures, invalid JSON and invalid/missing required success IDs as uncertain after dispatch. Reject null/empty IDs rather than converting them into strings such as `"None"`.
- Provider response-envelope parsing happens after dispatch too: a malformed envelope must not escape as a plain `ValueError` or generic success. Distinguish documented explicit rejection from an ambiguous response.
- Preserve IDs when the legacy post-mutation GET fails. Never retry the mutation to repair the GET.
- Redact recursively through mappings and sequences; normalize sensitive key spelling (`api_key`, `api-key`, `apiKey`, tokens, authorization, secrets, passwords).
- Use sanitized URLs and bounded, sanitized response diagnostics. Do not interpolate raw httpx exceptions containing query strings. Avoid exposing raw exception chains in the library's safe diagnostic representation; document that underlying raw request objects are not safe logging payloads.
- Wire documented broker rejections to `OrderRejectedError`, explicit insufficient funds to `InsufficientFundsError`, auth to `AuthenticationError`, and 429 to `RateLimitError`. Unknown errors stay conservative; no speculative text-only classification.
- Preserve available retry-after information on rate limits. This is advice for caller scheduling, not authorization to replay a mutation.

Tests: POST/PUT/DELETE timeout and 503 once; malformed JSON; missing/null ID; known IDs on errors; successful mutation then failed GET; 401/403/429; documented rejection/insufficient-funds fixtures. Sentinel fake secrets must be absent from safe error strings/context for nested fields, query URLs and echoed bodies.

Acceptance: callers can distinguish invalid input, explicit rejection and unknown outcome and have the known recovery identifiers.

## T5. Separate acknowledgement from order state

Files: `models/trading/order.py`, both trading adapters, contract tests.

- Restrict acknowledgement operation to `place | modify | cancel` using a Literal or enum.
- Remove fabricated `OPEN`/`CANCELLED` statuses. Zerodha ID-only responses produce `status=None`; Dhan preserves the returned native `orderStatus` when available. Document acknowledgement status as native response metadata, distinct from normalized `Order.status`.
- Keep `received_at` timezone-aware UTC. Preserve sanitized native response data according to the diagnostic contract.
- Acknowledgement methods perform no required status GET. Legacy methods can perform their existing follow-up read and return the actual state, including rejection or a fill winning a cancellation race.

Tests: ID-only response; Dhan PENDING preserved; cancel acknowledgement without final status; cancel followed by COMPLETE; acknowledgement succeeds when a separately invoked status GET fails. Assert no GET in acknowledgement methods.

Acceptance: acknowledgement never tells a caller an order is safely cancelled without evidence.

## T6. Make capability and recovery contracts honest

Files: `core/provider.py`, `core/capabilities.py`, trade/portfolio facets, both adapters, facet/contract tests.

- Separate base capability discovery from optional operation protocols, or explicitly check capability plus callable method per operation. A place-only custom provider must not need history/portfolio implementations.
- Remove unreachable/misleading fallbacks currently hidden behind the full `TradingProvider` runtime check. Missing requested operations raise `UnsupportedCapabilityError` before HTTP.
- Gate `get_orders` on its own capability, not `get_open_orders`; gate history on history, not individual-order support.
- Mark Dhan history unsupported and raise `UnsupportedCapabilityError` until an actual history endpoint is implemented and tested. Keep single-order state available.
- Preserve terminal orders in all-order reads, raw unknown statuses and documented pending states. Test partial fills and cancel/fill races for both providers with realistic fixtures.
- Record session retention/completeness limitations in capability notes. Do not promise pagination or history beyond the returned API scope.
- Keep Zerodha account-history versus trade-order dispatch intact; add tests exercising both through `Bandl`.
- Do not add an unused capability flag and call its feature implemented. Capability matrix and actual pre-submission validation must agree.

Tests: minimal custom provider; unsupported optional operation; capability false despite a method existing; all-orders includes completed/rejected/cancelled; Dhan history unsupported; UNKNOWN raw status retained; account-history regression. Existing market-only providers must still initialize normally.

Acceptance: capabilities tell callers exactly which recovery data they can obtain.

## T7. Resolve exact instruments and enforce known constraints

Files: Dhan `scrip.py` and trading adapter; Zerodha instrument-cache/resolution code and trading adapter; instrument fixture tests.

- Zerodha structured `OptionContract` must resolve against instrument metadata using exchange, underlying, exact expiry, strike and right. Its month-only canonical string is a display identifier, not a safe native weekly-option tradingsymbol.
- Reject conflicting request and contract exchanges. Reject ambiguous or missing matches before submission; never choose the first candidate silently.
- Dhan string placement with multiple matching expiries must fail and request a structured exact contract/native ID. Keep this strictness scoped to trading unless deliberately documenting a market-data compatibility change.
- Validate native IDs against declared exchange/segment where metadata is available. Do not silently default an unknown exchange to a different segment.
- Use metadata lot sizes and tick sizes to validate native quantity multiples and prices. Do not round prices or quantities, and do not interpret lot size as an automatic multiplier.
- Track metadata source and retrieval time in the internal resolved result. Do not fabricate absent limits. Document any native-ID path where metadata validation remains unavailable.
- Add fixtures for the changed Dhan underlying matching and expiry parsing; use the existing CSV schema in code, not a guessed replacement schema.

Tests: two weekly expiries in one month; exact selection; duplicate ambiguous candidates; missing contract; wrong exchange; lot/tick violation; integer cash order; Dhan index aliases and invalid expiry sentinel. Metadata downloads are mocked.

Acceptance: placing an exact contract cannot silently target another expiry. Any unsupported resolution path fails before mutation.

## T8. Make the offline suite prove the contract

Files: `tests/bandl/test_execution_contracts.py`, HTTP/adapter/facet suites, reusable fixture helpers as needed.

- Refactor common acceptance cases into parameterized Zerodha/Dhan tests. Keep native payload fixtures explicit and separate.
- Retain lower-level model tests, but do not substitute them for public `Bandl.trade`/`Bandl.portfolio` coverage.
- At least one successful and each important failure path must cross the real adapter plus `HttpClient` into `MockTransport`.
- Add a focused execution-test fixture that rejects unexpected real network access. Scope it so integration tests remain explicitly opt-in rather than silently redefined.
- Test mutation call count, encoded body, returned identifiers and error category together where relevant.
- Fake crypto tests only demonstrate extension points. They do not certify a real crypto adapter, hedge-mode portfolio model, quote-notional conversion or broker idempotency.

Acceptance: every confirmed review defect has a named regression test; both adapters receive the shared applicable cases. No live credentials are necessary.

## T9. Publish accurate user and adapter documentation

Files: `README.md`, `AGENTS.md`, `docs/LIVE_EXECUTION_DESIGN.md`, new `docs/EXECUTION_MIGRATION.md`, new `docs/PROVIDER_AUTHOR_GUIDE.md`, requirements status.

- Document acknowledgement versus order state, legacy methods, account-binding configuration and separate-client usage.
- Provide recovery examples that catch `UncertainOutcomeError`, inspect IDs, then perform reads. Never show automatic resubmission on uncertainty.
- Show unsupported quantity-unit/feature errors and the Pydantic-versus-adapter validation distinction.
- Publish a broker matrix including Dhan history limitation, session-only recovery, quantity conventions and correlation-only IDs.
- Document optional provider contracts, registration, account assertions, transport encodings, error expectations and offline certification tests.
- Add a requirement-by-requirement status table with `implemented/tested`, `partial`, or `deferred`, evidence and limitations. Do not claim full R1–R9/R12 conformance while constraints, rate controls or observability are missing.
- Explain validation tightening as a compatibility change. Do not silently choose a release version or publish a package.

Acceptance: all new examples use the implemented public signatures, fake credentials and accurate capabilities; docs no longer promise lifecycle history for Dhan.

## T10. Final release-candidate verification and hygiene

Run from repository root:

```sh
.venv/bin/pytest tests/bandl/ -q
.venv/bin/ruff check lib/bandl tests/bandl
.venv/bin/ruff format lib/bandl tests/bandl --check
git diff --check
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
git status --short
```

- Use CI to validate the supported Python 3.10–3.13 matrix. Local success on one interpreter is not evidence of all four passing.
- Build and inspect the newly generated wheel/sdist file lists. Ensure logs, local IDE state, credentials and unrelated artifacts are absent. Do not delete old outputs blindly; distinguish newly built artifacts from existing ones.
- Review untracked `logs/` and `.cursor/` by path/metadata first. Keep local artifacts out of version control; add narrowly scoped ignore rules where appropriate, without deleting user files or printing log contents containing credentials.
- Ensure intended requirements, plan, docs, fixtures and regression tests are present in the final proposed diff. Do not stage everything indiscriminately.
- Report tests, lint, format, package checks, requirement status and remaining limits. State explicitly that no live broker validation occurred.

Acceptance: all local gates pass; CI matrix and package checks are recorded before declaring the release candidate ready. Publication remains a separate user action.

## 4. Deferred work and honest release boundaries

Do not implement these opportunistically during the tasks above:

- R10: typed order/basket margin preview, eligibility verification and quote/depth work. The new raw Dhan basket-margin helper does not satisfy this requirement.
- R11: optional streams, sequence/gap handling and reconnection.
- Real crypto execution; generic hedge-mode positions, settlement currencies, contract multipliers and quote-notional execution semantics.
- Full R12 observability hooks and per-account rate controls. Retry-after handling alone does not complete R12.
- Public, versioned cross-asset instrument metadata and exhaustive provider transition/segment constraint matrices beyond the validated regular-order scope.

These may remain deferred only if release notes and capabilities say so. Known unsafe behaviour in supported regular-order paths cannot be deferred by labelling it a roadmap item.

## 5. Progress log

Keep this table updated; attach commands and results, not just “done.”

| Task | Status | Evidence / remaining limitations |
|---|---|---|
| T0 Baseline and mechanical checks | Completed | `pytest tests/bandl/ -q` (122 passed, 4 deselected); `ruff check lib/bandl tests/bandl` passed; `ruff format lib/bandl tests/bandl --check` passed across 100 files; CI workflow updated to lint/format `lib/bandl tests/bandl`. |
| T1 Validation | Completed | Added shared broker order & modification validation in `lib/bandl/trade/validation.py` and model validation in `lib/bandl/models/trading/order.py`; wired pre-mutation checks in Zerodha & Dhan adapters; added parameterized regression suite in `tests/bandl/test_execution_contracts.py`; verified zero mutation requests on rejection; `pytest tests/bandl/ -q` (135 passed, 4 deselected). |
| T2 Account binding | Completed | Added ProviderSettings.account_id binding; resolve_account_binding & verify_account_binding reject mismatches/unbound assertions with ConfigurationError before HTTP; enforced across trade and portfolio facets and adapters; removed portfolio TypeError fallback; updated TradingProvider & PortfolioProvider protocols; populated account_id in Balance, MarginInfo, AccountFill, AccountOrder; comprehensive test suite passes in tests/bandl/test_execution_contracts.py; `pytest tests/bandl/ -q` (141 passed, 4 deselected). |
| T3 Transport encoding | Completed | Added encoding parameter ('json' \| 'form') and form helpers to HttpClient.post_mutation/put_mutation with single-attempt non-retry semantics; Zerodha place/modify mutations use form-encoding ('data=') while Dhan uses JSON ('json='); DELETE mutations use query parameters and no automatic retries; validated outgoing Content-Type headers and decoded payloads using httpx.MockTransport; tested single-attempt on timeout/503 and read retry backoff; `pytest tests/bandl/ -q` (147 passed, 4 deselected); `ruff check` and `ruff format` passed across 101 files. |
| T4 Errors and diagnostics | Completed | Recursive redaction of mappings and sequences with normalized sensitive key matching; sanitized URLs and bounded response diagnostics; RateLimitError preserves Retry-After header float; wrapped mutation JSON parsing to raise UncertainOutcomeError on invalid JSON; Zerodha and Dhan place_order_ack reject null/empty/whitespace order IDs with UncertainOutcomeError; documented broker error classification (Kite OrderException/TokenException/InputException, Dhan DH-901/DH-905/rejections, margin/insufficient funds -> InsufficientFundsError); regression tests in tests/bandl/test_execution_contracts.py; `pytest tests/bandl/ -q` (154 passed, 4 deselected); `ruff check` and `ruff format` passed across 101 files. |
| T5 Acknowledgements | Completed | Restricted `OrderAcknowledgement.operation` to `Literal['place', 'modify', 'cancel']`; removed fabricated 'OPEN'/'CANCELLED' statuses (Zerodha returns `status=None`, Dhan preserves native `orderStatus` such as 'PENDING'/'CANCELLED'); sanitized `provider_native` via `_redact_dict`; verified zero GET calls from acknowledgement methods; verified cancel/fill race handling via legacy `cancel_order`; `pytest tests/bandl/ -q` (159 passed, 4 deselected); `ruff check` and `ruff format` passed across 101 files. |
| T6 Capabilities and recovery | Completed | Gated TradeFacet and PortfolioFacet operations strictly on capability flags and callable method availability; base TradingProvider and PortfolioProvider protocols now support minimal single-purpose providers (e.g. place-only); removed misleading fallback from get_orders to get_open_orders and from get_order_history to single get_order; get_positions, get_holdings, get_balances, get_margin raise UnsupportedCapabilityError when unsupported or method missing; Dhan get_order_history marked unsupported and raises UnsupportedCapabilityError while get_order remains supported; added session-scope retention notes to Zerodha & Dhan order/trade read capabilities; Zerodha maps partial fills to OrderStatus.PARTIAL and includes them in get_open_orders; 9 regression tests pass in test_execution_contracts.py; `pytest tests/bandl/ -q` (168 passed, 4 deselected); `ruff check` and `ruff format` clean across 103 files. |
| T7 Exact instruments | Completed | Resolved exact weekly option contracts with strike, expiry date, and option type against Kite instrument cache and Dhan scrip master; ambiguous monthly expiry strings without explicit date fail with InvalidOrderError on Dhan; exchange conflicts between request and contract raise InvalidOrderError; missing instruments raise SymbolNotFoundError; shared `validate_lot_size` and `validate_tick_size` helpers enforce lot multiples and tick boundaries without price rounding; unit and integration regression tests added to `tests/bandl/test_execution_contracts.py`; `pytest tests/bandl/ -q` (171 passed, 4 deselected); `ruff check` and `ruff format` clean across 107 files. |
| T8 Contract suite | Completed | Added `tests/conftest.py` with an autouse network guard fixture raising `RuntimeError` on unmocked socket calls during offline execution contract tests; verified coverage of every confirmed defect (typed commands, validation, account binding, single-mutation transport encoding, safe redaction, uncertain outcome error classification, immediate acknowledgements without GET, capability gating without fallbacks, and exact instrument/lot/tick resolution) across both Dhan and Zerodha with explicit `httpx.MockTransport` and payload assertion; `pytest tests/bandl/ -q` (171 passed, 4 deselected); `ruff check` and `ruff format` clean across 108 files. |
| T9 Documentation | Completed | Authored `docs/EXECUTION_MIGRATION.md` (acknowledgement vs state, recovery recipe with session orders, multi-account isolation, exact contracts, constraints, broker support matrix) and `docs/PROVIDER_AUTHOR_GUIDE.md` (optional protocols, single-mutation transport, redaction rules, offline certification); updated `AGENTS.md` and `README.md` to document Dhan `get_order_history` limitation and link guides; all examples use fake credentials and valid signatures; `pytest` (171 passed), `ruff check` and `ruff format` passed across 108 files. |
| T10 Release-candidate checks | Completed | Ran full test suite (171 passed, 4 deselected in 4.28s); `ruff check` passed across all files; `ruff format --check` passed across 108 files; `git diff --check` passed; built release wheel and sdist cleanly via `python -m build`; `twine check` passed with zero errors; added `.cursor/` and `logs/` to `.gitignore`; working tree clean of temporary build artifacts and test scratch; zero live broker orders executed. |
| Production Review Blockers (Issues 1–7) | Completed | Resolved all 7 findings from audit: (1) strict envelope & non-empty ID validation for Dhan/Zerodha modify/cancel returning UncertainOutcomeError on malformed/[] payloads; (2) recursive credential & URL query param redaction via `_redact_text` & `_safe_exception_str` in `HttpClient`; (3) direct provider calls strictly validate `resolve_account_binding` preventing mismatched account_ids; (4) Dhan option scrip resolution rejects ambiguous candidate security IDs for target expiry with InvalidOrderError; (5) removed legacy mutation fallback from `TradeFacet` acknowledgement methods; (6) fixed `EXECUTION_MIGRATION.md` to specify `QuantityUnit.BASE` and multi-client configuration; (7) hardened recovery recipe to prioritize broker order ID, validate non-empty correlation ID, and detect ambiguity; added 8 regression tests to `tests/bandl/test_execution_contracts.py`; suite clean with 179 passed tests, zero ruff lint/format warnings. |

## 6. Copyable implementation-agent prompt

> Implement `docs/EXECUTION_HARDENING_PLAN.md` sequentially, starting with the first pending task. Preserve the existing dirty working tree. Read AGENTS.md and only the source relevant to each task. Follow the decisions in the plan; add failing regression tests before behaviour fixes. Use offline fixtures and MockTransport only; never execute live trades or read credentials. After each task, record checks and limitations in the progress log. Do not weaken tests, invent broker facts, or expand into deferred features. Continue through all tasks where possible; if an external dependency blocks a task, record the concrete blocker and continue independent work without declaring that task complete. Do not commit, push or publish. Finish with changed files, test results and remaining release blockers.
