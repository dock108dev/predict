# Architecture and data

The product is a local read-only prediction-market comparison board. Its ordinary runtime owns bounded latest state and source acquisition; retained finite-session collectors and saved readers remain separate. Module ownership below identifies the authoritative components. Venue and market support varies; inspect exact market identity and calculation basis before interpreting a result.

Current production behavior is the Odds board, explicit opposing-pair Arbs page and Admin, with live Details. Native streams run while the app runs; shared aggregate acquisition uses 15-minute Eastern daytime slots and the paid 100,000-credit policy. `current_aggregate_policy.POLICY` owns current aggregate constants; `current_schedule.schedule` computes slots and `QuotaLedger.begin_cycle` consumes them.

## Current request and collection flow

1. `scripts/opportunity-board` launches `opportunity_board.main`. The ordinary
   CLI loads `collection.current_policy`, constructs `CurrentService` and injects
   it into `multi_game_server.create_app`. The listener binds loopback and denies
   database connections; opening the ordinary app does not load saved quotes.
2. `current_state.mount` constructs `CurrentStore` and starts its provider during
   application startup. `CurrentService` acquires exclusive ownership, consumes
   a fresh operational record and starts independent Kalshi/Polymarket US native
   workers plus one shared aggregate scheduler when `aggregate_enabled` is true.
   Native resource ceilings can still stop work; the default service deadline follows process lifetime.
3. `current_native.NativeWorker` supplies admitted native metadata and books;
   `current_aggregate.AggregateScheduler` supplies both aggregate venues through
   one budgeted sport batch. `LatestStateSink` reuses `SessionProjection` as an
   in-memory reducer, validates original inputs and commits normalized current
   state atomically. This path does not advance a quote journal or archive.
4. `CurrentStore` validates the `predict-current-1` contract, advances source
   eligibility with monotonic aging and publishes bounded latest revision notices.
   The browser filters existing rows locally; tabs, filters and Details do not
   create source workers or multiply paid requests.
5. A price selection opens live Details on the current coherent quote revision.
   Manual What-if alone creates/releases a temporary immutable calculation lease;
   expiry, shutdown and recovery invalidate it. `current_contract` derives display
   and calculation output from originals. `arbitrage_pairs` enumerates opposing
   legs through shared normalized percentage math; missing model inputs withhold EV.
6. `/admin` exposes source status, shared quota, pause/Stop and guarded recovery.
   Shutdown revokes dispatch and closes workers before releasing ownership and
   expiring reviews. Recovery preserves consumed attempts, spend, reservations
   and due times; it does not reset the account or replay a missed schedule.

## Retained finite-session request and collection flow

The compatibility router still constructs a `CoverageOwner` for retained routes.
That owner does not replace the injected ordinary `CurrentService` or make saved
observations current. The following machinery serves retained inspection, finite
qualification collectors and explicit test instances.

1. `scripts/opportunity-board` launches `app.dashboard.opportunity_board`, which
   delegates to `multi_game_server.create_app`. Retained callers may supply an
   explicit owner and saved sessions through this same router.
2. The router serves list/details, status, saved sessions, calculations and
   resolution queries, plus Start/Stop and retained reference/result imports.
   `local_security` owns browser protections and request-body bounds;
   `query_policy` owns supported selectors and manual assumptions for HTTP and
   direct product callers. See [security](security.md).
3. The compatibility factory constructs `CoverageOwner(product_mode=True)`.
   `ContinuousSession` extends shared transport and journal infrastructure;
   native venue extensions use the same lifecycle. Real source execution needs
   an explicitly configured spec/approval. Isolated fixture and qualification
   launchers supply their own owner configuration to the same router.
4. Acknowledged observations feed `SessionProjection`, which preserves native
   identities and derives current/saved game, market, reference and result views.
   Its durable cursor/hash accounts for every admitted row, including historical
   selection records that no longer need a separate in-memory copy.
5. `session_history` verifies flat or segmented storage before saved projection.
   Native replay and finalization precede completion publication. Failed packages
   remain retained and unavailable or incomplete; see [failure handling](error-handling.md).
