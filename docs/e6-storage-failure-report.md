# E6 storage-failure accounting and controlled shutdown

September 15, 2026, America/New_York. **This bounded local storage-failure slice is implemented and verified.** No live capture, credentials, provider requests, database operations, guard reset, trading, commit, push or publishing occurred. Existing running applications were not restarted or changed.

## Exact candidate and changed files

- HEAD remains `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`, with existing uncommitted work preserved.
- [Candidate manifest](../evidence/e6/storage-failure/candidate.json): `466f3646d7db7dfee2adc3faaa0b988f7167da00c3d5c408d77ff0667cb446ef` (SHA256 of compact sorted JSON mapping implementation paths to file hashes). It also records the full retained app/tests/scripts digest.
- `app/collection/transport_session.py`: unbuffered exact-length writes; write/flush/fsync acknowledgement; first-failure latch; ingress and journal counters; failed startup/terminal handling; supplemental best-effort report.
- `app/collection/prediction_producer.py`: adapter close runs in `finally` even if native stream close raises.
- `app/dashboard/e6_live.py`: idle owner retains errors/counts after failure; no projection of a failed journal; no repeat attempt within the same runtime; finalization stage errors; unbuffered exact JSON writes; manifest remains pending until its write/flush/fsync succeeds.
- Four new test tools: `tests/test_e6_storage_failure.py`, `tests/e6_storage_faults.py`, `tests/e6_storage_fault_worker.py`, `tests/run_e6_storage_faults.py`.
- This report and the Desktop tracker. Accepted static assets and the recovery reader are unchanged.

## Accounting contract

The unit is an **ingress record proposed to the owner**, including control/health/session-start rows. It is not a raw network frame, native book, packet, upstream delivery, or queue dequeue. The separate terminal row is counted only by the `journal_*` counters.

| Counter | Meaning |
|---|---|
| `received` | Calls to owner `emit`, including proposals rejected after storage failure. Suppressed health callbacks that never form a proposal are not counted. |
| `accepted` | Proposals admitted past the closed-intake and ingress-cap checks, before persistence. |
| `write_attempted` | Admitted ingress records for which the journal entered its write operation. One attempt per record; no disk retry. |
| `durably_acknowledged` | Full-length write, flush and file fsync all returned successfully. |
| `rejected` | Proposals refused before a journal attempt; disjoint from accepted records. These proposals were not saved by this owner. This is not a count of lost upstream deliveries. |
| `unresolved` | Accepted minus durably acknowledged. Never relabeled confirmed loss or zero. |
| `queue_pending`, `queue_drained` | Bookkeeping for already-fsynced write-ahead rows. Draining does not acknowledge them again. |
| `journal_write_attempted`, `journal_durably_acknowledged`, `journal_unresolved` | Same write/acknowledgement boundary including the separate terminal row. |
| `confirmed_byte_offset`, `confirmed_chain` | End/hash of the last write/flush/fsync-acknowledged record, never advanced after a failure. |

At the tested checkpoints, `received = accepted + rejected` and `accepted = durably_acknowledged + unresolved`. Legacy `delivered` is acknowledged ingress, and legacy `persisted` is queue-drained ingress; new consumers should use the explicit counters. Successful new terminals include an ingress-accounting snapshot. A failed terminal can leave ingress unresolved = 0 while journal unresolved = 1. A failed export/manifest can leave both = 0 and still make overall finalization fail.

A pre-write ENOSPC injection writes no bytes in the test, but the runtime conservatively retains the accepted failed operation as unresolved: an arbitrary I/O exception alone is not evidence of a durable outcome. Similarly, visible complete bytes after failed fsync are not a successful durability acknowledgement. Total upstream deliveries and lost counts remain null. This contract records file fsync acknowledgements; it does not prove physical-media behavior or establish complete upstream history.

## First failure and finalization

The first storage failure poisons the journal, closes intake, signals Stop, and invalidates both current venue health states. Producer cleanup callbacks cannot append to the poisoned journal or restore current usability. The owner cancels/joins producer tasks, closes native streams/adapters using their existing close bounds, and drains bounded bookkeeping for already-saved records. No terminal record is attempted after an earlier journal failure. Raw unbuffered file closing cannot flush a buffered retry onto the preserved partial tail.

Storage failure wins over ordinary Stop/deadline reasons. Runtime state finishes as `failed`, with no current book projection. A separately tracked terminal acknowledgement distinguishes completed primary writing from successful export/manifest finalization. A failed manifest write or fsync leaves `manifest.pending.json`; it cannot enter the completed saved-session catalog. Partial export/manifest files are retained, not replaced.

