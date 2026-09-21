# Kalshi delivery diagnostic — offline implementation and verification

September 19, 2026. Implementation is delivered in an isolated path; ordinary production defaults and validators are unchanged. No live capture is authorized. The [capture plan](upstream-delivery-capture-plan.md) remains the contract.

## Implementation

- `app/collection/delivery_capture.py`: deterministic native KXNFLGAME selection, Start+600-second kickoff margin, fixed selected identity at safety refresh, one connection attempt, native receive-to-coverage records, separate REST references, serial account pacing, lifecycle cleanup, and one-shot ownership. `DiagnosticOwner` reuses the existing owner release and flock convention; its attempt marker lives in the ownership directory, so changing the output path cannot reuse an attempt ID.
- `app/collection/delivery_budget.py`: stricter diagnostic subcaps, shared 40+40+16 request allocation with 44/52 generation ceilings, HTTP/WS pending-body reservations, clock anchors, fsynced records, bounded queue, and output/write guards. The frozen profile is not edited.
- `app/collection/delivery_analysis.py`: incremental native replay and comparison, using the existing Kalshi reconstructor and segmented reader. Raw hashes, native identity, sequence reconstruction and processing lineage determine results. REST cannot establish an authoritatively ordered missed exchange change; controlled fixture truth is separately marked synthetic. Intentional post-Stop rejection is distinct from local software loss.
- `app/collection/delivery_supervisor.py`: separate-process direct Stop at 240 seconds and intake termination at 300 seconds even when the collector loop blocks. A stalled/killed process leaves incomplete history, no fabricated terminal and no success receipt. Finalization has its own 300-second cutoff. The included CLI runs synthetic fixtures only; the native Kalshi transport accepts an injected existing Kalshi credential and does not load keyring or US credentials.
- Existing components reused include catalog exclusions/selection, account pacing rules, `BookReconstructor`, `CaptureQueue`, `SegmentedJournal` / `SegmentedReader`, exact identity spool, and `write_supplement`. There is no calculation/ranking integration or production-factory selection.

Raw native bodies are retained once at the application receive boundary, before parsing. Stage records link receive IDs to parser completion, canonical book emission, admission, durable acknowledgement, queue insertion/drain and primary coverage. Subscription commands, native acknowledgements/SID/sequence, health, expiry, Stop and paired UTC/monotonic anchors are retained. This boundary is not packet arrival; protocol ping/pong visibility remains unavailable. REST observations have their own request/body/parsed records and never touch primary receipt freshness. Strict age >30 seconds is preserved with an independent expiry deadline.

Reference slots are +60 through +285 at 15-second intervals, no overlapping HTTP or catch-up, no reference retry, and early termination on reference failure. Discovery and account calls share the same quota/pacing; 429 stops without retry. References retain failed/partial bodies and request/response intervals. The canonical comparison is the exact native Yes/No top20 bid window; omitted versus empty sides remain distinct. Cached or slow references never become authoritative exchange clocks.

## Identity and verification

Starting HEAD: `edad00dd980cc8535d69a815d1199b82dd0e83cb`. Every file in the retained 230-file repair candidate matched at entry. Existing uncommitted work was preserved.

Final source/test candidate: **`63f5510b768065130bbb6b645dc6b8fc8bb5afb4ee2623d07a63a41a075d654c`**, 237 hashed files. [Candidate](../evidence/upstream-diagnostic-offline-20260919/candidate-qualified.json), [starting identity](../evidence/upstream-diagnostic-offline-20260919/starting-identity.json), [revision record](../evidence/upstream-diagnostic-offline-20260919/candidate-revision.json).

**71 distinct tests pass:** 49 diagnostic checks, 17 applicable expiry/budget/finalization regressions, one retained 575-book replay check, and four independent saved-math checks. The final diagnostic suite took 7.94 seconds and peaked at 72 MiB; separate regression/retained/math processes also passed the 180-second (60-second retained) and 256 MiB limits. The largest of those processes was 173.61 MiB for saved math. External connections/DNS and keyring operations were blocked; only literal loopback fixture connections were allowed. Outputs were temporary or under this new evidence directory. Tests were inspected before execution; historical generators were not run.

