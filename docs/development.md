# Development

Use Python 3.11+ from a source checkout. Python 3.14 and Node 24 match primary CI.
Run commands from the repository root. Native operation uses macOS Keychain;
portable offline tests also run on Linux.

## Ordinary app and background data

```sh
scripts/opportunity-board start
scripts/opportunity-board status
scripts/opportunity-board stop --role app
scripts/opportunity-board start --role app
scripts/opportunity-board status --role data
scripts/opportunity-board stop --role data
scripts/opportunity-board start --role data
```

The default role is both. App-only stop/restart leaves acquisition and shared
calculations running. Stopping data ends its process; Admin global/source Stop
is an acknowledged acquisition control with a persistent Stop latch. Starting a
data process preserves explicit pauses and unresolved accounting; it does not
clear holds or force catch-up. Use existing guarded Admin recovery only with its
required evidence. [Runtime contract](data-app-runtime-contract.md).

Focused separation SQL and the small authored working loop use disposable storage:

```sh
PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config .venv/bin/python scripts/ci/postgres.py --da-separation --report-dir test-results/da-separation/sql
```

This focused lane excludes the broader compatibility manifest and stress workloads.
Its fixture sources make zero provider requests. It also verifies independent
observation publication under missing/expired/malformed finance, bounded depth,
source health versus estimate validity, per-game reuse and database-only Inputs. Ordinary authorized source
activity is attributed separately.

For freshness and comparison changes, use authored mixed-state inputs and the
affected latest-board SQL tests. Preserve original source clocks, exact peer
identity and explicit missing-input states. Browser filters and age updates must
not dispatch providers or calculate the whole slate.

Original-input identity binds the retained source facts, independently of elapsed
age. Crossing the native 30-second freshness boundary keeps unchanged inputs
inspectable and labels them expired; changed quotes, books, matching dependencies
or runtime authority still invalidate the selection. Ordinary slate reads decode
only the requested stored Odds/EV/Arbs view, within the existing read deadline and
memory guards. The consistent-slate SQL test covers expiry between page and Details,
view projection, and pagination through the actual browser module imports.

Background shutdown cancels active SQL operations as well as cooperative Python
work. Connections and worker tasks remain owned until they finish, including when
the cleanup deadline expires. The multisport SQL lane verifies cancellation of
an active 30-second database sleep within the existing cleanup limit. Offline
recovery fixtures use their authored clock for scheduler windows, so running CI
outside collection hours does not change the test outcome.

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
| Captured multi-page reads and recovery | `test_consistent_slate_reads_sql.py` in the disposable SQL lane, `test_consistent_slate_reads.cjs` |
| Calculation policy and requested funding | `test_estimated_policy.py`, `test_ev09_s01.py`, `test_comparison_cashflows.py` |
| Event matching and combined inputs | `test_ev02_occurrence.py`, `test_ev09_n01.py`, `test_comparison_event_links.py` |
| SQL ingress, expiry and retired routes | `test_database_ingress_repair.py`, `test_current_route_retirement.py`, `test_ev09_ingress_isolation.py` |
| Native HTTP admission and retry bounds | `test_native_http_reader.py`, `test_ordinary_native_transport.py` |
| Runtime failure handling and detached reads | `test_data_runtime_unit.py`, `test_selected_read_work.py`, `test_abend_handling.py`; `test_sc02_sql.py` through the disposable SQL harness |
| Local browser, error privacy and launcher log targets | `test_security_hardening.py`, `test_dashboard_security.py`, `test_current_board_reads.py` |
| CI reporting and isolation failures | `test_ci_reporting.py`, `test_ci_environment.py`, `test_ci_assurance.py`, `test_ci_secrets.py` |

Client tests that generate server fixtures also need the locked Python environment.
Set `PYTHON="$PWD/.venv/bin/python"` when running them directly, for example
`PYTHON="$PWD/.venv/bin/python" node tests/test_b02_client.cjs`. The full portable
runner selects its own Python interpreter for these child processes.

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

The SQL lane includes small financial current-row roundtrips, ready tickets,
original-clock expiry and missing-depth refusal. Full-scale performance and
burst testing are not routine CI prerequisites or established performance claims.

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
  advanced Scanner at `/scanner`. `ticket-client.js` and `ticket-view.js` own selected
  commands, persistent panel/sheet and exact frame presentation;
  `scanner-arrivals.js` consumes filter-wide server transition observations;
  `scanner-summaries.js` validates the optional bounded observed-summary disclosure. The generator
  also produces scanner.js/css/html and scanner-runtime.json. See the
  [client contract](scanner-client-contract.md) for bounds, ticket interaction and summary reads.
