# Architecture and data

The data process owns source collection, admission and affected-game calculations.
The web process serves Research, Data and Settings from committed PostgreSQL
records and local owner settings. Archive export, paper grading and the retained
Scanner APIs consume admitted observations through their own workflows.
[Current pregame](current-pregame.md) · [Runtime](data-app-runtime-contract.md)

## Personal workspace

- **Research** (`/research`) opens the Workbench. Experiments save versioned
  definitions and scheduled campaigns, replay retained Eastern game dates, and
  display versioned paper results. Fixed-profit and Kelly runs can share frozen
  capture inputs while retaining their own tickets and outcomes. Exact evidence
  and report exports use the selected run and result revision.
- **Data** (`/data`) groups current markets by game, market family and period before
  pagination. Positive EV and price arbitrage are views of stored acquisitions.
  The offer inspector opens exact revisions, source receipts, historical pulls
  and saved evidence. A newer covering attempt can withhold a numeric headline
  while the previous complete capture remains in History.
- **Settings** (`/settings`) shows source health, discovery and checkpoint timing,
  credits, holds, storage and fee assumptions. Stop, Resume, source pauses and
  fee edits use protected commands.

The browser reads stored data during ordinary navigation, refresh and inspection.
Saved comparisons preserve their original capture, fee assumptions and revision.
The former Opportunities, Browse, game and replay bookmarks resolve into Data.
Admin and coverage bookmarks resolve to Settings or the relevant Data view.
[Workspace guide](personal-data-workspace.md) · [Paper experiments](paper-experiments.md)

## Product boundary

Predict presents observed prices and modeled opportunities. Data keeps source
observations available when a reference or fee input is missing. Calculations
depend on documented fee assumptions, and price comparisons use illustrative
allocations. The journal retains manually reported fills and exposure. Exchange
orders, executable depth and slippage are outside those records.

## Ordinary current data flow

The data and web processes share PostgreSQL. Existing adapters admit ordered
observations with original clocks. The source transaction commits offers and
their receipt before publishing the Monitor projection. If projection fails,
the committed receipt still describes accepted source evidence. The collector
resumes the queued local projection from retained inputs after a retry or restart.
The app reads, groups and pages indexed SQL records. Kickoff, sporting status,
explicit withdrawals and scoped line omissions govern pregame removal.

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

The data CLI selects `CurrentService(database_mode=True)`. The app CLI selects
`RuntimeClient` and current SQL readers. `DatabasePipeline` owns startup, expiry
and Stop. Stop revokes dispatch and reports incomplete cleanup until owned workers
and clients close and ownership is released. The data runtime calls shared
financial owners. Explicit selected Details and ticket calculations retain bounded
transient sizing.

## HTTP surfaces

| Surface | Responsibility |
| --- | --- |
| `/`, `/research` | Root opens Research by default. Research serves the Workbench, including Experiments and paper results. |
| `/data` | Current markets, positive EV, market-to-market arbitrage, offers and retained evidence |
| `/settings` | Source controls, credits, holds, storage and fee assumptions |
| `/api/research/workspace` and its campaign/run routes | Save definitions, replay retained inputs, read results, inspect exact offers and export evidence |
| `/api/research/games`, `/api/research/game`, `/api/research/markets`, `/api/research/market` | Grouped Data reads and selected acquisition evidence |
| `/api/pregame`, `/api/pregame/updates`, `/api/pregame/arbs` | Current pregame rows, update metadata and modeled arbitrage from stored prices |
| `/api/odds-replay`, `/api/workspace/session` | Authentic saved captures and separately retained sessions with revision-bound details |
| `/api/workspace/status`, `/api/workspace/fees`, `/api/admin/status`, `/api/admin/current`, `/api/admin/activity-mode` | Operating status, fee settings, capture readiness, Stop/Resume, source pauses and mode settings |
| `/api/workspace/mens-d1` and its evidence routes | Dated schedule, capture and result coverage, issues and original receipts |
| `/ev`, `/browse-odds`, `/game`, `/odds`, `/raw-odds`, `/replay`, `/arbs` | Local compatibility redirects to the relevant Data context |
| `/admin`, `/coverage`, `/current/coverage` | Local compatibility redirects to Settings or Data |
| `/scanner`, `/my-bets`, `/about`, `/trading-fees` | HTTP 410 retirement pages with links to the Workbench. Retained APIs and records have independent owners. |
| `/api/comparison-snapshot` | GET a ranked or grouped page. POST captures local inputs or recalculates the selected assumptions. |
| `/api/comparison-snapshot/details` | Exact captured inputs for one result revision and selection |
| `/api/boards/readiness`, `/api/boards/coverage`, `/api/boards/games` | Current board readiness, coverage and bounded game reads |
| Superseded `/api/boards/{view}` result reads | HTTP 410 in ordinary SQL mode |
| `/api/stored/games`, `/api/stored/result`, `/api/boards/history` | HTTP 410: retired ordinary sports history |
| `/api/current` and its subroutes | HTTP 410 in ordinary SQL mode; validated state and bounded notices in explicitly injected mode |
| `/api/comparison`, `/api/arbs` | HTTP 410 in ordinary SQL mode; explicitly injected inspection only |
| `/api/coverage` | Latest bounded coverage publication |
| `/api/selections` and its subroutes | HTTP 410 in ordinary SQL mode; injected inspection and manual What-if only |

