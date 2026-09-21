# D3a mock collector integration — September 16, 2026

**Delivered offline. D2 live validation and full D3 remain incomplete.** The existing `CoverageOwner` and `ContinuousSession` now support an explicitly selected, isolated mock segmented path. Production selection, idle Start, consumed-attempt protection and legacy D2 lifetime limits are unchanged. No beta restart, credential access, external venue request or live collection occurred.

Candidate: `9b2cfe4de38e0a1157ca4f7281449a1a0363c42dd9bcdbccbe59ab8651ccb3ba`. This is SHA-256 of canonical JSON containing 219 source hashes, including the evidence runner; it is not a commit. All four measured runs match that identity. [Verification](../evidence/d3-mock-integration/verification.json) confirms all 2,269 preexisting evidence files unchanged, including original recovery indexes and the 575-book/1,150-packet evidence. Existing uncommitted work is preserved.

## Integration and lifecycle

`mock_history.py` adapts the existing transport journal contract to D3a. It does not implement another collector. The same discovery, native producers, bounded queue, owner lock, Stop, task join and lifecycle terminal run against explicit numeric-loopback HTTP/WebSocket endpoints. Mock mode rejects credentials, reference feeds, external endpoints and DNS hostnames; redirects are not followed. The measured runner additionally blocks non-loopback connections and credential loading. Native catalogs/books are marked synthetic, with newly generated observation identities and receipt timestamps, not reused historical identities.

Native stream state and catalog dependencies survive rotation. Discovery publishes a durable complete generation before exposing it. Producer reconciliation records its applied generation after metadata/subscription work, while actual usable books remain a separate counter. Tests cover an added market, unchanged subscriptions without reconnect, refresh publication across a seal, and Stop after metadata but before a producer task starts.

Active Stop closes both fixture feeds, joins producers, drains admitted queue work, accounts for rejected cleanup writes, seals the journal and streams exact native replay. Rotation is synchronous: a Stop requested at the seal is pending until the admitted rotation transaction finishes. The overlap fixture therefore publishes generation 2 while producers remain applied to generation 1, explicitly recorded rather than combined into a false denominator. Only a genuine shared-collector terminal can complete the journal. Failed rotation has no fabricated terminal; failed final manifest publication is reported as failed finalization, not successful operator Stop.

## Measured local fixtures

Each scenario ran in a fresh process with supported native Kalshi subscription acknowledgements, snapshots/sequenced deltas and US full-book messages. Refresh was invoked deterministically through the real discovery implementation, not qualified by waiting 60 seconds. The busy case explicitly stopped with both feeds active and usable. These instrumented local results are not venue throughput or duration forecasts.

| Scenario | Durable logical ingress | Physical journal records | Segments | Exact books / packets | Outcome |
|---|---:|---:|---:|---:|---|
| Busy refresh + Stop | 2,301 | 2,308 | 3 | 758 / 1,516 | Successful operator Stop |
| Resource exhaustion | 4,092 | 4,101 | 4 | 1,350 / 2,700 | `offline_segment_cap`; intended Stop never issued |
| Stop at rotation | 1,024 | 1,029 | 2 | 333 / 666 | Successful operator Stop; published/applied generations differ honestly |
| Injected rotation failure | 1,023 | 1,025 | 1 sealed prefix | Not finalized | Storage failure; one unresolved write; no terminal |

Logical counts exclude the terminal; physical counts include headers, seals and any genuine terminal. The failed run observed 335 books before interruption, but does not claim completed exact replay. Its accepted count is 1,024, with 1,023 durable and one unresolved. Successful runs have zero unresolved writes and zero pending queue work. Busy/rotation-Stop/resource cases reject 6/6/8 writes respectively; resource rejection includes late cleanup work, not eight additional capacity grants. Queue saturation separately tests a durable-but-not-queued record and reports it explicitly.

