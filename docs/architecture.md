# Architecture and data

Predict is a local read-only odds, EV and arbitrage comparison app. The current
product needs current event/contract/price rows, shared depth and calculation
rules. Sports/test history is disposable. Full feed archives and expanded result
snapshots are not required for ordinary use.

## Ordinary current data flow

1. Existing source adapters validate bounded responses and reconstruct native
   books in bounded memory. Provider response bodies/websocket messages are
   discarded after normalization rather than archived on every receipt.
2. A direct SQL ingress owner upserts events, exact native contracts and current
   offers by stable identities. Current depth is replaced atomically. Original
   source and receipt clocks stay separate; a partial refresh is not a complete
   scope deletion.
3. The read/calculation adapter builds coherent typed inputs from current rows
   and shared fee/payout/reference policies. Financial owners calculate requested
   funding, EV and opposing allocations per read. Details expands only the selected
   item; calculation reports are not persisted.
4. Expiry removes completed/out-of-scope sports rows and dependent caches. Default
   history is off. Account/quota/attempt/due records, credentials and settings have
   separate lifetimes and are not sports cache data.
5. Collection remains independent of tabs. Reads, filters, settings and Details
   do not dispatch providers or mutate quota. Stop revokes acquisition/publication;
   calculation or receipt time never renews source freshness.

`DatabaseIngressSink` commits directly through
`CurrentRowStore` and migration 012. Ordinary collection does not construct a
journal or import diagnostics. The v2 board/slate reader captures typed current
facts, hydrates selected depth and calculates transiently. Details requires the
clicked context revision. There is no persistent calculation cache. The
[storage guide](current-row-storage.md) describes tables, ordering, expiry and
retired paths.

## HTTP surfaces

| Surface | Responsibility |
| --- | --- |
| `/`, `/ev`, `/arbs` | Current comparison presentation and v2 transport |
| `/api/boards/{view}` | Current facts, transient calculations, revision-bound Details and typed Original |
| `/api/stored/games`, `/api/stored/result`, `/api/boards/history` | HTTP 410: retired ordinary sports history |
| `/admin`, `/api/admin/status`, `/api/admin/current` | Sources, quota, storage, pause, Stop and guarded recovery |
| `/api/current`, `/api/current/changes`, `/api/current/updates` | Validated current-state compatibility interface and bounded revision notices |
| `/api/comparison`, `/api/arbs`, `/api/current/details` | Current-state calculations and exact selected evidence |
| `/api/selections/{token}` and related POST routes | Temporary immutable inspection and explicit manual What-if |
| `/admin/retained`, `/game`, `/coverage` | Finite-session and retained capture interfaces |

The [board contract](comparison-board-api-contract.md) defines current v2 reads;
the [current-state contract](contracts/predict-current-1.md) describes injected and
compatibility readers. Shared Host/Origin and request validation applies to both.

## Identity and calculation

Occurrence resolution groups sporting events using exact metadata and bounded
matching provenance. Display grouping does not merge native economic contracts:
NO, Short, tie treatment, completion windows and quantity units remain distinct.
Conflict or ambiguity cannot authorize a cross-venue hedge.

Shared versioned fee/payout/reference definitions are referenced by current
offers and transient calculation inputs. Selected Details expands only its coherent
current context, using an expected-revision check.
A context binds game, instrument/pair, relevant input revisions, policy and engine;
it does not require a permanent sports snapshot/result. Changed/reset/removed
inputs are explicit rather than new clocks beside old money. Defaults and HTTP overrides use one policy owner; financial and display
benchmark consumers use the same validated original outcomes and no-vig weights.
Single and opposing allocation evaluators reuse fee, payout and funding owners.
Conditional EV, complete modeled EV and scenario minima have separate meanings.
See [financial contract](requested-trade-financial-contract.md) and
[combined inputs](combined-occurrence-input-contract.md).

## Storage and retained readers

