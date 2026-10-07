> **October 6: U6 blocked before owner usability review; REVISE / not user-ready.** Restart-safe accounting recovery and a currently applicable native gross comparison are qualified. The one ordinary NBA batch charged 3 credits but admitted no prices: Novig admission failed, ProphetX unobserved in that batch. Active aggregate Details remains blocked. [Current evidence](evidence/u6-restart-recovery-20261006/README.md) · [U6 handoff](docs/u6-current-handoff.md).

# Prediction Arb

A local, read-only odds board for comparing exact sports selections across venues and inspecting original prices, conditional calculations and explicit-assumption What-if results. It does not place trades.

Kalshi and Polymarket US have native adapters. Novig and ProphetX observations can come through The Odds API; Pinnacle, DraftKings and BetMGM are reference-only. Actual sport and market availability varies. Missing fees, settlement terms, probabilities or usable depth withhold dependent calculations while preserving valid raw comparisons.

## Run locally

Use a macOS source checkout and Python 3.11 or newer. Current local validation and CI use Python 3.14. From the repository root:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
scripts/opportunity-board start
```

Open the printed address, normally [localhost:8783](http://127.0.0.1:8783/). The ordinary current provider automatically acquires the configured native scope, or reports source-specific connecting/unavailable states. Startup does not load saved quotes or synthetic prices. PostgreSQL and a Node.js service are not required.

```sh
scripts/opportunity-board status
scripts/opportunity-board stop
```

For a foreground server, use `.venv/bin/python -m app.dashboard --port 8783`. The board assets also ship in the Python package; retained development fixtures remain separately available in the checkout. Restart after source changes. The older `scripts/dashboard` launcher is retired.

Ordinary native operation uses bounded configuration, fixed read-only endpoints, guarded credentials and a fresh consumed runtime record derived from the standing grant; see [native operation](docs/u3-native-operation.md). Retained finite qualification still requires its sealed run specification and run-specific authorization; see [configuration](docs/configuration.md). [Security](docs/security.md) describes the loopback browser boundary. Remote, proxy and shared-user hosting are unsupported.

## Use the dashboard

Compare a same-selection row, use local league/market/period/venue/search filters, and select a price for Details. A review keeps its original revision while the board updates; adopting a newer price is explicit. Manual What-if requires your probability, every cost and payout quantity. Missing inputs withhold dependent results; zero and negative results remain valid.

**Admin** provides native/aggregate status, shared quota, sanitized source issues, pause/stop and guarded recovery controls, plus preserved inspection at `/admin/retained`; U5 local engineering is complete. Saved prices establish only their recorded state. The isolated design remains `/preview/u0`. For populated integration testing, run `.venv/bin/python -m tests.current_integration_server --synthetic-test --port 8797` and follow the [test workflow](evidence/u1-u2-integration-20261002/README.md). This test provider uses production interfaces and labels every screen as synthetic.

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
