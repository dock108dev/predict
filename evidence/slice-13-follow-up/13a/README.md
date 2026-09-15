# Slice 13A — reproduction and measurement only

This package uses wholly invented, normalized book images with synthetic provenance.
It runs the existing 32-entry Controller queue, consumer, one-thread executor,
Pipeline.book/evaluate/depth, and PostgreSQL Store. It does not repair those paths.
No venue I/O, credential access, owner database connection, app restart or live scan
is part of this tooling. No historical arrival timing is inferred or replayed.

## Reproduce

From `/Users/michaelfuscoletti/Desktop/prediction-arb`, use the existing environment
and installed PostgreSQL binaries:

```sh
.venv/bin/python scripts/capture-benchmark --output evidence/slice-13-follow-up/13a/rerun-NEW-ID
.venv/bin/python scripts/capture-benchmark --smoke --output evidence/slice-13-follow-up/13a/smoke-NEW-ID
.venv/bin/python scripts/capture-benchmark --tests --output evidence/slice-13-follow-up/13a/tests-NEW-ID
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evidence/slice-13-follow-up/13a/analyze.py
```

Use a fresh output directory to preserve evidence. `analyze.py` checks the saved
24-run baseline and rebuilds `summary.json`; it does not contact a database.
The supervisor writes its budget and source hashes **before** launching work.
It creates an isolated temporary project PostgreSQL cluster under `.local/13a-*`,
using its own socket and port 55439, with no TCP listener. It neither invokes nor
changes `scripts/project-postgres`. The cluster is removed in `finally`; the
cleanup record survives. Database integration imports are redirected to that
socket before test discovery. Never call the benchmark module with an owner socket.

The full matrix is 24 sessions: two repeats of ordinary, burst24, overflow40,
slow, and depth at two and four markets per venue, plus two timing-disabled
ordinary repeats at each size. Each session has a 60-second controller deadline,
128-item tooling ceiling, 512-receipt ceiling, 128 MiB raw ceiling, and existing
per-payload/audit bounds. A 256 MiB actual database guard runs after each bounded
worker job; it can overshoot by one bounded job. The whole child has a 900-second
supervisor timeout. Maximum depth calls: one per depth trial. Actual baseline
session time totals about 152 seconds. These are diagnostic budgets, not production
throughput promises. Preliminary smoke trials and verification runs are separately
retained; the 24-session declaration applies to each full-matrix invocation.

## Inputs and units

`baseline/fixtures.json` contains deterministic templates and schedules. Its hash
is saved in `baseline/measurements.json` and `summary.json`. Source dependencies
and the exact benchmark candidate are in `baseline/source-identity.json`. The final
rejection-label-only correction is identified in
`rejection-label-verification/source-identity.json` and explained in the report.
Books cycle through two or four markets per venue; all refer to one invented
matched event, creating four or sixteen cross-venue market pairs. Each book has
two native sides and four levels per supplied ladder. Kalshi asks are derived by
its existing complementary-bid logic; PMUS uses supplied asks. Values remain
Decimal strings. Sizing and fee/settlement qualification remain unknown.

Receipt clocks are assigned at production of each **synthetic** item. This
reproduces input load and ordering, not byte-identical timestamped audits.
`item:NNNN` is a stable producer item identity within its run/session; bootstrap
receipts use `bootstrap:N`. The fixture hash plus session ID disambiguates runs.
The scope shim labels normalization synthetic and converts synthetic books into
the ladder form expected by the existing synthetic depth path. Synthetic metadata
and seed-book bootstrap are fixture setup, not measured live REST discovery.
Production source files and capture semantics are unchanged.

Ordinary input is 16 books at nominal 4 books/s plus one disconnect. Slow/depth
input is 16 books at nominal 10 books/s plus one disconnect. Disconnect adds a
200 ms quiet interval. Burst24 offers 24 books in one event-loop turn. Overflow40
first places a book in flight, then offers 40 in one turn with an explicit 100 ms
receipt delay (two sides). Slow adds 50 ms per receipt. Depth launches one request
concurrently with the remaining input. Producers then have a fixed 3-second quiet
interval before requesting Stop; they do not implement a drain. Actual scheduling
rates and spans are saved, rather than equated with nominal rates.

Wire-message fields are null because this producer injects normalized items, not
wire messages; venue/network requests are known zero. Unknown historical/upstream
counts stay null. Book/control items and retained per-side observation rows are
separate. Raw `committed_receipts` includes bootstrap; `summary.json` splits out
bootstrap and offered book/control counts. A book is two side receipts here, not
one wire message. Queued/rejected inputs have no claimed persisted observations.

## Accounting and timing

The ledger logs IDs, kinds, outcomes and timing only, never input bodies, signed
headers or credentials. Store receipt/calculation/event calls are attempts until
fresh-connection readback confirms their IDs. A returned inner write is not
assumed committed. An unsuccessful item can have a durable subset of receipts;
that subset remains visible and the item stays explicitly unprocessed. The
independent analysis checks every processed book's two receipts, each control
event, one evaluation per processed item, all calculation receipt links, bootstrap
sides, and the accepted/processed/unprocessed equations.

Queue samples cover offers and dequeues; oldest-age maxima additionally include
items still queued at final readback. Serialized byte estimates exclude Python
object overhead and are not RSS or a future memory-limit recommendation. Queue
wait and executor wait are separate. Stage timers are inclusive: do not add
`store.put`, SQL, replay and transaction totals to their parent operation totals.
Timers measure normalization/receipt work, complete evaluation, detector compute,
audit-validation replay, storage methods, SQL calls, transaction scopes,
bootstrap, depth, and diagnostic size-guard overhead. A successful database
readback is the durability evidence; timer outcome `returned` is not.

See [baseline report](baseline-report.md), [13B targets](13b-targets.md),
[reconciled summary](summary.json), [full ledger](baseline/measurements.json),
[verification](verification.json), and [fresh manifest](manifest.json).
