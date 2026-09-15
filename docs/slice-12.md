# Slice 12 — PostgreSQL historical capture

Implemented September 12, 2026. Next: **Slice 13 — simple live dashboard**.
Stop before Slice 13. All venue access, fee, settlement, sizing and actual-fill
limitations from Slices 1–11 remain in force. No live venue requests were needed.

## Working workflow

Run from `/Users/michaelfuscoletti/Desktop/prediction-arb`:

```sh
# Reuses installed Homebrew PostgreSQL 14.20. No service registration.
uv pip install --python .venv/bin/python -e '.[stream]'
scripts/project-postgres start
.venv/bin/python -m app.storage migrate

# Imports the selected preserved Kalshi/PMUS captures and original audit files,
# then writes finite historical and explicitly synthetic calculation sessions.
.venv/bin/python -m app.storage ingest-default
# The twelfth example runs the same complete workflow:
.venv/bin/python -m app.storage_example

.venv/bin/python -m app.storage query
.venv/bin/python -m app.storage replay
.venv/bin/python -m app.storage history SESSION_ID CANDIDATE_ID
.venv/bin/python -m app.storage export .local/replay-bundle.json
scripts/project-postgres stop
```

`query` supplies session and candidate IDs for `history`, along with coverage,
classification, engine, normalized quotes, raw artifact references and liquidity-family fields. Use `query --session SESSION_ID --limit 100` to scope a bounded result (maximum 1,000 rows per section). Each invocation of
`ingest-default` deliberately creates new sessions. Retrying an individual
receipt/calculation with its original identity is idempotent; re-importing a
capture into a new session is a separately identified replay run.

The default import selects the original Slice 10 and Slice 11 example files,
plus the historical loader's exact Kalshi/PMUS source files. It checks the rebuilt
historical detector/depth reports against those preserved reports before writing.
The historical session has 20 candidate combinations from ten structural pairs,
all settlement-UNKNOWN and zero qualified opportunities. Synthetic sessions use
Slice 11's invented books/rules and real fee formulas. Their conditional positives
remain separate from production data. No private accounts or credentials are read.

## Dedicated runtime and restore

The installed PostgreSQL runtime is reused. Project storage is `.local/postgres`,
with socket `.local/pgsocket`, PostgreSQL port identifier 55432, role
`prediction_arb` and database `prediction_arb`. It has **no TCP listener**. The
socket and parent directory have mode 0700; local trust authentication is confined
to that private socket. There is no password to expose, system configuration
change, container, login service or global Homebrew service registration.
`connect()` accepts only project-prefixed databases on this exact socket.

The database was stopped after verification. Its data directory, local failure
journals, export and backup remain available. Restart with the command above.

A self-contained bundle includes exact content bytes, all referenced artifact
nodes, immutable matcher snapshots, raw captures, fee inputs/registries, full
calculation audits, receipts, metadata, scope, coverage and session state. Replay
uses the installed versioned project engines and never reads the original capture
paths or current JSON stores. This is a data bundle, not an embedded Python runtime.

To restore into a separate disposable project database:

```sh
scripts/project-postgres start
createdb -h "$PWD/.local/pgsocket" -p 55432 -U prediction_arb prediction_arb_restore_demo
.venv/bin/python -m app.storage --database prediction_arb_restore_demo migrate
.venv/bin/python -m app.storage --database prediction_arb_restore_demo import evidence/slice-12/replay-bundle.json
.venv/bin/python -m app.storage --database prediction_arb_restore_demo replay
# Explicit disposal of this demonstration database only:
dropdb -h "$PWD/.local/pgsocket" -p 55432 -U prediction_arb prediction_arb_restore_demo
scripts/project-postgres stop
```

Bundle import requires an empty migrated destination and matching migration
checksums. Hash verification, relational constraints and arithmetic replay all
occur inside one transaction; failure rolls back the import. A PostgreSQL custom
backup is also included as `evidence/slice-12/project-postgres.dump` and was restored
with `pg_restore --exit-on-error` into another disposable project database.

## Storage and precision

Three checksum-checked migrations create explicit session, receipt, quote,
metadata-version, calculation, calculation-receipt, candidate-observation,
coverage-event and content-artifact relationships. Market/time, engine/time,
candidate-history and coverage indexes serve the actual queries. Migration
application is transactional and serialized with an advisory lock.

Raw payloads are BYTEA with SHA-256 identities. This preserves the exact bytes
supplied to storage; separately imported original capture files preserve their
exact file bytes. Existing adapters may already have decoded transport bytes into
text; storage cannot recover information lost before the retained capture.
JSONB is used for queryable metadata, never as a substitute for original JSON text.
Large nested audit objects use a tagged content-addressed tree with foreign-keyed
edges, so common embedded catalogs, rule snapshots and fee registries are shared.
The bundle includes both the trees and all exact raw artifacts.

Queryable prices and sizes use unconstrained PostgreSQL NUMERIC. Normalized
artifacts also preserve their original decimal strings, including trailing zeros;
binary float quotes are rejected. Original receipt/source timestamp strings are
retained separately from microsecond timestamp indexes. Submicrosecond receipt
regression is detected from the original timestamp representation. Adapter-derived
source times may already be rounded; the exact retained raw payload remains the
source for its original representation.

Receipts have `(session_id, id)` identities and retain independent provenance even
when their raw hash is identical. A collision with different content raises an
error. Calculation identities bind the full immutable audit and complete receipt
set. Receipt links cannot cross sessions; a missing referenced input rolls back
both calculation and new artifacts. Native event/market snapshots, event/market
mapping revisions, rule profiles and fee registries are immutable metadata
versions. Existing JSON stores are imported as snapshots, never rewritten.

