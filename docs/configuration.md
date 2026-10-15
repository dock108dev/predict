# Configuration and operation

Use the [README](../README.md) to install the app. The supported runtime is a local
macOS source checkout, Python 3.11+ with `stream` dependencies and a dedicated
socket-only PostgreSQL cluster. Keep the listener on loopback.

Ordinary ingress uses direct SQL
upserts and shared depth; v2 boards derive transient calculations from those
rows. The [storage guide](current-row-storage.md) and
[current-read contract](comparison-board-api-contract.md) describe this path.

Ordinary launch explicitly selects current SQL boards and their all-games paging.
The retired `--game` option and observation-archive directory constructor option
are rejected. `enabled=false` permits current SQL inspection without acquisition.
Explicit injected/research factories retain their own ephemeral state transport.

## Source configuration

Copy [the sample](../config/current.example.json) to
`.local/predict-current-config.json`. The launcher reads that file; foreground
operation accepts `--current-config PATH`. Both `enabled` and `aggregate_enabled`
must be explicit booleans. The sample enables native acquisition and disables
aggregate requests. Set `enabled=false` for current-data inspection without acquisition.
A missing explicit path fails. If the default file is absent, validated internal
defaults enable both native and aggregate acquisition, so create the file deliberately.

`sports` scopes native discovery. Supported values are NFL, NCAAF, NBA, NCAAB, MLB
and NHL; actual listings vary. `aggregate_sports` independently scopes aggregate
requests and inherits `sports` when absent or empty. Families are `moneyline`,
`spread` and `total`. Resource bounds cannot exceed `current_policy.DEFAULT`;
rediscovery must be at least 60 seconds. The one-year `duration_seconds` default
is the process-lifetime sentinel; smaller valid values select finite operation.

The shared aggregate scheduler requests Novig, ProphetX and Pinnacle through
The Odds API. `current_aggregate_policy.POLICY` supplies a 100,000-credit monthly
ceiling, 50-credit reserve and 15-minute slots from 09:00 inclusive to 23:00
exclusive in America/New_York. Missed slots are skipped. These configured limits
are not proof of an account plan or balance. Explicit Admin refresh uses the same
ledger without changing automatic sports or due times. Native-only configuration
stays aggregate-disabled during recovery.

## Start and stop

```sh
scripts/opportunity-board start
scripts/opportunity-board status
scripts/opportunity-board stop
```

`start` starts the project database, reuses a verified existing app or selects a
free loopback port. `--port` selects the first port to try. `--instance beta`
(default) and `--instance poc` use separate process records and logs, but share
ordinary data and service ownership; they are not independent collection accounts.
Runtime files live under `.local/opportunity-board-beta` or `.local/opportunity-board`.
Start does not reload an existing process. Stop, then Start after backend or
credential changes. There is no operating-system service or automatic restart.

For foreground operation, start PostgreSQL first:

```sh
scripts/project-postgres start
.venv/bin/python -m app.dashboard --port 8783
```

Ctrl-C stops the foreground app. App Stop does not stop the PostgreSQL cluster;
`scripts/project-postgres stop` stops that dedicated cluster when no app needs it.
Do not remove `.local` to troubleshoot: it includes data, ledgers and process state.

| Surface | Behavior |
| --- | --- |
| `/`, `/ev`, `/arbs` | All-game current Odds, EV and opposing allocations |
| Details and Original | Expected current context; changed/removed inputs require a fresh selection |
| Old history routes | HTTP 410; sports history was retired |
| `/admin` | Source, quota, storage and issue status; pause, Stop and guarded recovery |
| `/admin/retained` | Separate finite-session and saved-capture readers |

Source workers run while the owned app runs, independently of browser attendance.
Startup does not import old journals or retained diagnostics. Current rows retain original source and
receipt clocks. Reads/calculations require no acquisition or quota mutation;
any available stale current values lose current positive-list eligibility.
Discarded sports history need not reopen. Database failure is visible; there is
no in-memory financial fallback.

## Credentials

The launcher uses a minimal environment and does not forward shell keys or load
`.env` itself. Source-specific guarded loaders retrieve credentials when needed.

