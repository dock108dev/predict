# Development

Run commands from the repository root. Python 3.14 and Node 24 match primary
CI. The package supports Python 3.11 and later. Some native sources use macOS
Keychain. Linux can run the portable tests and the container deployment.
If you use nvm, run `nvm use` to select the project's Node version.

## Install tools

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-ci.txt
.venv/bin/python scripts/ci/validate_lock.py
.venv/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
.venv/bin/python -m pip check
```

The CI lock includes runtime, stream, test, and build dependencies. The
[README](../README.md) uses a smaller installation for ordinary operation.
For PostgreSQL and browser prerequisites, see [CI](CI.md).

## Ordinary app and background data

Follow the [README quickstart](../README.md#requirements-and-quickstart) to
start the web app without starting a collector. Use `--role app` or
`--role data` with the launcher to manage each process independently.
Stopping the web app leaves collection and shared calculations running.
Stopping data ends acquisition. Restarting either role preserves the collector's
explicit pauses and accounting holds. [Operation](configuration.md#start-and-stop) ·
[Runtime contract](data-app-runtime-contract.md)

## Frozen replay

Use [Saved odds](configuration.md#saved-odds) to inspect an available capture.
Saved offers preserve their recorded prices, fee terms, and before-fee
payouts. A tie that pays $0.50 is a different outcome from a stake refund.
Computing full EV requires probabilities for those outcomes.
[Calculation basis](benchmark-ev.md)

## Focused checks

Choose the checks that exercise the changed behavior. CI's portable manifest
and disposable database harness separate ordinary tests from historical tools
that require local evidence. Avoid running SQL tests directly against the
ordinary project database.

```sh
.venv/bin/python -m ruff check app tests scripts/ci browser_tests
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ev09_asset_delivery.py
node tests/test_f07_desk_ui.cjs
git diff --check
```

| Change | Focused tests |
| --- | --- |
| Desk rendering, selection, and refresh | `tests/test_f07_desk_ui.cjs`, `browser_tests/test_ranked_opportunities.py`, `browser_tests/test_ranked_desk_journey.py` |
| Snapshot math and evidence | `tests/test_snapshot_display.py`, `tests/test_snapshot_benchmark.py`, `tests/test_comparison_snapshot_sql.py` |
| Source lifecycle and acquisition | `tests/test_current_service.py`, `tests/test_ordinary_native_transport.py`, `tests/test_data_runtime_unit.py` |
| SportsGameOdds scheduling, discovery and cursor recovery | `tests/test_sportsgameodds_worker.py`, `tests/test_sportsgameodds_discovery.py` |
| Scanner policy, settlement, and fees | `tests/test_scanner_kalshi.py`, `tests/test_scanner_polymarket.py`, `tests/test_scanner_native.py` |
| Failure handling and launcher security | `tests/test_abend_handling.py`, `tests/test_security_hardening.py`, `tests/test_dashboard_security.py` |

For fixture-generating Node tests, set `PYTHON="$PWD/.venv/bin/python"` if
your test interpreter differs. The portable runner sets it itself.

The SQL harness creates and tears down a disposable socket-only PostgreSQL
cluster. Primary SQL checks use PostgreSQL 16. If needed, pass
`--pg-config /path/to/postgresql@16/bin/pg_config` to select tools.
Select specific modules with `--tests`, or use the registered suite with no
selection. Use a fresh report directory for each run.

```sh
.venv/bin/python scripts/ci/postgres.py --report-dir "$(mktemp -d)" \
  --tests tests/test_comparison_snapshot_sql.py
```

Use `--da-separation` when checking app and collector isolation, per-game
result reuse, or publication of observations while financial results are
unavailable. Fixtures make zero provider requests.
`PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci` runs the portable manifest.
[CI checks and reports](CI.md)

The ordinary database launcher selects tools for the existing cluster's
`PG_VERSION`. Set `PREDICT_PG_BIN` to a matching installation if needed.
A cluster major upgrade requires a data migration. The SQL harness uses
separate state.

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

- `desk.html` is the shared shell for Opportunities, Arbitrage, Browse odds,
  game detail, and Saved odds. `desk.js` owns the list and its current/saved
  requests. `desk-polling.js` owns the update timer and expiry rechecks.
  `opportunity-cards.js` assembles cards and matrices. `desk-quote-display.js`
  shares quote and reference presentation with the drawer. `desk-drawer.js`
  owns selection history, leases, and adoption. `desk-inspection.js` renders
  captured evidence and the trade preview.
- Pages that share desk styling load `desk.css` before `desk-components.css`.
  The first defines fonts, chrome and base styles. The second adds the
  toolbar, inspection, card and matrix rules in cascade order.
- `snapshot-controller.js`, `snapshot-views.js`, `snapshot-live.js`,
  `snapshot-drawer.js`, and `ui-common.js` supply the stored results view.
- `scanner-controller.js`, `scanner-client.js`, `scanner-style.css`, and
  `scanner-shell.html` supply Scanner. The ticket, arrival, and summary modules
  own their respective reads and controls. [Scanner API](scanner-client-contract.md)
- Raw Odds and Coverage have their own authored HTML, CSS, and JavaScript entry
  points. Admin uses `admin.html` and `admin.js`. Its Database tab uses bounded
  read-only transactions and shows schema and paged stored values.

After editing an authored input to the stored or Scanner bundles, regenerate
the tracked assets. The generator handles a closed set of named imports.
Edit the authored files and keep the generated files in sync.

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

Review mixed responsibilities above 500 physical lines in Python, 300 in
authored JavaScript or CSS, 250 in templates, and 100 in shell. Above twice
the review length, extract a cohesive owner or document the state or transaction
that belongs together. Generated assets follow their source boundaries.

- Keep source Stop, synchronization, and socket shutdown in the transport
  lifecycle. Exact book persistence acknowledges the active generation before
  downstream publication. Catalog selection and diagnostic helpers live in
  `app/collection/current_native_catalog.py`.
- Keep authority checks and transaction boundaries with the publication
  owners. `ordinary_publication.py` owns capture, retries, sealing, and leases.
  `ordinary_dependencies.py` reads exact dependency witnesses.
  `ordinary_result.py` binds capture authority, fees, and payoff.
  `desk_sportsbooks.py` enriches exact desk lines without dispatching data.
- Current reads use the read clock for pregame cutoff. Saved lists and details
  use each offer's capture clock, falling back to its result clock.
  Preserve source clocks and exact offer identities across list and detail reads.
- The desk list controller keeps ranking, filters, fetch cancellation, scroll,
  and Back state together so it can restore the exact loaded page. The drawer
  keeps leases, adoption, and cancellation under one selection lifecycle.
- The compatibility `latest_board.py` coordinates retained publication and
  detached snapshot and slate reads. SQL fixtures cover restart and captured
  reads. Changes to targeted tests also need to update the SQL runner's selectors.
- The compatibility `stored-controller.js` owns polling, retained list state,
  and selection for the older reader. Its checks run separately from the
  current desk.
- `deploy/release.sh` keeps digest validation, migration checks, and rollback
  under one restricted-SSH rollout transaction.

Keep credentials, operator state, local reports, and coding notes out of Git.
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
