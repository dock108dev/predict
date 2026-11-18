# Predict

Predict is a read-only odds and opportunity dashboard. It opens directly on
**Pregame Opportunities**, showing complete main-line bets ranked by Opportunity
Score after fees. **Browse odds** includes complete comparisons with nonpositive
EV and optional alternate lines. Open a game or choose **Compare prices** to
inspect the same committed price, reference, fees, and Net EV.

The collector receives odds, normalizes affected games, calculates using posted
prices, and stores complete current rows in PostgreSQL. Refresh and inspection
only read SQL. Pregame observations have no age expiry: authoritative kickoff,
non-pregame status, and explicit withdrawal govern removal. Odds may be delayed.

[Desk guide](docs/ui-design.md#current-comparison-interface) ·
[Current data flow and API](docs/current-pregame.md) ·
[Calculation policy](docs/benchmark-ev.md)

**Arbitrage**, saved captures, and simulated practice remain separate research
views. Account connections and execution modeling remain backlog work.

## Requirements and quickstart

Local operation requires macOS, Python 3.11 or later, and PostgreSQL tools.
The commands below use Python 3.14 and PostgreSQL 16. Run them from the
repository root. The sample configuration leaves acquisition disabled.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
mkdir -p .local
cp -n config/current.example.json .local/predict-current-config.json
.venv/bin/python scripts/opportunity-board check-config
scripts/project-postgres start
.venv/bin/python -m app.storage migrate
.venv/bin/python scripts/opportunity-board start --role app --port 8784
```

Open the loopback address printed by the launcher. If port 8784 is free,
use [Predict on port 8784](http://127.0.0.1:8784/). The desk needs committed
prices to show current offers. Choose **Practice** to explore simulated calculations.
`cp -n` preserves an existing config, and `check-config` prints its acquisition scope.

## Collect prices

Set up [source configuration and credentials](docs/configuration.md#source-configuration)
before enabling collection. Start the data process with
`.venv/bin/python scripts/opportunity-board start --role data`.

Admin shows source health, spending, and Stop controls.
[Start and stop individual roles](docs/configuration.md#start-and-stop) ·
[Storage ownership](docs/storage-ownership.md) · [Hetzner runbook](docs/hetzner.md)

## Testing and maintenance

[Development](docs/development.md#install-tools) explains the locked test
environment, including Node 24 for client checks.

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
