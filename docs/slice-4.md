# Slice 4 — Kalshi read-only ingestion

Qualified **2026-09-12 UTC** for bounded NFL REST ingestion, authenticated native-book reconstruction and fresh-subscription recovery. **110 offline tests and all four offline examples pass.** This completes Slice 4 within the scope below. Stop before Slice 5. ProphetX remains partially qualified and deferred; no ProphetX investigation or outreach was performed.

## Working implementation

- [Adapter](../app/adapters/kalshi.py): existing `ReadOnlyAdapter` contract, bounded event/market pagination, sports milestones, native YES/NO identities, Decimal books and derived quotes, refreshed market state/rules, series and event fee metadata.
- [Streaming](../app/adapters/kalshi_stream.py): RSA-PSS authentication, dedicated Keychain access, initial snapshot and signed delta reconstruction, subscription sequence checks, invalidation, fresh connections/subscriptions, finite backoff, receipt staleness, cancellation and cleanup.
- [Offline example](../app/kalshi_example.py), [finite verifier](../app/kalshi_verify.py), [protocol tests](../tests/test_kalshi.py), [production replay tests](../tests/test_kalshi_live_replay.py).
- [Artifact manifest](../evidence/slice-4/manifest.json) records exact file hashes. No Git was initialized, and no commits, publishing, orders or fund movements occurred. Existing PLAN, venue implementations and historical evidence are preserved.

## Current official contract

