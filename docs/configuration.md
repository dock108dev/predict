# Configuration and operation

Use the [README](../README.md) for installation and [development guide](development.md)
for offline checks. The supported owner workflow is a local macOS source checkout,
Python 3.11+, the `stream` extra and existing dedicated Keychain credentials.
CI targets offline behavior on Ubuntu/Python 3.11; it does not test Linux credential
access. Current hosted verification limits are in the [development guide](development.md#pull-request-ci).

## Current beta controls

| Control | Source and behavior |
| --- | --- |
| HTTP listener | `app.dashboard.opportunity_board` binds `127.0.0.1`, default port 8783; `--port` overrides it |
| Launcher | `scripts/opportunity-board start\|status\|stop --port 8783 --instance beta`; start searches upward if the port is occupied |
| Instance | `beta` (default) uses `.local/opportunity-board-beta`; `poc` uses `.local/opportunity-board`. Both launch the same personal-beta factory; instance names only separate process records/logs |
| Scan controls | Current CoverageOwner uses bounded duration and run-spec limits; ordinary UI duration defaults to 175 seconds. The hidden `max_games` control only has an effect with historical MultiOwner |
| Saved sessions | Default product root `evidence/product-sessions`, older `evidence/multi-game/sessions`, and two original captures; qualification owners use their explicit output root |
| Run policy | `multi_game.configuration()` extends `e6_live.configuration()` and its retained run-spec; it is source configuration, not an environment override |

The launcher uses `.venv/bin/python` and a minimal child environment containing
PATH, unbuffered output and disabled bytecode writes. It does not load `.env` or
forward shell credentials. No `.env` keys are required for the current beta.
`process.json` records PID, command, start time, URL and port; `server.log` is in
the selected instance directory. Start returns the existing owned process when
present; edits require a later explicit stop/start to take effect. `--port` does
not move an already running instance.

The default factory selects `CoverageOwner(product_mode=True)` and starts idle.
Default source configuration is not an approval package: ordinary startup does not
enable real collection. Native/two-source previews supply an explicit spec, output
root and approval through the same router; isolated fixtures use mock endpoints.
Preserve consumed-attempt and candidate bindings. The current tracker governs
execution, not an old setup example.

`ContinuousSession` and native-source configuration bound discovery, subscriptions,
requests, frames, storage and cutoffs. The bootstrap six-game limit in
`multi_game.configuration()` belongs to historical MultiOwner/MultiSession;
CoverageOwner does not apply the hidden `max_games` request field. See
[SSOT](ssot.md) for the control-contract follow-up.

`query_policy` owns selection validation: unsupported choices and duplicate
selectors fail explicitly, and manual probability assumptions need a nonblank
basis. `local_security.body_limit` owns 4 KiB control and 1 MiB import limits,
including streamed requests.

## External access

`app/collection/venue_access.py` fixes the production destinations:

| Venue | REST | WebSocket | macOS Keychain service / account |
| --- | --- | --- | --- |
| Kalshi | `https://external-api.kalshi.com` | `wss://external-api-ws.kalshi.com/trade-api/ws/v2` | `prediction-arb.kalshi.production` / `market-data` |
| Polymarket US | `https://gateway.polymarket.us` | `wss://api.polymarket.us/v1/ws/markets` | `prediction-arb.polymarket-us` / `retail-api` |

The credential loader expects a JSON object with `key_id` and `private_key` for
Kalshi, or `key_id` and `secret_key` for Polymarket US. Reuse authorized credentials;
never put values in docs, captures or environment examples. Launch and saved-data
inspection do not load credentials; explicit real Start does. Credential presence
and provider entitlement are not established by an offline check.

The historical optional reference branch of `TransportSession.start` reads
`ODDS_API_KEY` only for a real run with reference collection enabled. It is not
needed or forwarded by the prediction-only beta launcher. Enabling paid reference
collection requires its own run specification, budget and authorization; adding
an environment key alone does not enable a beta feature. Native Novig/ProphetX
branches are implemented in `collection/native_product.py`, with dedicated
credential references. Actual access/qualification remain pending; credentials do
not bypass spec/approval gates. Public Novig GraphQL is display-only. See
[architecture](architecture.md) and the current tracker.

Environment settings in separate tools are not dashboard setup requirements:

| Variable | Consumer and scope |
| --- | --- |
| `ODDS_API_KEY` | The explicitly enabled historical reference branch described above |
| `PROPHETX_SANDBOX_ACCESS_KEY`, `PROPHETX_SANDBOX_SECRET_KEY` | `app.prophetx_verify`, sandbox verification only |
| `PROPHETX_PRODUCTION_ACCESS_KEY`, `PROPHETX_PRODUCTION_SECRET_KEY` | `app.prophetx_verify`, production verification only |
| `PREDICT_TWO_SOURCE_PARENT` | Set internally by `two_source_preview` when spawning its supervised child; not a user override |

The separate ProphetX verifier selects one complete environment-specific pair
from the shell, then the repository `.env`, then its dedicated Keychain entry;
an incomplete selected pair is rejected, never merged across sources. This is
different from the ordinary launcher's minimal environment. Do not run verifiers
as installation checks or copy credential values into the repository.

## Operation and deployment limits

There is no scheduler, system service, automatic scan, auto-restart or cloud
deployment workflow for the beta. The browser explicitly starts and stops bounded
work; finalization publishes a completed manifest before exposing a saved scan.
Use [failure handling](error-handling.md) for pending manifests, cleanup failures
and diagnostics. Captures accumulate without automatic retention or pruning.

Keep the listener on loopback. Browser origin/host checks are not authentication
of other local processes; remote, shared-host and reverse-proxy deployment are
unsupported. See [security](security.md). Installation is editable: packaged
assets and repository evidence are not a standalone distributable app.

The older PostgreSQL workflow is separate. `scripts/project-postgres` requires
`initdb`, `pg_ctl`, `psql`, `createdb` and `rg` on PATH; it manages `.local/postgres`
and `.local/pgsocket`, socket port 55432, role/database `prediction_arb`, without a
TCP listener. Start can initialize a cluster and change local directory modes.
`.venv/bin/python -m app.storage migrate` applies the migrations in `app/storage/migrations`;
these are explicit operations, never a beta startup prerequisite. See
[Slice 12](slice-12.md) before any database work. Neither database operations nor
live verifiers are installation checks.
