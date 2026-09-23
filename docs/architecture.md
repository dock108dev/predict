# Architecture and data

The current product is a local, file-backed sports prediction dashboard.
[SSOT](ssot.md) owns module and retention decisions; the [Desktop tracker](../../prediction_arb_next_steps.md)
owns current scope and execution authority. Engineering supports six sports and
multiple market families; actual venue/model qualification and beta signoff remain
open. Historical reports do not establish current live readiness.

## Current request and collection flow

1. `scripts/opportunity-board` launches `app.dashboard.opportunity_board`, which
   delegates to `multi_game_server.create_app`. The CLI binds loopback, denies
   database connections and starts idle with retained data.
2. The router serves list/details, status, saved sessions, calculations and
   resolution queries, plus Start/Stop and retained reference/result imports.
   `local_security` owns browser protections and request-body bounds;
   `query_policy` owns supported selectors and manual assumptions for HTTP and
   direct product callers. See [security](security.md).
3. The default factory constructs `CoverageOwner(product_mode=True)`.
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
7. Older saved captures still use `project_game` and `saved_rows`.
   `reference.multi_page` binds retrospective comparisons to their original games.
   Research keeps separate timing/ranking semantics and never supplies an earlier
   live probability.

## Data contracts and persistence

### HTTP and background work

| Route | Responsibility |
| --- | --- |
| `GET /`, `/game`, `/coverage` | List, game-detail and coverage pages |
| `GET /api/status`, `/api/sessions` | Owner state and available session catalog |
| `GET /api/dashboard`, `/api/calculate`, `/api/resolution` | Filtered rows, detailed calculations and saved result views |
| `POST /api/start`, `/api/stop` | Explicit bounded collection and stop request |
| `POST /api/references`, `/api/resolutions` | Validate and append retained records to an active product session |

Import routes require an active session with a projection; they do not edit a
completed saved package. Frozen two-source qualification excludes both imports.
Start creates in-process collector tasks and a finalizer. The collector manages
producer tasks and its monitor; Stop requests shutdown, and saving may still be
in progress when the HTTP response returns. Observe `/api/status` until saving
finishes. Application cleanup requests Stop and awaits the finalizer. There is
no independent worker queue, scheduled scan or automatic restart/resume service.

### Stored records

`models/core.py` defines immutable native models. The registry and shared sport
handlers resolve identity; matching, score/period/futures and settlement policies
retain explicit unsupported outcomes. Sporting identity does not prove equivalent
settlement.

Current flat coverage packages retain the run specification, aggregate limits,
session journal, replay/report and completion manifest. Segmented packages use
`history/` segments plus manifests and the same replay/report boundary.
`CoverageOwner` selects finalization according to mode; `session_history.verified`
selects the reader. Older MultiOwner packages retain their observations/export/
selection layout. No migration, automatic pruning or evidence replacement occurs.

`reference.product` validates original-input references. `resolution.core` binds
sporting/venue result records to exact prediction cutoffs. Both append through
the ordinary collector without overwriting the original prediction.

PostgreSQL remains separate: `storage/store.py` and migrations retain earlier
capture, reference, fair-price and opportunity-audit contracts. These are not
interchangeable with current conditional board results. See
[Slice 12](slice-12.md), [E2](e2-implementation-report.md),
[E3 contracts](e3-contracts.md) and [E4 contracts](e4-contracts.md).

## Retained surfaces and limits

| Surface | Current role |
| --- | --- |
| Ordinary Predict router | Current/saved multi-sport projection, conditional Arb/EV, references, results and bounded Start/Stop |
| Native / two-source qualification panels | Same router and shared owner, with explicit spec/approval and separate attempt constraints |
| Historical capture readers | Active saved-catalog and research dependencies; original identities retained |
| All-outcome/depth/audit engines | Distinct calculation contracts, reused where appropriate |
| E5/E6 previews and `scripts/dashboard` | Separate historical entry points; shared book/lifecycle helpers remain imported |
| Novig/ProphetX / GraphQL | Native collector extensions; real qualification gaps remain. Display-only prices are not sized opportunities |
| Trading | No order execution implemented |

Retirement requires call-site and evidence review before removing shared modules;
see [SSOT follow-up](ssot.md#conflicts-removed-and-retained-paths).
Original results remain in their dated reports: [coverage](data-coverage-d1-report.md),
[D2](data-coverage-d2-report.md), [journal efficiency](data-coverage-d2-journal-efficiency-report.md),
[segmented history](data-coverage-d3a-report.md), and
[mock integration](data-coverage-d3-mock-integration-report.md).
These are historical candidate evidence, not current operating instructions.
