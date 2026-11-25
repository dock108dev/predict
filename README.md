# Predict

Version **0.2.0** adds read-only amount research, decision-visible cashflows and
size status, retained comparisons, and session navigation context.

The [personal server](https://predict.dock108.dev/) requires the existing owner
login. Hosted use needs no local `.env` or running app. Pushes to `main` deploy
through the focused private-beta CI path; [server and Mac setup](docs/hetzner.md) explains
the private deployment and optional local development.

Predict opens on **Dashboard**, where the highest current positive expected
value appears first. Open an offer to see its captured prices and calculation
inputs while keeping your place on the board.

**Data** browses stored observations, odds pulls, sporting results, historical
captures and PostgreSQL tables. You can carry a filtered selection to experiment
creation. **Experiments** opens Win $10 and its Kelly comparison. New campaigns
use the same paper results and evidence view.

Open **Collection controls** from the status area for Stop, Resume, source
pauses, credit usage and retention. The status area shows the latest accepted
odds receipt, the next scheduled pull and collection problems. The three
destinations and their exports read committed evidence. Scheduled collection
runs independently of the browser. The [workspace guide](docs/personal-data-workspace.md)
and [simplification inventory](docs/engineering/predict-simplification-20261125.md)
describe the workflows and retained dependencies.

## Requirements and quickstart

Local operation requires Python 3.11 or later and PostgreSQL 16 tools.
The commands below use Python 3.14. Run them from the
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
use [Predict on port 8784](http://127.0.0.1:8784/). Dashboard shows committed prices. Collection controls preserve the existing
schedule and source pauses. Saved odds remain available in Data.
`cp -n` preserves an existing config, and `check-config` prints its acquisition scope.

For UI iteration with a real dev-server database and no local collectors, see
[local snapshot development](docs/local-ui-development.md).

## Collect prices

Set up [source configuration and credentials](docs/configuration.md#source-configuration)
before enabling collection. Start the data process with
`.venv/bin/python scripts/opportunity-board start --role data`.

Settings shows source health, spending, holds, Stop/Resume and source pauses.
[Start and stop individual roles](docs/configuration.md#start-and-stop) ·
[Storage ownership](docs/storage-ownership.md) · [Hetzner runbook](docs/hetzner.md)

## Testing and maintenance

[Development](docs/development.md#install-tools) explains the locked test
environment, including Node 24 for client checks.

```sh
.venv/bin/python -m pytest -q tests/test_ev09_asset_delivery.py
.venv/bin/python scripts/ci/affected.py --plan
.venv/bin/python scripts/ci/docs.py
```

Use affected tests for small changes; [CI](docs/CI.md) describes the broader
automated checks.

- [Calculation and fee policy](docs/benchmark-ev.md) · [Raw prices](docs/raw-prices.md)
- [Scanner filters and manual tickets](docs/scanner-usage.md)
- [Architecture, APIs, and module ownership](docs/architecture.md)
- [Acquisition and accounting](docs/acquisition.md) · [Data limitations](docs/market-data-gaps.md)
- [Security](docs/security.md) · [Failure recovery](docs/error-handling.md)
