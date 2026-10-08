# Configuration and operation

## Current operation

The ordinary launcher starts service-owned native streams and one shared Novig/ProphetX aggregate scheduler. The current paid policy is 100,000 monthly credits with a 50-credit reserve. Automatic refresh covers every selected active sport at 15-minute slots during 09:00 inclusive to 23:00 exclusive America/New_York while the app runs; missed slots are skipped. Admin refresh selects its own sport scope without changing automatic scope or scheduled due times. Native sources are independent. The Odds board, Arbs and live Details require no stake entry; model EV stays unavailable without an independent basis.

`current_aggregate_policy.POLICY` owns schedule and dispatch limits; `current_policy` owns the exact startup configuration. Both `enabled` and `aggregate_enabled` must be explicit booleans in a complete configuration. Missing keys fail before service ownership or credential access. `aggregate_enabled=False` is supported native-only operation and remains disabled through guarded recovery. Use `config/current.example.json` as a complete native-only template. It disables aggregate dispatch; it still attempts native acquisition. Copy it to `.local/predict-current-config.json` or pass its path to the foreground CLI. Set `enabled` to false for idle startup.

Startup can make read-only network requests within the configured resource limits. Aggregate requests consume account credits. Stop the app before changing credentials; preserve ledger reservations and uncertain charges when investigating failures.

## Dashboard controls

Use the [README](../README.md) for installation. The supported ordinary workflow is a local macOS source checkout with Python 3.11+ and the `stream` dependencies; current validation uses Python 3.14. PostgreSQL is not required.

| Control | Implemented behavior |
| --- | --- |
| Launcher | `scripts/opportunity-board start\|status\|stop`, normally at loopback port 8783; start reuses a verified existing process or finds a free port |
| Instance | `beta` (default) and `poc` separate process records/logs; both use the same ordinary application |
| Current provider | `CurrentService` uses validated `current_policy.load()` configuration and starts native workers plus the shared aggregate scheduler when enabled |
| Current configuration | `.local/predict-current-config.json`, or `--current-config`; default scope is NFL winner/spread/total while the process runs; explicitly reduced durations are finite |
| Board / Details | `/` reads latest state and Details follows current revisions; `/arbs` names opposing legs; filters and Details do not dispatch paid requests |
| Admin | `/admin` exposes source status, quota, Stop/Pause and guarded fresh-runtime recovery |
| Retained inspection | `/admin/retained` keeps finite/saved-session readers; it does not populate the ordinary live board |

The launcher uses `.venv/bin/python` with a minimal environment. It does not load `.env` or forward shell credentials. The aggregate worker itself reads the approved ignored/untracked repository `.env` through the guarded credential loader. `process.json` and `server.log` live in the selected `.local/opportunity-board*` directory. Start does not reload an existing worker; restart through verified owned-process controls after application or credential changes.

Current startup acquires lifecycle ownership and records fresh consumed authority before source dispatch. It does not load saved or synthetic quotes. Native source/resource limits remain bounded by `current_policy.DEFAULT`; the process-lifetime sentinel is declared as `APP_RUNNING_DURATION`. Aggregate envelopes are declared once by `current_aggregate_policy.POLICY` and copied into each consumed attempt. Keep Stop and accounting intact.

## External access

`app/collection/venue_access.py` fixes native production destinations:

| Venue | REST | WebSocket | macOS Keychain service / account |
| --- | --- | --- | --- |
| Kalshi | `https://external-api.kalshi.com` | `wss://external-api-ws.kalshi.com/trade-api/ws/v2` | `prediction-arb.kalshi.production` / `market-data` |
| Polymarket US | `https://gateway.polymarket.us` | `wss://api.polymarket.us/v1/ws/markets` | `prediction-arb.polymarket-us` / `retail-api` |

Native loaders expect JSON credential records in the Keychain services above: `key_id`/`private_key` for Kalshi and `key_id`/`secret_key` for Polymarket US. There is no native credential setup CLI; provision those records using your local Keychain tooling. Do not put native secrets in an environment template. Ordinary current startup resolves native credentials through the guarded path; aggregate credentials load at a permitted dispatch. Never include values in documentation, commands, logs or evidence. Saved-data inspection needs no credentials.

When paid-account metadata is present, aggregate credential selection requires the guarded ignored repository `.env`; failure is explicit and never falls back to another account. Without paid selection, the supported retained/pre-paid path accepts a supplied `ODDS_API_KEY`, then guarded `.env`, then the validated legacy Keychain record. The ordinary launcher strips inherited keys. `.env.example` documents the aggregate variable only; it is not a credential or a required startup file. A manually provisioned `.env` must be untracked, a regular file owned by the current user, and private (mode 0600). After stopping the app, `.venv/bin/python scripts/predict-paid-key` performs hidden local key entry and a paid-account ledger transition; it does not make a provider request. A worker caches its key until closure. Do not run this account-changing command as a test. Configured plan allowance is distinct from provider-observed usage and remaining credits.

The shared aggregate scheduler calls fixed The Odds API endpoints for both `novig,prophetx` in a sport-wide request. Existing native Novig/ProphetX collectors and the separate ProphetX verifier retain their own scoped credentials and attempt policies. Public Novig GraphQL is display-only. Optional references are not comparison legs.

## Operation and deployment limits

Current operation has native streaming workers and one shared aggregate scheduler. There is no configured operating-system service, automatic process restart or cloud deployment. Daytime 15-minute dispatch is implemented through the shared policy and durable cycle ledger. Multiple tabs must share acquisition; a filter or Details click must not create a paid call. Stop revokes dispatch and closes owned workers while preserving accounting and calculation-lease expiry.

Keep the listener on loopback. Remote, shared-host and reverse-proxy deployment are outside current personal use. See [security](security.md) and [failure handling](error-handling.md). There is no configured installer or cloud deployment.

## Saved review and live collection

Retained finite/saved-session tools use `CoverageOwner`, `ContinuousSession`, acknowledged journals and exact saved cutoffs. Explicit real collection needs its applicable run specification and fresh consumed authority; isolated tests use mock sources. Their older Start/Stop, duration and Saved scan controls do not apply to the ordinary current board. Do not reuse historical acquisition packages or consumed attempts as fresh authority. Historical `plan_evidence` strings in saved specifications identify original access assertions; they are compatibility labels, not current setup-document links.

Preserve saved packages, references, replay readers and separate research timing. Retained finalization publishes completion only after journal/replay checks; failed packages remain incomplete. Historical source ages describe their saved cutoff, not today's freshness. See [module ownership](architecture.md#module-ownership), [architecture](architecture.md) and [development](development.md).

The older PostgreSQL workflow remains separate. `scripts/project-postgres` manages its local cluster/socket and `.venv/bin/python -m app.storage migrate` applies its migrations. Neither is an ordinary dashboard startup prerequisite. See [storage CLI](../app/storage/__main__.py) and [schema migrations](../app/storage/migrations/001_capture.sql) before explicitly scoped database work. Live verifiers are not installation checks.
