# Prediction Arb

A local, read-only dashboard for comparing sports prediction prices across venues, calculating conditional arbitrage and what-if expected value, and reopening saved scans. It does not place trades.

Kalshi and Polymarket US have native adapters. Novig and ProphetX observations can come through The Odds API; Pinnacle, DraftKings and BetMGM are reference-only. Actual sport and market availability varies. Missing fees, settlement terms, probabilities or usable depth withhold dependent calculations while preserving valid raw comparisons.

## Run locally

Use a macOS source checkout and Python 3.11 or newer. Current local validation and CI use Python 3.14. From the repository root:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
scripts/opportunity-board start
```

Open the printed address, normally [localhost:8783](http://127.0.0.1:8783/). Startup is idle and saved-data review needs no credentials. The dashboard is file-backed; PostgreSQL and a Node.js service are not required.

```sh
scripts/opportunity-board status
scripts/opportunity-board stop
```

For a foreground server, use `.venv/bin/python -m app.dashboard --port 8783`. Run from this checkout so repository assets and tracked saved inputs are available. Restart after source changes. The older `scripts/dashboard` launcher is retired.

Live collection requires an explicitly configured run specification, source endpoints and valid run-specific authorization. Credentials alone do not enable Start scan. See [configuration and operation](docs/configuration.md) for the concrete requirements and [security](docs/security.md) for the loopback browser boundary. Remote, proxy and shared-user hosting are unsupported.

## Use the dashboard

Choose a scan from **Saved scan**, then filter by sport, venue, market or search. Open **Details** to inspect games and their original cutoff; return to the comparison feed to choose another scan. Saved prices and source ages describe their recorded time, not current quotes.

All opportunities groups raw price comparisons separately from supported return calculations. Arbitrage, What-if EV and Saved-page research are distinct views. Negative, zero and unavailable results are valid. Retrospective research does not supply a live probability, and informational sizing does not guarantee execution.

[Sport and market integration](docs/sports-integration.md) describes implemented handlers. [Data limitations](docs/market-data-gaps.md) explains what those handlers do not establish.

## Development

Focused offline checks:

```sh
.venv/bin/python -m compileall -q app/dashboard app/collection
.venv/bin/python -m unittest tests.test_dashboard_security tests.test_ssot_policy tests.test_coverage_failure_handling -q
```

The checks use saved fixtures, temporary output and mocks. Node 22 runs the browser regression scripts. See [development and CI](docs/development.md) for component checks and the locked CI installation.

- [Architecture and data](docs/architecture.md)
- [Module ownership](docs/ssot.md)
- [Configuration and operation](docs/configuration.md)
- [Failure handling and recovery](docs/error-handling.md)
- [UI conventions](docs/ui-design.md)