Fixtures cover quiet/unchanged primary state without reference freshness restoration; authoritative synthetic missing change and downgrade without ordering; change/revert invisible between samples; exact parser/emission/admission/queue loss boundaries; malformed/slow/failed/partial/skipped/cached/overlapping/incomparable references; empty sides and top20 ordering; clock jumps; subscription/sequence failures; startup deadline; deterministic/no/unknown/near-kickoff selection and failed refresh; shared quotas/pacing/reservations; resource guards; pending Stop; consumed attempts; and secret/external-access rejection.

A separate streamed read-only replay matches the historical **1,885 native +149 stale books /4,068 packets**, all 2,034 original emission/receipt times, and original 112/37 stale counts. [Replay](../evidence/upstream-diagnostic-offline-20260919/historical-replay.json). No inferred timing replaces original timestamps.

The first focused failures are retained: invalid fixture title shape, a post-Stop pacing-skip ordering error, and an indentation error in a new test. Each run stopped, and each bounded repair is recorded before its replacement run. A later audit comparator incorrectly demanded identical process-dependent memory telemetry; deterministic evidence fields matched, and both memory observations were far below the unchanged limit. Its original failure and comparator repair are retained too. No full-suite pass is claimed.

## Two major experiments; no attempt reset

The direct-Stop run used candidate `3601a26697b27172d924552f883b0d7800d027e41ef848182174da196d5ee89f`. Closeout inspection then added a post-Stop ready-receive guard and a regression. The final 49-check focused suite verifies the last revision, including actual HTTP/WS refresh/Stop/finalization, disconnected-HTTP no-retry, and reference ticker/path binding fixtures. **Do not relabel the earlier timed direct run as a full timed run of the final revision.** The second, forced-cutoff run uses the Stop-guard revision `2bb98f5bef358ced807ff1048af46b8d7debc9327e74cf75066149875720eb75`. Final review subsequently disabled aiohttp’s implicit disconnected-GET retry and strengthened analyzer request-path identity validation. These changes passed the complete focused suite; neither timed run is relabelled as the final revision. [Final delta](../evidence/upstream-diagnostic-offline-20260919/candidate-final-delta.json). The two-run envelope is exhausted; no third timed run or automatic retry is implied.

Direct run results:

| Measurement | Result |
|---|---:|
| Intake closed from Start | 240.046677 s |
| Direct Stop send-to-close | 0.010939 s |
| Feed/task cleanup after close | 0.002740 s |
| Native frames / qualifying books | 1,448 / 1,447 |
| Book pipeline accounting | Received = emitted = admitted = durable = queued = drained |
| REST attempts | 4 initial +2 refresh +12 reference =18 |
| Reference slots | 12 attempted, 1 skipped, 3 not reached |
| Collector RSS high-water | 70,254,592 bytes (67 MiB) |
| Matched-cardinality post-warmup RSS growth | 294,912 bytes |
| Retained output, including helper and marker | 8,621,346 bytes |
| Cumulative writes, including helper and marker | 8,659,603 bytes |
| Minimum spare against frozen record/frame/ingress/output ceilings | 79.96% |
| Minimum spare against stricter diagnostic equivalents | 34.34% |

No post-Stop primary coverage admission occurred in that run. Two stale-interval references matched the primary image without restoring freshness. Other timing-overlap samples remained inconclusive. [Direct audit](../evidence/upstream-diagnostic-offline-20260919/direct-audit.json).

The fixture offered 8 native frames/second outside a deliberate quiet interval. Its one-market frame/body totals exceed twice the maximum corresponding one-market totals in the retained historical session (62 frames /18,360 body bytes). This is a bounded workload comparison, not a worst-case single-frame, all-market, future venue traffic, or sustained-capacity guarantee. Resource violations stop instead of dropping authoritative records.

