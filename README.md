# Prediction Arb

A local, read-only dashboard for cross-venue sports prediction prices, conditional
arbitrage calculations, explicit what-if EV, and saved-page research. The current
personal beta supports a multi-game view; trading is not implemented.

## Run locally

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
Launching the app does not authorize collection. Live access requires the existing
venue credentials and authorization described in the [operation guide](docs/personal-beta-operation-report.md).

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
[PLAN.md](PLAN.md) is the preserved original proposal; current scope comes from the
roadmap and tracker. The roadmap also records the local SDA and Scroll Down source
copies and their completed reuse audit.
