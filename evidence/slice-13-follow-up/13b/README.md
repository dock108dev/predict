# Slice 13B — capture and shutdown repair; incomplete

**The 250 ms view-refresh gate fails. Do not mark 13B complete or begin 13C/live verification.** The final synthetic candidate preserves the supported capture envelope and meets receipt throughput and measured shutdown bounds. Passing capture accounting is not passing the whole slice, owner acceptance, or production qualification.

## Exact candidate and preservation

The starting candidate matched **161/161 entries** in the frozen 13A manifest. `before.json` preserves those checks and hashes of every existing evidence file and `PLAN.md`. `preservation.json` checks them after this work. The original 13A failures, fixtures, measurements, historical manifests and owner evidence remain unchanged.

Final source-identity file: [final-candidate/source-identity.json](final-candidate/source-identity.json), SHA-256 `c2939e0598cb77bb159a83b4ba6e59b44f8fdbe447e48b4a2347558252a2144f`. It identifies application, tests, integration tests and scripts. Final integration/fault supervisors record the same source identity. The fresh package manifest additionally binds documentation, logs, helper scripts and the updated Desktop tracker.

The frozen fixture SHA-256 remains `54eaf221ebbd0c5eb32c091076468f14c50bef53f094ec74bee648369f74dd26`. Four/sixteen cross-venue pairs, two native sides, four supplied ladder levels and unknown economic inputs are unchanged. The 93–98% baseline calculation share describes that synthetic benchmark; the historical owner-run bottleneck remains unknown.

## Implementation

- Book handling commits both immutable side receipts in one bounded transaction. Full-image normalization is reused within that book. Receipt counts, bytes, observations, books and current receipt bindings roll back together. Detector sequence advances only after the calculation and view commit.
- Receipt capture is separate from full calculation/view refresh. The controller requests refreshes against the original 250 ms target and coalesces intermediate evaluations, while retaining all accepted book observations. Full audits still replay, with every detector input checked against the exact durable receipt's raw hash, receipt timestamp, market and Decimal side quote. Disconnect invalidation and unknown fields remain intact.
- Repeated matcher snapshot file writes/fsyncs are replaced with the identical validated in-memory envelope. Loaders still validate checksums, native evidence and revision history. Store reuses compiled immutable subtrees and cached SQL construction. Its 4 MiB cache accounts for retained Python objects; cached compilation never claims a write committed, so a rollback cannot poison later artifact writes.
- The queue now has **48 item slots and a 1 MiB recursively measured item-byte ceiling**. Forty pending burst books plus eight control/headroom slots determine the item limit. Exhaustion disables acceptance and records item-versus-byte rejection reasons; later rejected offers record acceptance closed. This is additional bounded capacity alongside the capture/calculation repair.
- Depth is limited to one request. Capture backlog or an in-flight capture operation refuses new depth. An accepted depth request has its own tracked task; cancellation of an HTTP await does not cancel its worker. Finalization waits for it, and stopped depth cannot publish a new current result. Database connections and mutable pipeline state remain on one owning worker; no separate compute worker was introduced.
- Stop immediately closes acceptance/current eligibility and preserves the first reason, UTC timestamp and initiator. Later causes are recorded separately. Producer closure precedes completion of accepted-work drain. Drain admission has an 8.5-second budget, with finalization reserved through 10 seconds. Remaining SQL calls use the worker deadline and statement timeouts. Stop is idempotent, finalization runs once, and another scan is refused until shutdown settles.
- Book-to-receipt bindings are durable coverage records in the same transaction as the book. Finalization reads receipts and bindings through a fresh connection. Failures retain committed subsets and sanitized journals. Necessary backend outcomes use complete/interrupted/failed; unavailable finalization leaves the stored running session incomplete, with its journal. Broader saved-session projections, legacy interpretation and UI wording remain 13C.

## Before/after results

The final matrix is 28 independent finite sessions: the unchanged 24-run 13A matrix plus two no-added-delay 40-book repeats at each market limit. [Full measurements and reconciled ledgers](final-candidate/measurements.json), [gate analysis](summary.json), [analysis log](analysis.log).

| Measurement | Two markets/venue | Four markets/venue |
|---|---:|---:|
| Frozen overflow baseline, each repeat | 1 processed, 32 unprocessed, 8 rejected | 1 processed, 32 unprocessed, 8 rejected |
| Repaired in-flight + 40 burst, each repeat | 41 processed, 0 unprocessed, 0 rejected | 41 processed, 0 unprocessed, 0 rejected |
| Durable side receipts in that burst | 82 + 8 bootstrap | 82 + 16 bootstrap |
| Burst offer span, including first handoff | 6.7–6.8 ms | 6.8–8.4 ms |
| No-delay 40-book receipt throughput | 83.8–92.6 books/s | 27.3–33.0 books/s |
| Ordinary full book service in 13A | 85.9–104.4 ms | 240.7–254.9 ms |
| Repaired ordinary receipt-only book service | 4.7–5.4 ms | 4.6–4.7 ms |
| Repaired separate evaluation mean, ordinary repeats | 48.7–49.8 ms | 178.1–178.7 ms |
| Maximum supported-matrix Stop to finalization | 6.82 s | 7.73 s |
| Maximum active view calculation/persistence latency | 83.5 ms | 266.8 ms |
| Maximum interval between active view completions | 309.2 ms | 454.6 ms |

Receipt-only book service is explicitly a changed work boundary, not a claim that the full detector now takes five milliseconds. Receipt throughput includes intervening worker work and is measured from the first book worker start to the last book transaction completion. Instrumentation and database-size guards remain enabled in the principal trials. View latency/age and throughput are separate measurements.