The [storage ownership contract](storage-ownership.md) describes the ordinary
publication and current read surface. The [board contract](comparison-board-api-contract.md)
and [current-state contract](contracts/predict-current-1.md) document the retained
board and injected readers. Shared Host/Origin and request validation applies to
these surfaces. [Current-row API and examples](examples/current-pregame-1/README.md)

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
| Entry points and workspace routes | `dashboard/opportunity_board.py`, `dashboard/multi_game_server.py`, `dashboard/workspace_routes.py` |
| Workbench and paper results | `dashboard/research_workspace_api.py`, `research/workspace.py`, `research/paper_campaigns.py`, `dashboard/paper_results_view.py` |
| Data views and evidence | `dashboard/research_api.py`, `storage/market_board.py`, `storage/acquisition_snapshot.py`, `storage/research_catalog.py`, `dashboard/replay_api.py` |
| Background lifecycle/status/controls | `collection/data_runtime.py`, `collection/runtime_status.py`, `collection/runtime_client.py` |
| Configuration and lifecycle | `collection/current_policy.py`, `collection/current_service.py`, `collection/local_ownership.py`, `collection/current_native.py` |
| Aggregate schedule and accounting | `collection/current_aggregate_policy.py`, `collection/current_schedule.py`, `collection/current_quota.py`, `collection/current_conservative.py` |
| Credentials and recovery | `collection/credential_handoff.py`, `collection/current_account_recovery.py`, `collection/venue_access.py` |
| Native HTTP transport | `collection/native_http_transport.py`; `collection/continuous_rest.py` owns sequential admission/pacing/retries with session-owned budgets and an explicit clock |
| Native discovery selection | `collection/current_native_catalog.py` owns pure bounded selection/diagnostics; `collection/current_native.py` owns discovery/stream lifecycle |
| Direct admitted-only current ingress and guards | `collection/current_database.py`, `collection/current_storage_policy.py` |
| Current pregame writes and committed-row reads | `storage/current_pregame.py` owns affected-game calculation/recovery and keeps the public `read` facade; `storage/current_pregame_read.py` owns pure SQL filtering, grouping and pagination. The facade supplies the clock and configured route resolver without changing transaction ownership. |
| Current SQL ownership and reset | `storage/current_rows.py`, migration 012, `storage/current_reset.py` |
| PostgreSQL authority | `storage/store.py` owns connections and migrations. `storage/database_roles.py` owns the managed grants for web, collector and archive operations. |
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

The retained board v2 API traverses the canonical-game catalog in pages of
at most 50 games and 8 MiB, with expected-revision checks and total-byte guards.
Sports rows and account and configuration records have independent lifetimes.
[Development](development.md)
explains checks and frontend composition; [configuration](configuration.md) covers
storage/account limits and operation. [Offline pricing](offline-pricing.md) and
[opportunities](offline-opportunities.md) document separate research contracts.

## Acquisition and publication

