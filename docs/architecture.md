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
3. `MultiOwner` owns one scan and its finalizer. `MultiSession` extends
   `TransportSession`; discovery uses shared normalization and native venue
   adapters, then binds event/market/purchase sides before subscribing.
   Async producer tasks collect bounded REST/WebSocket observations; there is
   no separate worker service or job scheduler.
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