`storage-failure.json` is attempted once as a supplemental report. It contains the session, primary path, confirmed offset/hash, counters, error stage and cleanup result. It is explicitly not primary-journal evidence or a recovery index. Its own failure leaves `failure_report = unavailable`; API counts/error remain available. No second file or disk is assumed to work. The read-only recovery path does not trust or import this report. After restart, unpersisted runtime acknowledgements/rejections cannot be reconstructed.

## Injected local failures and observed counts

All processes used newly bound localhost mock HTTP/WebSocket producers and disposable/new output directories. No disk was filled. The harness held queue bookkeeping until Stop so faults occurred with queued work and active producer tasks. It independently counted emission calls and counted complete pre-fault journal rows/bytes, rather than using the counters under test as its expected checkpoint. Each subprocess returned explicit failure exit code **3** and was reaped.

| Fault | Session | Received / accepted / attempted | Acknowledged / rejected / unresolved | Verified ingress / books / packets | Excluded bytes |
|---|---|---:|---:|---:|---:|
| disk_full | `912257f4-d813-4e2b-a51a-fb3a28ec566b` | 24 / 23 / 23 | 22 / 1 / 1 | 22 / 2 / 4 | 0 |
| short | `cd266cee-5fa3-4419-b465-a5534462fa59` | 24 / 23 / 23 | 22 / 1 / 1 | 22 / 2 / 4 | 23 |
| partial | `6bedefe2-c858-42a1-9b73-f296782e0064` | 24 / 23 / 23 | 22 / 1 / 1 | 22 / 2 / 4 | 23 |
| flush | `67b26e16-948c-4c45-ba8e-3f35679f9a73` | 24 / 23 / 23 | 22 / 1 / 1 | 23 / 3 / 6 | 0 |
| fsync | `0e33888d-403c-468f-8aca-0108e7d80640` | 24 / 23 / 23 | 22 / 1 / 1 | 23 / 3 / 6 | 0 |
| terminal | `0721127c-ee2d-43ee-bc0c-6d8ebc59d712` | 46 / 46 / 46 | 46 / 0 / 0 | 46 / 8 / 16 | 0 |
| export | `e41571d9-cf25-47a6-bcad-3836ed998940` | 46 / 46 / 46 | 46 / 0 / 0 | 46 / 8 / 16 | 0 |
| manifest | `dcc61df2-1832-4ac3-a4ad-d0daa21d1f7e` | 46 / 46 / 46 | 46 / 0 / 0 | 46 / 8 / 16 | 0 |
| report | `e7d97198-fe4f-4752-8d79-aa2c88f7dbd3` | 24 / 23 / 23 | 22 / 1 / 1 | 22 / 2 / 4 | 23 |
| race | `6747ca01-822e-4001-8080-cb962ffd4020` | 24 / 23 / 23 | 22 / 1 / 1 | 22 / 2 / 4 | 0 |
| deadline | `2b6839c5-f456-4914-9743-1607a334c397` | 5 / 5 / 5 | 5 / 0 / 0 | 5 / 0 / 0 | 0 |


For the seven record-write failure cases, 22 ingress rows were already acknowledged and queued at the checkpoint; one attempted record became unresolved. Short/partial/report cases retained exactly 23 excluded trailing bytes. Flush/fsync cases exposed a third readable book (23 verified ingress, 6 packets) while **only 22 ingress remained runtime-acknowledged**. The recovery reader validated that extra full record structurally without inventing its fsync receipt.

Terminal failure retained 46 acknowledged ingress and one unresolved terminal attempt. Export/manifest failures retained all 46 ingress plus an acknowledged terminal (47 journal records), but finalization remained failed. The actual deadline case expired during discovery, retained five ingress and no images, and then failed its terminal write. It remained failed rather than successful deadline completion.

The Stop/deadline race case submits both normal stop reasons at the failing persistence boundary; storage failure wins. The separate deadline process exercises the real timed session deadline. Later Stop calls cannot overwrite the failure reason. Existing cancellation and Stop-during-discovery regressions also pass.

Fault-to-joined-shutdown timing was **at most 0.105 seconds** in the ten-case matrix (not a latency/reliability promise); the worker asserted a six-second ceiling and confirmed empty queue/zero queue bytes, closed journal and native connection release. Terminal/export/manifest failures occur after producer closure, so their shorter measurements are not producer close latency. All fixture servers were subsequently closed and processes reaped.

