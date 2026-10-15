# D03 current-row write and storage ownership

October 15, 2026. This map records the completed D03 current ingress/storage ownership and its original qualification. Exact end-to-end cutover, current-read/client, reset and installed evidence belong to the dated D03 closeout. Later SSOT and cleanup integration retains these storage semantics; its source identity and installed handover are assessed separately. This document does not transfer earlier runtime evidence to a newer candidate.

## Ordinary write path

`CurrentService` uses `DatabaseIngressSink` for ordinary database operation. Existing native adapters reconstruct synchronized books in bounded memory; normalized admitted records go directly into `CurrentRowStore`. Aggregate transport strictly decodes one bounded `ParsedAggregateFrame`, preserving exact decimal spellings. The credential-echo check, independent venue/reference admission, existing normalizer, market exclusions and coverage all reuse that frame. The normalizer accepts optional parsed events without serializing and reparsing the response. Aggregate admission supplies its accepted venue records and selected-reference records. A SQL transaction publishes all affected records, source statuses and native depth before acknowledging a saved observation. SQL failure leaves the previous rows intact, returns the failure and exposes an unavailable persistence status. There is no raw retry queue or file spill.

| Relation | Owner and lifetime |
| --- | --- |
| `current_row_epoch` | One runtime/reset generation, rotated transactionally on ordinary startup; an earlier process cannot recreate an old Details context. |
| `current_event` | One exact provider/event mapping, compact allowlisted sporting and occurrence-witness facts, pregame start expiry. |
| `current_contract` | One exact venue/provider/event/market/outcome/native-side selection, including selections with no offer. |
| `current_offer` | One actual current offer for a contract; exact price and units, source and receipt clocks stored separately. |
| `current_native_book` | One synchronized native book header, outcome presence, original sequence and clocks. |
| `current_native_depth` | Exact ordered bids and asks stored once per native book/outcome/side/level. |
| `current_depth` | Optional non-native normalized depth; native asks are reconstructed from shared native depth. |
| `current_source_status` | Bounded latest source status, without full response bodies. |
| `current_refresh_scope` | Latest authoritative exact-scope ordering guards; expires after 48 hours and has an explicit capacity. |

Migration `012_current_rows.sql` adds these independent working tables. Applied migrations 009–011 and their checksum history are unchanged. None of these tables references protected provider account, quota, audit, reservation or financial authority.

Current snapshots and calculation results are not persisted by this owner. Shared financial definitions and user configuration retain their existing separate owners. `capture(include_depth=False)` supplies a coherent repeatable-read metadata frame and semantic dependencies. MVCC binds reads without taking the writer advisory lock; catalog construction cannot hold that write lock. A standalone capture starts its own repeatable-read, read-only transaction; ordinary API callers provide an existing repeatable-read transaction through selected-depth hydration. `hydrate_records` reads only selected execution ask ladders; its caller binds the expected revision before/after hydration. The API integration owner provides the transient calculation and Details context.

## Ordering, removals and expiry

Known source clocks precede receipt ordering. Older source observations and unknown clocks attempting to replace known source evidence are rejected. Equal source/receipt clocks cannot identify conflicting prices or books. Receipt-only observations retain the source timestamp and semantic dependency revision; source, price, units, contract and depth changes invalidate the appropriate dependencies.

Only admitted complete refresh scopes remove absent contracts. Aggregate scopes identify venue and sport. Native scopes additionally identify the exact event and market. Errors or incomplete/unknown-state books cannot clear healthy offers. A complete native book can retain exact selections while removing only missing offers. Material native predicate/identity/terms changes withdraw the previous exact market until a fresh image arrives. Partial discovery absence alone does not authorize removal.

Pregame rows expire at scheduled start; explicit completed/final/settled/cancelled event statuses expire immediately. Cascading ownership removes dependent offers, contracts and depth. Configured sport/family changes retire out-of-scope rows at startup. A small 60-second maintenance task performs expiry only, stops after three failures and joins on Stop.

## Retired ordinary archives

`CurrentService` neither constructs nor reopens `CurrentJournal`; the former retention callback and diagnostic bootstrap task are removed. `DatabasePipeline` has no journal catch-up, import-cursor advance, diagnostic bootstrap, saved snapshot calculation or result publication. Startup never restores aggregate diagnostics. Both automatic and manual aggregate paths discard response bodies after admission and do not write sports diagnostic/baseline files. Provider consumed attempts, charge headers, original response hashes, quota and independent account audit continue through their existing protected owners.

The ordinary SQL ingress accepts admitted aggregate records and native/health observations only. Raw aggregate payloads and legacy batch wrappers are rejected explicitly. `current_aggregate_admission.py` owns shared parsing/normalization; SQL publication cannot independently re-admit raw responses. The expiry lifecycle has no import switches, journal catch-up helper or saved-calculation request method.

Legacy codecs/readers remain available to separately selected retained/research paths. Their presence does not create an ordinary startup writer. The lead's sports reset allowlist coordinates discarded old SQL and files; this ingress slice does not reset owner storage itself.

## Focused evidence

The final affected ingress/matching/financial subset passes 49 checks in 4.639 seconds: 14 disposable PostgreSQL current-store/direct-ingress/lifecycle/concurrency/projection checks, six SQL occurrence witness vectors, one authentic SQL financial roundtrip, seven strict parse-once checks, 12 unchanged N01 financial cases and nine unchanged odds-sample cases. This subset is included in the lead's 89 affected Python checks. Final log: `test-results/d03-current-rows-20261015/matching-runtime-financial-tests.log`.

Tests cover bounded unchanged/receipt rows, semantic replacements, stale/unknown/equal-clock conflicts, scoped partial/authoritative removal, one-sided native selection presence, shared bid/ask depth, expiry/empty use, direct native/aggregate publication, failed SQL without acknowledgment or spill, restart without journal/diagnostic access, a concurrent writer committing while a coherent MVCC reader remains open, exact original projection/source/receipt clocks, one strict aggregate decode and full-row normalizer equivalence, numeric spelling, independent venue errors and JSON rejection.

The authentic SQL roundtrip compares complete existing-owner single/pair metrics, funding, exact canonical native identity and selected depth. It exposed missing resolver witnesses in the initial allowlist; the final compact facts hoist named shared provider IDs, game number, original start, replacement/reschedule and neutral-venue state without raw events. Six repeated-opponent/shared-namespace/role/neutral/reschedule vectors preserve resolver method, occurrence ID, membership, conflicts and candidates.

Startup rotates the single epoch transactionally with configured-scope retirement while preserving prices and original clocks; failed startup does not rotate it. Declared projection timestamps survive and absent older projection remains explicit `None`, never fabricated receipt time. The lead's exact 500-event working-data run and actual installed Stop/reopen prove their separate resource/runtime scopes.

Historical research `tests/test_odds_acquire.py` has 20 setup failures because `evidence/source-bindings-20260929/proposal.json` is absent; no provider dispatch occurs. The missing historical fixture was not reconstructed. This does not replace the passing ordinary parse-once/current-row checks or claim full unrelated CI.
