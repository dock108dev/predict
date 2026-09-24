# Prediction Arb

A local, read-only dashboard for cross-venue sports prediction prices, conditional
arbitrage calculations, explicit what-if EV, and saved-page research. The existing prototype supports saved multi-game views; trading is not implemented.

**September 23: not ready for beta signoff.** The required beta is Kalshi, Novig,
Polymarket US and ProphetX, plus a power-index/model reference and free
delayed Pinnacle data; NFL, NBA, MLB, NHL, NCAAF and NCAAB; winners, spreads,
totals, halftime and futures. Live/in-play is a stretch goal. See the
[current beta definition](docs/product-roadmap-review.md),
[gap assessment](docs/beta-gap-assessment-20260920.md) and
[delivery plan](docs/data-coverage-plan.md).

Public native-rule research is complete. Full venue/model qualification and owner
review remain open. See the [development guide](docs/development.md) for local
checks and CI.

## Existing prototype tooling

From the repository root, using Python 3.11 or newer. The owner-operated live
workflow requires macOS Keychain; offline CI runs on Linux. No Node.js or
PostgreSQL service is needed to serve the current beta:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
scripts/opportunity-board start
```

Reuse an existing `.venv` when available. The launcher starts idle at
[Predict](http://127.0.0.1:8783/) and prints a different port if needed. Explicit
**Start scan** uses the selected owner's bounded run configuration;
ordinary startup stays idle and requires an explicit supported spec/approval for
real collection. **Stop** finishes saving; **Saved scans** reopens retained results.
The current owner uses run-spec coverage limits; the historical six-game control
is hidden. See [configuration](docs/configuration.md). These controls do not
establish qualification for the expanded beta.
Launching does not authorize collection or reuse of a consumed attempt. Check
the current tracker and applicable run-specific scope before any Start; the
[operation report](docs/personal-beta-operation-report.md) describes historical implementation.

```sh
scripts/opportunity-board status
scripts/opportunity-board stop
```

These commands manage only the identified instance. Source edits do not reload an
existing process. The beta is file-backed and does not use PostgreSQL. Run from this
checkout: saved fixtures, research evidence and static assets are repository inputs.

## Offline development checks

Use the existing virtual environment and run from the repository root:

```sh
.venv/bin/python -m compileall -q app/dashboard app/collection
.venv/bin/python -m unittest tests.test_dashboard_security tests.test_ssot_policy tests.test_coverage_failure_handling -q
```

These focused checks use saved inputs, temporary output and local mocks. They do
not require provider credentials or PostgreSQL. Node 22 is needed for browser
regression scripts. The [development guide](docs/development.md#focused-checks)
lists checks by affected component and the separate full CI command. No `.env`
file is needed for ordinary dashboard setup.

## Interpretation

Arbitrage, manually entered What-if EV, and Saved-page research stay separate. Missing
probability, fees or exceptional settlement remain unknown. Negative, zero and
unavailable results are valid. Saved-page research is retrospective/time-mismatched
and never enters live ranking or prospective scoring. See the
[six-game research report](docs/multi-page-research-report.md) for its exact basis.

## Development and operations

- [Architecture and data](docs/architecture.md): current flow, schemas and historical subsystems.
- [Configuration and operation](docs/configuration.md): credentials, limits, paths and supported deployment.
- [Development guide](docs/development.md): source layout and focused validation.
- [Sources of truth and maintenance decisions](docs/ssot.md): authoritative modules
  and why shared historical paths remain.
- [Failure handling and recovery](docs/error-handling.md): scan finalization,
  cleanup errors, safe diagnostics and incident response.
- [Local security boundaries](docs/security.md): browser protections and limitations.
- [Roadmap](docs/product-roadmap-review.md) and [Desktop tracker](../prediction_arb_next_steps.md):
  product priorities and current owner action.
- [Historical implementation records](docs/implementation-history.md): original
  implementation summaries, evidence links and older workflows.

The older PostgreSQL dashboard and research and collection previews are separate historical tools.
Their lifecycle and authorization boundaries remain in the linked handoffs.
[PLAN.md](PLAN.md) routes to the current definition and delivery order. Previous
planning versions and their historical reuse notes are preserved in
[planning history](docs/history/beta-reset-20260920/README.md).

## Shared UI design

See [UI design and templates](docs/ui-design.md) before changing this interface,
and [current UI verification](docs/ui-verification.md) for reviewed behavior and
limits. The repository's [portable requirements](docs/ui-design-requirements.md)
and local runtime styles are authoritative for this checkout. The historical
Desktop `UI Templates` gallery is unavailable and is not a runtime dependency.
