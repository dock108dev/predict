# Local UI development from the dev server snapshot

The selected flight-board UI runs in this checkout. Collectors remain on the
Hetzner dev server. A PostgreSQL logical snapshot supplies actual source quotes,
references, fee schedules, complete calculations, and saved data locally.

## Normal iteration

```sh
.venv/bin/python scripts/dev-snapshot serve
```

Open http://127.0.0.1:8784/. The command runs only the app. CSS, HTML and client
modules are served from this working copy; reload to see edits. Python server
changes require restarting this command. If another app process occupies 8784,
stop that verified process first or use `serve --port 8785`.

A snapshot contains captured source quotes, references and fee inputs. It is not
a claim about currently available execution. League coverage depends on the
captured slate; games leave the board at kickoff even while the database is frozen.

## Refresh the dataset

Stop the running snapshot app with Ctrl-C, then:

```sh
.venv/bin/python scripts/dev-snapshot pull
.venv/bin/python scripts/dev-snapshot serve
```

`pull` keeps an interrupted download as a private `.dump.partial` file and only
renames it to a restore-ready `.dump` after a successful transfer. It reads a
consistent custom-format `pg_dump` through the existing `hetzner`
SSH alias. It does not stop or reconfigure server collection. It restores into a
new private local cluster using PostgreSQL 16 tools, checks applied migration
hashes against this checkout, and atomically selects it in
`.local/dev-snapshot/current.json`. PostgreSQL 16 tools are currently expected at
`/opt/homebrew/opt/postgresql@16/bin`. Dumps and previous snapshot clusters are
retained under `.local/dev-snapshot/`; each complete cluster uses roughly 2 GiB.
To inspect the active paths, use `scripts/dev-snapshot status`. If importing a
previously downloaded dump, use `restore --dump /absolute/path/to/file.dump`.

The server remains the acquisition owner. The existing local database, provider
secret files, account/quota/hold ledgers, Stop choices, source pauses and remote
ownership marker are preserved. Snapshots use a separate Unix socket and have
`default_transaction_read_only=on`. No local collector is launched. Admin
mutation/collection workflows are outside this read-only development mode;
server heartbeat information in the copied data will naturally become old.

My Bets writes only its separate private SQLite journal. It survives snapshot
pulls; the source database remains read-only. See the [journal contract](bet-journal.md).

## Limits and verification

A snapshot is frozen, while kickoff eligibility still uses real time. Games
will drop off as they start; refresh when the remaining slate becomes sparse.
Do not move kickoff/source timestamps or change EV to keep examples visible.
Synthetic fixtures remain useful for deterministic empty, failure and long-title
cases. A snapshot supports real-data UI integration; scheduled ingestion and
new provider updates still need operating-runtime evidence when those change.

## Local schema and calculation upgrades

`restore` and `pull` validate the applied migration prefix, apply new packaged
migrations in the private cluster, and recover queued affected-game calculations
from stored observations before selecting it. They also revalue version-5 rows
using the selected lowest-no-vig policy where a full rebuild was unnecessary.
For an existing local snapshot, run:

```sh
.venv/bin/python scripts/dev-snapshot revalue
```

This guarded session verifies the private socket and actual cluster identity.
It applies migrations and recovers generated rows game by game with the ordinary
owner, without acquisition. Migration 105 builds fee-qualified prices for arb
research independently of complete sportsbook references. Original source quotes,
source clocks, controls and financial ledgers are preserved. Normal app connections
remain read-only; no collector starts. Reference-only revaluation is atomic and
idempotent; affected-game recovery uses its normal per-game transactions. Other
calculation-version changes still require the appropriate full owner rebuild.
Revaluation also retires superseded main-line quotes using retained source
evidence before recovering affected games, matching collector startup.
