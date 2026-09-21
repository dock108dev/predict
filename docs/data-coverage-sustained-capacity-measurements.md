# Sustained policy — measurements and implementation limit audit

September 16, 2026. **Pre-implementation measurement/audit snapshot.** Immediate delivery is now the [five-minute policy](data-coverage-sustained-capacity-policy.md); thirty-minute qualification is deferred. The earlier 30-minute sensitivity and proposed limits below are historical analysis, not current implementation instructions. Use the frozen five-minute budgets and qualification report for the current candidate. The original measurement task changed documentation and added derived analysis only. No collector tests or new native traffic were run. No applicable `AGENTS.md` was found in the repository or ancestor directories; the active instructions are the user boundary and [current coverage plan](data-coverage-plan.md), with historical decisions preserved.

## New bounded measurement

[Analysis source](../evidence/sustained-policy-20260916/analyze.py) · [machine-readable distributions, input/source hashes and limits](../evidence/sustained-policy-20260916/measurements.json) · [output log](../evidence/sustained-policy-20260916/analysis.log).

Declared before execution: ≤128 MiB input, 20,000 physical rows, 256 MiB RSS, 60 CPU seconds, 120 seconds elapsed, 8 MiB output. Actual: **25,606,361 input bytes, 9,353 physical rows, 1.291 seconds, 57,982,976 bytes peak RSS**. Read one JSONL row at a time; keep bounded scalar size samples, not payload lists. CPU/time/file-size guards plus record/input/RSS checks applied. Source/input SHA-256 checks match after analysis. This verifies the selected input files and Python application sources, not an independent whole-repository evidence audit. Original evidence was only opened read-only. The analysis does not repeat the earlier native/hash-chain qualification.

Original source: `3b9cf13c-0696-4fcb-b643-bdd545d9bbd3`, file SHA-256 `e293f8d2433bfc3c5d8313358a06636ff881cd864a75f5b8dc42066390fde0d4`. Its file is the original **uncompressed** 17,083,545-byte journal. Re-encoding each row in memory reproduces **4,635,301 encoded / 16,770,735 expanded ingress bytes**, without writing a replacement. Thus original file size, proposed encoded ingress and earlier 4,948,000-byte compressed journal are deliberately different measures.

Quantiles are exact nearest-rank quantiles of this finite sample, not confidence bounds:

| Ingress distribution | Real retained | Busy mock |
|---|---:|---:|
| Logical observations | 1,914 | 2,301 |
| Mean encoded bytes/row | 2,421.8 | 981.7 |
| Mean expanded bytes/row | 8,762.1 | 1,653.8 |
| Expanded p50 / p95 / p99 | 1,092 / 25,753 / 57,325 | 692 / 4,143 / 4,143 |
| Maximum expanded / encoded row | 457,631 / 271,249 | 8,403 / 2,699 |
| Mean retained Python bytes/row | 27,750.9 | 6,366.5 |
| Mean expanded derived book row | 19,776.2 | 3,861.2 |
| Largest retained Python row | 758,515 | 32,958 |

Real average encoding is **2.47×**, expanded serialization **5.30×** and Python object size **4.36×** the busy fixture. Real selected-market metadata reaches 57,580 expanded bytes; the catalog publication is 286,951 expanded / 758,515 retained Python bytes. The proposed 1 MiB row ceiling fits this sample but does not guarantee future deeper books or catalog pages fit. The 4 MiB queue holds at most about 43 p95 real book objects (97,366 bytes each), versus the separate 48-object ceiling, before other work. The existing tiny mock queue peak cannot qualify this larger workload.

Python object sums count shared referents independently across rows; they are not simultaneous RSS. The earlier whole-list retained-size result was 53,058,673 bytes; this analysis's sum is 53,115,255 bytes. That difference is expected from sharing/list-accounting conventions, not altered input.

Real rows: 581 frames, 580 health observations, 575 derived books, 96 selected metadata, 74 REST responses, one catalog publication, five commands, one account-budget row and one Start. The earlier classification of 570 repeated same-state health rows remains valid; the policy budgets their retention. Frames: Kalshi 405 (four acks, 64 snapshots, 337 deltas), US 176. Received body bytes: Kalshi REST **488,009**, frames **225,138**; US REST **329,305**, frames **580,457**. Reservations for pending frame reads are additional transient charged allowance; do not mistake them for actual received bytes.

## Traffic sensitivity, not a duration forecast

The first-to-last admitted observation spans 50.703 seconds; reported session collection is 50.904 seconds. But native frames span only **23.180 seconds**. Whole-session averaging (37.60 logical rows/second) amortizes discovery startup and is insufficient to size sustained streams. Observed frame average during that short active window is **25.06/second**, with **97 frames in a rolling second** (calendar-second peak 96). Calendar-second ingress peak is 292. Receipt bursts may include buffering and subscription startup; they do not establish exchange production rate.

Two transparent arithmetic scenarios:

| Scenario, 1,800 seconds | Logical rows | Encoded MiB | Expanded MiB | Frames |
|---|---:|---:|---:|---:|
| Repeat whole-capture average, 1× | 67,681 | 156.31 | 565.55 | 20,545 |
| Repeat whole-capture average, 2× | 135,361 | 312.63 | 1,131.10 | 41,090 |
| Active-stream mix, 1× | 134,985 | 277.17 | 981.44 | 45,117 |
| Active-stream mix, 2× | 269,793 | 553.47 | 1,959.49 | 90,234 |
| Active-stream mix, 4× | 539,408 | 1,106.08 | 3,915.58 | 180,468 |
| Active-stream mix, 8× | 1,078,637 | 2,211.30 | 7,827.75 | 360,936 |

Whole-capture formula: metric × 1,800 / 50.904 × factor. Active formula: fixed startup + (`prediction_frame` + `source_health` + `prediction_book`) metric × 1,800 / 23.1797301769 × factor. Active mix has 1,736 flowing / 178 fixed rows. It conservatively treats some initial health/snapshot activity as recurring but still cannot represent an unseen busy game. **Neither scenario includes extra refresh/reconnect metadata, errors, new markets or larger payloads.** They are sensitivity arithmetic, not additional observations or throughput claims. The JSON contains whole-capture sensitivities; the active calculation is reproducible from its type totals/span using this formula.

At 2× active mix, the proposed logical/frame ceilings use 67.4% / 60.2%; encoded/expanded ceilings use 54.1% / 47.8%. Refresh and churn must fit the remaining qualification margin. Five extra unchanged discovery traversals add 360 REST responses, about 4 MiB of raw response bodies under the stable-payload assumption, plus catalog publications and applied-generation records; this is not zero overhead. At 4×, logical and frame totals already exceed proposal limits, even before that overhead. Larger payloads can instead bind expanded/encoded/disk limits first. No single limiting duration is guaranteed.

The five-minute fallback arithmetic substitutes 300 seconds into the 2× active formula: **45,114 rows, 92.96 MiB encoded, 329.41 MiB expanded and 15,039 frames**, before refresh/churn. Its resource margin is materially larger, but its actual duration remains to be demonstrated.

## Existing measured results and what they do not prove

The [mock integration report](data-coverage-d3-mock-integration-report.md) measured busy/resource/rotation-Stop runs at **2,301 / 4,092 / 1,024 logical rows**, **2,308 / 4,101 / 1,029 physical lines**, exact **758 / 1,350 / 333 books** and twice those packet counts. Peak RSS was **69,877,760 / 71,565,312 / 69,189,632 bytes**; replay traced peaks **1,319,135 / 2,148,814 / 969,929 bytes**, and replay **2.942 / 5.360 / 1.328 seconds**. Total output **2,648,978 / 4,729,350 / 1,183,240 bytes** includes metadata, not just journals. Resource Stop prevented the intended manual Stop. Failed rotation was unfinalized with one unresolved write, not exact completed replay.

New distribution analysis shows the busy mock has only **one selected market per venue** and 2.431 seconds of frame activity. The resource fixture has 22 selected metadata rows and 4.665 seconds of frames. Its 304 rolling frames/second and busy mock's 365 are small-payload local bursts. They cannot qualify 96 real-sized markets or 30 minutes. Historical fixtures need not fit the new proposal's lower protective burst ceiling; their existing default policy remains unchanged.

The [retained D3a replay](data-coverage-d3a-report.md) measured **95,862,784 bytes RSS**, **15,933,251 bytes traced peak**, and **11.350 seconds / 168.7 observations per second** on original payloads. Linear arithmetic at that instrumented replay rate would take about **1,600 seconds for 270,000 rows**, longer than the proposed 600-second finalization ceiling; even the ≤300-second headroom gate requires roughly **900 rows/second**. This is an additional binding uncertainty, not a prediction: tracing, fixture size and implementation costs differ. Measure actual full-volume replay after bounding history; do not silently extend the deadline. The five-minute fallback's roughly 45,000 rows correspond to about 267 seconds at the old instrumented rate, supporting it as the practical smaller target if measured 30-minute qualification fails.

## Hard-coded limits and growth audit

All changes below are **proposals for the named mode only**. Legacy D2, generic adapters, old segment formats, evidence/recovery readers and existing defaults stay compatible. A single validated immutable policy must reach writer, reader, owner, streams and finalizer; do not monkey-patch module globals for qualification.