The Stop-guard revision passed the forced-cutoff test: the collector entered the deliberate stall on the +240 Stop command, and the independent supervisor terminated it at **300.019916 seconds** (exit status -15). Ownership released and the consumed attempt marker remained. Its inability to acknowledge direct Stop is the injected failure, not a successful direct Stop. The history is incomplete and no finalization receipt exists. The unfinished suffix, process lifetime memory peak and cumulative writes of the killed process remain unknown. [Run audit](../evidence/upstream-diagnostic-offline-20260919/run-audit-final.json).

The collector receipt preserves its original boundary: report serialization/write/sync are included, receipt creation is excluded from its own timing/RSS measurement, and its fixed 16 KiB is counted once. A separate fixed-size supervisor artifact accounts for itself and the external attempt marker. Successful file writes were also independently observed in the focused real-loopback finalization fixture. OS metadata and network framing overhead are not application payload bytes.

## Preservation and reproduction

[Preservation report](../evidence/upstream-diagnostic-offline-20260919/preservation.json): **3,320 preexisting files /1,864,183,603 bytes unchanged**, including all 2,693 prior evidence files. The original tracked diff remains byte-identical. Preservation hashing consumed 3,728,367,206 input bytes, below 4 GiB. No credentials, external requests, beta restart, attempt reset, data migration, trade, commit, push or publication occurred.

Focused verification (new disposable outputs only):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m tests.run_delivery_checks focused
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m tests.run_delivery_checks regressions
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m tests.run_delivery_checks retained
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m tests.run_delivery_checks math
```

Read-only diagnosis of a completed diagnostic history:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m app.collection.delivery_analysis evidence/upstream-diagnostic-offline-20260919/direct/history
```

Do not rerun the major lifecycle commands under this task's consumed envelope. All original failures, candidates, attempt markers and interrupted history remain retained in `evidence/upstream-diagnostic-offline-20260919/`.

## Conclusion and execution boundary

This implements and verifies the offline diagnostic path. Its useful live question remains sampled native consistency/disagreement and a provable local processing boundary. Ordinary REST cannot prove uninterrupted delivery or a temporally ordered missing exchange change. The stronger missing-change result is restricted to explicitly controlled synthetic evidence.

**Next action belongs to engineering:** review the final deltas and prepare a separately scoped qualification/live handoff, including the explicit launcher/credential/ownership binding below. The consumed timed runs are evidence for their named revisions; any required complete timed qualification of the final revision needs a new bounded offline envelope. No owner authorization is requested here. A future live handoff must explicitly bind the final candidate, Kalshi-only credential injection, shared production ownership and direct Stop to the independent supervisor; the shipped command-line entry point is fixture-only. The existing two-venue live validator remains unchanged and must not be repurposed by changing flags. Any demand for another full timed direct-Stop run on the final revision needs a new bounded offline envelope first; neither a third run nor live access is implied.

US completeness, unsupported Short depth, sustained capacity, D2/full D3 and the separate device-identity findings remain unresolved. The 44 historical pre-Stop losses remain freshness expiry; this synthetic work does not establish why upstream updates stopped or promise higher usable coverage.

**Proposed later owner scope, not authorization:** one Kalshi NFL pregame market, one WS attempt, REST depth20 references every 15 seconds from +60 to +285 (16 maximum; 96 total REST attempts), direct Stop at +240, independent intake cutoff at +300, offline finalization at most 300 seconds, all frozen limits and stricter diagnostic caps. Stop on any reference, eligibility, subscription, sequence, connection, retention, resource or owner-Stop condition. No US, paid feed, reconnect or replacement attempt. The reference’s exchange-time/cache-age limit remains unresolved.

Final focused verification also pins the installed aiohttp retry seam (`_retry_connection=False`); a dependency upgrade must preserve the one-server-request disconnect regression. Reference request path/query are independently checked during replay because the native REST body does not echo its ticker. All new retained artifacts total less than 18 MiB, below the 1 GiB envelope.
