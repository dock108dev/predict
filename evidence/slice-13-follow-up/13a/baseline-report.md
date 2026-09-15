# Slice 13A baseline — complete, defect preserved

The real-storage reproduction and accounting gates pass. The existing pipeline's
full detector evaluation and calculation/view persistence dominate service time
in this synthetic workload. This does **not** establish the precise cause of the
historical owner-review runs. No throughput, shutdown or status repair was made.

## Measured baseline

24 bounded sessions ran on a separate disposable PostgreSQL 14.20 cluster,
Python 3.14.5, arm64 macOS 26.6.2. Fsync, synchronous commit and full-page writes
were enabled; shared buffers were 32 MiB. Actual database size peaked at
50,455,331 bytes, below the 256 MiB guard. Session durations totaled 151.87 seconds.
The fixture SHA-256 is
`54eaf221ebbd0c5eb32c091076468f14c50bef53f094ec74bee648369f74dd26`.
There were two trials per scenario/size, plus two timing-disabled ordinary trials
per size. The exact source, environment, samples and inclusive stage distributions
are retained in `baseline/`, with independent reconciliation in `summary.json`.

| Markets per venue | Scenario | Processed / offered, each repeat | Explicitly unprocessed, each repeat | Mean book service across the two trials | Queue high water |
|---|---|---|---|---|---|
| 2 | Ordinary, 4 books/s nominal + disconnect | 17 / 17 | 0 | 85.9–104.4 ms | 1 |
| 4 | Ordinary, 4 books/s nominal + disconnect | 17 / 17 | 0 | 240.7–254.9 ms | 1 |
| 2 | Burst of 24, then 3-second quiet | 24 / 24 | 0 | 78.2–79.3 ms | 24 |
| 4 | Burst of 24, then 3-second quiet | 12 / 24 | 12 | 251.0–266.5 ms | 24 |
| 2 | In-flight book + burst of 40, 100 ms/receipt delay | 1 / 41 | 32 (8 rejected) | 305.8–315.1 ms | 32 |
| 4 | In-flight book + burst of 40, 100 ms/receipt delay | 1 / 41 | 32 (8 rejected) | 453.3–481.9 ms | 32 |
| 2 | 10 books/s nominal, 50 ms/receipt delay + disconnect | 17 / 17 | 0 | 189.6–193.4 ms | 7 |
| 4 | 10 books/s nominal, 50 ms/receipt delay + disconnect | 14 / 17 | 3 | 356.9–366.2 ms | 11–12 |
| 2 | 10 books/s nominal + concurrent depth + disconnect | 17 / 17 | 0 | 76.9–79.6 ms | 1 |
| 4 | 10 books/s nominal + concurrent depth + disconnect | 17 / 17 | 0 | 225.0–244.0 ms | 9–10 |

Ordinary service capacity from the book timings is roughly 9.6–11.6 books/s at
two markets per venue and 3.9–4.2 at four. These are service-rate estimates, not
sustained loss-free arrival guarantees. Four markets per venue produces sixteen
cross-venue market pairs, versus four at two markets per venue. This deliberately
exercises complete-detector scaling within a single invented event; the owner
universe was different.

For the ordinary trials, sum the non-overlapping worker book and disconnect
service times as the denominator. Complete evaluation takes 93.4% at two markets
and 98.4% at four; receipt normalization/persistence takes 5.6% and 1.3% respectively.
Calculation persistence alone takes about 74% and 80% of that service time.
Nested `Store.put` tree serialization/hash/artifact persistence takes about 54%
and 59%; SQL execution across all stages about 17% and 14%; detector compute about
15% and 14%; validation replay about 15% at either size. These nested shares
**overlap**. They do not separate Python serialization, hashing, SQL transfer,
server execution, and commit wait into independent CPU profiles. The measured
conclusion is repeated full calculation/artifact work, not an unsupported claim
that network I/O or PostgreSQL alone is slow.

Synthetic bootstrap (metadata setup plus 4 or 8 seed books and their evaluations)
takes 0.37–0.38 seconds at two markets and 2.02–2.10 seconds at four in ordinary
trials. No venue discovery latency was measured. Unknown-sizing depth takes
50–54 ms / 109–137 ms, after waiting 77–85 ms / 167–211 ms for the same executor.
Depth is a measurable additional shared-worker cost, but did not itself overflow
this bounded fixture. Profitable fully sized depth-search cost remains unmeasured.

