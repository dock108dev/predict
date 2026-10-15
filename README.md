# Predict

A local, read-only prediction-market comparison app for macOS. **Odds** groups
observed NFL winner prices, **EV** shows modeled single-trade estimates, and
**Arbs** compares opposing allocations. Details exposes original inputs, costs,
settlement assumptions and typed current originals. Admin manages source status and collection.

Kalshi and Polymarket US use native adapters; Novig and ProphetX can arrive through
The Odds API. Pinnacle is a reference, not a purchase leg. The default calculation
uses $1,000 funding and one 0.5% buffer on deployed capital. Estimates can be
negative or unavailable. Predict does not place trades.

## Requirements and quickstart

Requires macOS, Python 3.11+ and PostgreSQL tools (`pg_ctl`, `initdb`, `psql`,
`createdb`) on your PATH. Run commands from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
mkdir -p .local
cp -n config/current.example.json .local/predict-current-config.json
```

Read [configuration](docs/configuration.md) before starting. The sample enables
native acquisition and disables aggregate requests. Set `enabled` to `false`
for current-data inspection without acquisition. `cp -n` keeps existing settings.
Credentials are provisioned separately; aggregate requests consume provider credits.

```sh
scripts/opportunity-board start
scripts/opportunity-board status
scripts/opportunity-board stop
```

Open the printed loopback address, normally [localhost:8783](http://127.0.0.1:8783/).
The launcher starts a dedicated socket-only PostgreSQL cluster. There is no cloud
service or automatic restart. Current prices keep their original clocks; a recent
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

Node 22 is used for client tests; it is not an app service. Use affected tests for
small changes; [CI](docs/CI.md) describes the broader automated checks.

- [Architecture and module ownership](docs/architecture.md)
- [Calculation basis and limitations](docs/benchmark-ev.md)
- [Current-board API](docs/comparison-board-api-contract.md)
- [Interface design](docs/ui-design.md)
- [Security](docs/security.md) and [failure recovery](docs/error-handling.md)
- [Sport support](docs/sports-integration.md) and [data limitations](docs/market-data-gaps.md)
