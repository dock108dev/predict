# Architecture and data

Predict is a local read-only comparison app. Its ordinary workflow stores source
observations in a journal and PostgreSQL, computes a selected game's immutable
result, and presents Odds, EV, Arbs and saved Details/history. Finite-session
collectors and retained research readers remain separate supported interfaces.

## Ordinary data flow

1. `scripts/opportunity-board` starts the dedicated PostgreSQL cluster and launches
   `dashboard.opportunity_board`. `CurrentService` owns configured source workers,
   aggregate scheduling, quota and cleanup.
2. `DatabaseIngressSink` admits native catalogs/books and aggregate batches into
   bounded `CurrentJournal` storage before projection. `DatabasePipeline` catches
   up records independently using the existing SQL connection and migration lock.
3. `GameStore` retains immutable envelopes and rebuildable source-local projections.
   Exact prices, units, source IDs and clocks remain in payloads. Sportsbook decimal
   odds are not forced into probability-quote columns.
4. Combined input capture resolves one occurrence, retains each original member,
   selects the named benchmark and binds source dependencies, policy and engine.
   A short transaction creates a stable snapshot; finance runs outside capture locks.
5. Complete results remain immutable. Latest pointers publish only if relevant
   inputs, membership, policy, engine and request generation still match. Unrelated
   arrivals do not cancel a game's job. One calculation and at most four coalesced
   pending requests are owned by the pipeline; it does not recalculate every game
   merely because another game changed.
6. Saved-board reads request selected game/policy variants. Details pins exact
   result, snapshot and quote/pair identities. Freshness depends on original source,
   reference and model clocks, not save/read time. Stop withdraws positive-list
   authority while historical results remain inspectable.

Database errors are explicit; ordinary operation never falls back to whole-slate
in-memory finance. Source acquisition runs independently of tabs. Reads, filtering,
Details and settings do not dispatch provider requests or mutate quota.

## HTTP surfaces

| Surface | Responsibility |
| --- | --- |
| `/`, `/ev`, `/arbs` | Ordinary saved Odds, EV and opposing allocations |
| `/api/boards/{view}` | Catalog, compact comparisons, exact Details, inputs and history |
| `/api/stored/games`, `/api/stored/result` | Compatible source-local saved inspection |
| `/admin`, `/api/admin/status`, `/api/admin/current` | Sources, quota, storage, pause, Stop and guarded recovery |
| `/api/current`, `/api/current/changes`, `/api/current/updates` | Validated current-state compatibility interface and bounded revision notices |
| `/api/comparison`, `/api/arbs`, `/api/current/details` | Current-state calculations and exact selected evidence |
| `/api/selections/{token}` and related POST routes | Temporary immutable inspection and explicit manual What-if |
| `/admin/retained`, `/game`, `/coverage` | Finite-session and retained capture interfaces |

The [saved-board API](comparison-board-api-contract.md) defines ordinary reads;
the [current-state contract](contracts/predict-current-1.md) describes injected and
compatibility readers. Shared Host/Origin and request validation applies to both.

## Identity and calculation

Occurrence resolution groups sporting events using exact metadata and bounded
matching provenance. Display grouping does not merge native economic contracts:
NO, Short, tie treatment, completion windows and quantity units remain distinct.
Conflict or ambiguity cannot authorize a cross-venue hedge.

Content-addressed templates retain shared fee/payout/reference graphs without
repeating them for every quote. Selected Details expands the exact graph used by
its result. Defaults and HTTP overrides use one policy owner; financial and display
benchmark consumers use the same validated original outcomes and no-vig weights.
Single and opposing allocation evaluators reuse fee, payout and funding owners.
Conditional EV, complete modeled EV and scenario minima have separate meanings.
See [financial contract](requested-trade-financial-contract.md) and
[combined inputs](combined-occurrence-input-contract.md).

## Storage and retained readers

`storage/store.py` provides dedicated project connections and ordered, hash-checked
migrations. Current tables retain immutable originals, snapshots and results plus
rebuildable pointers. Earlier capture, reference, fair-price and audit tables have
distinct serializers. Do not reinterpret an old result under a new policy/engine.

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
| Journal and SQL pipeline | `collection/current_journal.py`, `current_storage_policy.py`, `current_database.py` |
| Saved state and publication | `storage/current_games.py`, `storage/comparison_board.py` |
| Occurrence and native adaptation | `comparison/occurrence_matching.py`, `event_links.py`, `combined_inputs.py`, `combined_native.py`, `domain.py`, `source_inputs.py` |
| Policy and request overrides | `comparison/estimated_policy.py`, `effective_policy.py`, `dashboard/query_policy.py` |
| Named benchmark | `comparison/benchmark.py`; retained gross references use `collection/current_benchmark.py` |
| Financial assembly | `comparison/current_metrics.py`, `estimated_ev.py`, `estimated_pair.py`, `requested_sizing.py`, `estimated_consumer.py`, `financial_metrics.py` |
| Shared input graphs | `comparison/shared_templates.py`, `current_dependencies.py`, `projection_batches.py`, `current_details.py` |
| Current-state compatibility | `dashboard/current_state.py`, `current_contract.py`, `current_incremental.py` |
| Browser boundary and presentation | `dashboard/local_security.py`; authored saved-board modules under `dashboard/opportunity_static/current/` |
| Retained lifecycle and projection | `dashboard/coverage_owner.py`, `session_projection.py`, `session_history.py`, `collection/continuous.py`, `continuous_streams.py` |
| Shared domain mathematics | `fees/`, `settlement.py`, `normalization/`, `depth.py`, `opportunities/percentages.py` |

Keep state owners cohesive, transports independent and versioned readers usable.
Retiring retained formats or collection modes needs a usage/migration decision;
they still have route, tool and fixture callers. [Development](development.md)
explains checks and frontend composition; [configuration](configuration.md) covers
storage/account limits and operation. [Offline pricing](offline-pricing.md) and
[opportunities](offline-opportunities.md) document separate research contracts.