6. `product_view` maps shared snapshots to list/detail responses, enumerates
   references and selects an explicitly requested reference ID. It calls
   `multi_game.game_calculation` and shared board/score-line engines. Depth, fees,
   settlement and ranking remain server-side; browser code presents the results.
   `price_comparison.comparisons` builds same-outcome venue comparisons separately
   from net-return calculations. `saved_snapshot_cache` reuses verified saved
   snapshots; cutoff loading still validates the requested retained point.
7. Older saved captures still use `project_game` and `saved_rows`.
   `reference.multi_page` binds retrospective comparisons to their original games.
   Research keeps separate timing/ranking semantics and never supplies an earlier
   live probability.

## Data contracts and persistence

### Ordinary current HTTP and background work

| Route | Responsibility |
| --- | --- |
| `GET /`, `/arbs`, `/admin` | Odds board, explicit opposing pairs and separate operator surface |
| `GET /api/arbs` | Signed conditional opposing-pair results from the current snapshot |
| `GET /api/current`, `/api/current/updates` | Latest validated state and bounded revision notices |
| `POST /api/selections`, `GET /api/selections/{token}` | Create and inspect a temporary immutable calculation lease |
| `POST /api/selections/{token}/release`, `/api/selections/{token}/what-if` | Release a calculation lease or evaluate the existing explicit manual scenario |
| `GET /api/admin/status`, `GET/POST /api/admin/current` | Source/quota status, source pause, Stop, guarded recovery and owner sport-selectable refresh |
| `GET /admin/retained` | Preserved finite-session and saved-data inspection |

Source workers and the shared scheduler run inside the owned application process.
There is no external scheduler or unattended background service. Current aggregate
dispatch requires a live owned service/store, not browser attendance. Automatic
cycles consume daytime slots; owner refresh uses the same ledger without changing due times.
Browser connection state is not provider quote freshness. Current snapshots and
calculation leases are bounded memory; small configuration, attempt, issue and quota records
are durable. There is no ordinary ongoing quote-history requirement.

### Retained HTTP and background work

| Route | Responsibility |
| --- | --- |
| `GET /admin/retained`, `/game`, `/coverage` | Retained list, game-detail and coverage pages |
| `GET /api/status`, `/api/sessions` | Owner state and available session catalog |
| `GET /api/dashboard`, `/api/calculate`, `/api/resolution` | Filtered rows, detailed calculations and saved result views |
| `POST /api/start`, `/api/stop` | Explicit bounded collection and stop request |
| `GET /api/updates` | Bounded server-sent update notifications; HEAD returns headers only |
| `POST /api/references`, `/api/resolutions` | Validate and append retained records to an active product session |
| `GET/POST /api/watchlists`, `GET /api/signals` | Persist local filter criteria and report eligible current signals |
| `POST /api/decision-sizes`, `/api/math-scenario` | Evaluate supported quantities and conditional scenarios |
| `GET /api/opportunity-history`, `/api/math-scenario-download` | Exact saved-history review and scenario downloads |
| `GET /api/native-reviews`, `/api/source-bindings`, `/api/public-contracts` | Inspect retained judgments and source contracts without starting collection |

Import routes require an active session with a projection; they do not edit a
completed saved package. Frozen two-source qualification excludes both imports.
Start creates in-process collector tasks and a finalizer. The collector manages
producer tasks and its monitor; Stop requests shutdown, and saving may still be
in progress when the HTTP response returns. Observe `/api/status` until saving
finishes. Application cleanup requests Stop and awaits the finalizer. There is
no independent worker queue, scheduled scan or automatic restart/resume service.

Opportunity-history work runs in a thread with bounded concurrency; cancellation
of a request does not abandon its active worker. Resolution-history subprocesses
remain bounded local readers. Neither worker initiates provider collection.
Watchlists persist in `.local/predict-watchlists.json`; criteria authorize no
collection. Browser-held What-if assumptions are separate from provider credentials.

### Stored records

`models/core.py` defines immutable native models. The registry and shared sport
handlers resolve identity; matching, score/period/futures and settlement policies
retain explicit unsupported outcomes. Sporting identity does not prove equivalent
settlement.