- [Readiness preparation reuse](scanner-preparation-contract.md) documents the
  bounded scanner/selected-ticket caches, exact invalidation and temporal proof.
- `opportunity-dashboard.js` renders the default `/` opportunity dashboard, exact supplied-value ordering, independent availability, and separate research groups.
- `stored-controller.js` owns dashboard and Odds/EV settings, selection, polling, cancellable reads,
  dialogs and Stop.
- `board-client.js` owns settings, game continuity and coherent slate pagination;
  `board-contract.js` validates and expands response identities, and `board-values.js`
  owns presentation numbers and exact decimal equality. The public client exports
  remain compatible. `board-elements.js`
  provides shared formatting and display primitives. `board-read.js` owns bounded
  cancellable reads and completion-based polling; `board-client.js` preserves its
  public read-helper exports for existing controllers.
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
`CurrentRowStore`; background owners calculate affected shared results and the app
reads latest database publications. Only selected Details/tickets calculate amounts
on request. Details binds to the clicked input context. A leased selected frame preserves
its original evidence across current-input changes, labels it captured and withdraws
current eligibility; View updated results selects the latest inputs. Expired or
unknown frames still require a new selection. Older archive readers serve separate retained-research
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

Review Python modules above 500 physical lines and extract a cohesive responsibility
or document a concrete retention reason above 1,000. For authored JavaScript and
CSS use 300/600 lines. Tests use their language's thresholds. Judge extensionless
launchers by their shebang: `scripts/opportunity-board` is Python. These are review
triggers, not reasons to compress formatting or add forwarding fragments.

Native catalog selection and bounded diagnostics live in
`collection/current_native_catalog.py`; `current_native.py` preserves public helper
imports and owns transport lifecycle. Its remaining worker intentionally keeps
discovery, socket replacement, Stop, hourly budgets and cleanup together: these
operations share the same socket/task/credential/budget ownership. Splitting its
methods into stateful mixins would obscure that ownership. Review another
extraction if a separate transport or lifecycle owner becomes necessary.

Latest-board SQL capture sizing and fair source scheduling live in
`storage/board_capture.py`; `storage/board_view.py` renders captured results and
bounds wire pages without acquiring inputs. `latest_board.py` owns transactional
publication, reconciliation, snapshot authority and its background task. The
public `board`/`bounded_page` imports remain available there. Engine identity
includes both extracted modules. SQL tests share disposable setup in
`tests/latest_board_fixture.py`; `test_latest_board_sql.py` retains its public test
class and independently reset behavioral cases.

The native worker remains just above 1,000 lines after adding async book publication:
its queued books, pending publication task, discovery replacement and close path
share one cancellation/Stop owner. The existing catalog extraction remains the
stateless boundary; separating publication into a second state owner would make
shutdown and resync ordering harder to verify. The 648-line `stored-controller.js`
likewise retains one UI lifecycle: generation cancellation, applied settings,
selection leases, modal focus and Stop all mutate the same current view. Rendering,
wire validation, pagination and read scheduling are already separate modules;
extract a new controller only when it can own an independent state lifecycle.
Review these decisions when those responsibilities change.

CI regression tests are separated into `test_ci_reporting.py`,
`test_ci_environment.py`, `test_ci_assurance.py` and `test_ci_secrets.py`, with
tool loading in `tests/ci_support.py`. The quality workflow runs all four:

```sh
.venv/bin/python -m pytest -q tests/test_ci_*.py
```

Generated runtime bundles (`stored.js`, `stored.css` and `scanner.*`) are excluded
from mechanical splitting; review their authored modules and generator instead.
Keep generated runtime resources tracked. The PDFs under the native scoring and
retained-retail fixtures and the sealed `scripts/v1_*_package/SOURCE.zip` archives
are required fixture or frozen-package inputs. Preserve them alongside their
manifests; they are not disposable test evidence. Existing ignore rules cover
local output, caches, reports and private state; inspect tracked ignored files
with `git ls-files -ci --exclude-standard` before adding new exceptions.

EV uses the dashboard's metric-specific renderer with a single EV scope. Its
controller requests all retained results so an empty positive subset cannot stand
in for complete evaluation. `coverage.js`, `coverage-model.js` and
`coverage-view.js` are authored ES modules served directly, with `coverage.html`
and `coverage.css`; they are not generated into `stored.js`. After changing the
Coverage read contract, restart the app owner. Static-only edits need the normal
asset build (for stored modules) and reload.
