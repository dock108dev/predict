# Five-minute supervised profile — offline qualification complete

September 16, 2026. **All required selected offline gates pass: 59 focused/regression checks and two representative busy wall-clock lifecycle cases.** Profile `predict-supervised-segmented-5m-v1` remains isolated/offline-only. No live collection or production activation occurred. Thirty-minute/daily capacity is unqualified; US completeness is unknown. D2 live validation and full D3 remain incomplete.

## Candidate and changes

Final candidate: `39017e90b75b0b2ade6fe91ef4bbc9b646c186f87adf8ce470937877976f31b9` (225 application/test files). Application-only identity: `f94f5c9b502eca78cc91af3a37f69445a8d3f40ed703d57adf18bb9f90dbf020`. [Complete hashes, gate provenance and preservation audit](../evidence/supervised-5m-complete-20260916/verification.json).

The lifecycle/pacing/bounds/history gates ran on `f5c001e1eee0e50c2b13ab00867857131060851021cd8653a4638f34c8c7c350`. Two subsequent test-file corrections added `profile=None` to three legacy session stubs, matching the real constructor; affected suites were rerun. **Every application file is identical across all gates and the final candidate.** Verification lists each gate's exact identity and these differences; unaffected lifecycle cases were not repeated for stub-only changes.

This continuation changed only test/harness code: the intended retry routes now explicitly return 429, and the pacing check records the completed transport receipt plus entry into the actual backoff branch before issuing Stop. No assertions, traffic objectives or resource limits were weakened. The preceding pacing-identity and immediate accounting-scratch release fixes are now qualified by the busy cases. No further collector optimization was performed.

## Pacing and lifecycle results

[Pacing evidence](../evidence/supervised-5m-complete-20260916/pacing/result.json) confirms both venues received 429 and entered retry handling before Stop. Kalshi's 0.7-second account-cost interval measured 0.7045/0.7049 seconds; retry spacing was 1.7061 seconds. US measured 0.5043/0.5055 seconds; retry spacing was 1.5063 seconds. Stop cancelled backoff in 0.323/0.242 ms respectively, with no additional request. Shared-deadline expiry during pacing and during confirmed retry backoff likewise produced no extra request. Server responses had no artificial pacing sleeps.

| Measurement | Active Stop | Automatic deadline |
|---|---:|---:|
| Start through closure, approximately | 240.15 s | 300.09 s |
| Manual Stop issued | 240.0465 s | None |
| Stop/cutoff to closure and drain | 105.16 ms | 95.71 ms |
| Exact incremental finalization | 35.72 s | 46.79 s |
| Whole experiment wall time | 276.39 s | 347.43 s |
| Logical / physical records | 34,434 / 34,509 | 43,779 / 43,874 |
| Segments | 37 | 47 |
| Frames / exact native books | 11,394 / 11,390 | 14,509 / 14,505 |
| Active traffic interval | 217.29 s | 277.19 s |
| Frames per active second | 52.44 | 52.34 |
| Encoded / expanded payload volume versus 2× retained-active target | 111.80% / 120.10% | 111.56% / 119.87% |
| Kalshi / US REST attempts | 68 / 78 | 68 / 78 |
| Minimum request interval, Kalshi / US | 0.5044 / 0.5038 s | 0.5053 / 0.5024 s |

Both cases used the separate bounded fixture with retained real payload shapes, 64 Kalshi/32 US markets, five stream groups/connections, actual refresh at 120 seconds, and coherent published/applied generations 1 and 2. All 96 markets were initially usable; all remained usable immediately before active Stop. Terminal usable counts correctly become zero after disconnect. Unchanged subscriptions survived refresh. These are local wall-clock lifecycle observations, **not accelerated clocks or real venue throughput evidence**.

In [active](../evidence/supervised-5m-complete-20260916/active/result.json), received 34,449 = admitted 34,434 + rejected 15. In [deadline](../evidence/supervised-5m-complete-20260916/deadline/result.json), received 43,794 = admitted 43,779 + rejected 15. Rejections are cleanup observations. In both, admitted = durable = drained, with zero unresolved writes, pending queue or durable-not-queued records. Every admitted observation passed exact identity/clock validation and incremental native/packet replay; journal sequence digests matched the independent observer. All feeds/tasks closed, locks released and a second Start was rejected. Fixture market frames match native book counts; four additional received frames are subscription acknowledgements.

