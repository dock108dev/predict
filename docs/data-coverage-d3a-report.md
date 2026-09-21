# D3a — bounded offline segments and incremental exact replay

September 16, 2026. **D3a's offline history foundation is delivered. D2 and full D3 remain incomplete.** No live collection, credentials, venue requests, beta restart, attempt reset, database work, evidence deletion, trading, commit, push or publication occurred.

Candidate: `af3108026381d368f56a3171ae01ff46b42c17c1a99b4d292ab216d50ded44ce`, defined by the 216 source/test/experiment hashes in [verification.json](../evidence/d3a-offline/verification.json). The checkout already contained D2 work; it was preserved. All **2,177 preexisting evidence files** remain byte-identical, including recovery indexes. Legacy transport, continuous collector, recovery implementation and production factory match their pre-D3a hashes.

## Implementation and boundaries

`app/collection/segmented.py` adds `d3a-offline-segments-1` around the existing `ObservationJournal` and lossless row encoding. Raw rows stay unchanged, with no batching, deduplication, regenerated identity/clock or hidden payload sidecars. Segment headers bind run ID, ordinal, segment position and predecessor chain. Seals bind counts and sizes. There are no checkpoints: replay must begin at segment zero and retain the bounded stream engines, selected metadata and last native images. A missing metadata, command or image dependency fails replay.

`NativeVerifier` shares the original parser and quote conversion logic with the legacy API; `GroupedNativeVerifier` incrementally verifies native books, packets and health-derived books. Completed replay verifies the entire segment chain before yielding rows, then streams a second pass. It never creates a whole-run row list. The offline verifier also has a 24-group guard; this is not a promise of unlimited discovery churn.

`OfflineHistoryOwner`, in the existing owner module, accepts retained inputs only, uses `CaptureQueue`, and cancels/joins attached offline tasks, closes both fixture feeds, drains pending work and seals the active segment on Stop. A source terminal and successful cleanup are necessary for completed publication. Resource/manual Stop before the source terminal remains interrupted. Production still selects `CoverageOwner`; no live segmented Start route was added. Collector integration is a separate next slice.

Legacy D2's **2,048 lifetime ingress rows**, byte/resource limits, whole-session finalizer and attempt guard are unchanged. Rotation never replenishes the offline allowance either.

## Explicit finite policy and measured accounting

Per offline run: at most 4,096 logical ingress observations, four segments and 16 MiB encoded ingress. Rotate **before** reaching 1,024 logical rows, 4 MiB encoded bytes or 8 MiB expanded payload per segment, including control payload. Rotation conservatively reserves 64 KiB inside both thresholds; the encoded threshold also includes physical wrappers. Strict row boundaries therefore permit at most 4,092 small ingress rows across four segments. Tests verify the next row is rejected. Terminal/header/seal work retains 64 records/64 KiB headroom inside the existing 4,096-record/32 MiB physical journal ceiling.

The original terminal is separately counted, not a logical ingress observation. Admission/queue totals include that terminal. Manifests, temporary publication files, seals and dependencies count toward physical disk use; cumulative manifest write bytes are separate from currently retained bytes. Checkpoint records/bytes are zero. Guards retain 256 MiB RSS, 48 queued objects/4 MiB expanded retained objects, 128 MiB output reservation and the 1 GiB disk floor. Disk admission reserves the output allowance above that floor.

| Measurement | Original retained capture | Repeated busy pressure fixture |
|---|---:|---:|
| Logical ingress observations | 1,914 | 3,572 |
| Original terminal records | 1 | 0 |
| Segments / segment controls | 3 / 6 | 4 / 8 |
| Physical journal records | 1,921 | 3,580 |
| Encoded ingress bytes | 4,635,301 | 8,738,007 |
| Expanded ingress bytes | 16,770,735 | 31,676,720 |
| Total disk bytes, including current manifest | 4,952,235 | 9,325,736 |
| Manifest publications / cumulative write bytes | 4 / 4,089 | 5 / 5,966 |
| Queue peak objects / expanded bytes | 1 / 758,515 | 1 / 758,515 |
| Rejected / unresolved / pending work | 0 / 0 / 0 | 1 / 0 / 0 |

[Retained write accounting](../evidence/d3a-offline/bounded-retained-write.json) and [pressure accounting](../evidence/d3a-offline/bounded-pressure-write.json) include physical/expanded journal bytes, manifest bytes and write attempts separately. Queue saturation tests additionally reach 48 objects and exercise expanded-byte rejection: a durably written row rejected by the queue remains in the journal and is counted as durable-but-not-queued.

An initial pressure run exposed a 106-byte expanded-payload overrun because rotation omitted control payload. That defect was corrected and a regression added; [earlier derived experiments](../evidence/d3a-offline/superseded-experiments.json) are preserved but superseded. Only the `bounded-*` runs qualify the final candidate.

The corrected two-copy pressure workload **does not fit**: observation 3,573 requires a fifth segment. The implementation stops with `offline_segment_cap`, seals the fourth segment as interrupted and preserves all 3,572 admitted rows. It does not increase any bound. Repetitions retain duplicate source identities and are explicitly labeled pressure, not new market history. They do not predict a live duration or establish sustained capacity.