Evidence: [ten-case results](../evidence/e6/storage-failure/faults-final/results.json), [actual deadline response](../evidence/e6/storage-failure/deadline.stdout.json), [raw process outputs and retained files](../evidence/e6/storage-failure/faults-final/), [independent fresh-process replay](../evidence/e6/storage-failure/independent-replay.json).

## Recovery and focused checks

**11 retained fault sessions reopen and replay exactly** through the unchanged strict recovery reader. Each separate index pins source identity, verified offset/hash and excluded bytes. Incomplete capture and complete journal/incomplete finalization remain distinct. No repair, truncation, fabricated completion, retry, automatic import or resume occurs. Corrupted complete records/chains/dependencies continue to fail closed; active/changing source checks remain in force. Structural validation is not proof against every possible tampering method, and verified visible rows are not evidence that every write received an fsync acknowledgement.

Focused verification covered **20 distinct unittest checks** across the retained runs, plus the 11 subprocess fault cases:

- [14 initial focused checks](../evidence/e6/storage-failure/focused-tests.txt): prefix corruption/dependencies/source changes, exact completed 44-book/88-packet and 36-state/72-packet real replay, unchanged real-run guard, idle credential/network isolation, native reconnect/manual Stop, and first storage checks.
- [Seven finalization/transport checks](../evidence/e6/storage-failure/final-tests.txt): six storage tests plus native recovery/manual Stop.
- [Eight final checks](../evidence/e6/storage-failure/last-regressions-corrected.txt): storage tests, cancellation/backoff, and Stop during discovery. Includes all-writes-fail with zero acknowledgements, supplemental-report failure, startup open failure, full but unacknowledged terminal fsync, and full but unacknowledged manifest fsync.
- [Actual loopback API response](../evidence/e6/storage-failure/api-check.json): HTTP 200 after failed fsync, failed state, explicit counts, no usable/live book, consumed test guard and no broken-journal projection. The temporary HTTP server was closed. No browser/owner acceptance checklist or new preview was needed for this API slice.
- [All-writes-fail startup check](../evidence/e6/storage-failure/all-writes-fail.txt): the first journal record and supplemental report both fail, resources close, and the surviving runtime reports exactly one accepted/attempted/unresolved record and zero acknowledgements.
- Syntax compilation passed. No broad performance matrix or 250 ms gate was run.

Intermediate harness failures remain retained: the first fsync injector also matched a reused report file descriptor; it was constrained to the still-open primary file. One regression invocation named the wrong existing test class and was corrected. Neither is offered as a successful product check. The matrix preceded the additive terminal-acknowledgement/ingress-snapshot fields; those final fields are covered by the final focused checks and actual deadline run.

## Preservation, cleanup and reproduction

[Preservation audit](../evidence/e6/storage-failure/preservation.json): **1,736 preexisting files checked**, with only the three intended implementation files changed. All original journals, exports, archived evidence, accepted view assets and the consumed real-run guard remain byte-identical. Existing application processes on 8775, 8778 and 8779 remained running and untouched. All new workers, mock servers and API test resources stopped; retained evidence is file-only.

To reproduce without changing the existing application:

```sh
cd /Users/michaelfuscoletti/Desktop/prediction-arb
.venv/bin/python -m unittest tests.test_e6_storage_failure
.venv/bin/python -m tests.run_e6_storage_faults /tmp/e6-storage-faults-new-directory
```

The matrix destination must not exist. It starts only local mock producers, exits after finite cases, and retains their files and separate recovery indexes. To inspect the retained evidence read-only, use the existing recovery module with the separate catalog in `evidence/e6/storage-failure/faults-final/catalog`; this does not need another capture. The normal existing application was not reloaded onto this engineering candidate.

**Limitations:** local returned-I/O-error injection is not a power-cut, filesystem/controller failure or indefinitely blocked kernel-I/O test. Native close bounds are reused; no general reliability hardening or continuous collection qualification is claimed. Peer-side missing deliveries, exact failure/crash time, fees, settlement, fair price and economic qualification remain unsupported. Engine arithmetic and monetary presentation were unchanged. Engineering evidence does not imply owner acceptance or full E6 completion.

**One concrete next action:** expose the verified storage-failure counts in an isolated market-watch interface using these local fixtures, clearly separating runtime acknowledgements from structurally recovered rows. No new live run is needed. Stop after this storage-failure slice.