SportsGameOdds discovery stores the request scope and received pages before
catalog publication. The discovery traversal and the early and T−10 experiment
checkpoints have independent clocks and admission guards. Native bulk discovery
builds metadata in an owned CPU process per source and replaces books by exact
source, event and market identity. Cancellation joins active calls and child
shutdown. Receipt disposition, current rows and downstream publication each
have their own commit or completion boundary.

See [acquisition](acquisition.md) for ownership, capacity and completeness limits.

## Shared policy and view ownership

| Domain | SSOT module/file | Why authoritative | Known callers |
| --- | --- | --- | --- |
| Pregame ranking methods, labels and calculation | `app/storage/pregame_ranking.py` | Owns the method catalog/default, exact SQL expressions and wire/display presentation. `catalog()` generates browser metadata through the existing asset build; the browser does not maintain a second method list. | `current_pregame.read`, generated `pregame-ranking.js`, `pregame.js` and `pregame-math.js`. |
| Monitor/Live cadence, settings and operational object limits | `app/collection/activity_mode.py` | Owns validated durable viewing intent, clock/default projection and returned-event ceilings. The ordinary SQL service selects `ActivityCollector`; status and budget-delay diagnostics use `operating_budget()`, while admission reads the same limits. Provider account, quota, reservation and Stop/hold guards remain independently stricter. | `activity_mode_api`, `current_pregame_api`, `activity_collector.budget_admit` and collector scheduling/diagnostics. |
| Personal appearance contract | `app/dashboard/appearance_policy.py` | Owns the approved starter palettes, default, modes and validation patterns. The existing asset builder emits `appearance-policy.js`; SQLite validation and browser cache/server-response validation use the same contract. | `Appearance.read/save/validate`, generated metadata, `prism-theme.js`, `prism.js`. |
| Theme color derivation and contrast | `app/dashboard/opportunity_static/current/prism-theme.js` | Computes every applied token, including accent text color. The interaction controller no longer maintains a second luminance calculation. | `prism.js`, theme preview, saved theme application and system-color changes. |
| Source lifecycle and current-row withdrawal | `app/comparison/game_phase.py::sgo_event_status` and `app/storage/sportsgameodds_reference.py::apply_event_lifecycle` | Normalizes sporting evidence and commits lifecycle changes under the ingestion writer transaction. The worker's page filter preserves notices while excluding post-start prices; it does not implement a second persisted lifecycle. | Source ingress, current board reads and journal source sampling. |
| Saved quote identity and correction transactions | `app/dashboard/bet_journal.py::Journal` | Owns canonical manual identity, original snapshots, revisions and SQLite read/write transactions. API and browser actions delegate persistence to it. | `bet_journal_api`, manual Save, opportunity observation and export. |
| Reported trade validation and stake-only fill derivation | `app/dashboard/bet_journal_trade.py` | Owns actual price/stake/fee validation and derives fills from frozen quotes using the existing fee engine. Journal preview and correction pass their clock explicitly; these helpers perform no storage writes. | `Journal.preview`, `Journal.update`; existing helper imports through `bet_journal` remain available. |
| Test inventories and selection | `scripts/ci/suites.json`, `scripts/ci/python-policy.json` and `scripts/ci/postgres.py` | Own the extended suites and exclusions. `affected.py` selects local change owners. `fast_checks.py` selects focused contracts for the personal release. Both use the same disposable SQL runner. | Local checks, full validation and the personal release. |
| Aggregate provider and phase configuration | `app/collection/current_policy.py` and the committed `data_runtime.config` | Validates provider choices and Live defaults. Read-side code passes the provider from its committed runtime snapshot into publication identity and desk update cursors. | Collection workers, SQL publication, desk reads, Coverage, Scanner and Raw Odds. |
| PostgreSQL socket and outage cache partition | `app/storage/store.py::socket_directory` | Resolves and validates the same absolute socket for PostgreSQL connections and the corresponding last-known desk cache. | Storage connections and the ordinary app launcher. |
| Comparison evidence leases | `app/storage/comparison_snapshot.py` | Owns two-hour renewals and bounds explicit selections using the PostgreSQL clock. Result and input timestamps renew together. Evidence tokens retain exact published revisions independently. | Manual refresh and recalculation, saved reads, and current Details. |
| SportsGameOdds discovery scope | `app/collection/sportsgameodds_worker.py`, `app/collection/sportsgameodds_adapter.py` | The worker builds the exact request used across a cursor walk. The adapter owns the supported leagues and page bounds. | Worker, transport, checkpoint restore, accounting and SQL admission. |
| The Odds API featured market keys | `app/collection/current_aggregate_policy.py` | Maps the product market families to their provider request keys. | Configuration, scheduler, quota declarations, quote admission and coverage reporting. |
| Persisted current event and contract identity | `app/storage/current_rows.py` | Builds the identifiers used to persist and find exact event and contract rows. | Admission, desk overlays, ordinary publication, Scanner and Coverage. |
| Ordinary page and API routing | `app/dashboard/workspace_routes.py` and `app/dashboard/multi_game_server.py` | Mounts Research, Data and Settings and keeps canonical compatibility redirects in one place. The pregame API and retained readers have independent handlers. | `opportunity_board`, workspace navigation and saved bookmarks. |
| Desk and replay phase selection | `app/dashboard/snapshot_display.py` | Applies the pregame boundary consistently to selected rows and related games and pairs. | Current and captured snapshot reads, replay lists and replay details. |
| Best sportsbook payout and two-sided de-vig | `app/comparison/sgo_reference.py` | Owns the book order, tie-break, exact American-price parsing and normalization of a qualified pair. | Settlement-reviewed SGO reference, direct public book estimates, Browse odds and same-frame SGO baseline. |
| Desk sportsbook line selection and enrichment | `app/dashboard/desk_sportsbooks.py` | Matches sportsbook prices to the exact displayed live line and applies live freshness. | Live snapshot list and Quote Quality. |
| Joined thread cancellation | `app/owned_work.py` (`joined_thread`) | Owns result/error-as-data, repeated-cancellation joining and error precedence in one implementation. | `collection/bulk_checkpoint.py::owned_thread` and the raw API's `joined` binding; checkpoint, ingress, accounting shutdown and raw read/export operations. |
| Safe failure details | `app/diagnostics.py` | Builds class/frame-only diagnostics without messages or payloads. | Shared completion helper, runtime, storage and disposable calculation workers. |
| Retained Raw Odds controls | `app/dashboard/opportunity_static/current/raw-odds.js` and its `raw-odds.html` shell | Owns received-price filtering, pagination, selection and loading state for the retained reader. | Retained readers and `tests/test_raw_odds_controls.cjs`. The ordinary `/raw-odds` bookmark routes to Data. |