## Exactness and memory evidence

Source session `3b9cf13c-0696-4fcb-b643-bdd545d9bbd3`, original chain `abb0baea87f750515618b50d3de13fc298431e8239f7d541da98f0836bf1d592`, file SHA-256 `e293f8d2433bfc3c5d8313358a06636ff881cd864a75f5b8dc42066390fde0d4`.

All 1,915 original rows compare exactly and in order, including native frames, repeated health observations, source/receipt timestamps, identity and exact calculation inputs. An explicit boundary at ordinal 174 separates selected metadata from stream commands; automatic rotation splits ongoing traffic. Native replay verifies **400 Kalshi + 175 US books and all 1,150 packets**. Separate segmented reopening verifies saved six-game calculations with a fixed analysis clock; the existing independent 18-candidate/96-scenario baseline also passes unchanged.

Fresh-process measurement includes sequential verification, comparison against a streaming original reader and, for the retained capture, native engines and quote conversion:

| Replay | Peak RSS | Peak traced Python allocation | Time / observations per second |
|---|---:|---:|---:|
| Three-segment retained capture, native verification | 95,862,784 bytes (91.4 MiB) | 15,933,251 bytes | 11.350 s / 168.7 |
| Four-segment pressure, exact row/order verification | 69,451,776 bytes (66.2 MiB) | 3,431,756 bytes | 13.999 s / 255.2 |

[Retained replay](../evidence/d3a-offline/bounded-retained-replay.json) and [pressure replay](../evidence/d3a-offline/bounded-pressure-replay.json) retain per-segment memory samples, sizes and timing. Pressure replay does **not** claim native verification of duplicated sessions. These instrumented local timings are not storage benchmarks or venue-throughput guarantees. Native state remains resident; segmentation bounds row history, not every possible future state dimension.

## Publication, recovery and tests

Order: fsync segment rows and seal → close segment → write/fsync manifest temporary → atomic replace → fsync directory → create/fsync next header and directory. Any failure closes intake; failed writers do not retry publication or append after a failed write. A new session requires a new directory/run ID. Existing sources and indexes are never resumed or rewritten.

Recovery distinguishes published segments from an unpublished physical prefix. It excludes a torn final line, rejects complete corrupt lines, and never promotes an unpublished tail to completed/usable history. A fully visible manifest after a failed final directory sync can verify on reopening, but cannot prove the failed writer acknowledged publication. Indexes bind content plus device/inode/size/times; drift remains a rejection.

The [retained interrupted fixture](../evidence/d3a-offline/retained-interrupted-result.json) preserves 174 published observations plus an unpublished header/126 observations and seven torn bytes. Its separate index reopens exactly. Unpublished-tail inspection is physical-prefix evidence only; importing it into a new qualified history requires separate explicit work.

**Selected validation: 134 pass, two known environmental checks fail; the entire suite is not passing.** Logs: [19 D3a tests](../evidence/d3a-offline/focused-tests.log), [70 collector/storage/recovery regressions](../evidence/d3a-offline/collector-regressions.log), [45 saved-math/dashboard regressions](../evidence/d3a-offline/saved-math-regressions.log). Coverage includes actual process exit at all eight rotation publication boundaries, exception injection, missing/reordered/corrupt segments, unresolved native dependencies, partial write/fsync failure, recovery identity drift, resource stops, pending queue rejection, both-feed/task Stop, terminal/finalization failure, and fresh legacy/compressed recovery with exact native and health-derived books/packets.

The two `ReadOnlySurface` checks still produce **one failure and one error**. [Current drift evidence](../evidence/d3a-offline/legacy-device-drift.json) confirms only device `16777234` → `16777233` differs across the original indexes; other source signatures, hashes and verified-prefix fields match. [Failure log](../evidence/d3a-offline/legacy-environment-tests.log). These confirmed environmental failures are separate from the new D3a checks; no new regression was observed in the selected checks. Python compilation and whitespace validation pass.

## Remaining constraints and one next task

Daily operation remains unqualified. Four segments, cumulative logical/encoded budgets, replay group/state limits, output reservation/disk floor and no retention deletion still stop growth. D2 additionally retains 100 REST-attempt totals per venue, per-group 600-message limits, connection budgets and finite lifetime. Rotation does not reset any of them. Outcomes, settlement, backfill, retention policy and dashboard integration remain incomplete. Live coherent refresh and direct manual Stop on the repaired D2 candidate are separate outstanding control checks, not sustained-capacity qualification. No live-validation proposal is justified by pressure repetition alone.

**Next task:** integrate segmented persistence and incremental finalization into the existing `ContinuousSession` through a mock-only test path, demonstrating discovery refresh and active Stop across rotations while leaving production D2 selection and limits unchanged. This is a recommendation for a separately invoked task. Work stops here after offline D3a delivery.

Follow-on mock integration is now delivered; see [actual integration results and remaining capacity constraints](data-coverage-d3-mock-integration-report.md). The measurements above remain the original D3a foundation evidence.