Rechecked the official [REST OpenAPI](https://docs.kalshi.com/openapi.yaml) and [WebSocket AsyncAPI](https://docs.kalshi.com/asyncapi.yaml); saved exact copies under [research](../evidence/slice-4/research). These are mutable specifications; the local hashes identify this qualification's inputs.

| Concern | Contract and implementation |
|---|---|
| Discovery | `/series/{ticker}`, paginated `/events` with `with_milestones=true`, and paginated `/markets` scoped by native event ticker. Default supported series are `KXNFLGAME` and `KXMLBGAME`. Fixed allowlist is intentionally narrower than a sports census. Cursor cycles fail; capped pagination is exposed as truncated. |
| Schedule | Related Sports `football_game` / `baseball_game` milestone `start_date`, with explicit event relationship. Conflicting/missing starts remain unknown and are excluded by default pregame discovery. Expiration, close, settlement and metadata-update times remain separate native metadata. The current NFL milestone schedule was observed live. MLB configuration is implemented but was not independently live-qualified in this slice. |
| Market state | `initialized` → PREOPEN, `active` → ACTIVE, `inactive` → SUSPENDED, `closed`/`determined`/`disputed`/`amended` → CLOSED, `finalized` → SETTLED; unrecognized states → UNKNOWN. Native strings remain in `market_metadata` and raw evidence. Market status is a separately timed REST observation, refreshed by `get_market`; books retain UNKNOWN state because book traffic does not establish current tradability. |
| Prices and quantities | JSON fractional numbers decode directly to Decimal; fixed-point strings parse directly to Decimal. Prices are dollar payout fractions; quantities are contracts, including fractions. REST uses `orderbook_fp.yes_dollars`/`no_dollars`; WS snapshots use `yes_dollars_fp`/`no_dollars_fp`; deltas use `price_dollars` and signed `delta_fp`. No legacy cent/whole-contract fallback. |
| Native sides and quotes | Both native sides are bids. Native `OrderBook` asks stay unavailable, following the shared native-book model. `quotes(book)` derives each ask as one minus the opposite best bid and preserves its contract quantity. The quote source explicitly labels the transformation. Sorting is explicit; response ordering is not trusted. |
| Empty vs unavailable | REST missing/null side → unavailable; empty array → observed empty. WS omission has a different documented meaning: AsyncAPI says the side key is omitted when no offers exist, so omission in a valid snapshot → observed empty. Null WS sides fail. The original sanitized frame retains the distinction between omission and an empty array. |
| Depth | REST defaults to 20 levels per side and is PARTIAL. Explicit depth=0 requests all native aggregated levels. WS snapshots are documented complete aggregated images and have no requested depth window, so reconstructed native depth is FULL. FULL is scoped to that API image, not all exchange liquidity, hidden liquidity, or maximum executable capacity. |
| Rules | Each market's `rules_primary` and `rules_secondary` are retained, along with series contract terms and other native links. `get_market_rules` exposes market-specific text and the official terms link. Overtime, tie, cancellation and cross-venue equivalence are not inferred. |
| Fees | Retain original series metadata, `/series/fee_changes?show_historical=true`, and bounded `/events/fee_changes`, including IDs, scheduled/effective timestamps, overrides and null override clearing. Raw numbers retain Decimal precision. Return truncation explicitly. Effective fee selection, account rounding and a derived fee version remain unknown; no fee engine is implemented. |

References: [order books](https://docs.kalshi.com/api-reference/market/get-market-orderbook), [events](https://docs.kalshi.com/api-reference/events/get-events), [milestones](https://docs.kalshi.com/api-reference/milestone/get-milestones), [market lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle), [event fees](https://docs.kalshi.com/api-reference/events/get-event-fee-changes), [series fees](https://docs.kalshi.com/api-reference/exchange/get-series-fee-changes).

## Reconstruction and independent qualification fields

**SYNCHRONIZED** means a valid current-connection/current-subscription initial image has been accepted and every subsequent subscription sequence through the emitted image is contiguous. For REST it means a valid standalone response with both native sides available; a REST image is never used to seed a WS delta chain. Synchronization does not certify price age, market status, transport health, receipt of history before the initial snapshot or fills.

The client waits for the matching subscribe acknowledgement and binds its server SID. Sequence tracking belongs to that SID across all its markets and sequenced control replies. It is not per ticker or shared across unrelated channels. The production capture corroborates interleaved market sequences and reuse of SID 1 after reconnect. Connection generations therefore remain mandatory even when the SID repeats.

A delta adds its signed quantity to the existing aggregate. Zero removes a level; negative aggregate sizes, duplicate levels, invalid sides/identities, malformed frames, missing images and sequence gaps/duplicates/regressions invalidate the subscription's books. A gap can have affected any market on that SID, so all are invalidated. Recovery closes the connection and makes a new subscription, which yields new snapshots under the [documented protocol](https://docs.kalshi.com/websockets/orderbook-updates). The supported `get_snapshot` action is not required by this implementation; it uses fresh subscriptions instead. Old generation and old SID messages cannot repair or change the current book.

| Field | Meaning and limit |
|---|---|
| Local reconstruction | `BookSync` as defined above; invalidated on disconnect, gap, ambiguity, cancellation and completion. |
| Depth completeness | Per-ladder `Depth`, independent of synchronization. |
| Exchange/source time | Optional delta `ts_ms` is the recorded change time in milliseconds; deprecated RFC3339 `ts` is fallback. Snapshot and REST source times stay absent. Raw sanitized evidence preserves original timestamp precision. A delta timestamp does not date every untouched level. |
| Source progress | FIRST/ADVANCED/REPEATED/REGRESSED/MISSING, with a per-market high-water mark retained across connections. Legacy submicrosecond precision is compared without truncation. Reconnect never advances the source clock by itself. |
| Receipt freshness | RECENT for accepted stream receipts; STALE after a caller-configured local quiet interval (default ten seconds). Heartbeats do not refresh a book receipt. A repeated source change time may have a recent receipt. The threshold is an operational setting, not a measured execution-latency guarantee. Standalone REST/replay freshness stays UNKNOWN. |
| Market state | Separate native metadata observation; no ACTIVE inference from nonempty books, socket traffic or a future schedule. The caller must refresh/evaluate status and schedule before any later scanner eligibility decision. Lifecycle streaming and exchange-wide pause qualification are not claimed. |
| Transport | `transport_health` indicates connected/disconnected lifecycle independently. The WebSocket library handles ping/pong. A quiet old book can remain locally synchronized on a connected socket. |

Returned observations are immutable historical records. Consumers must process emitted invalidations and retire their session state when the iterator closes or is canceled. `engine.last` is invalidated during cleanup; previously retained immutable objects cannot be retroactively changed.

Default adapter limits: two pages of 20 rows, 40 total HTTP attempts including retries, one retry, ten-second HTTP timeout and modest spacing/backoff. Limits are local budgets, not claims about account entitlement. Stream defaults: 30 seconds, 500 frames, two connections, twenty markets maximum, ten seconds for initial images, bounded close time. Total duration/message/connection caps include recovery. Errors and missing credentials do not produce invented market data.

## Actual verification

| Evidence | Actual result |
|---|---|
| [Public REST](../evidence/slice-4/public-20260912/report.json) | Seven HTTP-200 requests. Five pregame NFL events in a truncated discovery page; Atlanta–Pittsburgh selected from the bounded page, scheduled 2026-09-13 17:00 UTC. Both native markets discovered; market rules, contract link, series fee history and event overrides captured. Selected Pittsburgh book had 20 YES and 20 NO levels. No book source timestamp. |
| [First authenticated capture](../evidence/slice-4/authenticated-20260912/report.json) | Seven additional HTTP-200 requests; one production WS connection; acknowledgement and initial snapshot, zero deltas in 30 seconds. This proved access and initial image only. The initial message-count-driven deliberate reconnect did not fire on the quiet book; corrected to a wall-clock trigger. Historical evidence retained. |
| [Timed recovery capture](../evidence/slice-4/recovery-20260912/report.json) | Seven additional HTTP-200 requests. Sixty-second two-market scope, two production connections, deliberate timed disconnect after about twenty seconds. Nineteen sanitized frames: two acknowledgements, four snapshots, thirteen deltas. Sequences interleave both markets within one SID. Fresh snapshots reset connection-local sequence; repeated source timestamps remain REPEATED. No protocol failures recorded. |
| [Cancellation](../evidence/slice-4/cancellation-20260912/report.json) | Zero REST calls. One further connection, acknowledgement and snapshot, then deliberate task cancellation. Socket closed, connection released and cached books invalidated. Ten-second/one-connection upper bound. |
| [Offline tests](../evidence/slice-4/tests.txt) | 110 pass, including 30 Kalshi tests. Decimal/subpenny/fractional arithmetic; side derivation; missing/empty/partial depth; schedule exclusion; pagination and HTTP budgets; signing; synthetic removal/negative levels; multi-market sequences; old generations/SIDs; replayed real frames; deliberate omitted-live-delta gap; clocks; quiet receipt aging; timed reconnect; cancellation and adapter resource ownership. |
| Offline examples | [Shared](../evidence/slice-4/shared-example.txt), [Polymarket US](../evidence/slice-4/polymarket-example.txt), [ProphetX](../evidence/slice-4/prophetx-example.txt), [Kalshi](../evidence/slice-4/kalshi-example.txt): all exit 0. |

Total live market-data work: **21 HTTP attempts, all HTTP 200; four WS connections; 23 retained market/control frames (six snapshots, thirteen deltas, four acknowledgements).** No natural zero-level removal or halt occurred; zero removal and halt/status mappings have offline coverage, not live-event proof. Gap detection was exercised by removing a frame from the saved production replay and through synthetic transport recovery. No order was submitted to generate activity. No continuous-feed reliability or measured tradable latency claim follows.

## Credentials and reruns

The owner completed Chrome login/MFA and supplied the production key. RSA validation and authenticated WS access succeeded. Credentials are stored only by this implementation in macOS Keychain service `prediction-arb.kalshi.production`, account `market-data`, as a JSON key ID/private-key pair. The owner-supplied key is shown as **Full access** in Kalshi's UI; it is not described as a venue-enforced read-only key. This adapter only sends public GETs and market-data WS commands. The unused locally generated candidate private key was removed; the supplied working credential remains in Keychain. No private key, account data, signatures, own-order IDs or subaccount numbers appear in source/captures. The secret supplied in the conversation was not copied into project files.

API use is under the owner's current own-trading authorization and the [existing data-use assessment](kalshi-data-use.md). This records actual API access, not new project-specific venue approval. No support request was sent.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m app.kalshi_example
# Explicit bounded production rerun; use a NEW output directory:
.venv/bin/python -m app.kalshi_verify --public --keychain --seconds 60 --output evidence/slice-4/new-run
# One-connection cancellation verification, reusing saved native discovery:
.venv/bin/python -m app.kalshi_verify --keychain --cancel-from evidence/slice-4/recovery-20260912 --output evidence/slice-4/new-cancel
```

Remaining limits: bounded NFL live coverage; default MLB support not independently captured here; native depth only; status freshness/exchange pauses and continuous reliability not qualified; fee selection/account precision and cross-venue settlement compatibility remain later work. These limits do not reopen bounded Slice 4 or block independent adapters. **Next action: authorize Slice 5 Novig read-only data access and ingestion.** Do not start it under this slice's authorization.