The checkpoint `owned_thread` import remains supported because acquisition,
ingress and accounting owners actively use it. It and the raw API binding supply
only diagnostic identity; neither implements a second cancellation policy.
Subprocess termination, process-pool accounting and retained read queues retain
their separate ownership protocols. They must not be replaced with the thread
helper without preserving their authority, capacity and cleanup contracts.

The retained raw reader exposes original observations. Data's positive EV and
arbitrage views own financial filtering. The stored and Scanner bundles and
retained-session readers have their own API and fixture contracts.

Browser ranking controls and explanations import metadata generated from
`pregame_ranking.py`; the frontend build checks that generated module for drift.
The supported `score` ranking uses the shared catalog. Unknown calculation-detail
kinds fail explicitly.

Ordinary `CurrentService(database_mode=True)` selects `ActivityCollector` after
initializing its guarded account window. `activity_mode.py` defines discovery
clocks and object limits. Saved Live intent does not drive repeated paid requests.
`SchedulePolicy`, `PREGAME_TARGET` and `budgeted_policy` serve the non-SQL research
and test path. `scripts/replay_comparison_net_inputs.py` uses that service with
both acquisition flags disabled.

Saved preference labels remain bounded lowercase identifiers rather than a
foreign key into today's palette list. The persisted colors determine appearance;
an older/custom label remains valid without rewriting owner records. Browser
storage is a cache, SQLite is the durable owner, and invalid cache shapes no
longer count as valid server preferences. First-paint CSS colors and the existing
cache fallback during an unavailable API read remain supported startup behavior.

Saved `line`/`quote_key` links and compatibility API endpoints resolve to current
exact reads. Retired amount/mode queries return HTTP 410. Journal legacy-ID lookup
preserves saved decisions and corrections. `PregameOwner` also starts
`OrdinaryOwner` for independent research, Coverage and Scanner work.