## Memory and resource headroom

| Memory, MiB | Active Stop | Deadline |
|---|---:|---:|
| Collector/checker collection high-water mark before replay | 96.89 | 94.55 |
| Collector/checker peak including finalization | 113.05 | 109.81 |
| Separate fixture peak | 69.25 | 69.50 |
| Sum of primary-process peaks, conservative upper bound | 182.30 | 179.31 |
| Additional resource-tracker helper, maximum sampled RSS | 17.69 | 17.66 |

Including the sampled helper gives approximately 199.98/196.97 MiB for primary peak sums plus helper overhead. This is not an exact simultaneous lifetime peak: primary figures are high-water marks, helper figures are passive samples. The helper is additional harness overhead, not collector state. The collector includes owner, native adapters, queue, journal, identity checking, replay and the independent digest/serialization checker. No collector-owned allocation moved to the fixture process. No allocation snapshots were repeated.

The 192 MiB collector qualification target has at least **78.95 MiB measured headroom**; the 256 MiB hard ceiling and 224 MiB intake stop remain unchanged. The preserved 219.92 MiB failure measured the previous combined fixture/collector setup. The subsequent 259.11 MiB instrumented diagnostic overrun remains a separate failure. Neither is erased or reclassified. The prior diagnosis attributed avoidable retention to accounting scratch sets; the qualified candidate releases those immediately. Measurement isolation also removes fixture/server allocations from collector RSS, and their cost is reported above.

Peak retained live state was 13,390,267 / 13,386,197 bytes; post-warmup ranges were 2,441,669 / 2,438,564 bytes. Replay state peaked at 15,165,378 bytes in both, with range 183,963. These pass the 48 MiB qualification target and 8 MiB growth limit across rotations. Queue peaks were 16 objects/973,376 bytes and 15/916,558, below 24 objects/2 MiB.

Active encoded/expanded ingress was 79,678,926 / 302,509,756 bytes; deadline was 101,024,540 / 383,748,163. Physical journals were 85,326,883 / 108,205,140 bytes; physical expanded payload was 302,526,509 / 383,769,291. Total outputs were 85,931,356 / 108,964,155 bytes. The longer case retained **33.20% logical, 39.55% frame, 39.78% encoded, 28.52% expanded and 53.61% output allowance**. Expanded bytes provide the narrowest measured margin. Busier real traffic may stop earlier; no duration guarantee follows.

## Regressions, failures and preservation

Selected passes: pacing 1; bounds 6; segmented collector 12; history/crash/owner 17; legacy D2 12; D2 repair 8; original replay/saved calculations 3. The last gate finished in 9.00 seconds at 133.33 MiB RSS. It preserves every original row across segmentation, **575 books/1,150 packets**, fresh recovery checks, and saved calculations including unknown and explicit probability inputs. Tests reuse existing queue, rotation, storage, identity, publication, deadline and cleanup failure coverage. This is not a claim that the entire repository suite passed.

Two new harness failures are retained in `d2/` and `d2-repair/`: two errors and one error respectively, all absent `profile=None` fields in test doubles. Minimal stub corrections passed fresh reruns in `d2-stub-corrected/` and `d2-repair-stub-corrected/`; no application changes or unexplained retries followed. The prior failed pacing fixture and both memory failures remain preserved.

The two established environmental recovery findings were not rerun or normalized: `ReadOnlySurface.test_catalog_reopen_no_activation_and_identity_error` (failure) and `test_offline_guarded_reopening` (error), from device 16777234 versus 16777233. They are separate from harness and memory findings.

All **2,435 preexisting evidence files, 1,634,806,736 bytes**, match before/after streamed hashes. New artifacts are approximately 196 MB, below the 1 GiB envelope. [Declared experiment limits](../evidence/supervised-5m-complete-20260916/experiment-limits.md) remained fixed; all qualification processes used fresh directories, loopback-only network and blocked credential loading. No external requests, live collection, beta restart, attempt reset, production activation, migration, original-evidence mutation, trading, commit, push or publishing occurred.

Next: the [finite live-validation handoff](data-coverage-supervised-5m-live-handoff.md), requiring later explicit authorization. Offline qualification does not activate the profile or complete D2/full D3.
