# Five-minute supervised profile — implemented, qualification blocked

Current follow-up: [consolidated offline qualification](data-coverage-supervised-5m-qualification-report.md). The failed result below and the intermediate repair failures are preserved historical evidence.

September 16, 2026. **Stopped at the required RSS-headroom failure.** The explicit offline profile `predict-supervised-segmented-5m-v1` is implemented, but five-minute qualification is incomplete. Thirty-minute qualification is deferred. No live-validation handoff is ready.

Exact candidate: **`0955bf09eca73aef73c996a720d9bc22f9fb58ea7c2ed3f9b8490dac4db3291d`**, SHA-256 of canonical JSON containing **222 application/test asset hashes**, not a commit. All three executed cases have this identity and report unchanged sources. [Busy-case evidence and full source map](../evidence/supervised-5m-20260916/active/result.json) · [pre-implementation budgets](../evidence/supervised-5m-20260916/frozen-budgets.md) · [preservation verification](../evidence/supervised-5m-20260916/verification.json).

## Implemented scope

The existing `CoverageOwner`/`ContinuousSession`, native producers, segmented journal and incremental reader now accept the named profile only through explicit isolated mock construction. Its maximum is 300 seconds including discovery, with initial discovery and one scheduled refresh at 120 seconds. Production owner selection, default D2 configuration and consumed-attempt protection are unchanged by selection; the broader legacy regression suites were not run after the stop condition, so full regression qualification is not claimed.

The profile supplies effective transport/message/body/request limits, cumulative logical/physical/encoded/expanded journal guards, bounded segments, output reservation and remaining free-disk reservation. Legacy manifests still use the old policy dispatch. In this mode native frame/response lists retain no redundant raw history; authoritative input remains in the journal. Diagnostic samples and session snapshots are bounded. Replay uses 4,096-UUID sorted disk chunks and exact merge duplicate detection instead of a whole-run UUID set, plus bounded native state and a finalization deadline. Group departure releases native dependencies and rejects subsequent observations requiring them. No logical capacity is restored on rotation.

The frozen budgets derive from twice the retained active mix, including real payload sizes: about 45,114 logical rows, 15,039 frames, 92.96 MiB encoded and 329.41 MiB expanded over 300 seconds before refresh. Limits were not raised after testing. [Current policy](data-coverage-sustained-capacity-policy.md) states all ceilings and reserves.

## Results

**Eight focused tests passed** in two fresh processes: three retained/saved-calculation checks and five new boundary checks. The original 1,914 ingress observations and terminal compare exactly across segment boundaries; all **575 books / 1,150 packets** replay exactly using bounded native history. Saved calculations and fresh old/new-format recovery pass. New checks cover opt-in/default separation, immutable profile constants, duplicate IDs spanning chunks, single-row/logical/encoded/expanded limits, rolling frame/byte limits, cumulative accounting across rotation, diagnostic samples and disk reserve refusal. [Retained log](../evidence/supervised-5m-20260916/retained.log) · [boundary log](../evidence/supervised-5m-20260916/bounds.log).

The major fixture used the retained 32-event-per-venue catalog/native payload shapes, rescheduled synthetic events, fresh observation UUIDs/receipt clocks, all **64 Kalshi and 32 US markets**, and five active sockets. Historical source timestamps remain template values, honestly reported as repeated/missing; these are not current venue observations or source-latency evidence. US independent market-query contradictions remain represented: completeness is `unestablished`, not promoted to complete.

| Busy active-Stop measurement | Result |
|---|---:|
| Direct Stop requested, relative to Start | 240.0257 seconds |
| Request to collector closure/drain | 0.03415 seconds |
| Exact incremental replay/finalization loop | 37.6339 seconds |
| Total case wall time, including finalization | 277.7104 seconds |
| Logical / physical records / segments | 37,698 / 37,779 / 40 |
| Native frames / exact books / exact packets | 12,482 / 12,478 / 24,956 |
| Encoded / expanded ingress bytes | 87,088,927 / 330,858,006 |
| Physical journal / retained total output bytes | 93,271,770 / 93,929,689 |
| Manifest publications / cumulative manifest write bytes | 41 / 300,468 |
| Frame rate across active interval | 52.399/second, exceeding 2× retained mean 50.13/second |
| Flowing encoded / expanded volume versus declared 2× target | 111.65% / 120.00% |
| Queue peak | 4 objects / 562,060 retained bytes |
| REST attempts, Kalshi / US | 68 / 78 |
| Stream groups / connection attempts | 5 / 5; unchanged subscriptions survived refresh |

