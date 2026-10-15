# Development

Use Python 3.11+ from a source checkout. Python 3.14 and Node 22 match primary
CI. Run commands from the repository root. Native operation uses macOS Keychain;
portable offline tests also run on Linux.

## Install tools

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-ci.txt
.venv/bin/python scripts/ci/validate_lock.py
.venv/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
.venv/bin/python -m pip check
```

The hash lock includes runtime, stream, test and build dependencies. For ordinary
app use, the smaller editable installation in the [README](../README.md) suffices.

## Current-row ownership

Ordinary ingress commits through `CurrentRowStore`; v2 board/slate reads hydrate
selected depth and calculate transiently. Old `GameStore` archive methods and
codecs serve retained research compatibility. Ordinary board reads do not fall
back to them. See [architecture](architecture.md), [current storage](current-row-storage.md)
and the [board contract](comparison-board-api-contract.md).

The v2 slate admits up to 500 games through pages of at most 50 and rejects
changed cross-page revisions. Sports rows are disposable; credentials, settings,
account/quota/audit/due/attempt/hold state have independent lifetimes. Use the
explicit sports reset when needed. Applied migration SQL/checksums are immutable.

## Focused checks

Choose tests for the changed behavior. Do not discover every test indiscriminately:
some historical acquisition tools require captured inputs or provider access.

```sh
.venv/bin/python -m compileall -q app/dashboard app/collection
.venv/bin/python -m ruff check app tests scripts/ci
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ev09_asset_delivery.py
node tests/test_stored_views.cjs
node tests/test_comparison_usability.cjs
```

| Change | Useful existing tests |
| --- | --- |
| Asset delivery, publication and calculation Stop | `test_ev09_asset_delivery.py`, `test_ev09_b01.py`, `test_ev09_calculation_stop.py` |
| Settings, selection and read cancellation | `test_ev09_u01.cjs`, `test_ev09_game_continuity.cjs`, `test_ev09_read_polling.cjs` |
| Current SQL, expiry, ordering, failed saving and concurrent readers | `test_d03_current_rows.py`, `test_d03_aggregate_frame.py`, `test_current_reset.py` |
| Current v2 contracts, financial adapters, Details and Stop/read bounds | `test_current_board_reads.py`, `test_d03_current_client.cjs`, `check_current_api_client.cjs` |
| Calculation policy and requested funding | `test_estimated_policy.py`, `test_ev09_s01.py`, fee, cashflow and metric tests |
| Occurrence matching and combined inputs | `test_ev02_occurrence.py`, `test_ev09_n01.py`, event-link and domain tests |
| Legacy/research journal admission; no ordinary-history requirement | `test_current_journal_segments.py`, `test_current_retained.py`, `test_ev09_ingress_isolation.py` |
| Native HTTP framing | `test_native_http_reader.py` |
| CI support and report failures | `test_ci_reporting.py` |

Python test filenames above are under `tests/`. Run resource-sensitive modules in
fresh processes: combining them can exceed process caps that each module tests.
Use authored fixtures and disposable state, not credentials or ordinary storage.
The SQL tests in the table need a disposable socket-only database and a redirected
`app.storage.store.ROOT`; do not invoke them directly against ordinary storage.
`scripts/ci/postgres.py` supplies that isolation for `integration_tests`. Its
current command does not select the separate current-row roundtrip modules.
`sh scripts/check-ci` selects the portable manifest and writes ignored reports
under `test-results/ci`. [CI](CI.md) describes SQL, browser and scheduled checks.

## Synthetic preview

```sh
.venv/bin/python -m tests.current_integration_server --synthetic-test --port 8797
```

Open its loopback address, `/arbs` or `/admin`; stop with Ctrl-C. The provider is
explicitly synthetic and does not acquire data. Its `/__test/commit` route is
exclusive to this test server. `.venv/bin/python -m tests.comparison_preview`
provides additional comparison fixtures. These previews use the injected current
state interface. Browser tests under `browser_tests/` intercept the current v2
slate and revision-bound Details interface. Neither injected previews nor
intercepted responses demonstrate ordinary SQL persistence or live coverage.

## Frontend sources

Under `app/dashboard/opportunity_static/current/`:

- `stored-controller.js` owns settings, game/result selection, three cancellable
  read channels, polling, dialog ownership and Stop.
- `board-client.js` validates exact settings/response identities and bounded reads.
- `board-elements.js` provides display primitives, participant labels and exact
  rational/decimal reference prices formatted as American odds.
- `comparison-slate-views.js` owns compact all-games grouping, cross-venue
  presentation selection and immutable per-row callbacks. `stored-views.js`
  retains the compatible per-board presenter and ordinary factory.
- `stored-details.js` renders selected current reconciliation. The controller requires the clicked context revision, replaces the whole dialog on refresh and clears financial content on changed/removed inputs. Old history/envelope controls are removed; Original requests allowlisted selected current facts.
- `stored-shell.css`, `stored-boards.css`, `stored-details.css` and
  `stored-responsive.css` compose styles in cascade order.

Regenerate the required public assets after editing their sources:

```sh
python3 scripts/build_stored_frontend.py
python3 scripts/build_stored_frontend.py --check
node --check app/dashboard/opportunity_static/current/stored.js
```

The dependency-free generator supports this closed graph and unaliased named
imports; new client symbols must be added to `CLIENT_NAMES`. Module-local mutable
state belongs only in the controller. It is not a general JavaScript bundler.
Keep generated `stored.js` and `stored.css` available to packaging and routes;
do not edit or ignore them. CI checks generated drift. The fixed public names
also work with an already loaded asset allowlist. Reload the page after rebuilding
frontend assets; restart the app after backend or credential changes.

## Maintenance

[Architecture](architecture.md#module-ownership) defines module boundaries. Preserve
public imports, packaged resource paths and explicit protocol versions. Legacy
sports-history readers need not survive a deliberate reset; current contracts
and protected account/configuration state must remain correct. Ruff checks
critical defects; formatting checks cover CI support. Keep localized product
edits consistent with adjacent source. Review physical Python lines above 500,
with extraction or justification above 1,000; JavaScript uses 300/600, UI presenters
250/500, CSS 300/600, markup 250/500 and shell 100/200. Generated files, immutable
schemas and applied migrations are not mechanically split.

The comparison controller keeps one selection/cancellation mutation boundary; splitting
it among mutable owners would make publication races harder to reason about.
The view presenter shares one participant/callback context; responsive CSS keeps
cross-view breakpoints and final overrides together. Discovery, native lifecycle
and quota owners also keep ordering, budgets and cleanup in cohesive state
machines. Transport and stream mechanics already have separate modules. Wire
validators stay beside the types they admit. Revisit these choices when a module
grows or gains a responsibility.

Keep credentials, local state, reports and coding notes out of Git. Required
fixtures live in `tests/fixtures` and `app/fixtures`; schema examples live in
`docs/contracts`. Sealed executors depend on exact inputs under
`scripts/v1_coverage_package` and `scripts/v1_counterpart_package`; preserve them.
The retained fee PDF is a test input, not disposable output. Run
`git diff --check` after edits. Public docs must stand on repository-owned paths
and must not depend on local reports, plans or personal trackers.
