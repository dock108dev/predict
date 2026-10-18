# Configuration and operation

Install the app using the [README](../README.md). The ordinary runtime uses a
local macOS source checkout, Python with the `stream` dependencies and a dedicated
socket-only PostgreSQL cluster. The web listener binds to loopback.

## Source configuration

Copy [config/current.example.json](../config/current.example.json) to
`.local/predict-current-config.json` before starting. The launcher reads this
default path; foreground operation also accepts `--current-config PATH`.

- `enabled` controls all acquisition. Set it to `false` to inspect stored current
  observations without starting source workers.
- `aggregate_enabled` controls The Odds API requests when acquisition is enabled.
  The sample enables native acquisition and disables aggregate requests.
- `sports` scopes native discovery. Values are `NFL`, `NCAAF`, `NBA`, `NCAAB`,
  `MLB` and `NHL`; actual source listings and supported calculations vary.
- `aggregate_sports` independently scopes aggregate requests. An absent or empty
  list inherits `sports`. The sample therefore selects NFL for both paths.
- `families` selects `moneyline`, `spread` and/or `total`.

Configuration must match the validated fields in
`app/collection/current_policy.py`. Both enable flags must be booleans. Resource
bounds may be lowered from `DEFAULT`; rediscovery must be at least 60 seconds.
The default `duration_seconds=31536000` means operation for the app's lifetime;
smaller valid values set a finite duration. An explicit missing path fails. If
the default file is absent, internal defaults enable native **and aggregate**
acquisition, so create the file deliberately.

The aggregate scheduler requests Novig, ProphetX and Pinnacle through The Odds
API. `app/collection/current_aggregate_policy.py` defines a 100,000-credit monthly
ceiling, 50-credit reserve and 15-minute slots from 09:00 inclusive to 23:00
exclusive in `America/New_York`. Missed slots are skipped. These are application
limits, not evidence of the provider account's plan or balance. Admin refresh
uses the same quota ledger and does not change the automatic schedule.

## Start and stop

Run from the repository root:

```sh
scripts/opportunity-board start
scripts/opportunity-board status
scripts/opportunity-board stop
```

`start` starts PostgreSQL and the independent data/app processes, reusing verified
existing processes. Add `--role app`, `--role data` or `--role both` (default).
App-only restart leaves the collector identity, epoch and shared calculations
intact. `--port PORT` selects the first free loopback app port to try.
`--instance beta` (default) and `--instance poc` have separate app records under
`.local/opportunity-board-beta` and `.local/opportunity-board`; both share the
single data owner under `.local/predict-data-runtime`.

Starting an existing process does not reload it. Restart data after source
configuration/credential changes; restart affected processes after backend
changes. Source pauses, explicit global Stop and uncertain accounting survive a
data restart. Admin controls require the owning runtime's acknowledgment; a
failed or timed-out command stays explicit. The runtime heartbeat expires after
eight seconds. [Runtime contract](data-app-runtime-contract.md).
There is no operating-system service or automatic restart. For foreground use,
start PostgreSQL, then run these in separate terminals:

```sh
.venv/bin/python -m app.collection.data_runtime
.venv/bin/python -m app.dashboard.opportunity_board --port 8783
```

Ctrl-C stops that foreground role. Stopping the app leaves data running; stopping
data ends acquisition. Both leave PostgreSQL running; use
`scripts/project-postgres stop` when no app needs the cluster. Do not delete
`.local` as a troubleshooting step: it contains data and accounting state.

| Surface | Purpose |
| --- | --- |
| `/`, `/ev`, `/arbs` | Current Odds, single-trade EV and opposing allocations across games |
| Details and Original | Selected current calculations and their original inputs; changed inputs require a new selection |
| `/admin` | Source, quota, storage and issue status; collection controls and guarded recovery |
| `/admin/retained` | Separate finite-session and saved-capture readers |

