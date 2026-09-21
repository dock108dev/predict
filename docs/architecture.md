# Architecture and data

The current product is the file-backed personal beta. [SSOT](ssot.md) owns module
and retention decisions; this guide describes how those pieces connect.

## Current request and collection flow

1. `scripts/opportunity-board` launches `app.dashboard.opportunity_board`, whose
   factory delegates to `multi_game_server.create_app`. Startup loads retained
   captures and stays idle. The CLI explicitly denies psycopg connections.
2. `multi_game_server` serves the list at `/`, details at `/game`, and browser
   assets from `opportunity_static`, shared E5 state and historical base CSS.
   `GET /api/status`, `/api/dashboard`, `/api/sessions` and `/api/calculate`
   expose status, projections, cutoffs and calculations. Same-origin JSON
   `POST /api/start` and `/api/stop` control the owner.
3. Production uses `CoverageOwner`, the D2 mode of `MultiOwner`, with one
   collector/finalizer and a persistent one-attempt guard. `ContinuousSession`
   extends `TransportSession`; D1 inventory builds each venue independently
   before subscriptions. `/coverage` supplies bounded pilot Start/Stop and health.
   Historical `MultiSession` remains for retained sample-mode workflows/tests.
   No separate worker service or job scheduler is introduced.
4. The journal retains native inputs and health changes. Finalization reopens the
   journal, verifies native replay and publishes a manifest. Saved reads validate
   recorded file hashes and the journal chain. See [recovery](error-handling.md)
   for failure states and durability limits.
5. `project_game` isolates native event and market identity. Saved views select a
   retained cutoff; live projection ages each leg. `game_calculation` calls
   `opportunities.board.evaluate`, sharing depth, fee and settlement helpers.
   Decimal ranking happens server-side; the browser presents results.
6. `reference.multi_page` binds separate retained page comparisons to their games.
   Page research, explicit manual probabilities and observed Arb calculations
   remain separate. Page receipt timing cannot supply an earlier live probability.

## Data contracts and persistence

`models/core.py` defines immutable event, market, quote, order-book and raw-payload
models, typed quantities, monetary values and separate synchronization/freshness
states. `normalization/registry-v1.json` supplies identity aliases;
`matching.py` and `moneyline.py` implement versioned event/market decisions.
Sporting identity alone does not establish settlement equivalence.

A beta session directory contains `run-record.json`, `run-spec.json`,
`aggregate-limits.json`, `selection.json`, the finalized `observations.jsonl`,
`saved-observations.json`, `replay.json` and `manifest.json`. Discovery can also
retain `account-api-limits.json`. The manifest hashes the six calculation/replay
inputs listed in `MultiOwner.finish`; it does not claim every file in the folder
is covered. A pending manifest is not a completed catalog entry. Originals and
partial runs are retained; there is no automatic file migration or garbage collection.

The SQL path is independent: `storage/store.py` and migrations 001–003 retain
artifacts, sessions, receipts, quote observations, metadata, calculations,
candidates and coverage. Migrations 004–006 add reference histories, fair-price
inputs and opportunity audits. `reference/records.py`, `pricing/baseline.py` and
`opportunities/service.py` provide versioned records/calculations and replay;
their storage modules persist those contracts. These audited research paths are
not interchangeable with the current conditional board API. See
[Slice 12](slice-12.md), [E2](e2-implementation-report.md),
[E3 contracts](e3-contracts.md) and [E4 contracts](e4-contracts.md).

## Supported and retained surfaces

| Surface | Current role and limits |
| --- | --- |
| Multi-game beta | Kalshi/Polymarket US NFL pregame comparisons, bounded explicit collection and saved replay |
| Conditional board | Normal-winner Arb and explicit what-if EV; unknown fees/exceptional settlement remain unavailable, not guaranteed profit |
| Saved page research | Retrospective, event-bound DraftKings page estimates; bookmaker timing/delay and unconditional EV remain unresolved |
| `arbitrage.py`, `depth.py` | Earlier all-outcome detection and depth sizing; stricter qualification is distinct from conditional board results |
| `pricing/`, `opportunities/service.py` | Retained fair-price and opportunity audit engines; not automatic live fair-value generation |
| `scripts/dashboard` | Historical PostgreSQL Slice 13 dashboard, separate from the beta |
| E5/E6 preview launchers | Historical synthetic, saved-real, live-watch and recovery workflows; shared helpers are still imported by the beta |
| ProphetX adapter | Historical sandbox transport/REST evidence; live sizing and selection reconstruction incomplete |
| Novig adapter | Offline-tested implementation; live credentials and wire qualification pending |
| Trading / execution | No order integration; no observed or simulated result authorizes trading |

