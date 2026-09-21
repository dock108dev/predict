# Five-minute offline repair — stopped at a required check

Subsequent authorized continuation: [consolidated offline qualification](data-coverage-supervised-5m-qualification-report.md). The failed results below remain preserved historical evidence.

September 16, 2026. **Not qualified; no live handoff.** Candidate `0abee67ccbfb13287aa2f9e5afb708357a096ef915f44ec038b81ffba264f8bc` covers 225 application/test source files. The complete file hashes and preservation results are in [preservation.json](../evidence/supervised-5m-repair-20260916/preservation.json). Frozen profile budgets, 192 MiB qualification target, 256 MiB hard ceiling and 1 GiB disk floor are unchanged. Five minutes remains the immediate scope; thirty minutes is deferred. D2 live validation and full D3 remain incomplete; US completeness is unknown.

## Changes and root causes

Mock discovery previously omitted `venue` because real venue identity also selected production endpoint validation. That skipped transport pacing. Discovery now supplies a separate pacing identity on the explicit supervised profile, while endpoint validation still requires loopback. The existing REST transport invokes an overridable pacing hook; account cost/refill pacing and the US 0.5-second minimum apply through that hook. Profile pacing and retry waits observe Stop and the shared Start deadline, including initial account discovery. No fixture REST sleeps were added. Production selection, legacy limits and consumed-attempt protection were not changed; their remaining regressions have not passed on this candidate.

Memory diagnosis found a recursive closure in `retained_bytes`: its temporary set of visited object identities survived until cyclic garbage collection. Twelve diagnostic catalog measurements retained 31.9 MiB at that allocation site; GC released approximately 31.9 MiB. The minimal fix clears the scratch set in `finally`, preserving the returned size, shared-object handling and all authoritative state. A focused check verifies exact size and empty scratch sets even with cyclic GC disabled. No observation, identity, clock, native dependency or replay state was removed.

The original fixture server, payload templates and independent observation checker shared the collector process. A separate loopback fixture process is now prepared, with a 128 MiB RSS ceiling, 120 CPU seconds, 660-second lifetime, 256 REST receipts, 24 connections and 2 MiB artifact ceiling. Collector ownership, native adapters, journal and incremental finalization stay in the collector process under the unchanged bounds. The constant-state sequence/count checker and its redundant serialization remain charged to collector RSS; this is conservative, not hidden collector state. Reports include fixture RSS and the sum of both process high-water marks as a conservative total. **This separated setup has not run:** qualification stopped before lifecycle gates.

## Measurements and limits

All runs used fresh processes/new outputs under `evidence/supervised-5m-repair-20260916`; networked runs blocked non-loopback connects and credential loading. The allocation-only probe made no network calls. No budgets were expanded after a result.

| Run | Bound and result |
|---|---|
| Initial allocation probe | 120 s wall/CPU, 256 MiB sampled RSS, 4 MiB artifact limit; 12 calls with cyclic GC deliberately disabled; not a capacity test |
| Phase diagnostic, before memory fix | 20 s requested busy traffic after paced discovery; 120 s wall/CPU; 256 MiB RSS; 32 MiB journal + 4 MiB diagnostics. **Instrumentation overrun preserved:** 259.11 MiB final process peak |
| Initial pacing check | 30 s wall, loopback only; passed both venues' spacing, one HTTP 429 retry, Stop during pacing and deadline during pacing |
| Expanded pacing gate | Existing focused-run ceiling 180 s wall/CPU; **failed**, described below |
| Bounds regression | Existing 180 s focused ceiling; 6 passed in 0.50 s; RSS 66.14 MiB |

The phase diagnostic is deliberately not a representative-capacity result: tracing reduced throughput, only generation 1 ran, and no 240/300-second objective was attempted. It retained 548 frames and exactly replayed 544 books. Closure took 56.84 ms; replay took 11.10 s. These timings do not qualify the required cases.

Collection RSS immediately before the diagnostic snapshot was 168.77 MiB. Taking the allocation snapshot raised the process high-water mark to 254.08 MiB; the final snapshot raised it to 259.09 MiB, and post-GC sampling reached 259.11 MiB. This exceeded the diagnostic's declared 256 MiB ceiling: it is a separate failed diagnostic resource boundary, not evidence that the hard ceiling was increased. No further traced lifecycle experiment was launched.

