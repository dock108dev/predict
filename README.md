# Prediction Arb

A local, read-only prediction-market comparison app for macOS. It compares venue
prices, shows opposing-leg arbitrage percentages, and exposes the inputs and
limitations behind each calculation. It does not place trades.

- **Odds board:** matched selections, local filters and live price Details.
- **Arbs:** explicit opposing legs and signed gross conditional percentages.
- **Admin:** source status, quota, refresh, pause, Stop and guarded recovery.
- **Manual What-if:** calculations with explicit probability, costs and quantity.

Kalshi and Polymarket US use native adapters. Novig and ProphetX can arrive through
The Odds API. Venue coverage varies; unknown fees, settlement, probabilities and
depth withhold dependent calculations. Positive, zero and negative results are
valid. Reference prices are separate from executable comparison legs.

## Quickstart

Requires macOS and Python 3.11+; CI uses Python 3.14. PostgreSQL and a Node service
are not required. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
scripts/opportunity-board start
```

Open the printed address, normally [localhost:8783](http://127.0.0.1:8783/).
Startup automatically attempts configured read-only source acquisition; configure
credentials and scope first using [configuration and operation](docs/configuration.md).
Missing access is reported per source. Saved or synthetic prices never replace
missing current data.

```sh
scripts/opportunity-board status
scripts/opportunity-board stop
```

For foreground operation: `.venv/bin/python -m app.dashboard --port 8783`.
Restart after source or credential changes. The listener must remain on loopback;
remote and shared-user hosting are unsupported.

## Development

Install the locked development tools using [development](docs/development.md),
then run focused offline checks:

```sh
.venv/bin/python -m pytest -q tests/test_current_ssot.py tests/test_current_contract.py
node tests/test_current_client.cjs
```

Python tests use mocks, fixtures and temporary state; Node 22 runs dependency-free
client checks. The [synthetic preview](docs/development.md#synthetic-preview) provides
populated UI data without provider access.

- [Architecture and module ownership](docs/architecture.md)
- [Configuration and operation](docs/configuration.md)
- [Development and testing](docs/development.md)
- [CI workflows](docs/CI.md)
- [Security](docs/security.md) and [failure recovery](docs/error-handling.md)
- [Sport support](docs/sports-integration.md) and [data limitations](docs/market-data-gaps.md)
- [UI design](docs/ui-design.md)
