# Development

Run commands from the repository root. Python 3.14 and Node 24 match primary
CI. The package supports Python 3.11 and later. Some native sources use macOS
Keychain. On a machine with nvm, run `nvm use` to select the version in `.nvmrc`.

## Install tools

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-ci.txt
.venv/bin/python scripts/ci/validate_lock.py
.venv/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
.venv/bin/python -m pip check
```

The CI lock includes runtime, stream, test and build dependencies. The
[README](../README.md) uses a smaller installation for ordinary operation.
Install both locks to run browser tests. On Ubuntu 24.04, install Chromium with
`--with-deps` to match the extended browser job.

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-ci.txt -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
```

For the focused release checks, install the checksum-pinned workflow and secret
validators on Apple Silicon macOS or x86-64 Linux.

```sh
.venv/bin/python scripts/ci/install_tools.py
```

## Ordinary app and background data

Follow the [README quickstart](../README.md#requirements-and-quickstart) to
start the web app without starting a collector. Use `--role app` or
`--role data` with the launcher to manage each process independently.
Stopping the web app leaves collection and shared calculations running.
Open Research at `/research`, with Data and Settings at `/data` and `/settings`.
Settings controls acquisition. A successful Stop confirms collector cleanup.
Restarting either role preserves explicit pauses and accounting holds.
[Operation](configuration.md#start-and-stop) ·
[Runtime contract](data-app-runtime-contract.md)

The ordinary database launcher selects tools for the existing cluster's
`PG_VERSION`. Set `PREDICT_PG_BIN` to a matching installation if needed.
A cluster major upgrade requires a data migration. Test scripts create their own
clusters.

## Frozen replay

Open saved capture and quote bookmarks in Data. For a dated paper run, use
Research → Experiments to save a definition, replay retained inputs, inspect
published results or export frozen evidence. Saved offers preserve recorded
prices, fee terms and before-fee payouts. Missing archives remain unavailable.
Synthetic replay fixtures belong to development tests.
[Workspace guide](personal-data-workspace.md) · [Calculation basis](benchmark-ev.md)

## Focused checks

Start with `.venv/bin/python scripts/ci/affected.py --plan` to see the complete
working-change plan and its routing/fallback reasons. Omit `--plan` to execute,
or use `--full` for all registered behavior lanes. For the focused personal
release checks, use `.venv/bin/python scripts/ci/fast_checks.py --plan` and omit
`--plan` to execute the local checks. Add `--paths` followed by sample changed
paths when checking routing. The local selector commands execute validation with
fixtures. Push and deployment use the hosted release workflow.
[CI checks and local reproduction](CI.md#local-reproduction)

Choose the checks that exercise the changed behavior. CI's portable manifest
and disposable database harness separate ordinary tests from historical tools
that require local evidence. Avoid running SQL tests directly against the
ordinary project database.

```sh
.venv/bin/python -m ruff check app tests scripts/ci browser_tests
.venv/bin/python -m ruff format --check scripts/ci browser_tests tests/test_ci_*.py tests/ci_support.py
.venv/bin/python scripts/ci/validate_contract.py
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ev09_asset_delivery.py
git diff --check
```

| Change | Focused tests |
| --- | --- |
| Workbench campaign save, retained replay, grading and export | `browser_tests/test_paper_campaign_integration.py` through the disposable SQL harness |
| Workbench dated offers export and its digest | `tests/test_research_offer_export_api.py` |
| Data markets, filters, grouping and exact offer evidence | `browser_tests/test_personal_data_workspace.py`, `tests/test_data_workspace_sql.py` |
| Current PostgreSQL admission, game grouping, arb expiry and recovery | `tests/test_current_pregame_sql.py`, `tests/test_pregame_board_views_sql.py`, `tests/test_fee_pricing_sql.py` |
| Private local snapshot transfer and target guards | `tests/test_dev_snapshot.py` |
| Retained desk rendering and selection | `tests/test_f07_desk_ui.cjs`, `browser_tests/test_ranked_desk_journey.py` |
| Snapshot math and evidence | `tests/test_snapshot_display.py`, `tests/test_snapshot_benchmark.py`, `tests/test_comparison_snapshot_sql.py` |
| Source lifecycle and Stop | `tests/test_current_service.py`, `tests/test_data_runtime_unit.py` |
| SportsGameOdds admission, reference retention and Monitor recovery | `tests/test_sportsgameodds_ingress_sql.py`, `tests/test_sportsgameodds_reference_sql.py`, `tests/test_pregame_cohorts_sql.py` |
| Scanner policy, settlement, and fees | `tests/test_scanner_kalshi.py`, `tests/test_scanner_polymarket.py`, `tests/test_scanner_native.py` |
| Failure handling and launcher security | `tests/test_abend_handling.py`, `tests/test_security_hardening.py`, `tests/test_dashboard_security.py` |

For fixture-generating Node tests, set `PYTHON="$PWD/.venv/bin/python"` if
your test interpreter differs. The portable runner sets it itself.

The SQL harness creates and tears down a disposable socket-only PostgreSQL 16
cluster. Run it as an ordinary user. If needed, set `PG_CONFIG` or pass
`--pg-config /path/to/postgresql@16/bin/pg_config` to select tools.
Select specific modules with `--tests`, or use the registered suite with no
selection. Use a fresh report directory for each run.

```sh
.venv/bin/python scripts/ci/postgres.py --report-dir "$(mktemp -d)" \
  --tests browser_tests/test_paper_campaign_integration.py
```

Use `--da-separation` when checking app and collector isolation, per-game
result reuse, or publication while financial results are unavailable.
Fixtures make zero provider requests.

## Extended checks

The manual Full validation workflow uses Ubuntu 24.04, Python 3.14, Node 24,
Poppler, Chromium and PostgreSQL 16. Run the descriptor-relative security
regression on Linux. It skips on macOS. Use fresh output directories to preserve
results from earlier attempts.
[Extended workflow](CI.md#optional-extended-checks)

```sh
PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci --output "$(mktemp -d)"
.venv/bin/python -m pytest -q tests/test_ci_*.py
.venv/bin/python scripts/ci/package_smoke.py --report-dir "$(mktemp -d)"
```

The portable runner uses the registered Python and client suites. The package
smoke builds and installs a fresh wheel in a temporary directory outside the
checkout and loads the bundled November 23 audit input with database access and
decision application disabled for that loader check.

## Synthetic preview

```sh
.venv/bin/python -m tests.current_integration_server --synthetic-test --port 8797
```

Open the printed loopback address. The injected provider makes no source
requests. Stop it with Ctrl-C. `/__test/commit` is a route on this test server.
Browser fixtures exercise presentation and API contracts, while disposable SQL
tests exercise persistence.

## Frontend sources

The authored frontend is under `app/dashboard/opportunity_static/current/`.

- Research starts with `research-workspace.html` and `research-workspace.js`.
  It owns the Workbench, campaign forms, saved runs and paper results.
- Data starts with `data.html`, `data-workbench.js` and `data.js`. It owns
  market filters, exact offers and the evidence views reached by saved bookmarks.
- Settings starts with `settings.html` and `settings.js`. It owns the operating
  status and protects the source and fee controls through their API owners.
- `workspace-nav.js` and `workbench-shell.css` provide shared navigation and
  layout. `app/dashboard/workspace_routes.py` owns the page mounts and legacy
  bookmark mapping.

The retained desk, pregame, journal, stored and Scanner modules still have
compatibility and fixture coverage. `pregame-math.js` owns its disclosures and
`pregame-ranking.js` remains generated. Retained desk pages load `desk.css` before
`desk-components.css` to preserve the cascade. The journal API owns recorded
fills and correction history. [Scanner API](scanner-client-contract.md) ·
[Journal](bet-journal.md)

After editing an authored input to the stored or Scanner bundles, regenerate
the tracked assets. The generator handles a closed set of named imports.
Edit the authored files and keep the generated files in sync.
The same command generates `pregame-ranking.js` from the pure catalog in
`app/storage/pregame_ranking.py`. Edit that Python owner for method metadata,
defaults and explanations; the dropdown and math disclosures import its generated
module. The command also emits `appearance-policy.js` from
`app/dashboard/appearance_policy.py`: edit that owner for starter palettes,
defaults, modes and preference validation patterns. `prism-theme.js` owns color
derivation and contrast; `prism.js` owns interaction and uses the generated
contract to validate browser cache and server responses. `--check` rejects
stale ranking/appearance metadata alongside stored/Scanner drift.

```sh
.venv/bin/python scripts/build_stored_frontend.py
.venv/bin/python scripts/build_stored_frontend.py --check
node --check app/dashboard/opportunity_static/current/stored.js
```

Reload frontend changes in the browser. Restart the affected app or collector
process after changing its backend code.

## Maintenance boundaries

[Architecture](architecture.md) describes module ownership. Preserve public
imports, packaged asset paths, protocol versions, and applied migration files.

Keep database queries in `current_pregame_read.py` separate from calculation and
recovery writes in `current_pregame.py`. The public read facade preserves the
clock and route resolver. Local-selector tests live in `tests/test_ci_affected.py`;
CI environment guards and reporting tests have separate modules.
`test_ci_required_evidence.py` owns artifact/shard qualification and rerun
evidence; it remains in the existing quality-only collection. Journal browser
flows use `browser_tests/journal_fixture.py`, with manual edits/settlements in
`test_bet_journal.py` and observed-log/lazy-close flows in
`test_journal_opportunity_log.py`. Local journal selection includes both files.

Keep transaction and mutable-state ownership clear. The personal journal owns
entry identity, revisions and history in one transaction. Reported-fill
validation and frozen-price/fee derivation live in `bet_journal_trade.py`; callers
pass the journal clock explicitly. Measurements and source sampling remain
separate modules. The SGO worker owns event cursors,
in-flight pages, Stop handling and admission acknowledgement. Transport,
scheduling, accounting and measurement logic have separate owners.

- Keep source Stop, synchronization, and socket shutdown in the transport
  lifecycle. Exact book persistence acknowledges the active generation before
  downstream publication. Catalog selection and diagnostic helpers live in
  `app/collection/current_native_catalog.py`.
- Keep authority checks and transaction boundaries with the publication
  owners. `ordinary_publication.py` owns capture, retries, sealing, and leases.
  `ordinary_dependencies.py` reads exact dependency witnesses.
  `ordinary_result.py` binds capture authority, fees, and payoff.
  `desk_sportsbooks.py` enriches exact desk lines without dispatching data.
- `desk_lines.py` resolves published main-line roles for Browse and the unit
  board. Retained comparisons use the same signed-line normalization with
  their existing coverage-based selection.
- Current reads use the read clock for pregame cutoff. Saved lists and details
  use each offer's capture clock, falling back to its result clock.
  Preserve source clocks and exact offer identities across list and detail reads.
- The desk list controller keeps ranking, filters, fetch cancellation, scroll,
  and Back state together so it can restore the exact loaded page. The drawer
  keeps leases, adoption, and cancellation under one selection lifecycle.
  Inspection retains its single-quote and pair renderers together where they
  share fee evidence, source clocks, state labels, and disclosure primitives.
- The compatibility `latest_board.py` coordinates retained publication and
  detached snapshot and slate reads. SQL fixtures cover restart and captured
  reads. Changes to targeted tests also need to update the SQL runner's selectors.
- The compatibility `stored-controller.js` owns polling, retained list state,
  and selection for the older reader. Its checks run separately from the
  current desk.
- `deploy/release.sh` keeps digest validation, migration checks, and rollback
  under one restricted-SSH rollout transaction.

The journal storage owner remains one class because identity lookup, revision
checks, correction receipts and history must share explicit SQLite transactions;
fill validation/derivation is the independent boundary extracted from it.
`bet_journal_metrics.py` retains exact entry/close/settlement analysis together:
those outputs share quote-eligibility clocks and cashflow completeness checks.
The controlled-clock activity tests retain their common Store/Worker state machine
so interleaving, final authority checks and held exposure use the same fake clock.
The remaining manual journal browser cases share editor/settlement controls;
opportunity-log flows now have their own module. Large modules still require a
cohesion review when their responsibility changes; line counts are maintenance
review triggers, not a target to reach by compressing code. Applied migrations,
generated assets, authored replay fixtures and sealed source ZIPs are retained.

Keep credentials, operator state, local task queues, reports and coding notes
out of Git. Lasting documentation describes software behavior and supported
workflows, not individual development runs.
Keep required fixtures in `tests/fixtures` or `app/fixtures`, and keep reusable
wire examples with their contracts. Preserve the packaged frontend assets and
the exact sources and guard receipts required by sealed tools. Each `SOURCE.zip`
under `scripts/v1_coverage_package` and `scripts/v1_counterpart_package` has an
exact digest in its seal and is used by offline tests or the package launcher.
To find paths already tracked despite ignore rules, run
`git ls-files -ci --exclude-standard`.

## Acquisition and publication

Use authored mixed-state fixtures and the disposable PostgreSQL lane for
census, cancellation, and current-row checks. The acquisition report reads
committed census data without fetching providers. A partial census or featured
query cannot establish full-provider coverage.
[Acquisition boundaries](acquisition.md)

## Raw reader

`raw_price_api.py` owns read snapshots and `raw_prices.py` reads acquisition
rows. Optional captured calculations have a separate owner. Exercise changed
reads through `tests/test_raw_prices_sql.py` in the disposable SQL harness.
[Raw prices and read lifecycle](raw-prices.md)
