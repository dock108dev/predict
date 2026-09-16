# Configuration and operation

Use the [README](../README.md) for installation and [development guide](development.md)
for offline checks. The supported owner workflow is a local macOS source checkout,
Python 3.11+, the `stream` extra and existing dedicated Keychain credentials.
Ubuntu/Python 3.11 CI verifies offline behavior, not Linux credential access.

## Current beta controls

| Control | Source and behavior |
| --- | --- |
| HTTP listener | `app.dashboard.opportunity_board` binds `127.0.0.1`, default port 8783; `--port` overrides it |
| Launcher | `scripts/opportunity-board start\|status\|stop --port 8783 --instance beta`; start searches upward if the port is occupied |
| Instance | `beta` (default) uses `.local/opportunity-board-beta`; `poc` uses `.local/opportunity-board`. Both launch the same personal-beta factory; instance names only separate process records/logs |
| Scan controls | Browser Start accepts integer `max_games` 1–6 and `duration` 1–180 seconds; defaults 6 and 175 |
| Saved sessions | `evidence/multi-game/sessions`, plus two retained single-game captures loaded by `opportunity_board.load_sessions` |
| Run policy | `multi_game.configuration()` extends `e6_live.configuration()` and its retained run-spec; it is source configuration, not an environment override |

The launcher uses `.venv/bin/python` and a minimal child environment containing
PATH, unbuffered output and disabled bytecode writes. It does not load `.env` or
forward shell credentials. No `.env` keys are required for the current beta.
`process.json` records PID, command, start time, URL and port; `server.log` is in
the selected instance directory. Start returns the existing owned process when
present; edits require a later explicit stop/start to take effect. `--port` does
not move an already running instance.

Discovery selects exact participant/schedule overlaps for NFL pregame events more
than five minutes before kickoff. Bounds in `multi_game.configuration()` include
128 aggregate requests, 4 aggregate connections, 2 concurrent sockets, 1,200
messages, 32 MiB aggregate body bytes, 2,048 ingress records / 16 MiB ingress bytes,
and 4,096 journal records / 32 MiB journal bytes. These are ceilings, not promised
coverage or sustained throughput. Discovery rejects truncated catalogs. Start
also checks the Kalshi account read budget within the run.

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
an environment key alone does not enable a beta feature. ProphetX and Novig are
retained adapters, not current beta scan sources; see [architecture](architecture.md).

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
`python -m app.storage migrate` applies the migrations in `app/storage/migrations`;
these are explicit operations, never a beta startup prerequisite. See
[Slice 12](slice-12.md) before any database work. Neither database operations nor
live verifiers are installation checks.
