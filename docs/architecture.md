# Architecture and data

Predict is a local read-only odds, EV and arbitrage comparison app. The current
product needs current event/contract/price rows, shared depth and calculation
rules. Ordinary operation replaces and expires sports working data rather than retaining
full feed archives or expanded calculation snapshots.

## Product boundary

Predict collects supported source observations and presents read-only comparisons.
Observation visibility is independent of financial-estimate completeness: source
prices, identities, original clocks and available depth remain useful when a
particular estimate is unknown. Personal-website execution rules and exact order
routes are outside collection/display requirements. Financial claims retain
their own model applicability and uncertainty. Current latest-board price
publication is independent of calculation success; unavailable estimates do not
hide admitted source prices.

## Ordinary current data flow

Acquisition, storage/publication, matching, financial logic, frontend and
integration QA have distinct responsibilities. Current architecture has **two OS processes**:
the background data process hosts collection and calculation workers; the app
process reads publications. Logical worker separation does not establish complete
resource/failure isolation: workers within the data process share its memory and
process lifetime.

The ordinary launcher runs an independent background data process and an app
process against the existing PostgreSQL database. The data runtime owns
collection, expiry, the shared scanner, Odds/EV calculations and compact episode
summaries. The app reads bounded latest database publications. Opening a page is
not necessary to start calculation. App-only restart preserves the data identity
and epoch; explicit collection Stop has acknowledged cross-process semantics.
[Runtime and latest-result contract](data-app-runtime-contract.md).

1. Existing bounded adapters normalize source observations and upsert stable
   current events/contracts/offers/shared depth with original clocks.
2. Background workers discover committed database revisions, capture coherent
   typed facts, then calculate affected economics outside SQL transactions.
   Unrelated economics retain original calculation times.
3. Final publication compares exact dependencies and runtime authority under the
   current-writer lock, replacing compact latest rows and scope status.
4. Scanner, Odds and EV reads filter/page stored results without acquisition or
   whole-slate finance. Selected tickets/Details may calculate the selected amount
   from exact fresh database inputs. Expanded reports remain transient.
5. Original expiry, Stop, configuration/model/policy/epoch changes and an
   eight-second missing heartbeat withdraw current action eligibility. Stored
   observations remain last-known where useful; reading never renews freshness.

`DatabaseIngressSink` commits directly through `CurrentRowStore`; ordinary
collection does not construct a journal or import old diagnostics. Migrations
013–015 add bounded runtime controls and latest results to the current-row schema.
Protected accounts, quota, reservations, settings and financial records retain
their separate owners. No sports reset is part of separation.

`AggregateScheduler.admit_response` sends admitted `current_aggregate_records`
through that SQL sink. Shared strict frame parsing and independent venue/reference
admission belong to `current_aggregate_admission.py`. Raw responses, legacy batch
wrappers and unknown observation types fail at the ordinary SQL boundary rather
than being normalized again. Explicit injected `LatestStateSink` fixtures retain
their separate raw-response adapter.

The data CLI selects `CurrentService(database_mode=True)`; the app CLI selects
`RuntimeClient` and current SQL result readers. It does not accept a historical `--game` selector or an
observation-archive directory. `DatabasePipeline` owns startup, expiry and Stop;
it has no journal catch-up, diagnostic bootstrap or saved-calculation request queue.
The data runtime calls shared financial owners; selected Details/tickets retain
bounded transient sizing.

## HTTP surfaces