| Scenario | Encoded ingress bytes | Expanded ingress bytes | Total output bytes | Peak RSS bytes | Incremental replay traced peak bytes |
|---|---:|---:|---:|---:|---:|
| Busy refresh + Stop | 2,258,966 | 3,805,352 | 2,648,978 | 69,877,760 | 1,319,135 |
| Resource exhaustion | 4,041,875 | 7,002,162 | 4,729,350 | 71,565,312 | 2,148,814 |
| Stop at rotation | 1,002,643 | 1,691,951 | 1,183,240 | 69,189,632 | 969,929 |
| Injected rotation failure | 1,000,815 | 1,687,459 | 1,179,006 | 68,321,280 | Not run |

Busy/resource/rotation-Stop queue peaks are 3 records and 28,678/62,276/28,678 expanded bytes. The separate saturation test reaches 48 records. Successful replay takes 2.942/5.360/1.328 seconds respectively. Replay tracing starts after collection; process RSS is the lifetime high-water mark. Finalization uses sequential two-pass validation and native state, plus bounded identity/generation summaries, without materializing the run.

[Per-scenario results and logs](../evidence/d3-mock-integration/) retain exact record types, source hashes, observation sequence digests, queue work, physical controls, manifests, disk/file hashes and task/feed closure. For example, the resource case has 8 controls, one retained manifest of 1,834 bytes, 5 manifest publications totaling 6,027 write bytes, zero checkpoints, 4,713,272 journal bytes and 14,244 non-history metadata bytes. Total output also includes the retained history manifest/lock. Replaced manifest write traffic is distinct from retained disk bytes. External test logs/results are derived harness evidence, outside each collector output ledger.

## Bounds and validation

D3a POLICY is unchanged: 4,096 logical ingress, four segments, 16 MiB cumulative encoded ingress; per-segment limits 1,024 logical, 4 MiB encoded and 8 MiB expanded; 64 records/64 KiB reserve within those bounds; queue 48 objects/4 MiB expanded; RSS 256 MiB; output 128 MiB and free-disk floor 1 GiB. Rotation before the logical threshold yields at most 1,023 ingress per segment, hence 4,092 in this fixture. Manifests and owner metadata charge the isolated output-root disk budget. Legacy D2 remains 2,048 logical ingress/16 MiB; REST/message/connection budgets do not reset on rotation. No bound was increased.

Focused final results, run as separate fresh-process suites:

- 12 collector integration tests: busy Stop, refresh/rotation, changed subscriptions, Stop during rotation/pending work, exhaustion, queue saturation, startup/rotation/finalization failure, endpoint/redirect isolation and consumed-attempt protection.
- 70 legacy collection/coverage/storage/recovery checks passed.
- 19 segmented-history checks passed, including exact original 575-book/1,150-packet replay, interrupted rotation, corrupt/missing/reordered segments and recovery.
- 45 saved-calculation checks passed with unchanged inputs/results.

**146 selected checks passed; the full suite is not claimed passing.** The two established `ReadOnlySurface` environmental tests remain one failure and one error: saved device 16777234 versus current 16777233. Fresh inspection of all five original recovery sources finds only that signature field differs. Recovery code, indexes and identity checks were not weakened. Separately, an attempted combined saved-math/history process exceeded the unchanged process-peak RSS guard; its failed log is preserved. Those suites pass in fresh processes. Earlier development/debug logs are preserved and superseded by the explicitly named final logs, not presented as additional passing evidence.

Reproduce focused integration with `.venv/bin/python -m unittest tests.test_segmented_collector -q`. The evidence runner uses exclusive scenario output directories; preserve existing runs and choose a new derived directory before rerunning it.

## Remaining constraint and next task

This slice qualifies the mock integration, not daily collection or D2 live refresh/manual Stop. Retained pressure previously bound at 3,572 observations; this smaller synthetic workload binds at 4,092. State, ingress, REST, message, connection and disk allowances are still finite. Outcomes, settlement, backfill and retention remain undelivered.

**One next task:** prepare an explicit finite sustained-capacity policy and offline qualification experiment, using both retained and new fixture measurements to budget cumulative ingress, expanded state, REST/messages/connections, disk and retention against stated duration/coverage objectives. Do not prepare another live pilot until that policy can meet its objectives. No further implementation or live work is authorized by this recommendation.
