# Development

Use Python 3.11+ from a source checkout. Python 3.14 and Node 24 match primary CI.
Run commands from the repository root. Native operation uses macOS Keychain;
portable offline tests also run on Linux.

## One local working copy

Develop, integrate, build and run directly in the primary repository on `main`.
Do not create successor repositories or candidate workspaces unless explicitly
requested. Use disposable test fixtures/databases in place. Older isolated
closeouts are historical evidence, not a requirement to defer local integration.
Keep credentials, settings and account/quota/hold state intact.

## Install tools

```sh
python3.14 -m venv .venv
nvm use
.venv/bin/python -m pip install --require-hashes -r requirements-ci.txt
.venv/bin/python scripts/ci/validate_lock.py
.venv/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
.venv/bin/python -m pip check
```

The hash lock includes runtime, stream, test and build dependencies. The smaller
editable installation in the [README](../README.md) is enough for ordinary use.

## Focused checks

Use existing tests for the behavior you change. The manifests under `scripts/ci/`
distinguish portable tests from SQL tests and older acquisition tools that require
captured inputs or provider access. Do not run every discovered test against
ordinary local data.

```sh
.venv/bin/python -m ruff check app tests scripts/ci browser_tests
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ev09_asset_delivery.py
node tests/test_stored_views.cjs
node tests/test_comparison_usability.cjs
git diff --check
```

| Change | Useful tests under `tests/` |
| --- | --- |
| Asset delivery and calculation cancellation | `test_ev09_asset_delivery.py`, `test_ev09_b01.py`, `test_ev09_calculation_stop.py` |
| Settings, game selection and polling | `test_ev09_u01.cjs`, `test_ev09_game_continuity.cjs`, `test_ev09_read_polling.cjs` |
| Current board contracts and selected Details | `test_current_board_reads.py`, `test_d03_current_client.cjs`, `check_current_api_client.cjs` |
| Calculation policy and requested funding | `test_estimated_policy.py`, `test_ev09_s01.py`, `test_comparison_cashflows.py` |
| Event matching and combined inputs | `test_ev02_occurrence.py`, `test_ev09_n01.py`, `test_comparison_event_links.py` |
| SQL ingress, expiry and retired routes | `test_database_ingress_repair.py`, `test_current_route_retirement.py`, `test_ev09_ingress_isolation.py` |
| Native HTTP admission and retry bounds | `test_native_http_reader.py`, `test_ordinary_native_transport.py` |
| CI reporting failures | `test_ci_reporting.py` |

Run resource-sensitive Python modules in fresh processes: some deliberately
measure process caps. Use authored fixtures and temporary state. For SQL tests,
use `.venv/bin/python scripts/ci/postgres.py`; it creates a disposable socket-only
cluster, redirects the storage root, runs `integration_tests` and the registered
current-row roundtrips, then tears down the cluster. Do not invoke those SQL
modules directly against ordinary storage. The harness also keeps socket paths
short enough for Unix limits. Primary SQL qualification requires PostgreSQL 16;
set `PG_CONFIG` to that installation's `pg_config` when PATH selects another
major. `--report-dir` (or `PREDICT_CI_POSTGRES_REPORT_DIR`) preserves separate
environment results, including a `toolchain.json` identity receipt. The explicit
`--allow-other-postgres` flag labels intentional older-major diagnostics as
compatibility runs. Python 3.11 remains a supported compatibility lane.

```sh
PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config .venv/bin/python scripts/ci/postgres.py --report-dir test-results/postgres-py314-pg16
```

The SQL lane includes SC06's varied financial current-row roundtrip. The actual
500-event SQL-to-Chromium workload uses the same disposable PostgreSQL owner:

```sh
PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config .venv/bin/python scripts/ci/postgres.py --sc06-browser --report-dir test-results/postgres-sc06-browser
```

It requires the locked browser tooling and matching Chromium. A missing socket,
database or browser does not establish qualification. The browser CI wrapper
provisions this PostgreSQL lane rather than replacing financial work with scalar
fixtures. The retained timing report preserves waiting, failures and timeouts.

The ordinary launcher selects tools matching its existing cluster's `PG_VERSION`
even when PATH selects PostgreSQL 16. `PREDICT_PG_BIN` can select that matching
installation explicitly. An existing database requires a separate data migration
to change major versions; these test commands never migrate it.

`PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci` runs the full portable manifest
and writes ignored reports under `test-results/ci`. See [CI](CI.md) for browser,
packaging and scheduled checks. A documentation-only edit usually needs the
documentation checker, reference review and whitespace check.

The optional `browser_tests/test_u02_browser.cjs` replay takes explicit response
and partial-failure JSON paths and uses `PREDICT_PLAYWRIGHT_MODULE` to locate an
installed Playwright module. Its reports stay under `test-results/u02-replay/`;
it does not read an implicit temporary export or contact the running app.

## Synthetic preview

```sh
.venv/bin/python -m tests.current_integration_server --synthetic-test --port 8797
```

Open its loopback address, `/arbs` or `/admin`; stop with Ctrl-C. The provider is
synthetic and does not acquire source data. Its `/__test/commit` route belongs
only to this test server. `.venv/bin/python -m tests.comparison_preview` supplies
additional comparison fixtures. Injected previews and intercepted browser tests
exercise presentation and contracts; SQL persistence and live coverage have
separate tests.

## Frontend sources

The authored frontend is under `app/dashboard/opportunity_static/current/`:

- `scanner-client.js` validates scanner v1, bounded page reads and compatibility;
  `scanner-controller.js`, `scanner-style.css` and `scanner-shell.html` own the
  compact landing scanner. `ticket-client.js` and `ticket-view.js` own selected
  commands, persistent panel/sheet and exact frame presentation;
  `scanner-arrivals.js` consumes filter-wide server transition observations;
  `scanner-summaries.js` validates the optional bounded observed-summary disclosure. The generator
  also produces scanner.js/css/html and scanner-runtime.json. See the
  [client contract](scanner-client-contract.md) for bounds and SC05/SC06 seams.
- [Readiness preparation reuse](scanner-preparation-contract.md) documents the
  bounded scanner/selected-ticket caches, exact invalidation and temporal proof.
- `stored-controller.js` owns auxiliary Odds/EV settings, selection, polling, cancellable reads,
  dialogs and Stop.
- `board-client.js` validates settings and response identities; `board-elements.js`
  provides shared formatting and display primitives.
- `comparison-slate-views.js` groups games and rows; `stored-views.js` supplies
  the compatible per-board presenter and view factory.
- `stored-details.js` renders the selected current calculation and original inputs.
- `stored-shell.css`, `stored-boards.css`, `stored-details.css` and
  `stored-responsive.css` compose styles in cascade order.

Regenerate the public assets after editing their authored sources:

```sh
.venv/bin/python scripts/build_stored_frontend.py
.venv/bin/python scripts/build_stored_frontend.py --check
node --check app/dashboard/opportunity_static/current/stored.js
```

The dependency-free generator handles this closed graph and unaliased named
imports; add new client symbols to `CLIENT_NAMES`. It is not a general JavaScript
bundler. Generated `stored.js` and `stored.css` are required packaged resources:
keep them tracked and do not edit them directly. CI checks for drift. Reload the
page after rebuilding assets; restart the app after backend or credential changes.

## Maintenance boundaries

[Architecture](architecture.md) describes module ownership. Ordinary ingress uses
`CurrentRowStore`; board and slate reads calculate transiently from current SQL
rows. Details binds to the clicked input context and requires a new selection
when those inputs change. Older archive readers serve separate retained-research
interfaces. See the [storage guide](current-row-storage.md) and
[board contract](comparison-board-api-contract.md).

Preserve public imports, packaged resource paths, protocol versions and applied
migrations. Keep financial validation beside the models it admits, collection
Stop and cleanup ordering with lifecycle owners, and quota/hold updates with
their accounting owners. Prefer focused helpers when a module gains a distinct
responsibility; keep controller state and CSS cascade ordering coherent.

Keep credentials, local state, generated reports and coding notes out of Git.
Required fixtures belong in `tests/fixtures` or `app/fixtures`; schemas and wire
examples belong in `docs/contracts`. Retained fee documents and the exact inputs
used by sealed executor packages are test/runtime inputs, not disposable output.
Public documentation should use repository-owned paths and explain current
behavior without depending on local plans or reports.