| Surface | Responsibility |
| --- | --- |
| `/`, `/arbs` | Globally ranked scanner and selected manual tickets |
| `/odds`, `/ev` | Observed prices and single-trade estimates |
| `/api/boards/{view}` | Latest shared results, revision-bound selected Details and typed Original |
| `/api/stored/games`, `/api/stored/result`, `/api/boards/history` | HTTP 410: retired ordinary sports history |
| `/admin`, `/api/admin/status`, `/api/admin/current` | Sources, quota, storage, pause, Stop and guarded recovery |
| `/api/current` and its subroutes | HTTP 410 in ordinary SQL mode; validated state and bounded notices in explicitly injected mode |
| `/api/comparison`, `/api/arbs` | HTTP 410 in ordinary SQL mode; explicitly injected inspection only |
| `/api/coverage`, `/current/coverage` | Latest bounded Coverage publication and current coverage page |
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
offers and transient calculation inputs. Selected Details expands its coherent input context, using an expected-revision
check or its bounded captured selection frame. A leased selection retains its
original facts across live updates and becomes captured when dependencies change;
that cache lease never renews price freshness or current financial eligibility.
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
| Background lifecycle/status/controls | `collection/data_runtime.py`, `collection/runtime_status.py`, `collection/runtime_client.py` |
| Configuration and lifecycle | `collection/current_policy.py`, `collection/current_service.py`, `collection/local_ownership.py`, `collection/current_native.py` |
| Aggregate schedule and accounting | `collection/current_aggregate_policy.py`, `collection/current_schedule.py`, `collection/current_quota.py`, `collection/current_conservative.py` |
| Credentials and recovery | `collection/credential_handoff.py`, `collection/current_account_recovery.py`, `collection/venue_access.py` |
| Native HTTP transport | `collection/native_http_transport.py`; `collection/continuous_rest.py` owns sequential admission/pacing/retries with session-owned budgets and an explicit clock |
| Native discovery selection | `collection/current_native_catalog.py` owns pure bounded selection/diagnostics; `collection/current_native.py` owns discovery/stream lifecycle |
| Direct admitted-only current ingress and guards | `collection/current_database.py`, `collection/current_storage_policy.py` |
| Current SQL ownership and reset | `storage/current_rows.py`, migration 012, `storage/current_reset.py` |
| Shared latest publications and readers | `storage/scanner_latest.py`, `storage/latest_board.py`, `dashboard/scanner_api.py`; `storage/board_capture.py` owns bounded capture planning and `storage/board_view.py` owns pure captured-result rendering |
| Selected current inputs and transient calculations | `storage/comparison_board.py`, `dashboard/comparison_board_api.py`, `dashboard/comparison_slate.py` |
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

Native scoring applicability has one ordinary owner:
`comparison/native_scoring_scope.py` (`resolve`, `attach`, `source_rules` and
`publication_dependencies`). `combined_native` and `current_normalized` use it
for admission; observation publication and Coverage use its source/type dependency
keys. It verifies shared source evidence plus each observation's own identity,
predicate, terms and exceptions. Event-specific target registries cannot authorize
ordinary scoring or invalidate current publications. Their bounded schema readers
remain only for retained-fixture inspection; the unreachable event-specific
admission and dependency implementations have been removed.

NFL and NHL spread/total inventory checks both route through
`normalization/reviewed_winner.py:line_inventory_gaps`, then its shared
`inventory_gaps` identity conflict checker. `nfl_lines` and `nhl_lines` retain their
sport-specific event and score rules. Winner-only events are excluded from line
review rather than subjected to a second, conflicting identity policy.

The unused `storage/comparison_board.view_bundle` identity wrapper and
`prophetx_verify.ResponseLike` adapter have been removed. Current selected reads
use `ReadContext` and the bounded selected-frame owner; retired archive operations
continue to refuse explicitly. Applied migrations, frozen packages, versioned
estimate policies and explicitly injected research/preview routes remain supported
contracts, not ordinary-runtime fallback implementations.

Keep state owners cohesive, transports independent and current API versions explicit.
The launcher and `python -m app.dashboard` enter through `opportunity_board`,
which delegates routing to `multi_game_server`. The former fixed-port
`dashboard/server.py` router and its separate scan frontend have been removed.
Current routes share `request_guard` and `local_security`; source configuration
belongs to `current_policy`, loaded by the independent data runtime. App-only
operation cannot silently accept an unused source configuration override.

Retained session helpers, finite capture controllers and the explicitly isolated
synthetic collection server remain separate supported research tools. Their
callers use retained projections or disposable environments; they are not
fallbacks for current SQL boards. Preview pages still share
`dashboard/static/style.css`. Frozen source manifests describe historical
packages and are not inventories of the current checkout.

The v2 API/client supports up to 500 canonical games through at most 50-game/8 MiB
pages, with expected-revision coherence and complete coverage checks. This is a
capacity bound, not a claim about live game availability. Sports rows expire;
account and configuration records have independent lifetimes. [Development](development.md)
explains checks and frontend composition; [configuration](configuration.md) covers
storage/account limits and operation. [Offline pricing](offline-pricing.md) and
[opportunities](offline-opportunities.md) document separate research contracts.