`storage/store.py` provides project connections and ordered migrations. Migration
012 adds independent current working tables; applied 009–011 checksums are
unchanged. `storage/current_reset.py` declares the exact old sports SQL/file
allowlist, refuses unexpected dependencies and verifies protected state. Startup
does not run this reset or import discarded sports data. Old codecs and archive
readers remain for separately selected research paths; ordinary routes do not
fall back to them. Account/configuration owners retain separate lifetimes.

Finite collectors use `CoverageOwner`, `ContinuousSession` and acknowledged
journals. Flat or segmented saved packages are verified before projection;
replay and successful finalization precede completion publication. Pending files
or journals alone do not establish completion. Research and result/reference
imports keep their original cutoffs and never become fresh observations.

Retained routes include `/api/status`, `/api/sessions`, `/api/dashboard`,
`/api/calculate`, `/api/resolution`, explicit `/api/start` and `/api/stop`, saved
history, reference/result imports and native-review/source-contract downloads.
They require their own configured session and do not inherit ordinary acquisition
permission from a read. Watchlists store filter criteria, not dispatch authority.
History workers are bounded local readers; request cancellation does not discard
an active worker's resource ownership.

## Module ownership

Paths are relative to `app/`.

| Domain | Authoritative modules |
| --- | --- |
| Entry points and routes | `dashboard/opportunity_board.py`, `multi_game_server.py`, `comparison_board_api.py` |
| Configuration and lifecycle | `collection/current_policy.py`, `current_service.py`, `local_ownership.py`, `current_native.py` |
| Aggregate schedule and accounting | `collection/current_aggregate_policy.py`, `current_schedule.py`, `current_quota.py`, `current_conservative.py` |
| Credentials and recovery | `collection/credential_handoff.py`, `current_account_recovery.py`, `venue_access.py` |
| Native HTTP transport | `collection/native_http_transport.py`; producers retain admission and request budgets |
| Direct current ingress and guards | `collection/current_database.py`, `current_storage_policy.py` |
| Current SQL ownership and reset | `storage/current_rows.py`, migration 012, `storage/current_reset.py` |
| Current reads and transient calculations | `storage/comparison_board.py`, `dashboard/comparison_board_api.py`, `comparison_slate.py` |
| Occurrence and native adaptation | `comparison/occurrence_matching.py`, `event_links.py`, `combined_inputs.py`, `combined_native.py`, `domain.py`, `source_inputs.py` |
| Policy and request overrides | `comparison/estimated_policy.py`, `effective_policy.py`, `dashboard/query_policy.py` |
| Named benchmark | `comparison/benchmark.py`; retained gross references use `collection/current_benchmark.py` |
| Financial assembly | `comparison/current_metrics.py`, `estimated_ev.py`, `estimated_pair.py`, `requested_sizing.py`, `estimated_consumer.py`, `financial_metrics.py` |
| Shared input graphs | `comparison/shared_templates.py`, `current_dependencies.py`, `projection_batches.py`, `current_details.py` |
| Current-state compatibility | `dashboard/current_state.py`, `current_contract.py`, `current_incremental.py` |
| Browser boundary and presentation | `dashboard/local_security.py`; authored saved-board modules under `dashboard/opportunity_static/current/` |
| Retained lifecycle and projection | `dashboard/coverage_owner.py`, `session_projection.py`, `session_history.py`, `collection/continuous.py`, `continuous_streams.py` |
| Shared domain mathematics | `fees/`, `settlement.py`, `normalization/`, `depth.py`, `opportunities/percentages.py` |

Keep state owners cohesive, transports independent and current API versions explicit.
The v2 API/client supports up to 500 canonical games through at most 50-game/8 MiB
pages, with expected-revision coherence and complete coverage checks. This is a
capacity bound, not a claim about live game availability. Sports rows expire;
account and configuration records have independent lifetimes. [Development](development.md)
explains checks and frontend composition; [configuration](configuration.md) covers
storage/account limits and operation. [Offline pricing](offline-pricing.md) and
[opportunities](offline-opportunities.md) document separate research contracts.