## Capture policy and lifecycle

Default policy: at most **1,000 receipts, 60 seconds, 16 MiB per raw/normalized
image, and 128 MiB of raw receipt input per session**. The documented default
historical importer declares a 300-second processing bound to allow audit
verification. Individual calculation envelopes are bounded to 32 MiB (configurable separately). The preserved historical detector envelope is 17,427,419 bytes before content deduplication. A periodic
snapshot is labeled every 30 observed seconds; all supplied full images are
retained within the finite run, which also retains candidate context between those
markers. There is no automatic deletion or retention job. Disk growth across
separate authorized runs is not capped; the limits apply per finite session.
Only explicitly disposable verification databases/corrupt test files were removed.

`Store.ingest(session, iterable)` pulls a finite iterator of stable receipt IDs and
packets. A packet contains exact raw bytes, venue/event/market IDs, source, receipt
and optional source time strings, explicit environment/evidence class, and a
normalized image. `workflow.packet()` bridges existing detector Observations;
the historical importer also retains normalized native book images. The API is
synchronous with one receipt in flight and a committed write before the next pull.
There is no unbounded queue or silently dropped observation. These processing
bounds are checked between iterator items; this is not a deadline wrapper for a
blocking live network source, and no live stream collector is introduced here.

Every receipt is retained compactly through shared raw/BBO artifacts. BBO changes
include prices, sizes, state, lock/reconstruction/qualification fields and clock
problems; raw source-time representations participate too. Depth-only changes
retain the full image without inventing a BBO change. Collection bounds record a
censored `limit` event. Upstream or persistence failures stop ingestion and record
failure/shutdown when the database is reachable. A database outage writes a local
journal containing only session ID, time, count and error type. No body, secret or
connection string is logged. An unreachable database leaves its session `running`,
which is **incomplete**, never proof of a healthy active collector.

After establishing that the previous collector is stopped, run:

```sh
.venv/bin/python -m app.storage recover SESSION_ID
```

This imports matching local failure journals, records an unknown coverage gap and
marks that session interrupted. A restarted collector creates a new session; it
cannot append to or imply continuity with a closed one. Raw receipt, calculation,
metadata and candidate writes are transactional. Shutdown records are censored.

Structural matching, conditional positive calculations and qualified modeled
opportunities are distinct columns. A standalone depth audit lacks the full
structural matcher decision, so that column is null there; the linked detector
report retains the decision. Unknown inputs and absent candidates never become
observed negative-price results. Complete detector evaluations produce explicit
`not-observed` transitions for disappeared candidates. Full results, assumptions,
exclusion reasons and related liquidity families remain accessible through each
audit reference. Related candidates are never summed as independent profit.

## Replay and duration limits

Supported: exact saved detector calculations through `detector-capture-1` (wrapping
`top-of-book-1`) and existing `depth-1` audit replay. The wrapper retains and loads
the existing validated matcher snapshot formats and fee registry, then invokes the
unchanged detector. Depth uses the existing replay function. New input/result
versions append; supported prior audit versions remain untouched.

Retained full native images can be inspected; acquisition ladders replay saved
depth arithmetic. **This slice does not claim stream-message book reconstruction
or recovery of every exchange event.** It does not infer missing deltas,
subscription lifecycles, disconnect-free history or actual fills. Source clocks,
staleness and historic receipt skew remain part of replay inputs.

Candidate history displays first/last evaluation times and every discrete sample
with coverage/gap records. Its **observed duration is zero seconds for discrete
samples**, with explicit censoring and no proven interval between samples. It does
not report first-to-last wall time as opportunity survival. Continuous survival
statistics require a separately qualified continuous collector and coverage model.

## Verification and handoff

- 321 existing offline tests and all eleven existing examples pass.
- The new real-PostgreSQL storage example passes.
- 26 PostgreSQL integration tests cover fresh/idempotent migrations, exact raw,
  Decimal/timestamps, retries/distinct receipts, scope, rollback/FKs, restart,
  gaps/failure/limits, BBO and clock changes, metadata versions, lifecycle,
  versioned calculation replay and indexed query paths.
- Separate end-to-end verification restores the complete bundle and PostgreSQL
  backup into fresh disposable databases and reruns all 96 saved calculations in each destination (repeated, separately identified verification imports, not independent opportunities).
  A corrupted restore is fully rolled back. An actual database connection
  termination verifies incomplete-session and failure-journal recovery.
- Query evidence includes normal planner choices and forced indexed access paths
  on stored data; it is not a large-volume performance benchmark.
- PLAN.md and 547 preexisting implementation/test/evidence files were checked
  unchanged. Credentials were excluded from reading and hashing.

Exact counts, runtime identity, replay and restore results:
[verification](../evidence/slice-12/verification.json),
[PostgreSQL test log](../evidence/slice-12/integration-tests.txt),
[restore verification](../evidence/slice-12/restore-verification.json),
[candidate history](../evidence/slice-12/candidate-history.json),
[runtime stop/restart verification](../evidence/slice-12/runtime-verification.json),
[preservation](../evidence/slice-12/preservation.json),
[artifact manifest](../evidence/slice-12/manifest.json).

Reproduce with `python -m app.storage migrate`,
`python evidence/slice-12/verify.py`, and
`python evidence/slice-12/verify_restore.py` using the project virtual environment
while the project database is running. The latter explicitly creates and removes
only named disposable project databases and retains its real outage session.

**Next action: Slice 13 — simple live dashboard**, consuming scoped observations,
coverage and calculations while preserving all current qualification boundaries.
No dashboard, unattended scanner, trading, account history, funds, purchases,
outreach, commits, pushes or publishing were performed.
