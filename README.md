# Predict

Version **0.2.0** adds read-only amount research, decision-visible cashflows and
size status, retained comparisons, and session navigation context.

The [personal server](https://predict.dock108.dev/) requires the existing owner
login. Hosted use needs no local `.env` or running app. Pushes to `main` deploy
through the focused private-beta CI path; [server and Mac setup](docs/hetzner.md) explains
the private deployment and optional local development.

Predict opens on **Data**: games, captured observations, and exact source and
calculation evidence. Trading views cover prediction-market offers against
sportsbook references and other prediction markets; sportsbook prices remain
reference evidence. Positive EV and arbitrage are Data views. **Experiments**
contains the existing first-observation/T−10 comparisons, coverage, outcomes and
exports. **Settings** holds collection controls and operating status.
See the [personal workspace guide](docs/personal-data-workspace.md).

The collector receives odds, normalizes affected games, calculates using posted
prices, and stores current prices and complete calculations in PostgreSQL. Refresh and inspection
only read stored data. Arb reads also balance a bounded illustrative allocation
using the stored fee inputs. Pregame observations have no age expiry: authoritative kickoff,
non-pregame status, explicit withdrawal, replacement by a newer main line, and repeated scoped line omissions
after a 15-minute grace period govern removal. Odds may be delayed.

[Workspace guide](docs/personal-data-workspace.md) ·
[Current data flow and API](docs/current-pregame.md) ·
[Calculation policy](docs/benchmark-ev.md)

Authentic saved-capture bookmarks open evidence inspection within Data.
Live executable size and cross-venue fills are not established by these boards.
[Price and liquidity limitations](docs/liquidity.md).
[Monitor and Live collection](docs/monitor-live.md) describes the personal-app defaults, controls and retention.
Underlying source identity and calculation limitations remain beside the exact
observation. Aggregate observations retain their SportsGameOdds provenance.

The standalone My Bets interface is retired. Existing journal records, APIs,
exposure and the provider-free quote sampler remain intact. Trading remains
outside Predict.
[Journal workflow, measurement definitions and durability](docs/bet-journal.md)

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
use [Predict on port 8784](http://127.0.0.1:8784/). The desk needs committed
prices to show current offers. Collection settings control Monitor and Live;
authentic saved odds remain available for later inspection.
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
