# Configuration and operation

Start with the [README quickstart](../README.md#requirements-and-quickstart).
The local app listens on loopback and reads from a dedicated socket-only
PostgreSQL cluster. The app and collector run as separate processes.

## Saved odds

**Saved odds** reads recorded captures available under `.local/odds-replay/`.
Open an offer to inspect its original price, clock, and calculation. The capture
determines which calculation bases are available. See the
[desk guide](ui-design.md#current-comparison-interface).

## Source configuration

<a id="saved-review-and-live-collection"></a>

Copy [config/current.example.json](../config/current.example.json) to
`.local/predict-current-config.json` before starting a collector. Validate it
with `.venv/bin/python scripts/opportunity-board check-config`. Validation
requires only the configuration file. To select another file, pass
`--current-config PATH` to both `check-config` and `start --role data`. An
explicit missing path fails validation. Starting without the default file
selects internal defaults that enable acquisition, so create the file first.

| Setting | Purpose |
| --- | --- |
| `enabled` | Enables acquisition. The sample leaves it off. |
| `aggregate_enabled` | Enables the selected metered route when acquisition is enabled. The sample leaves it off. |
| `aggregate_provider` | Selects `sportsgameodds` or `the_odds_api`. The sample selects SportsGameOdds. An older configuration that omits this setting uses The Odds API. |
| `sports`, `families` | Base scope. Supported sports are NFL, NCAAF, NBA, NCAAB, MLB and NHL. Families are `moneyline`, `spread` and `total`. Listings vary by source. |
| `native_sports`, `native_families` | Optional native-source overrides. Absent or empty overrides inherit the base scope. |
| `aggregate_sports` | Optional aggregate sport override. An absent or empty list inherits `sports`. |
| `live_enabled` | Enables in-game acquisition and display. The sample and omitted setting both select pregame only. |
| `direct_kalshi_enabled`, `direct_polymarket_us_enabled` | Set both to `false` to use SGO prices for these venues. The direct adapters remain installed. Omitted flags preserve the older direct-source behavior. |

For the current SGO-only test, use `aggregate_provider: "sportsgameodds"` with
both direct flags false. SGO's `kalshi` quotes appear as Kalshi; its `polymarket`
quotes appear as Polymarket US under the owner's temporary test mapping. The
original `polymarket` bookmaker ID remains in source metadata. This is a configured
test mapping, rather than independently established venue identity.
Existing global Stop and source pauses remain in force.

## Editing fee rules

The current pregame fee rules live in the existing PostgreSQL
`public_fee_schedule.state.pricing_rules` records. Source verification receipts
remain in those same records. The calculation and Trading Fees page read these
configured rules.

```sh
.venv/bin/python -m app.fees.catalog seed
.venv/bin/python -m app.fees.catalog export > /tmp/predict-fees.json
```

`seed` copies applicable reviewed terms for venues that have no configured rules.
It preserves existing edits. Edit the exported JSON, then apply it atomically:

```sh
.venv/bin/python -m app.fees.catalog import /tmp/predict-fees.json
```

Each rule defines its formula, decimal-string coefficient, multiplier, balance
precision, quantity increment, optional league override, effective interval,
source URL and account/conservative profile. `set-rate VENUE RULE_ID RATE` changes
one rule coefficient. The existing engine owns the supported formulas and
rounding; rates and effective schedules are data.

Edits validate before writing and enqueue only affected venue occurrences.
Future cutovers take effect without a new source receipt. A configured interval
gap withholds that fee calculation rather than using a packaged fallback.
Known account failures and native product applicability still govern configured
rules. Private account evidence and credentials stay outside exported fee rules.

The [configuration validator](../app/collection/current_policy.py) defines bounds
and types. With Live off, a game leaves current results at verified kickoff or
earlier withdrawal. Saved pregame evidence can still be inspected. The web
app reads the selected provider and Live setting from the committed data
runtime.

SportsGameOdds shares its object budget across discovery and event refresh.
Its worker schedules scans at 15-minute intervals when account guards permit.
League discovery retains one cutoff across cursor pages, including after a
restart. A saved cursor resumes under matching query and phase settings.
**Admin → Spending** shows account usage, holds, reserves, and pacing.
The Odds API uses its own ledger and a 15-minute schedule from 09:00 to
23:00 Eastern. [SportsGameOdds operations](sportsgameodds-operations-20261110.md)

## Start and stop

Run these commands from the repository root after setting up the intended
configuration.

```sh
.venv/bin/python scripts/opportunity-board start
.venv/bin/python scripts/opportunity-board status
.venv/bin/python scripts/opportunity-board stop
```

The launcher starts the database and both roles by default. Use `--role app`
or `--role data` to manage one process. For the app, `--port PORT` is the
starting point when looking for a free port. Starting an already running process
reuses it. Restart the collector after changing the configuration or credentials.
Restarting the web app leaves collection and shared calculations running.
Source pauses, global Stop, and accounting holds persist across collector restarts.
[Runtime contract](data-app-runtime-contract.md)

For foreground development, start PostgreSQL and migrate the schema, then run
the needed roles in separate terminals.

```sh
scripts/project-postgres start
.venv/bin/python -m app.storage migrate
```

```sh
.venv/bin/python -m app.dashboard.opportunity_board --port 8783
```

```sh
.venv/bin/python -m app.collection.data_runtime --current-config .local/predict-current-config.json
```

Ctrl-C stops the foreground role. PostgreSQL stays running until
`scripts/project-postgres stop`. The project state under `.local/` includes
stored data, controls, and provider accounting.
For foreground or container operation, `PREDICT_DB_SOCKET` can select an
absolute PostgreSQL socket directory. The local default is `.local/pgsocket`.
Current desk reads fail closed if the reader cannot validate committed price and event evidence. Saved captures remain separate.

## Credentials

The launcher uses a minimal process environment. Native credential loaders
read supported macOS login Keychain items.

| Source | Keychain service / account | JSON fields |
| --- | --- | --- |
| Kalshi | `prediction-arb.kalshi.production` / `market-data` | `key_id`, `private_key` |
| Polymarket US | `prediction-arb.polymarket-us` / `retail-api` | `key_id`, `secret_key` |
| Novig signed in-game stream | `prediction-arb.novig.v3.production` / `market-data-read` | `key_id`, `private_key_pem` (Ed25519) |

Use the service as the item's name and the account from the table. Store a
single JSON object as the password. Encode PEM line breaks as `\n` inside
the JSON string. On macOS, you can enter that JSON at the password prompt
after running `security add-generic-password -s prediction-arb.kalshi.production -a market-data -w`.
Check each feed independently in **Admin → Sources**.

For SportsGameOdds, place one `SPORTSGAMEODDS_API_KEY` assignment in a private
`.env` at the repository root. Use [.env.example](../.env.example) as a template.
Keep the file untracked, owned by the user running the collector, and set
`chmod 600 .env`. For The Odds API, run
`.venv/bin/python scripts/predict-paid-key` to enter the key at a private prompt
and record the account transition without a provider request.

Stop the data role before changing credentials, then restart it with the
same source config. Keep provider keys out of command arguments and logs.
Saved inspections require no provider keys. [Credential loading](security.md#providers-files-and-processes)

## Calculation settings

The ordinary pregame dashboard has one posted-price model and no saved unit or
calculation-mode preference. It uses the fixed internal $100 comparison basis
for amount-dependent fee and quantity arithmetic. Search, league, market, venue
and alternate-line filters only affect SQL reads.

Existing evidenced account facts may be supplied in
`.local/trade-fee-account-facts.json`; they remain private and are not created by
page loads. Where documented applicable charges vary and an exact account case
is unresolved, the current calculation uses the highest applicable documented
charge and records the conservative choice in fee details. Missing mandatory
terms exclude the opportunity rather than defaulting to zero.

Research, Arbitrage and historical replay retain their separately labeled math
settings. Account connections and execution modeling are backlog work.
[Calculation policy](benchmark-ev.md) · [Fee applicability](fee-coverage-policy.md)

## Storage and recovery

The collector writes transactional market data and publishes committed comparison
results. Current prices preserve their source and receipt clocks. Pinned or saved
evidence can outlive current eligibility. Long-term archiving is opt-in and covers
admitted pregame observations. See [storage ownership](storage-ownership.md) and
[archive setup and verification](odds-archive-operations.md).

Applied migration files and their checksums are immutable. Keep accounting
records, unresolved holds, and Stop state through restarts and upgrades.
Use the documented recovery commands for the intended database and scope.
A missing receipt leaves its charge unknown. [Failure recovery](error-handling.md) ·
[Admin API](contracts/predict-admin-1.md)

## Acquisition capacity and authority

Native event and discovery limits bound work. They do not describe the complete
provider universe. `markets_per_source` sets the publication chunk size.
Source-byte and RSS limits come from the loaded config. Aggregate alternate
requests also require the scoped local authority in
`.local/predict-alternate-authority.json`. Account windows, quotas, reserves,
holds, and Stop apply independently of that authority.
[Acquisition boundaries](acquisition.md)
