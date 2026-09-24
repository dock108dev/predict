# Prediction Arb

A local, read-only dashboard for comparing sports prediction prices across venues, calculating conditional arbitrage and what-if expected value, and reopening saved scans. Trading is not implemented.

## Run locally

Requires Python 3.11 or newer. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
scripts/opportunity-board start
```

Open the address printed by the launcher, normally [localhost:8783](http://127.0.0.1:8783/). The dashboard starts idle. Saved scans reopen retained results; Start scan requires configured sources and an explicit run specification and approval. Live credential access uses macOS Keychain. See [configuration](docs/configuration.md) for requirements and limits.

```sh
scripts/opportunity-board status
scripts/opportunity-board stop
```

The dashboard is file-backed and needs no PostgreSQL or Node.js service. Run it from this checkout so saved inputs and static assets are available. Restart the server after source changes.

## Interpreting results

Arbitrage, manually entered What-if EV and Saved-page research are separate views. Missing probabilities, fees or settlement terms remain unknown. Negative, zero and unavailable results are valid. Saved-page research is retrospective and does not enter live ranking.

Venue, sport and market coverage is incomplete. A displayed calculation is conditional on its source data and terms; it does not establish executable liquidity or verified support for every venue. See [sports integration](docs/sports-integration.md) and [configuration](docs/configuration.md).

## Development

Focused offline checks:

```sh
.venv/bin/python -m compileall -q app/dashboard app/collection
.venv/bin/python -m unittest tests.test_dashboard_security tests.test_ssot_policy tests.test_coverage_failure_handling -q
```

These checks use saved inputs, temporary output and mocks. Node 22 is needed for browser regression scripts. The [development guide](docs/development.md) lists component checks and the full CI command.

- [Architecture](docs/architecture.md) and [module ownership](docs/ssot.md)
- [Configuration and operation](docs/configuration.md)
- [Failure handling](docs/error-handling.md) and [security](docs/security.md)
- [UI design](docs/ui-design.md)

Older PostgreSQL and collection-preview tools are documented in [implementation history](docs/implementation-history.md).
