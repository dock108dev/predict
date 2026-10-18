# Current-row storage

Ordinary collection persists typed current events, contracts, offers and shared
native depth. This guide describes their ownership, ordering and expiry. See
[architecture](architecture.md) for the application flow and the
[board API](comparison-board-api-contract.md) for transient read identities.

## Ordinary write path

`CurrentService` uses `DatabaseIngressSink` for ordinary database operation. Existing native adapters reconstruct synchronized books in bounded memory; normalized admitted records go directly into `CurrentRowStore`. Aggregate transport strictly decodes one bounded `ParsedAggregateFrame`, preserving exact decimal spellings. The credential-echo check, independent venue/reference admission, existing normalizer, market exclusions and coverage all reuse that frame. The normalizer accepts optional parsed events without serializing and reparsing the response. Aggregate admission supplies its accepted venue records and selected-reference records. A SQL transaction publishes all affected records, source statuses and native depth before acknowledging a saved observation. SQL failure leaves the previous rows intact, returns the failure and exposes an unavailable persistence status. There is no raw retry queue or file spill.

| Relation | Owner and lifetime |
| --- | --- |
| `current_row_epoch` | Current data/reset generation; app and data restarts preserve it. Runtime identity and fresh exact dependencies independently invalidate old selections. |
| `current_event` | One exact provider/event mapping, compact allowlisted sporting and occurrence-witness facts, pregame start expiry. |
| `current_contract` | One exact venue/provider/event/market/outcome/native-side selection, including selections with no offer. |
| `current_offer` | One actual current offer for a contract; exact price and units, source and receipt clocks stored separately. |
| `current_native_book` | One synchronized native book header, outcome presence, original sequence and clocks. |
| `current_native_depth` | Exact ordered bids and asks stored once per native book/outcome/side/level. |
| `current_depth` | Optional non-native normalized depth; native asks are reconstructed from shared native depth. |
| `current_source_status` | Bounded latest source status, without full response bodies. |
| `current_refresh_scope` | Latest authoritative exact-scope ordering guards; expires after 48 hours and has an explicit capacity. |

Migration `012_current_rows.sql` defines these working tables. They are independent of protected provider account, quota, audit, reservation and financial authority records.

Current snapshots and calculation results are not persisted by this owner. Shared financial definitions and user configuration retain their existing separate owners. `capture(include_depth=False)` supplies a coherent repeatable-read metadata frame and semantic dependencies. MVCC binds reads without taking the writer advisory lock; catalog construction cannot hold that write lock. A standalone capture starts its own repeatable-read, read-only transaction; ordinary API callers provide an existing repeatable-read transaction through selected-depth hydration. `hydrate_records` reads only selected execution ask ladders; its caller binds the expected revision before/after hydration. The API integration owner provides the transient calculation and Details context.

The independent background runtime publishes bounded latest results through
migrations 013–015. `data_runtime` and its bounded command relation provide source
status, heartbeat, material revisions and actual control acknowledgments.
`scanner_latest` replaces one compact typed projection (32 MiB cap);
`latest_board` replaces up to 500 compact game rows (64 MiB total), with one
status publication. Inputs, raw source bodies and expanded reports are excluded.
The [runtime contract](data-app-runtime-contract.md) specifies authority, failure,
retention and app-read behavior. Existing protected owners remain separate.

## Bounded ordered SQL writes

`upsert_records` and `replace_native_books` pipeline their ordered SQL commands inside their existing transactions. Every SELECT/fetch barrier, input order, source/receipt comparison, equal-clock conflict check and authoritative-scope guard remains in place. There is no batch prefetch or change to transaction boundaries, schema or current-fact meaning.

The private helper explicitly synchronizes after every 128 counted commands and again before its method exits, delivering delayed SQL errors before transaction completion or the [postcommit observation](scanner-projection-contract.md). A failure rolls back the transaction. Existing fetches can flush sooner. Closed-market withdrawal statements run in the same native-book transaction outside that counter; a following fetch or the final synchronization flushes them. The 128-command threshold therefore describes the helper's counted commands, rather than an exact limit on every physical statement. Protected account, quota, audit, reservation and financial state retain their separate owners.

## Ordering, removals and expiry

Selected Kalshi contract facts may retain exact-present price ranges, price
structure and face value from the already-owned discovery response. Their
16 KiB observation cap, original discovery receipt/body proof and material hash
are separate from book/source clocks. Missing/null/oversized values stay explicit;
these unreviewed observations grant no legal quantity, cost, execution-channel
or settlement applicability. Metadata changes invalidate contract dependencies
without rewriting the quote's price or original clocks.

