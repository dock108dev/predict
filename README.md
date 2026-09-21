# Prediction Arb

A local, read-only dashboard for cross-venue sports prediction prices, conditional
arbitrage calculations, explicit what-if EV, and saved-page research. The existing prototype supports saved multi-game views; trading is not implemented.

**September 20: not ready for beta signoff.** The required beta is Kalshi, Novig,
Polymarket US and a fourth venue, plus a power-index/model reference and free
delayed Pinnacle data; NFL, NBA, MLB, NHL, NCAAF and NCAAB; winners, spreads,
totals, halftime and futures. Live/in-play is a stretch goal. See the
[current beta definition](docs/product-roadmap-review.md),
[gap assessment](docs/beta-gap-assessment-20260920.md) and
[B1–B7 delivery plan](docs/data-coverage-plan.md).

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
**Start scan** collects within 1–6 games and 1–180 seconds (defaults: six games,
175 seconds). **Stop** finishes saving; **Saved scans** reopens retained results.
These are existing tool controls, not qualification for the expanded beta.
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

## Interpretation

Arb, manually entered what-if EV, and Page-derived research stay separate. Missing
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
  slice summaries, evidence links and older workflows.

The older PostgreSQL dashboard and E5/E6 previews are separate historical tools.
Their lifecycle and authorization boundaries remain in the linked handoffs.
[PLAN.md](PLAN.md) routes to the current definition and delivery order. Previous
planning versions and their historical reuse notes are preserved in
[planning history](docs/history/beta-reset-20260920/README.md).