The queue reaches 32 entries and 39,543 **serialized fixture bytes**. This is not
heap memory. Maximum observed oldest queued age across scenarios is 1.83 seconds
at two markets and 3.47 seconds at four, including items still queued at final
readback. The overflow offered span is 4.8–5.6 ms including the first in-flight
handoff; it is an invented accelerated burst, not historical arrival evidence.

## Accounting and expected failures

Each overflow trial accounts for 41 offered = 33 accepted + 8 rejected, and
33 accepted = 1 processed + 32 explicitly unprocessed. The first rejected offer
finds a full queue; seven subsequent fixture offers find acceptance closed. The
processed book has exactly two committed side receipts. Bootstrap contributes
8 receipts at two markets or 16 at four, making 10 or 18 total retained side
observations in each overflow run. Receipt IDs bind every retained observation to
its originating item or separately identified bootstrap book. All calculation
receipt links point to those durable IDs. Wire/upstream counts are not invented.

The known failure assertions pass **because the defect remains present**. Saved
lifecycle still says `complete` despite backlog, as required for this baseline.
The real-database tests also inject a failure on the second side: the first write
returns but the outer transaction rolls back both, and the in-memory receipt
counter remains ahead by one. A separate evaluation failure commits both receipts
before failing the item. Readback distinguishes those cases; neither counter
rollback nor partial-item recovery was repaired.

The first queue smoke run (`smoke4`) left 31 items because an already-waiting
consumer processed one after the overflow stop. It was preserved as a failed
32-entry reproduction gate. The final envelope (`smoke5` and all four matrix
repeats) offers the burst while a book is in flight, with the declared injected
write delay. Earlier smoke logs record fixture-construction validation failures
before successful pipeline reproduction; they are not successful benchmarks.

## Overhead and limits of the evidence

Timing-enabled versus timing-disabled ordinary mean book service differs by
−1.3% at two markets and +9.0% at four. Only two sequential trials per arm were
run, so noise, cache warming and overhead are confounded; do not subtract 9% as
an exact correction. Both arms retain the identity ledger, synthetic scope shims,
SQL wrapper, and size guard. The timing context microbenchmark is about 1.01 µs
per call. The size guard adds about 2.8–3.0 ms per ordinary item outside worker
service. Absolute throughput is an instrumented local baseline, not a pristine
production benchmark or isolated-machine certification.

Saved owner evidence confirms backpressure, 32 queued items, and a contradictory
`complete` lifecycle. Source confirms a 32-entry queue, stop-conditioned consume
loop, per-book whole evaluation, shared depth worker, and finish-state behavior.
Historical arrival timing, exact offered/accepted counts, upstream losses, live
bootstrap cost and owner-run stage timings remain unknown. No owner sessions
were opened or modified in a database. The review JSON's separate synthetic
runtime snapshot is not treated as the reviewed production session.

The fixtures are small, deterministic four-level books with unknown financial
qualification. They do not reproduce original wire sizes, discovery payloads,
resynchronization, large books, or useful sized opportunity search. Disconnect
processing is exercised but not recovery reliability. This is engineering
measurement evidence, not owner acceptance or production readiness.

Recommended 13B repair: first reduce the measured repeated calculation/artifact
work and separate bounded view refresh from retaining observations, then give
capture priority over depth and implement bounded drain/accounting. Queue
capacity changes alone cannot fix the measured 24-item stop loss. Use the fixed
[13B envelope and targets](13b-targets.md), preserving this baseline. **Stop here:
13B, 13C, live verification, always-on collection and profit sorting are unimplemented.**

## Final diagnostic-label correction

After the matrix, review found that the diagnostic rejection label sampled queue
fullness even when acceptance was already closed. The preserved raw baseline
therefore labels all eight rejects `queue_full`. Source behavior still establishes
one overflow-triggering rejection followed by seven acceptance-closed rejections;
all offered/accepted/processed/receipt counts and stage timings are unchanged.
The final tooling checks the pre-offer acceptance state. It changes no controller
policy. Both market-size real-storage reproductions now assert the exact label
sequence; 35 database tests and 24 focused offline/dashboard tests passed after
this correction. The earlier full 345-test suite remains passing evidence before
this isolated label correction.

Baseline measured source identity: `b918fb0a8b49452151819f8a1f7d025d19f8f0a8250108675d7459e6e89781a0`.
Final source identity: `324ad7de79b0873fe09099b3278d58bda4cdc805d9e4131ad98020a4f839397a`,
in `rejection-label-verification/source-identity.json`. Only diagnostic rejection
classification and its offline/database assertions differ between these source
identities. The baseline remains immutable; no performance effect is claimed for
this label-only correction.
