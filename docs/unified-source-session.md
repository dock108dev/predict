# Unified source-session engineering

The ordinary product owner now carries independent native updates and one shared aggregate worker through Start, running status, Stop, durable finalization, Details, watch evaluation, history and exact cutoff reopening. This is an offline engineering delivery. The default unified activation boundary accepts explicit numeric-loopback mock transports. A real configuration must pass the existing native approval validator with the exact combined spec, candidate, output and allowlisted endpoints before lazy credential resolution. No such approval is created or used here; consumed acquisition attempts are unchanged.

## Source identity

| Source | Selected path | Product role |
|---|---|---|
| Kalshi | Existing native collector | Native comparisons |
| Polymarket US | Existing native collector | Native comparisons |
| Novig | Shared Odds API response | Non-executable aggregate comparisons |
| ProphetX | Same response | Non-executable aggregate comparisons |
| Pinnacle, DraftKings, BetMGM | Same response | Reference inputs only |

`unified-source-session-1` adds a validated policy to the existing `CoverageOwner` / `ContinuousSession` / `TransportSession`. `AggregateWorker` reuses `OddsHTTP` and its conservative budget, response limits, cancellation capture and no-redirect behavior. No second session owner, acquisition runner, history store, math engine, credential loader or scheduler is introduced. Legacy reference-only collection remains unchanged outside unified sessions; unified sessions disable it to prevent duplicate requests.

## Configuration and operation

Ordinary Start accepts `source_settings` only when an isolated aggregate endpoint is configured. The collapsed source settings panel supports sport/implemented market keys, provider event IDs, native event/market IDs, event caps, refresh/stale policy, requests, credits and response/storage bounds. Existing duration controls and native discovery configuration remain authoritative. Native selection filters the existing normalized catalog and never guesses new series/tags. A selected sport absent from that catalog remains unavailable. Empty provider event selection uses a bounded earliest-upcoming ordering; discovery refreshes each scope at the configured cadence. Unsupported MLB six/nine-inning and championship equivalents are rejected as request mappings while their required coverage cells remain visible.

Each Start requires a new quota baseline no older than 60 seconds. The browser saves preferences only; it does not save the include switch or quota baseline. Startup/reopening does not collect. Repeated runs have new session identities and immutable prior journals. Attempts under earlier qualification policies cannot be extended with these settings.

One sequential provider response supplies both comparison books and all three reference books. Requests carry durable consumed/uncertain reservations before dispatch. Missing, duplicated, contradictory or exhausted quota prevents further dispatch; uncertain charges are not refunded. The configured refresh interval is a minimum delay after a bounded cycle, not a delivery-frequency guarantee. Cadence and limits can end aggregate work before the native session ends. Requests, reservations, source state and quota reasons are visible in status and retained. Automatic library-level repeated GETs are disabled.

The aggregate task starts independently of native discovery. Aggregate failures do not stop native feeds, and native stream failures can reconnect within existing connection limits without stopping aggregate updates. Global Stop/duration/storage limits still stop the session. Cancellation is checked before dispatch and after response normalization; partial cancelled responses remain audit evidence and cannot become prices.

## Projection, identity and mathematics

Each admitted event response replaces that event's previous comparison and reference observations. Missing books, removed markets and changed lines therefore cannot leave old quotes in the current projection. A completed discovery removes events outside the current selection. Invalid responses retain earlier inputs with unavailable source health; they do not fabricate empty successful responses. Duplicate rows use the existing binder's deduplication and comparison IDs remain stable across refreshes. All original responses remain in the journal.

Provider timestamps, transport receipts, normalization completion and durable-admission times are separate. Receipt age and provider timestamp age are evaluated independently. Missing/malformed/future timestamps and unknown upstream delay are visible; repeated receipt alone cannot establish source freshness. Saved cutoffs use retained time, never the time they are reopened.

Provider-local comparisons require the same response, event, participant, period and oriented line. Optional `correspondence_policy=source-correspondence-1` also connects reviewed native outcomes to bound aggregate observations in the same session. It checks canonical participants, exact schedule, period, line orientation, predicates and receipt alignment. Source terms, incomplete MLB identity and championship identity remain explicit exclusions. The resulting raw price rows retain each source's cashflow units; aggregate prices never acquire executable size or native fee/settlement qualification. Provider-local rows continue independently. The reference books never enter comparison-leg selection. All 63 required cells remain visible, including the 18 unresolved aggregate mappings.

Explicit `native_scopes` selects native sport/period/family/category independently of aggregate request keys. Each source may use the compact `required-63-v1` selection to retain all 63 cells within the existing Start request bound. This selects requirements; it does not claim that a provider offers them. `/api/source-bindings` exports the per-source ledger, and an optional selected capture/cutoff adds that session's evidence without changing saved observations. See [current bindings](source-bindings-current.md) and [ordinary delivery](ordinary-native-delivery.md) for the current supported discovery and transport policies.

The shared comparator, conditional math, Details/What-if, rankings, watch evaluator and history are reused. Aggregate odds remain raw implied probabilities; unknown fees, execution/depth, active state, settlement and probabilities leave dependent economics unavailable. Watch evaluation retains aggregate exclusions. Unknown state/delay keeps aggregate observations ineligible for source-qualified signals; What-if scenarios remain hypothetical. The completed `math-package-1` is unchanged.

## Durable verification and recovery

Raw response hashes, quota decisions, source versions, rules/math version identifiers, bound records and their registry fingerprints are retained with the existing hash-chained journal. Finalization re-normalizes aggregate snapshots from their exact captured response and checks equality. Current and historical projections use the same reducer. Frozen unified Details have stable saved-cutoff metadata before and after Stop; legacy native-session metadata behavior is preserved.

Interrupted persistence stops admission and publication. The existing read-only recovery inspector now recognizes unified journals, verifies native groups and aggregate dependencies, and limits recovery to the acknowledged chain/byte offset when a storage-failure receipt exists. It never rewrites the original tail or treats recovered bytes as collection authority. `/api/recovery?capture=...&download=true` exports an explicitly incomplete, historical verified prefix. A new Start remains required after restart.

## Verification and external dependencies

See `evidence/unified-session-20260929/` for isolated integrated sessions, exact cutoff/detail/download checks, fault tests, browser proof, source identity and preservation manifests. Simulated sequences are explicitly labeled. Tests applying real retained observations leave their source/receipt timestamps intact; historical records are never relabeled as current venue delivery.

Remaining external facts are unchanged: effective native listing/rule crosswalks; source state/delay guarantees; exact fee/account/rounding/mandatory-charge data; executable depth/minimum/increments/shared-capacity facts; complete contemporary reference probabilities and exceptional-outcome mass; the unresolved period/championship identities and broader real observations. Live unified activation additionally needs an owner-provided exact combined source/candidate/limits approval, an unused explicitly authorized attempt/output, an available credential through the existing Start-time handoff, and genuinely fresh provider quota evidence. The approval and credential gates are implemented but unexercised with real accounts. This delivery provides no live activation, credential access, credit spending, recurring scheduling, outreach, trading or owner acceptance. Beta signoff remains open.

The crash-tail fixture now freezes admission at its declared crash boundary. Without that boundary, a background frame could append after the fabricated torn write before the parent killed the worker, producing interior corruption rather than the tail scenario the test names. Production native collection was not changed for that fixture repair; ordinary native disconnect/recovery is exercised separately by the unified integration suite.