Allocation attribution from [the phase diagnostic](../evidence/supervised-5m-repair-20260916/cohost-diagnostic/diagnostic.json):

- Accounting scratch identities: 29.3 MiB retained at collection end, 24.1 MiB after replay; the dominant avoidable allocation site.
- Collector discovery graph: 3,752,502 retained bytes; native adapters/current dependencies: 7,240,017. Replay working-state sample: 15,039,146. These graphs overlap; do not add them as independent RSS components.
- Fixture/server graph: 4,137,997 retained bytes, including real-shape templates, connections and request records. Runtime/server allocator overhead is additional.
- Collection traced current/peak: 41,754,103 / 43,098,094 bytes. Finalization traced current/phase peak: 36,897,848 / 53,326,874. After GC, traced current fell to 11,604,139 bytes. Traced allocation bytes are not RSS, and the fixture templates were created before tracing.
- Encoding/decoding and the independent checker allocate transient serialized buffers; the checker retains only digest/scalars, not a run history. End-of-phase snapshots cannot uniquely apportion their transient peaks. That attribution remains incomplete; no claim that all of the original RSS excess is explained.

The original **219.92 MiB failed qualification remains intact**. It measured collector + fixture + checker without tracing. Neither the heavily instrumented diagnostic nor the unexecuted separated setup supersedes that result. The repaired collector has **not** demonstrated 192 MiB headroom.

## Pacing result and exact stop point

[Initial recorded request timestamps](../evidence/supervised-5m-repair-20260916/pacing.json) show Kalshi consecutive intervals 0.7050/0.7059 seconds under a 0.7-second account-cost interval, with 1.7071 seconds across retry. US intervals were 0.5054/0.5056 seconds, with 1.5100 seconds across retry. Stop/deadline during pacing caused no additional requests. This limited pass does not establish retry-backoff cancellation or complete lifecycle pacing.

The expanded [required pacing gate](../evidence/supervised-5m-repair-20260916/pacing/result.json) failed at `test_timing_retry_stop_deadline`, expecting cancellation during retry. **Concrete cause:** its handler uses `req.path.endswith('/retry')`, but the new test requests `/kalshi/cancel-retry`; that route returns HTTP 200. The request completes instead of entering retry backoff. This is a newly introduced test-fixture defect, not a demonstrated collector cancellation regression. The failed candidate and timestamps are preserved. No test correction, limit increase or rerun followed the failure.

The 240-second busy active-Stop gate, 300-second deadline gate, remaining legacy/history regressions, and fresh original 575-book/1,150-packet/saved-calculation replay were **not run** after this stop. The prior exact replay result remains historical evidence, not a pass for this candidate. The new six-check bounds pass covers accounting scratch release, exact identity duplicates, unchanged opt-in/defaults, row/rate/cumulative boundaries, rotation accounting and disk reserve.

## Preservation and next action

All **2,413 preexisting evidence files (1,629,305,855 bytes)** match their before-work hashes, including the failed 219.92 MiB run and original recovery indexes. Before/after hashing read approximately 3.26 GB, below the 4 GiB audit allowance. New evidence is approximately 5.5 MB. No credentials, external venue requests, live collection, beta restart, attempt reset, production activation, database migration, original-evidence edit/deletion, trading, commit, push or publication occurred.

Keep three categories separate: this new pacing-test failure; memory findings (the preserved prior 219.92 MiB qualification failure and new traced diagnostic overrun); and the two established environmental recovery findings, neither rerun or normalized:

- `ReadOnlySurface.test_catalog_reopen_no_activation_and_identity_error`: failure, device 16777234 versus 16777233.
- `ReadOnlySurface.test_offline_guarded_reopening`: error from the same established device drift.

**One concrete next blocker:** correct the retry-cancellation fixture route so it demonstrably returns 429, then rerun that required pacing gate on a fresh candidate. Only after it passes may the prepared busy lifecycle and remaining exactness/regression gates proceed under the frozen bounds. [Bounded continuation prompt](data-coverage-sustained-capacity-prompt.md). No live-validation proposal is ready.