Every supported run has zero rejected and zero explicitly unprocessed items. The smaller 24 burst, ordinary 4/s, 16-book 10/s slow-write case, disconnect/quiet interval and concurrent depth request remain in the matrix. Active depth requests can be refused for capture priority; actual accepted depth during Stop is verified separately in both real-storage fault runs and the cancellation-order test. No useful fully sized depth-search performance is claimed.

**Failed cadence gate:** active completion intervals exceeded 250 ms at both sizes; one four-market evaluation also exceeded 250 ms. The original completion-relative scheduling was repaired to schedule from evaluation start, and repeated work was reduced, but the serial receipt/evaluation worker still misses the target. The gate was not relaxed. The final matrix records 251/290 intermediate evaluations not performed at two/four markets, including bootstrap/drain coalescing; raw observations remain retained. This count describes coalesced update evaluations, not missed profitable opportunities. `refreshes` records input count, coalescing, start, calculation latency, prior-view age and whether collection was still active. Quiet and post-Stop drain gaps are separated from active cadence analysis.

## Memory and failures

[Memory measurement](memory.json) compares retained allocation growth, recursively counted queue objects and serialized size. Forty items serialize to about 49.4 kB (49,430 bytes), recursively account for 255–314 thousand bytes, and add about 49–54 thousand traced retained allocation bytes because ladder objects are shared. Tracemalloc peaks near 0.54 MB include transient measurement/serialization work. Neither metric is RSS. The matrix's queue maximum is 251,151 recursively accounted bytes. The 1 MiB ceiling leaves room above the frozen small-book envelope but makes no large-wire-book guarantee. Byte-limit exhaustion is tested independently of item capacity.

[Final fault matrix](final-faults/measurements.json) contains 18 real-storage scenarios across both market limits: Stop with backlog, Stop during depth, overload, byte exhaustion, receipt exhaustion, raw-storage exhaustion, second-side rollback, terminated writer connection and finalization failure. Independent accounting and expected terminal outcomes pass. A missing final database record is left visibly incomplete; journals preserve the final known ledger.

[Drain-budget exhaustion](drain-budget/measurements.json) adds two beyond-envelope runs: 56 offered, 48 accepted, 8 rejected with 100 ms per side after bootstrap. Two markets committed 36 books and recorded 12 unprocessed; four committed 37 and recorded 11 unprocessed. In-flight rolled-back receipt attempts are distinguished from committed receipts. Finalization settled in 8.52/8.55 seconds. Neither run is represented as clean completion. Journals from these sessions are retained under `journals/`.

## Verification and reproduction

Use fresh output directories. Commands run from `/Users/michaelfuscoletti/Desktop/prediction-arb`:

```sh
.venv/bin/python scripts/capture-benchmark --repair --output evidence/slice-13-follow-up/13b/RERUN-MATRIX
.venv/bin/python scripts/capture-benchmark --faults --output evidence/slice-13-follow-up/13b/RERUN-FAULTS
.venv/bin/python scripts/capture-benchmark --tests --output evidence/slice-13-follow-up/13b/RERUN-TESTS
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evidence/slice-13-follow-up/13b/check_drain_budget.py evidence/slice-13-follow-up/13b/RERUN-DRAIN
.venv/bin/python evidence/slice-13-follow-up/13b/check_examples.py evidence/slice-13-follow-up/13b/RERUN-EXAMPLES
.venv/bin/python evidence/slice-13-follow-up/13b/measure_memory.py
.venv/bin/python evidence/slice-13-follow-up/13b/analyze.py
node --check app/dashboard/static/app.js
```

The supervisor creates only its own temporary socket-only PostgreSQL cluster, never calls `project-postgres`, and removes the cluster in `finally`. Each benchmark scenario retains the 128 item, 512 receipt, 60 second collection, 128 MiB raw and 256 MiB disposable-database guard limits. The database guard is checked between bounded worker operations, so one operation can overshoot. Collection time is distinct from drain/replay time. These finite runs are not combined into sustained collection.

**354 offline tests and 38 real PostgreSQL integration tests passed on the final source candidate**, plus all 28 supported ledgers, all 18 fault-accounting/outcome checks and the two additional drain-exhaustion runs. Verification also includes exact replay and receipt-input checks, examples and JavaScript syntax; see `verification.json` and corresponding logs for final counts. Integration/fault tests ran together after the performance matrix; principal performance measurements ran without the full suites competing for CPU.

The first smoke failed on an unsupported finalization event type; `smoke1/` preserves that failure. `smoke2/` confirms its repair. `matrix1/`, `optimization1/` and `final-matrix/` retain earlier candidates; `final-candidate/` is the authoritative final matrix, adding exact semantic receipt-input checks. Earlier log messages saying accounting passed are not cadence qualification. Source identities distinguish every iteration.

## Remaining boundary and next action

13B is **incomplete**. Repair the measured view-cadence bottleneck before any dependent slice. A further within-13B option is an immutable receipt-bound compute snapshot/worker design, with separately owned connections and measured capture priority; it is not implemented here. Simply enlarging this queue cannot pass the remaining gate.

Once 13B passes, the concrete 13C action is to implement one shared lifecycle/coverage projection for the saved-session picker and details, including the two legacy complete-with-backlog patterns. Do not start that work or live verification from this result. No venue requests, credentials, owner database access, owner-app restart, trading, publishing, commits, pushes, Slice 14 or 13C–13E work occurred. Live reconnection, oversized original payloads, fully sized depth, and non-cooperative/hung native work remain unqualified; cancelling an await is never treated as proof that such work stopped.
