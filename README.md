# Predict

Predict is a read-only prediction-market comparison app for macOS. The desk
opens on **Pregame Opportunities**, with ranked Expected value and Arbitrage
views. In-game collection and display require `live_enabled`, which defaults
to `false`.

Use **Browse odds** or **Find my game** to compare full-game winners, spreads,
and totals. The SportsGameOdds-backed pregame desk shows the latest posted price
and updates the list and trade preview when **Auto-update** is on. **Refresh list**
reads the latest board on demand. **Trading fees** explains the supported retail
estimates. **Saved odds** opens recorded captures available on the installation.
[Desk and inspection guide](docs/ui-design.md#current-comparison-interface)

## Requirements and quickstart

Local operation requires macOS, Python 3.11 or later, and PostgreSQL tools.
Use Python 3.14 and PostgreSQL 16 for new setups. The launcher selects tools
that match an existing cluster's major version. Client tests use Node 24.
Run these commands from the repository root to start the web app. The sample
configuration leaves acquisition disabled.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
mkdir -p .local
cp -n config/current.example.json .local/predict-current-config.json
scripts/opportunity-board check-config
scripts/project-postgres start
.venv/bin/python -m app.storage migrate
scripts/opportunity-board start --role app --port 8784
```

Open the loopback address printed by the launcher. If port 8784 is free,
use [Predict on port 8784](http://127.0.0.1:8784/). The desk needs committed
prices to show current offers. Choose **Saved odds** to open an available capture.
`cp -n` preserves an existing config, and `check-config` prints its acquisition scope.

## Collect prices

Set up read-only credentials and select the sports and markets before turning
on `enabled`. The sample selects SportsGameOdds as the aggregate provider.
`aggregate_enabled` opts into the selected provider's metered collection.
[Source configuration and credentials](docs/configuration.md#source-configuration)

```sh
scripts/opportunity-board check-config
scripts/opportunity-board start --role data
scripts/opportunity-board status
scripts/opportunity-board stop
```

The launcher runs the app and collector as independent processes against a
socket-only PostgreSQL cluster. Use `--role app` or `--role data` to target one
process. Admin shows source health, spending, Stop controls, and the database
browser. [Process lifecycle](docs/data-app-runtime-contract.md) ·
[Storage ownership](docs/storage-ownership.md) · [Hetzner runbook](docs/hetzner.md)

## Testing and maintenance

[Development](docs/development.md) explains the locked test environment. Basic
checks after installing those tools are:

```sh
.venv/bin/python -m pytest -q tests/test_ev09_asset_delivery.py
node tests/test_f07_desk_ui.cjs
.venv/bin/python scripts/ci/docs.py
```

Use affected tests for small changes; [CI](docs/CI.md) describes the broader
automated checks.

- [Calculation and fee policy](docs/benchmark-ev.md) · [Raw prices](docs/raw-prices.md)
- [Scanner filters and manual tickets](docs/scanner-usage.md)
- [Architecture, APIs, and module ownership](docs/architecture.md)
- [Acquisition and accounting](docs/acquisition.md) · [Data limitations](docs/market-data-gaps.md)
- [Security](docs/security.md) · [Failure recovery](docs/error-handling.md)
