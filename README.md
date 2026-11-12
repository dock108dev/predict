# Predict

Predict is a local, read-only prediction-market comparison app for macOS.

The desk opens on EV, with Arbitrage and Admin alongside it. Compare individual
source offers or group them by outcome. The live EV page starts with the
highest-payout sportsbook pair de-vigged for before-fee EV. Qualified before-fee,
reviewed-fee and conservative EV are also available as separate bases.
Open an offer for its exact
reference inputs, recorded starting fee terms, saved book rules and outcome
cashflows. Missing inputs stay visible in the inspection.

Kalshi and Polymarket US supply independent native prices. The aggregate route
is selected in the data configuration. The sample selects SportsGameOdds with
aggregate acquisition disabled. SGO supplies labeled offers and bookmaker
observations. The current sportsbook EV basis uses FanDuel, DraftKings, BetMGM
and Caesars. The Odds API has a separate legacy route and accounting.
Novig also supports a signed read-only feed for eligible in-game offers with a
post-reset book. The
[fee coverage policy](docs/fee-coverage-policy.md) defines what the desk
counts independently of reference and calculation eligibility.

**Open replay** displays a frozen local slate or a clearly labeled fictional
price scenario. The live desk follows the data owner's Stop and source controls.
See [replay and local operation](docs/development.md#frozen-replay) and the
[calculation contract](docs/benchmark-ev.md).

## Requirements and quickstart

Requires macOS, Python 3.11+ and PostgreSQL tools (`pg_ctl`, `initdb`, `psql`,
`createdb`) on your PATH. Use Python 3.14 and PostgreSQL 16 for new setups;
existing databases keep tools matching their cluster major. Node 24 is needed
only for client tests (`nvm use`). Run commands
from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
mkdir -p .local
cp -n config/current.example.json .local/predict-current-config.json
```

Read [configuration](docs/configuration.md) before starting. The sample enables
native acquisition and disables aggregate requests. Set `enabled` to `false`
for current-data inspection without acquisition. `cp -n` keeps existing settings.
Open replay and select Synthetic practice to try the desk without provider credentials. For live
collection, add your own read-only credentials. Enable SGO explicitly in the
local configuration when you are ready to consume account objects.

```sh
scripts/opportunity-board start
scripts/opportunity-board status
scripts/opportunity-board stop
```

Open the printed loopback address, normally [localhost:8783](http://127.0.0.1:8783/).
The launcher starts a dedicated socket-only PostgreSQL cluster plus independent
background data and app processes. Add `--role app` or `--role data` to any command
to manage them separately. Closing/restarting the app leaves collection and shared
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