Generation 2 was published and applied coherently by both venues after the actual scheduled refresh. Immediately before Stop, all 64/32 markets were requested, acknowledged, receiving and usable, with five active fixture sockets. Terminal usable counts correctly become zero after disconnect. `received=37,714`, `accepted=durable=drained=37,698`, `rejected=16` cleanup observations; zero unresolved writes, zero pending queue, zero durable-not-queued. Both feeds/tasks closed, owner lock released, completed journal/replay sequence matched the independent observer, and a second Start was rejected. Rejected cleanup observations are not fabricated retained evidence.

This is actual local elapsed-time evidence with busy traffic, not an accelerated clock and not real exchange performance. It demonstrates the 240-second Stop case, **not** the unexecuted 300-second deadline case.

## Binding failure and remaining gaps

**Peak process RSS was 230,604,800 bytes = 219.92 MiB, exceeding the frozen 192 MiB qualification target by 27.92 MiB.** It remained below the unchanged 256 MiB hard ceiling and 224 MiB intake-stop threshold, but lacked the required measured headroom. The collection high-water mark before replay was already 207,863,808 bytes = 198.23 MiB, so this is not solely a finalization spike.

Measured live retained working state peaked at 13,478,907 bytes; post-70-second sample range was about 2.25 MiB. Replay retained working state was about 14.46 MiB with a small bounded sample range. Those explicit state samples pass their frozen gates, but do not explain all process memory: runtime, allocator behavior, fixture and unmeasured transient allocations are also in RSS. No root cause is claimed without another authorized bounded investigation. The hard RAM ceiling was not weakened and no optimization/retry followed the failure.

Record/byte/output headroom passed: 42.48% logical, 48.09% encoded-ingress, 38.37% expanded-ingress and about 60% output allowance remained. Frame headroom was about 48%. Successful storage/Stop/replay does not override the failed memory gate.

Closeout source inspection also found a **remaining mock REST pacing gap**: inherited `MockREST.get` sleeps only when its `venue` is set, while isolated mock discovery supplies no venue. Thus this case used the correct 68/78 request counts but **does not qualify the declared per-second REST pacing**. This is an implementation gap to resolve on a future candidate, not evidence of a venue allowance; no repair or rerun was made after the stop condition.

The **300-second deadline case and remaining legacy/history fault regression suites were not launched** after this required failure. New-boundary coverage is limited to the checks listed above; connection/group/state/finalization failure paths and unchanged legacy behavior do not receive a new blanket pass. Existing prior tests remain available for the next separately authorized candidate.

## Handoff and preservation

**Disposition: blocked; do not prepare or execute a live pilot.** The concrete next candidate must resolve the RSS-headroom blocker and mock REST pacing gap under the same frozen budgets, then complete the remaining qualification. That follow-up is not executed here. [Updated handoff](data-coverage-sustained-capacity-prompt.md) records this disposition. Five-minute, thirty-minute and daily capacity remain unqualified; D2 live validation and full D3 remain incomplete.

All 2,345 preexisting evidence files were hashed before work and verified unchanged at closeout, including original recovery indexes. New artifacts remain in `evidence/supervised-5m-20260916`. The runner records loopback-only connections and blocked credential loading; no venue request, live collection, beta restart, attempt reset, production selection change, evidence deletion, database migration, trading, commit, push or publishing occurred. No production credential was loaded. The first-stage collector retains its output and never deletes evidence to recover space.

Two established environmental recovery findings remain separate and were **not rerun**:

- `ReadOnlySurface.test_catalog_reopen_no_activation_and_identity_error`: failure, original device 16777234 versus current 16777233.
- `ReadOnlySurface.test_offline_guarded_reopening`: error, same established device drift; original identity checks/indexes preserved.

The historical combined-process RSS failure remains a separate prior resource finding. This task's new RSS-headroom failure is another separately identified result, not a recovery-test failure. No full-suite passing claim is made.

Reproduction entry point is `.venv/bin/python tests/run_supervised_qualification.py MODE`, with `retained`, `bounds`, `active`, `deadline`, `legacy` or `history`. It refuses existing mode directories. A future authorized rerun must use a new run-root/candidate and preserve these files; do not delete outputs to reuse a mode. The retained and bounds cases passed; active returned exit 1 on the headroom gate. This task intentionally stops there.
