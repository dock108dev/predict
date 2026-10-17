# Current-row storage

Ordinary collection persists typed current events, contracts, offers and shared
native depth. This guide describes their ownership, ordering and expiry. See
[architecture](architecture.md) for the application flow and the
[board API](comparison-board-api-contract.md) for transient read identities.

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

Migration `012_current_rows.sql` defines these working tables. They are independent of protected provider account, quota, audit, reservation and financial authority records.

Current snapshots and calculation results are not persisted by this owner. Shared financial definitions and user configuration retain their existing separate owners. `capture(include_depth=False)` supplies a coherent repeatable-read metadata frame and semantic dependencies. MVCC binds reads without taking the writer advisory lock; catalog construction cannot hold that write lock. A standalone capture starts its own repeatable-read, read-only transaction; ordinary API callers provide an existing repeatable-read transaction through selected-depth hydration. `hydrate_records` reads only selected execution ask ladders; its caller binds the expected revision before/after hydration. The API integration owner provides the transient calculation and Details context.

Planned data/app separation adds a distinct bounded latest-result owner for
background shared calculations; it is not implemented by the current ingress
tables above. Results replace current derived rows and carry source/dependency,
engine/policy, expiry and scope-completeness facts. Expanded reports and raw feed
history remain excluded. An app-only restart must not rotate `current_row_epoch`
or reset ingestion. Existing source, account, quota and hold lifetimes stay separate.

## Bounded ordered SQL writes

`upsert_records` and `replace_native_books` pipeline their ordered SQL commands inside their existing transactions. Every SELECT/fetch barrier, input order, source/receipt comparison, equal-clock conflict check and authoritative-scope guard remains in place. There is no batch prefetch or change to transaction boundaries, schema or current-fact meaning.

The private helper explicitly synchronizes after every 128 counted commands and again before its method exits, delivering delayed SQL errors before transaction completion or the [postcommit observation](scanner-projection-contract.md). A failure rolls back the transaction. Existing fetches can flush sooner. Closed-market withdrawal statements run in the same native-book transaction outside that counter; a following fetch or the final synchronization flushes them. The 128-command threshold therefore describes the helper's counted commands, rather than an exact limit on every physical statement. Protected account, quota, audit, reservation and financial state retain their separate owners.

## Ordering, removals and expiry

Known source clocks precede receipt ordering. Older source observations and unknown clocks attempting to replace known source evidence are rejected. Equal source/receipt clocks cannot identify conflicting prices or books. Receipt-only observations retain the source timestamp and semantic dependency revision; source, price, units, contract and depth changes invalidate the appropriate dependencies.

Only admitted complete refresh scopes remove absent contracts. Aggregate scopes identify venue and sport. Native scopes additionally identify the exact event and market. Errors or incomplete/unknown-state books cannot clear healthy offers. A complete native book can retain exact selections while removing only missing offers. Material native predicate/identity/terms changes withdraw the previous exact market until a fresh image arrives. Partial discovery absence alone does not authorize removal.

Pregame rows expire at scheduled start; explicit completed/final/settled/cancelled event statuses expire immediately. Cascading ownership removes dependent offers, contracts and depth. Configured sport/family changes retire out-of-scope rows at startup. A small 60-second maintenance task performs expiry only, stops after three failures and joins on Stop.

## Compatibility readers and reset

Ordinary startup and `DatabasePipeline` do not reopen journals, restore aggregate diagnostics, import archived snapshots or publish saved calculation results. Both automatic and manual aggregate paths discard response bodies after admission. Provider consumed attempts, charge headers, original response hashes, quota and independent account audit have separate protected owners.

Legacy codecs/readers remain available to separately selected retained/research paths. Their presence does not create an ordinary startup writer. `storage/current_reset.py` coordinates the explicit sports-only reset. Ingress and startup do not reset owner storage.

## Scanner readiness reads

SC01's isolated successor adds a bounded, repeatable-read, read-only readiness inventory over these same current relations. It separates discovered contracts from priced instruments, preserves original source/book/receipt clocks and resolves shared model definitions transiently. It creates no readiness table, report cache, raw envelope archive or new migration. Existing upserts, ordering, expiry and protected-state ownership remain unchanged. The successor route is `/api/boards/readiness`; see the [readiness schema](contracts/predict-scanner-readiness-1.schema.json). The local SC01 closeout records the exact candidate and verification boundary. The ordinary installation has not been changed to include that route.


## Scanner projection and commit observations

SC02 adds one bounded process projection over detached read-only captures. Financial work runs after the SQL transaction/connection closes; cached scalar results and current inputs replace in place. A successor ingress wrapper records a genuine observation after successful top-level commit, tied to exact current-row revision; nested/rollback/foreign/pre-start cases remain unknown. Readiness v1 keeps `sql_committed_at=null`. No new SQL table/migration, raw-response archive or per-filter financial report is introduced. Scanner protocol and bounds: `docs/scanner-projection-contract.md`. The ordinary installation remains unchanged.