Known source clocks precede receipt ordering. Older source observations and unknown clocks attempting to replace known source evidence are rejected. Equal source/receipt clocks cannot identify conflicting prices or books. Receipt-only observations retain the source timestamp and semantic dependency revision; source, price, units, contract and depth changes invalidate the appropriate dependencies.

Event schedules have separate metadata authority. Native catalog admission retains
the exact schedule-bearing event or linked milestone response path, row, body hash
and metadata receipt, independently of book source/receipt clocks. Current contracts
retain their original derived start and schedule witness. A newer book cannot rank
or replace a newer schedule witness. A newer metadata witness can update the shared
event even when the accompanying price is rejected as older.

Reconstruction reconciles an older derived market start only when both retained
witnesses establish an ordered revision of the same source authority, native event
and occurrence facts. The original contract stays stored unchanged; detached
`schedule_reconciliation` evidence records the original derived start, metadata
revision and current witness. Equal-clock contradictions, incompatible occurrence
facts and legacy starts without the earlier witness remain unavailable. No title,
ticker, arbitrary contract order or price receipt supplies a missing date or
schedule authority. Missing original/rescheduled context stays unknown.

Explicit legacy recovery can use an already-retained complete SQL capture only
when its entire raw contract still matches the current stored contract and its
event preserves the exact native milestone/occurrence identity and original
derived start. The capture time is labelled `observed_no_later_than`, an upper
bound on the earlier observation, with a capture-file hash and row revisions;
`received_at` remains null. A strictly later ordinary native metadata receipt
must independently confirm the same authority before reconstruction can reconcile
the starts. Recovery updates only the contract's provenance binding. It never
inserts expired contracts, restores offers or edits event schedules, prices,
depth, book headers or quote clocks. A changed contract, wrong witness, missing
current authority or overlapping time bound refuses recovery.

Catalog diagnostics distinguish `schedule_binding_unverified`,
`schedule_equal_metadata_conflict` and `schedule_metadata_order_unverified`, with
bounded exact native keys and conflicting starts. Invalid occurrences remain
isolated; valid occurrences continue publishing. Previous obsolete frames retain
their captured inputs until valid replacements exist. Reconciliation dispatches
no providers, changes no original price/depth/clock and cannot extend an expired
offering around its old book.

Only admitted complete refresh scopes remove absent contracts. Aggregate scopes identify venue and sport. Native scopes additionally identify the exact event and market. Errors or incomplete/unknown-state books cannot clear healthy offers. A complete native book can retain exact selections while removing only missing offers. Material native predicate/identity/terms changes withdraw the previous exact market until a fresh image arrives. Partial discovery absence alone does not authorize removal.

Pregame rows expire at scheduled start; explicit completed/final/settled/cancelled event statuses expire immediately. Cascading ownership removes dependent offers, contracts and depth. Configured sport/family changes retire out-of-scope rows at startup. A small 60-second maintenance task performs expiry only, stops after three failures and joins on Stop.

## Compatibility readers and reset

Ordinary startup and `DatabasePipeline` do not reopen journals, restore aggregate diagnostics, import archived snapshots or publish saved calculation results. Both automatic and manual aggregate paths discard response bodies after admission. Provider consumed attempts, charge headers, original response hashes, quota and independent account audit have separate protected owners.

Legacy codecs/readers remain available to separately selected retained/research paths. Their presence does not create an ordinary startup writer. `storage/current_reset.py` coordinates the explicit sports-only reset. Ingress and startup do not reset owner storage.

## Scanner readiness, results and commit observations

The ordinary readiness route inventories the same current facts without finance.
The background scanner owns readiness preparation, affected pair calculations,
compact results and summaries; the app reads its latest PostgreSQL publication.
Selected tickets prepare only their exact current members. The process-local
commit callback supplies optional genuine commit measurement; correctness uses
committed offer/book plus event/contract/status revisions, runtime identity and
engine/policy facts across processes. Pre-start or foreign commit timing remains
unknown rather than invented.

Current-row writers, explicit market withdrawals, expiry and final derived
publication share advisory transaction lock 901095. Financial work happens before
that lock. The final comparison rejects superseded work, and readers independently
withdraw stale bindings before the worker catches up. App startup does not write
epochs, reset data or start acquisition. See the
[projection contract](scanner-projection-contract.md) and
[latest-result contract](data-app-runtime-contract.md).