Source workers run independently of browser attendance. Board reads and settings
changes do not request source data or consume provider credits. Prices retain
their source and receipt clocks; a new calculation does not make an old price
fresh. Old ordinary sports-history routes return HTTP 410. Database failures
are visible and have no in-memory financial fallback.

## Credentials

The launcher uses a minimal environment; it does not forward shell keys or load
`.env`. Source-specific loaders retrieve credentials when needed.

| Native venue | macOS Keychain service / account | JSON fields |
| --- | --- | --- |
| Kalshi | `prediction-arb.kalshi.production` / `market-data` | `key_id`, `private_key` |
| Polymarket US | `prediction-arb.polymarket-us` / `retail-api` | `key_id`, `secret_key` |

Provision native records through local Keychain tooling; there is no native setup
CLI. Fixed destinations are in `app/collection/venue_access.py`. Keep secrets out
of sample configuration, command arguments and logs.

[.env.example](../.env.example) names the aggregate `ODDS_API_KEY` without a value.
A populated `.env` must be untracked, a regular user-owned file and mode 0600.
`.venv/bin/python scripts/predict-paid-key` prompts for the key without echoing
it and records the paid-account transition without making a provider request.
Stop the app before changing credentials; a worker caches its selected key.
Paid selection requires the guarded `.env` and never falls back to another
account. Saved inspection needs no credentials. See [security](security.md) for
the remaining credential-loading rules.

## Calculation settings

Source controls and calculation settings are independent. The server's default
policy is `predict-estimate-policy-3`: requested funding `1000`, buffer rate
`0.005`, benchmark `pinnacle` and method `proportional_no_vig`. `novig` and
`prophetx` are also supported benchmarks. `capital_ceiling_usd` carries the
requested amount for compatibility; `sizing_mode=ceiling` is an explicit
sensitivity mode. The older `predict-estimate-policy-2` retains ceiling semantics.

Optional `.local/estimate-policy.json` supplies the server's base policy. Values
are exact strings and omitted fields use defaults. For example:

```json
{"capital_ceiling_usd":"1000","buffer_rate":"0.005","tie":"0.005","terminal_noncompletion":"0.001"}
```

Accepted fields are `version`, `capital_ceiling_usd`, `buffer_rate`, `tie`,
`terminal_noncompletion`, `sizing_mode`, `benchmark_venue` and
`benchmark_method`. Invalid configuration refuses the affected operation.
Each calculation request applies its explicit settings over this base policy.

The browser sends its amount, buffer and benchmark settings on every calculation
read and remembers them in the tab's session storage. Without saved tab settings,
and on **Restore defaults**, it uses fixed $1,000, 0.5% and Pinnacle settings;
these do not read `.local/estimate-policy.json`. The file still supplies unspecified policy
fields such as exceptional-state probabilities. Browser changes do not write the
file or request source data. See [calculation basis](benchmark-ev.md) for model
scope, fees and limitations.

## Storage and recovery

Current events, contracts, offers and native depth commit transactionally.
Updates replace current prices; completed or expired pregame events remove their
dependent rows. Ordinary operation does not persist calculation reports or a
sports-observation archive. A 60-second expiry worker stops after three failures.
The SQL soft ceiling is 2 GiB, minimum free disk is 1 GiB and the process RSS
guard is 768 MiB. Admin shows actual storage status and saving failures.

Use the [storage guide](current-row-storage.md) for migrations and the explicit
sports-only reset command. Applied migrations and their checksums are immutable.
Sports rows have a different lifetime from credentials, settings, quota/audit
records, attempts, reservations and holds; do not delete shared parent directories.
Startup never imports old journals or runs a reset automatically.

Quota availability accounts for unresolved and reserved exposure plus the
50-credit reserve without deducting confirmed spending twice. Missing receipts
remain unknown; reopening does not clear holds or authorize another dispatch.
Accounting recovery is an explicit audited operation with independent balance
evidence, not a routine diagnostic. See [failure recovery](error-handling.md)
and the [Admin API](contracts/predict-admin-1.md).