| Native venue | Keychain service / account | JSON fields |
| --- | --- | --- |
| Kalshi | `prediction-arb.kalshi.production` / `market-data` | `key_id`, `private_key` |
| Polymarket US | `prediction-arb.polymarket-us` / `retail-api` | `key_id`, `secret_key` |

Provision native records using local Keychain tooling; there is no native setup
CLI. Destinations are fixed in `app/collection/venue_access.py`. Do not put native
secrets into sample configuration, command arguments or logs.

[`.env.example`](../.env.example) names `ODDS_API_KEY` without a value. A real `.env`
must be untracked, a regular user-owned file and mode 0600. Stop the app before
credential changes. `.venv/bin/python scripts/predict-paid-key` provides hidden
aggregate key entry and a paid-account ledger transition without a provider call.
A worker caches its selected key until closed. Paid selection requires the guarded
`.env` and never falls back to another account. Without paid metadata, explicit
pre-paid readers can use a supplied key, guarded `.env`, then a validated legacy
Keychain record. Saved inspection needs no credentials.

## Calculation settings

Source controls and calculation settings are independent. Ordinary defaults are
`predict-estimate-policy-3`: requested funding `1000`, buffer rate `0.005`, benchmark
`pinnacle`, method `proportional_no_vig`. `novig` and `prophetx` are also supported
benchmarks. The wire field `capital_ceiling_usd` carries the requested amount;
`sizing_mode=ceiling` remains an explicit sensitivity mode. Older v2 policies keep
their original ceiling meaning.

Optional `.local/estimate-policy.json` overrides exact string fields from
`RequestedTradePolicy`: `version`, `capital_ceiling_usd`, `buffer_rate`, `tie`,
`terminal_noncompletion`, `sizing_mode`, `benchmark_venue`, `benchmark_method`.
Omitted fields use defaults. For example:

```json
{"capital_ceiling_usd":"1000","buffer_rate":"0.005","tie":"0.005","terminal_noncompletion":"0.001"}
```

Policy changes invalidate dependent results on the next read/projection. Malformed
configuration refuses the affected operation. Browser amount/buffer/benchmark
settings select a calculation policy variant without writing global configuration or
requesting source data. See [calculation basis](benchmark-ev.md).

## Storage and recovery

Ordinary observations commit current events/contracts/offers and synchronized
native depth in one transaction. Price changes replace rows; original source
clocks and receipt clocks remain distinct. Completed/pregame-expired events
cascade to dependent rows. A 60-second expiry worker stops after three failures.
There is no ordinary journal, diagnostic body file, retry archive, saved report
or persistent calculation cache. SQL failure is visible as unsaved/unavailable.

The 2 GiB soft ceiling counts public `current_*` heap, index, TOAST and owned
sequence bytes before bounded writes. Free disk must remain at least 1 GiB; the
RSS guard remains 768 MiB. Admin reports actual saving failures and SQL usage.
Migrations are ordered, transactional and hash-checked; never edit an applied
migration. Legacy journal codecs and their historical caps remain separate
research compatibility, not the ordinary writer.

`python -m app.storage.current_reset --plan PATH` writes an exact sports-only
reset plan without changing data. Applying it requires `--apply --receipt PATH`,
a stopped owned board, no database clients, the acquisition lock and an unchanged
plan/source/protected state. This deliberate cutover tool is never called on
startup. Sports SQL/journals/sidecars/cursors/diagnostics have no mandatory history.
Credentials/configuration, account/quota/audit/due/consumed-attempt records,
reservations, both original holds and actual financial records remain protected.
Those records share directories with disposable sports artifacts: never delete
their parent directory. Do not rewrite applied migration checksums. After a reset,
restart the app and check source and saving status in Admin.

Quota availability subtracts unresolved/reserved exposure and the 50-credit
reserve from the latest authenticated remaining balance. Confirmed spending is
not deducted twice. Missing receipts remain unknown; reopening does not clear a
hold or authorize another dispatch.

`recover_accounting` is an explicit audited operation for an eligible inactive
aggregate worker and exact expired pending set. It binds current runtime/account,
attempt hashes and independent balance evidence; one bounded no-retry observation
can establish conservative budget authority without attributing the old charge.
See [Admin API](contracts/predict-admin-1.md) and
[failure recovery](error-handling.md). Do not trigger recovery as a routine test or
reuse a completed request. Recovery preserves reservations, uncertainty and due times.
