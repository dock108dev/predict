# Offline timed qualification — FAIL before Start

The authorized attempt was not started. Candidate `724bcda648338cfbd8e83be347437b295dd006c3aeebee5f6e18bee29cf47249`, source identity `407a0b5a0398647e2c00f6c7fd59fff3789d722849420b549026c77442b1257c`, and spec `e7427b51b8594af05260cb2e17d2d62f1d07503dc18c3d38584d0261b691002a` match the frozen envelope, including runtime, dependencies, Git identity and profiles. All 255 executable and 244 source/test file hashes match.

Attempt `f72e404a-91e6-4fcf-8159-cfe562727346` remains unused. Its proposed output, ownership directory and private control socket were absent. No serve, Start, fixture, timed audit, live access or approval activation occurred. The user's authorization was received, but the separate executable approval was not created after the required evidence gate failed.

## First failed gate

The handoff requires retained fixture-origin/Start offset and server-observed requests. The frozen Server holds `origin`, `http_calls` and `ws_calls` only in memory; it has no retained per-request ledger and disables access logging. Runtime creates/closes the Server without exporting these fields. Worker finalization exports client-side counts, not server observations, and the qualification auditor does not require either fixture origin or server reconciliation. A run of this exact candidate cannot produce the required retained evidence. Client ledgers cannot substitute for server observations. No source mismatch or run failure is claimed.

Source pointers: `tests/delivery_fixture.py:64-99`, `tests/delivery_launcher_fixture.py:68-79`, `app/collection/delivery_live.py:129-154`, `tests/delivery_launcher_audit.py:qualification`. Requirements: retained pre-update handoff lines 65 and 95.

## Measurements and limitations

No +120 refresh, +240 Stop, cutoff execution, cleanup, finalization, replay or timed resource/headroom measurement exists for this task. The earlier 104 checks remain historical evidence of the identical candidate; they were not rerun. Offline qualification, live readiness and sustained capacity remain unestablished.

The post-stop preservation helper reported 279,724,032 bytes (266.77 MiB) peak RSS after hashing prior evidence with whole-file reads. This separately exceeds the 256 MiB helper ceiling; it is a closeout-helper failure, not collector memory or an eligible Start measurement. The immutable preflight JSON labels it `preflight_rss_bytes`; that field measures this preservation process, not the unstarted launcher. Further preservation verification uses streaming reads. Disk free was 125,571,829,760 bytes against a 1,308,622,848-byte requirement. Original evidence hashing covered 1,874,676,194 bytes; two passes remain below 4 GiB.

## One next action

Owner: authorize a bounded offline repair that retains fixture-origin and bounded server request telemetry, reconciles them in the auditor within existing joint helper/write caps, then refreezes the candidate for review before any timed Start. Use streaming preservation hashing in subsequent qualification preparation. Do not reuse this approval for a changed candidate. No attempt reset, replacement, budget increase or live proposal is implied.
