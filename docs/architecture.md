# Architecture and data

Predict is a local read-only odds, EV and arbitrage comparison app. The current
product needs current event/contract/price rows, shared depth and calculation
rules. Ordinary operation replaces and expires sports working data rather than retaining
full feed archives or expanded calculation snapshots.

## Ordinary current data flow

Collection is currently independent of browser tabs but still owned by the web
server. The shared scanner worker starts on HTTP access and keeps its projection
in process memory; legacy board/slate routes also calculate on read. This is
the implementation described below, not completed process separation.

The next local change separates a background data runtime from the app process.
It reuses this PostgreSQL/current-row design, moves shared affected-input
calculations into that runtime and publishes compact replaceable latest results.
The app reads those results; selected Amount-specific sizing may remain explicit
bounded backend work. One background process may own collection and calculation.
App-only restarts must leave collection and data epochs intact, while explicit
collection Stop and original source expiry still remove current-action authority.
No message broker, separate repository or feed/report archive is required.

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
`CurrentRowStore` and the current-row schema. Ordinary collection does not construct a
journal or import diagnostics. The v2 board/slate reader captures typed current
facts, hydrates selected depth and calculates transiently. Details requires the
clicked context revision. There is no persistent calculation cache. The
[storage guide](current-row-storage.md) describes tables, ordering, expiry and
retired paths.

`AggregateScheduler.admit_response` sends admitted `current_aggregate_records`
through that SQL sink. Shared strict frame parsing and independent venue/reference
admission belong to `current_aggregate_admission.py`. Raw responses, legacy batch
wrappers and unknown observation types fail at the ordinary SQL boundary rather
than being normalized again. Explicit injected `LatestStateSink` fixtures retain
their separate raw-response adapter.

The ordinary CLI explicitly selects `CurrentService(database_mode=True)` and
current SQL boards. It does not accept a historical `--game` selector or an
observation-archive directory. `DatabasePipeline` owns startup, expiry and Stop;
it has no journal catch-up, diagnostic bootstrap or saved-calculation request queue.
Board/slate reads call the transient financial owners directly.

## HTTP surfaces

| Surface | Responsibility |
| --- | --- |
| `/`, `/ev`, `/arbs` | Current comparison presentation and v2 transport |
| `/api/boards/{view}` | Current facts, transient calculations, revision-bound Details and typed Original |
| `/api/stored/games`, `/api/stored/result`, `/api/boards/history` | HTTP 410: retired ordinary sports history |
| `/admin`, `/api/admin/status`, `/api/admin/current` | Sources, quota, storage, pause, Stop and guarded recovery |
| `/api/current` and its subroutes | HTTP 410 in ordinary SQL mode; validated state and bounded notices in explicitly injected mode |
| `/api/comparison`, `/api/arbs`, `/api/coverage`, `/current/coverage` | HTTP 410 in ordinary SQL mode; explicitly injected inspection only |
| `/api/selections` and its subroutes | HTTP 410 in ordinary SQL mode; injected inspection and manual What-if only |
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
inputs are explicit rather than new clocks beside old money. Defaults and HTTP overrides use one policy owner. Financial and display benchmark
consumers use the same validated original outcomes and no-vig weights.
Single and opposing allocation evaluators reuse fee, payout and funding owners.
Conditional EV, complete modeled EV and scenario minima have separate meanings.
Requested-trade calculations can inspect retained prices when their models still
apply, while stale or stopped dependencies remove current positive eligibility.
`comparison/calculation_availability.py` distinguishes numeric current and
last-known results, missing references, unsupported inputs and calculation failures,
including per-metric and scoped summaries. Original clocks, the evaluation instant
and actual calculation completion stay separate. See the
[financial contract](requested-trade-financial-contract.md),
[availability transport](comparison-board-api-contract.md#calculation-availability)
and [combined inputs](combined-occurrence-input-contract.md).

## Storage and retained readers

`storage/store.py` provides project connections and ordered migrations. Current
working tables are independent of retained sports history.
`storage/current_reset.py` declares the exact legacy sports SQL/file allowlist,
refuses unexpected dependencies and verifies protected state. Startup
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
| Entry points and routes | `dashboard/opportunity_board.py`, `dashboard/multi_game_server.py`, `dashboard/comparison_board_api.py` |
| Configuration and lifecycle | `collection/current_policy.py`, `collection/current_service.py`, `collection/local_ownership.py`, `collection/current_native.py` |
| Aggregate schedule and accounting | `collection/current_aggregate_policy.py`, `collection/current_schedule.py`, `collection/current_quota.py`, `collection/current_conservative.py` |
| Credentials and recovery | `collection/credential_handoff.py`, `collection/current_account_recovery.py`, `collection/venue_access.py` |
| Native HTTP transport | `collection/native_http_transport.py`; `collection/continuous_rest.py` owns sequential admission/pacing/retries with session-owned budgets and an explicit clock |
| Direct admitted-only current ingress and guards | `collection/current_database.py`, `collection/current_storage_policy.py` |
| Current SQL ownership and reset | `storage/current_rows.py`, migration 012, `storage/current_reset.py` |
| Current reads and transient calculations | `storage/comparison_board.py`, `dashboard/comparison_board_api.py`, `dashboard/comparison_slate.py` |
| Occurrence and native adaptation | `comparison/occurrence_matching.py`, `comparison/event_links.py`, `comparison/combined_inputs.py`, `comparison/combined_native.py`, `comparison/domain.py`, `comparison/source_inputs.py` |
| Policy and request overrides | `comparison/estimated_policy.py`, `comparison/effective_policy.py`, `dashboard/query_policy.py` |
| Named benchmark | `comparison/benchmark.py`; retained gross references use `collection/current_benchmark.py` |
| Financial assembly | `comparison/current_metrics.py`, `comparison/estimated_ev.py`, `comparison/estimated_pair.py`, `comparison/requested_sizing.py`, `comparison/estimated_consumer.py`, `comparison/financial_metrics.py` |
| Calculation availability | `comparison/calculation_availability.py`; board/slate presenters summarize evaluated results before filtering |
| Shared input graphs | `comparison/shared_templates.py`, `comparison/current_dependencies.py`, `comparison/projection_batches.py`, `comparison/current_details.py` |
| Current-state compatibility | `dashboard/current_state.py`, `dashboard/current_contract.py`, `dashboard/current_incremental.py` |
| Browser boundary and presentation | `dashboard/local_security.py`, `dashboard/request_guard.py`; authored current-board modules under `dashboard/opportunity_static/current/` |
| Retained lifecycle and projection | `dashboard/coverage_owner.py`, `dashboard/session_projection.py`, `dashboard/session_history.py`, `collection/continuous.py`, `collection/continuous_streams.py` |
| Shared domain mathematics | `fees/`, `settlement.py`, `normalization/`, `depth.py`, `opportunities/percentages.py` |

Keep state owners cohesive, transports independent and current API versions explicit.
The v2 API/client supports up to 500 canonical games through at most 50-game/8 MiB
pages, with expected-revision coherence and complete coverage checks. This is a
capacity bound, not a claim about live game availability. Sports rows expire;
account and configuration records have independent lifetimes. [Development](development.md)
explains checks and frontend composition; [configuration](configuration.md) covers
storage/account limits and operation. [Offline pricing](offline-pricing.md) and
[opportunities](offline-opportunities.md) document separate research contracts.