Do not delete a module just because its launcher is historical. Known callers and
retirement prerequisites are recorded in [SSOT](ssot.md#conflicts-removed-and-retained-paths).
Use [configuration](configuration.md) for paths and credentials and
[development](development.md) for targeted tests. Historical test counts and
owner-review artifacts describe their original candidate, not the current checkout.

## Offline coverage inventory

`python -m app.collection.coverage` reads retained native discovery HTTP envelopes
or explicitly synthetic page fixtures. Independent venue catalogs preserve all
observed events/markets, including unresolved identities and unsupported sides,
then annotate event overlap and retained counterpart market presence. Page-chain
completeness and count partitions are explicit and independent of the beta's six
game cap. Reports do not authorize subscriptions or prove contract equivalence.
See [D1 report and command](data-coverage-d1-report.md). D2 will connect this
foundation to collection; the running beta is unchanged by D1.


## D2 bounded collector — current implementation

`collection/continuous.py` owns live discovery/reconciliation, reusing D1 catalogs,
native stream engines and the existing journal. `dashboard/coverage_owner.py`
owns the one-pilot guard, process lock, grouped native replay and finalization.
The production factory selects this owner. Startup is idle; the consumed attempt
prevents another Start, including after restart. Collection belongs to the server,
not a browser request. The 60-second refresh and five-minute cutoff remain inside
the same finite Start deadline and budgets.

D2 evidence is separate under `evidence/d2-coverage/<session>/`: immutable journal,
run spec, limits, replay, report and manifest. It is not added to saved calculation
catalogs or live opportunity ranking. Existing saved math/history remains unchanged.
The one live pilot failed before catalogs/subscriptions; the repaired code has only
offline validation. See [D2 outcome and gaps](data-coverage-d2-report.md). D3 segments,
outcomes, settlement and D4 dashboard integration remain deferred.

D2 offline journal-efficiency candidate uses versioned, lossless per-row compression inside the existing hash-chain journal; `reopen` restores identical rows for native replay. Logical record, expanded queue, memory and terminal-reserve accounting remain explicit. Legacy journals are untouched. This candidate is not live-validated; the unchanged record ceiling still limits the measured workload. See [efficiency report](data-coverage-d2-journal-efficiency-report.md).


## D3a offline segmented history — September 16, 2026

`collection/segmented.py` extends `ObservationJournal` with the separately versioned
`d3a-offline-segments-1` file mode, cumulative policy, seals, atomic manifests and
read-only interrupted-prefix indexes. `NativeVerifier` shares the legacy native
parsers/converter; `GroupedNativeVerifier` keeps sequential stream state across
segments without a whole-run list. Metadata, command and native image dependencies
must precede a usable book. No checkpoints or external payload store are used.

`dashboard/coverage_owner.py:OfflineHistoryOwner` handles retained-input admission,
expanded queue accounting and offline Stop/finalization; `replay_segmented` verifies
completed histories. The production factory still selects legacy `CoverageOwner`.
D2 transport, 2,048 lifetime ingress allowance and original recovery identity checks
are unchanged. Mock collector integration is delivered through an explicitly isolated path; there is no
live segmented route or daily collection authorization. See [D3a results, storage
format and recovery limits](data-coverage-d3a-report.md). D2 and full D3 are incomplete.


## Mock-only segmented collector integration — September 16, 2026

`CoverageOwner(mock_segmented=True)` requires an isolated output root and explicit
numeric-loopback fixture endpoints. It runs the existing `ContinuousSession`,
discovery and native producers, using `SegmentedTransportJournal` and sequential
finalization. Production construction does not select this option. No credential
resolution, reference feed or external redirect is permitted in the mock path.
Published catalog generations, producer-applied generations and usable books are
separate; shared lifecycle cleanup creates the terminal only after producer joins
and queue accounting. Failure cannot manufacture completion. D3a policy and D2
limits/attempt protection remain unchanged. Busy local Stop passes; resource
pressure still exhausts four segments at 4,092 ingress. See [integration report](data-coverage-d3-mock-integration-report.md).
Next is an offline sustained-capacity policy/experiment, not a live pilot.
