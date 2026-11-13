# Predict

Predict is a local, read-only prediction-market comparison app for macOS.

The desk opens on **Pregame Opportunities** with ranked EV and Arbitrage views.
Use **Live** to switch to in-game prices. Each EV
card groups an exact outcome and shows its venue offers and selected comparison
book. The default before-fee basis de-vigs both prices from the qualifying
sportsbook with the highest payout on that outcome. Qualified before-fee,
reviewed-fee and conservative EV remain separate bases. Arbitrage ranks the
lowest modeled net return on total funding across the evidenced settlement
states, with both fees included.

Use **Find my game**, **Browse odds**, or open a ranked game to compare both sides of full-game winners,
spreads and totals, including available alternates. An inspection keeps the
original prices, clocks and calculation pinned until you adopt a coherent
replacement with **Use latest prices**.
[Ranked dashboard design](docs/live-comparison-plan-20261104.md#november-12--compare-every-venue-on-the-line)

Kalshi and Polymarket US supply independent native prices. The aggregate route
is selected in the data configuration. The sample selects SportsGameOdds with
acquisition off. SGO supplies labeled offers and bookmaker
observations. The current sportsbook EV basis uses FanDuel, DraftKings, BetMGM
and Caesars. The Odds API has a separate legacy route and accounting.
Novig also supports a signed read-only feed for eligible in-game offers with a
post-reset book. The
[fee coverage policy](docs/fee-coverage-policy.md) defines what the desk
counts independently of reference and calculation eligibility.

**Open replay** starts a fictional practice slate. Local saved captures are
also available in the dataset selector. The live desk follows the data owner's
Stop and source controls.
See [replay and local operation](docs/development.md#frozen-replay) and the
[calculation contract](docs/benchmark-ev.md).

## Requirements and quickstart

Requires macOS, Python 3.11+ and PostgreSQL tools (`pg_ctl`, `initdb`, `psql`,
`createdb`) on your PATH. Use Python 3.14 and PostgreSQL 16 for new setups;
existing databases keep tools matching their cluster major. Node 24 is needed
only for client tests (`nvm use`). Run commands
from the repository root. Start with practice to explore the app without keys:

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

Open the loopback address printed by the launcher. With the command above,
use [Predict on port 8784](http://127.0.0.1:8784/) and choose **Open replay**. Search for Harbor Foxes and open a price or pairing.
Switch **Price step** to see how a move changes the math. `cp -n` keeps existing
settings. `check-config` validates the file and shows what it would collect.

For live collection, follow [source configuration and credentials](docs/configuration.md#source-configuration).
Choose the sports and markets, add your read-only keys, and turn `enabled` on.
Turn on `aggregate_enabled` to collect SportsGameOdds against your plan's object
allowance. Use Admin to check sources, spending, Stop, and display settings.

```sh
scripts/opportunity-board check-config
scripts/opportunity-board start --role data
scripts/opportunity-board status
scripts/opportunity-board stop
```

The launcher uses a dedicated socket-only PostgreSQL cluster and independent
background data and app processes. Add `--role app` or `--role data` to start,
stop or check either process on its own. Closing/restarting the app leaves collection and shared
calculations running. [Lifecycle and result contract](docs/data-app-runtime-contract.md).
There is no cloud service. The data process can restart itself after successful
planned storage maintenance; it preserves Stop choices and source pauses.
Current prices keep their original clocks; a recent
calculation does not make an old price fresh. Fee and payout models have bounded
applicability, so missing or expired models can withhold estimates.

## Testing and maintenance

[Development](docs/development.md) explains the locked test environment. Basic
checks after installing those tools are:

```sh
.venv/bin/python -m pytest -q tests/test_ev09_asset_delivery.py
node tests/test_stored_views.cjs
.venv/bin/python scripts/ci/docs.py
```

Use affected tests for small changes; [CI](docs/CI.md) describes the broader
automated checks.

- [Scanner filters, observations and manual tickets](docs/scanner-usage.md)
- [Architecture and module ownership](docs/architecture.md)
- [Acquisition and accounting boundaries](docs/acquisition.md)
- [Raw prices and original inputs](docs/raw-prices.md)
- [Calculation basis and limitations](docs/benchmark-ev.md)
- [Current-board API](docs/comparison-board-api-contract.md)
- [Interface design](docs/ui-design.md)
- [Security](docs/security.md) and [failure recovery](docs/error-handling.md)
- [Sport support](docs/sports-integration.md) and [data limitations](docs/market-data-gaps.md)