| Current path / limit | Effect and explicit disposition |
|---|---|
| `coverage_owner.py`: spec/start 180 seconds; coverage JS sends 180, HTML promises 180; server allows only max_games/duration options | Cannot express 1,800 seconds. Add explicit isolated named-policy construction/validation first; keep beta factory/UI unchanged. Later activation is a separate authorization. Existing attempt guard remains. |
| `run_spec.py`: duration ≤300, unknown policy fields rejected, kickoff window branch tests duration ≤300 | Add strict named-policy schema with shared 1,800-second deadline and kickoff validation for that duration. No generic duration widening or weaker Start windows. |
| Both native stream constructors: duration ≤300; Kalshi message ceiling 5,000, US 1,000; run-spec message ceiling 1,000; inherited configuration messages=600/group | All prevent sustained target. Explicit opt-in validated 100,000/group and 150,000 aggregate message allowance, shared deadline; replacement/reconnect never resets aggregate counts. Do not use repeated 300-second streams as a loophole. |
| `TransportSession.emit`: 2,048 logical default / 16 MiB encoded; mock overrides only logical to 4,096 | Named mode must supply both cumulative limits and add expanded/physical/message/rate counters; otherwise the transport still stops after rotation. Legacy 2,048/16 MiB unchanged. |
| `continuous.LIMITS`: 32 MiB ingress label versus actual 16 MiB guard; 100 REST/venue; spec/preflight max100; per-venue `PredictionBudget` 16 MiB; per-producer byte guard | Named policy must replace effective enforcement and exported labels consistently (384 requests, 256 MiB bodies/venue). Existing mismatched labels are not extra allowance. Count in-flight byte reservations and failures. |
| Discovery timer literal 60 seconds; spec cadence60; refresh result/page accumulation bounded only indirectly by requests/frame cap | Named cadence300, six generations, 64 attempts/traversal; explicit resident/catalog bounds. Preserve ten-page/query cap, 5-second timeout, two attempts and Retry-After≤180/deadline. Never claim a truncated query exhausted. |
| `GroupBudget.reserve` literal12 aggregate connection attempts; `Venue.reconcile` forces two/group | Twelve constrains churn/recovery. Named48 aggregate; retain two/group. Existing per-stream/validator max5 connections is not blocking with two/group; do not widen it. |
| Selection100/venue; Kalshi engine20/group; US100/group; concurrency6 label | Target64/32 fits. Retain these bounds, explicitly enforce aggregate simultaneous sockets and unique groups/IDs. A changed sort/group partition can recreate all five groups; 24 replay groups is a churn budget, not 24 concurrent sockets. |
| D2 journal32 MiB/4,096 physical; ordinary stop4,032 or32 MiB−64 KiB; output estimate `3×journal >=120 MiB`; output128 MiB / free floor1 GiB | Do not widen D2. New segmented path bypasses whole-session journal estimates with coherent cumulative journal/output ledger. Keep underlying 32 MiB/4,096 per-file writer/reader safeguards since segments remain smaller. |
| `segmented.POLICY`: 4,096 logical, four segments,16 MiB encoded; segment1,024/4 MiB/8 MiB;64 KiB/64 reserves;128 MiB output | Session caps cannot meet objective. New versioned policy uses proposed cumulative budgets; preserve small segment bounds. Old reader must still accept old manifests. |
| `SegmentedReader`: exact equality to global POLICY; at most eight history files; manifest≤64 KiB; per-file32 MiB,4,096 rows/32 MiB expanded | Explicit versioned policy dispatch, allow at most768 segment files + manifest/lock + one known pending manifest (771), manifest≤1 MiB. Enumerate allowed names; no arbitrary-file bypass. Keep per-file limits. |
| `journal_encoding.MAX_EXPANDED=32 MiB` per row; row/segment expanded checks | Preserve decoder compatibility; named admission's stricter1 MiB row cap and unchanged8 MiB segment apply first. No blanket decoder increase. Add missing cumulative expanded guard. |
| D2 finalizer `RSS +6×max(encoded,expanded)<256 MiB`, whole-run reopen/replay; legacy reader4,096 rows/32 MiB expanded | New mode exclusively uses streaming segmented verification; never route a larger session through legacy materialization. D2 unchanged. |
| RSS256 MiB; queue48/4 MiB; mock output guard repeatedly demands free floor+full128 MiB | Keep hard RAM/queue limits. Add224 MiB soft stop and bounded state; replace new-mode disk calculation with remaining reservation and protected finalization reserve. |
| `GroupedNativeVerifier` group cap24; group engines/previous_books never retired; per-group native histories grow | Keep24 distinct groups; bounded retire-on-departure semantics and64 MiB working cap. Rotation alone frees none of this. |
| `BookReconstructor.frames`, `MarketStream.responses/events/diagnostics`; live/replay gap/diagnostic lists | Grow with frames/errors, including within unchanged groups. Explicit new-mode journal-backed history with bounded samples is required in both live and replay paths. Raw history remains on disk. |
| `ContinuousSession.snapshots`; `Venue.records/ever`; finalizer `ids`, `published`; manifest segments/reader signatures | Grow with seconds, identity count, churn or rotations. Apply policy's ring/union/generation/descriptor/spool bounds; count object bytes. Discovery pages reset per generation, but old/new catalogs coexist during refresh and individual raw metadata can retain page copies. |

The environmental findings remain separate and unrepaired: (1) `test_catalog_reopen_no_activation_and_identity_error` failure; (2) `test_offline_guarded_reopening` error. [Original environmental log](../evidence/d3a-offline/legacy-environment-tests.log) and prior reports attribute both to device 16777234→16777233 with otherwise matching signatures/hashes. They were not rerun in this design task. The separate combined-process RSS failure from mock integration is a resource finding, not a third environmental recovery failure. No full-suite passing claim is made.
