# Configuration and operation

Install the app using the [README](../README.md). The ordinary runtime uses a
local macOS source checkout, Python with the `stream` dependencies and a dedicated
socket-only PostgreSQL cluster. The web listener binds to loopback.

## Practice without an account

Follow the [README quickstart](../README.md#requirements-and-quickstart) to copy
the acquisition-off example, create the database, and start the app role. On
the desk, choose **Open replay**. Search for Harbor Foxes, open an offer, and
compare its original price and calculation. Open **Arbitrage** inside the
replay, inspect a pairing, then select **Price moves** to step forward. Practice
has fictional inputs and a fixed clock. The two saved-capture options depend on
files in `.local/odds-replay`.

Use the header's **Odds** control for American or decimal prices. In
**Admin → Settings**, choose a time zone or follow the device. The EV and
Arbitrage schedule filters can override the default with Eastern or UTC. The EV
page remembers its selected calculation basis in the browser. Synthetic replay
has separate settings and offers the calculation bases supported by its data.

On the live desk, an offer can be visible even when its reference, settlement
terms or fee is unavailable. Clear return filters to see those prices. Arbitrage
needs current opposing offers with compatible settlement terms. Open an offer to
see why a calculation is missing. **Use latest prices** checks for a current
replacement and keeps the inspected evidence pinned if the price is unavailable.

## Source configuration

Copy [config/current.example.json](../config/current.example.json) to
`.local/predict-current-config.json` before starting. The launcher reads this
default path. Override it with
`scripts/opportunity-board start --role data --current-config PATH` (or
`--role both`). Foreground data operation accepts
`.venv/bin/python -m app.collection.data_runtime --current-config PATH`.
The app process reads the shared runtime; it does not accept source configuration.
The launcher rejects `--current-config` for app-only starts, stop and status.

- `enabled` controls all acquisition and is `false` in the example. Turn it on
  when you are ready to start source workers.
- `aggregate_enabled` controls the selected aggregate route when acquisition is
  enabled. The example leaves it off so you can opt into paid collection.
- `aggregate_provider` selects `sportsgameodds` or the legacy `the_odds_api`
  route. The sample selects SportsGameOdds. Earlier configurations without
  this field keep their legacy selection.
- `sports` scopes native discovery. Values are `NFL`, `NCAAF`, `NBA`, `NCAAB`,
  `MLB` and `NHL`; actual source listings and supported calculations vary.
- `native_sports` and `native_families` optionally override the native scope.
  Missing or empty values use `sports` and `families`. They do not widen aggregate requests.
- `aggregate_sports` independently scopes aggregate requests. An absent or empty
  list inherits `sports`. The sample therefore selects NFL for both paths.
- `families` selects `moneyline`, `spread` and/or `total`.

Configuration must match the validated fields in
`app/collection/current_policy.py`. Both enable flags must be booleans. Resource
bounds are validated as positive integers. Rediscovery must be at least 60 seconds.
Use Coverage and Admin to see the effect of source scope and resource settings.
The default `duration_seconds=31536000` means operation for the app's lifetime;
smaller valid values set a finite duration. An explicit missing path fails. If
the default file is absent, internal defaults enable native **and aggregate**
acquisition, so create the file deliberately. Run `scripts/opportunity-board
check-config` before starting data. With a custom config, run
`scripts/opportunity-board check-config --current-config PATH` and use that same
path when starting data. The check prints the selected provider and scope from the
validated configuration. It needs no database, credentials or network access.

The SportsGameOdds worker shares its object budget across discovery and event
refresh. Admin shows the plan, account usage, reserve, holds and pacing. The
first-of-month UTC boundary is a provisional pacing assumption whenever the
provider supplies no reset. Choose sports and market scope to fit your provider
allowance. Check **Admin → Spending** for remaining allowance, reserve and any
unresolved charges. Keep the existing ledger and Stop state on restart.
See [SGO operations](sportsgameodds-operations-20261110.md).

The legacy Odds API route uses its own ledger and 15-minute schedule from
09:00 to 23:00 Eastern. Its limits and held credits apply only to that route.

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
There is no operating-system service. For foreground use, start PostgreSQL and
prepare its schema, then run the roles you need in separate terminals:

```sh
scripts/project-postgres start
.venv/bin/python -m app.storage migrate
.venv/bin/python -m app.collection.data_runtime
.venv/bin/python -m app.dashboard.opportunity_board --port 8783
```

Ctrl-C stops that foreground role. Stopping the app leaves data running; stopping
data ends acquisition. Both leave PostgreSQL running; use
`scripts/project-postgres stop` when no app needs the cluster. Do not delete
`.local` as a troubleshooting step: it contains data and accounting state.

| Surface | Purpose |
| --- | --- |
| `/` | Opportunity dashboard with separate EV and arbitrage sections |
| `/arbs` | Stored opposing-comparison view |
| `/scanner` | Advanced Scanner, observed episodes and selected manual tickets |
| `/odds`, `/ev` | Observed source prices and single-trade estimates across games |
| `/replay?dataset=practice` | Fictional opening prices and a later move for trying EV and Arbitrage without keys |
| Details and Original | Selected calculations and original inputs; leased selections retain captured evidence when current inputs change |
| `/admin` | Source, quota, storage and issue status; collection controls and guarded recovery |
| `/admin/retained` | Separate finite-session and saved-capture readers |

Source workers run independently of browser attendance. Board reads and settings
changes do not request source data or consume provider credits. Prices retain
their source and receipt clocks; a new calculation does not make an old price
fresh. Old ordinary sports-history routes return HTTP 410. Database failures
are visible and have no in-memory financial fallback.

## Credentials

The launcher uses a minimal environment. Source-specific loaders retrieve
credentials from the supported local stores.

| Native venue | macOS Keychain service / account | JSON fields |
| --- | --- | --- |
| Kalshi | `prediction-arb.kalshi.production` / `market-data` | `key_id`, `private_key` |
| Polymarket US | `prediction-arb.polymarket-us` / `retail-api` | `key_id`, `secret_key` |
| Novig v3 | `prediction-arb.novig.v3.production` / `market-data-read` | `key_id`, `private_key_pem` (Ed25519) |

Add a password item in your login keychain with the service as the item's name
and the account from the table. Paste a single JSON object into the password
field with the named fields for that venue. Encode PEM line breaks as `\n` inside
the JSON string. You can also use Terminal's secure prompt, for example
`security add-generic-password -s prediction-arb.kalshi.production -a market-data -w`.
Paste the JSON only at the password prompt. macOS may ask you to allow the
local Python process to read the item. In Admin Sources, check the independent
status of each feed. A missing credential for one venue does not supply or
replace another venue's key. Keep secrets out of sample configuration, command
arguments and logs.

For SportsGameOdds, add exactly one `SPORTSGAMEODDS_API_KEY` assignment to the
repository's private `.env`. Copy [.env.example](../.env.example) if needed.
Keep the file ignored and untracked, owned by your macOS user, and set
`chmod 600 .env`. Keep the key out of commands and logs. The SGO worker
checks the file and validates the credential before starting. A failed SGO
credential leaves SGO unavailable. Native workers use their own keys.

For the legacy Odds API route, `.venv/bin/python scripts/predict-paid-key`
prompts without echoing the key and records the account transition without
a provider request. Use this command only for that route.

Stop data before changing credentials with `scripts/opportunity-board stop --role data`.
Start it again with the same selected configuration after saving the key.
Saved inspection and synthetic practice need no provider credentials.
See [security](security.md) for the credential-loading rules.

The Novig key is for the signed, read-only book stream. A missing key
keeps that feed unavailable while aggregate Novig follows its normal
schedule. Signed in-game authority requires an observed reset and a
qualifying subsequent image.

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
Selected calculations apply their explicit settings over this base policy.
Shared discovery rows retain the background owner's policy; changing selected
Details settings does not recalculate or rerank the shared slate.

The browser sends its amount, buffer and benchmark settings on board reads as
the requested policy for selected Details and remembers them in the tab's session
storage. The response distinguishes that requested policy from the shared
discovery policy. Without saved tab settings,
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
guard follows `rss_bytes` (installed 3 GiB for bulk acquisition). Admin shows
actual storage status and saving failures.

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

## Acquisition capacity and authority

Native event, market and discovery-page settings are not complete-universe
ceilings. `markets_per_source` is the publication chunk size. Source-byte and RSS
limits come from the loaded configuration; the watchdog and background worker
share the RSS setting. Example defaults are not an installed operator's values.

Aggregate alternate authority lives separately in
`.local/predict-alternate-authority.json`. Its credit ceilings and expiry do not
replace account-window, reserve, quota, Stop or hold checks. Exact alternate
manifests exceeding the allowed budget do not dispatch arbitrary subsets.
Accounting storage capacity is not permission to spend. See
[acquisition](acquisition.md) for lifecycle and completeness boundaries.
