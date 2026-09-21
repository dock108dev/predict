# Finalization resource telemetry — offline verified

September 19, 2026. Engineering implementation complete within the authorized offline scope. Candidate `9997a04dce4de0d2292e9d25ee1d4d7ff833d326a93e15284bd439b7524a9974` ([source hashes](../evidence/finalization-resources-offline-20260919/candidate.json)).

The isolated supervisor now writes `validation.json` through a dedicated finalization helper, then samples process memory high-water and publishes `finalization-resources.json`. The supplemental report's former “finalization finished” fields are now named `result_prepared_*`; they no longer imply that writing has finished. Final control status includes the receipt and its write-completion elapsed time. Collection, Stop, drain, replay, calculation inputs, production defaults, frozen budgets and consumed-attempt logic are unchanged.

## Measurement boundary

- Finalization duration runs from the collector's `closed_at` (feeds closed and admitted work drained) through supplemental report serialization, file write, file fsync/close and directory fsync. Separate fields report serialization/write duration, elapsed completion from Start, and measurement completion. Report construction and replay are included in the close-to-report interval.
- `post_report_write_process_high_water_bytes` reads `ru_maxrss` after that write. It includes earlier temporary allocations in the same process. It is not current resident memory or a lifetime-through-exit claim.
- Retained output is the sum of regular-file payload sizes under the exact attempt root, including reports, identity chunks and the final manifests. Cumulative application file-write bytes add all replaced history-manifest payloads: `retained + manifest_write_bytes - final_history_manifest_size`. Successful attempt files other than history manifests are created exclusively or appended; rename does not write their payload a second time. These totals are separate from ingress records/bytes and exclude OS metadata, allocation rounding, device write amplification, and artifacts outside the attempt root.
- The receipt is exactly 16,384 bytes, padded with legal JSON whitespace. Both final byte totals include this one fixed-size write. Its own serialization/write is excluded from its RSS/timing boundary, avoiding recursion; the control result separately records receipt completion. The helper checks the actual retained size again after receipt completion. No output writes follow inside this finalization path.
- Existing RSS, output, cumulative-write and 300-second finalization limits remain unchanged. RSS/deadline violations observed after report writing produce a failed receipt and failed control outcome. Write allowance is checked before writing. A write/fsync failure cannot publish a successful receipt; partial evidence remains and exclusive creation prevents overwriting it. The receipt describes successful payload writes, not arbitrary failed/retried low-level I/O.

## Offline verification

**74 distinct checks passed:** 73 checks in the combined affected run (including the first four new checks), then all five final focused checks after adding fsync-failure coverage and strengthening independent lifecycle write accounting. Application code was unchanged between those runs. No assertions were weakened. [Regression log](../evidence/finalization-resources-offline-20260919/regression.log), [final focused log](../evidence/finalization-resources-offline-20260919/focused-final.log).

Commands from the repository, using its existing environment:

```sh
.venv/bin/python -m unittest tests.test_finalization_resources tests.test_supervised_live tests.test_supervised tests.test_supervised_pacing tests.test_segmented_collector tests.test_segmented tests.test_continuous tests.test_d2_repair tests.test_journal_efficiency -v
.venv/bin/python -m unittest tests.test_finalization_resources -v
```

The focused checks use temporary output only. They independently intercept successful file writes and compare them with telemetry, both for rotated synthetic history plus the read-only saved 2,168,203-byte report payload and for the complete synthetic collector lifecycle. They verify that the RSS sample occurs after the report is readable, replaced manifests are counted, the receipt includes its own bytes once, deadline/RSS failures remain failures, write caps prevent output, and fsync failure leaves no successful receipt. The lifecycle covers generation refresh, direct Control Stop, drain, closed streams/tasks, exact sequence/book replay, ownership release and consumed-attempt rejection. Existing gates additionally cover pacing/cancellation/cutoff, rotation/fault handling, original 575-book replay and saved calculation equality.

A separate fresh-process measurement on the final candidate used the same saved report payload with new tiny synthetic history. [Measurement and independent file/write inventory](../evidence/finalization-resources-offline-20260919/measurement.json); [measurement script](../evidence/finalization-resources-offline-20260919/measure.py) (run from the repository with `PYTHONPATH=.` and the project Python; writes only temporary output and `/tmp/predict-finalization-audit/measurement.json`).

| Final offline measurement | Result |
|---|---:|
| Supplemental report payload | 2,168,203 bytes |
| Final retained output, including receipt | 2,192,781 bytes |
| Replaced manifest payloads | 8,294 bytes |
| Cumulative successful application writes | 2,201,075 bytes |
| Post-report process high-water | 77,660,160 bytes |
| Supplemental serialization/write | 0.005989 seconds |
| Synthetic closure through report completion | 0.006065 seconds |

These are new offline measurements, not live capacity results. The full lifecycle check also independently reconciles its actual files and writes. `git diff --check` passed. An initial evidence-packaging command used system Python, which lacked `aiohttp`; it failed before writing evidence. Using the existing project environment resolved that tooling error. No required check failed.

## Preservation, limitations and next action

[Preservation verification](../evidence/finalization-resources-offline-20260919/verification.json) confirms all **2,643 preexisting evidence files / 1,851,012,805 bytes** unchanged. Historical session `aa1a5562-5a5f-4b8c-aee2-6f00eaeabe62`, candidate `7f41489d2c52c5331cacbd076d406c3ab0786291a5feebb5c55cf2fff02e9961`, and its original report remain unchanged. Its missing lifetime memory peak cannot be recovered from these new measurements. Existing uncommitted work was preserved; only the isolated supervisor, a new helper, the optional test-fixture profile argument and new checks were changed for this task.

The two established device-identity recovery findings remain separate and were not rerun: `ReadOnlySurface.test_catalog_reopen_no_activation_and_identity_error` (failure) and `test_offline_guarded_reopening` (error), device 16777234 versus 16777233. This is not a full-suite pass claim. No new five-minute sustained run or thirty-minute/daily qualification was performed. US completeness remains unknown, Short depth unsupported, and D2/full D3 incomplete.

**Next action belongs to engineering:** analyze the retained September 16 observations offline to explain the initial-to-pre-Stop usable-coverage decline (Kalshi 64→23, US 32→29), distinguishing freshness expiry from transport or native-book gaps. Preserve the observations and existing freshness rules; document findings before proposing a repair or owner-authorized live check. No owner action is required for that diagnosis. This task performed no live requests, credential access, beta restart, attempt reset, increased limits, migration, trading, commit, push or publication.