Retained flat coverage packages retain the run specification, aggregate limits,
session journal, replay/report and completion manifest. Segmented packages use
`history/` segments plus manifests and the same replay/report boundary.
`CoverageOwner` selects finalization according to mode; `session_history.verified`
selects the reader. Older MultiOwner packages retain their observations/export/
selection layout. No migration, automatic pruning or evidence replacement occurs.

`reference.product` validates original-input references. `resolution.core` binds
sporting/venue result records to exact prediction cutoffs. Both append through
the retained finite-session collector without overwriting the original prediction.

PostgreSQL remains separate: `storage/store.py` and migrations retain earlier
capture, reference, fair-price and opportunity-audit contracts. These are not
interchangeable with current conditional board results. See
[storage CLI](../app/storage/__main__.py), [schema migrations](../app/storage/migrations/001_capture.sql),
[offline pricing](offline-pricing.md) and [offline opportunities](offline-opportunities.md).

## Retained surfaces and limits

| Surface | Current role |
| --- | --- |
| Ordinary Predict board and Admin | Shared `CurrentService` / `CurrentStore`, latest native/aggregate inputs, live Details, opposing-pair percentages and pause/Stop/recovery |
| Retained finite-session routes | Current/saved session projection, explicit Start/Stop, imports, references and result/history inspection |
| Native / two-source qualification panels | Same router and shared owner, with explicit spec/approval and separate attempt constraints |
| Historical capture readers | Active saved-catalog and research dependencies; original identities retained |
| All-outcome/depth/audit engines | Distinct calculation contracts, reused where appropriate |
| research and collection previews | Separate retained-evidence entry points; shared book/lifecycle helpers remain imported |
| Generic `python -m app.dashboard` | Delegates to the ordinary current-service entry point |
| Historical `scripts/dashboard` | Process controls retired with explicit failure before database actions or signals |
| Novig/ProphetX / GraphQL | Ordinary shared Odds API observations; separate retained native extensions and display-only GraphQL retain their own qualification boundaries |
| Trading | No order execution implemented |

Retained helpers still have runtime and fixture callers. Check those callers before retiring a shared reader or calculation contract.

## Module ownership

| Domain | Authoritative modules | Callers and boundary |
| --- | --- | --- |
| Routes | `dashboard/multi_game_server.py` | Ordinary CLI, app factories and explicit retained callers share one router |
| Configuration and ownership | `collection/current_policy.py`, `current_service.py`, `local_ownership.py` | Validation precedes workers and credentials; the service owns Stop/recovery |
| Aggregate policy | `collection/current_aggregate_policy.py`, `current_schedule.py` | One immutable policy supplies scheduler, transport, account and cycle limits |
| Credentials and quota | `collection/credential_handoff.py`, `current_quota.py` | Hidden key entry, guarded selection and durable reservations/reconciliation |
| Current ingestion | `current_native.py`, `current_aggregate_admission.py`, `current_overlap.py`, `current_sink.py` | Exact source admission and identity precede publication |
| Current state and math | `dashboard/current_state.py`, `current_contract.py`, `opportunities/percentages.py` | Validated revisions, temporary leases and original-input calculations |
| Browser boundary | `dashboard/local_security.py`, `query_policy.py` | Shared request/body and retained-selector validation |
| Browser presentation | Current browser modules and shared `u0/board.js` | Server-supplied values, ordered notices and keyed rendering |
| Retained data | `coverage_owner.py`, `session_projection.py`, `session_history.py`, finite collectors | Explicit saved cutoffs and durable completion; no current-data fallback |
| Shared domain math | `fees/`, `settlement.py`, `normalization/`, `depth.py` | Fees, payouts, identity and quantity math retain separate contracts |

Finite stream grouping is separated into `collection/continuous_streams.py` with
explicit dependencies supplied by the public collector constructor. Discovery and
finite-session ownership stay in `continuous.py`; the stream module never imports
its owner. Keep saved schema versions and required fixture identities stable when
changing these boundaries.
