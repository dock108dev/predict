# Kalshi expiry-timer repair — September 19, 2026

Bounded offline engineering repair complete. Quiet Kalshi markets now receive expiry checks independently of sibling traffic. This improves stale-classification timeliness; it does not cure the historical coverage decline or identify why qualifying native updates stopped arriving.

## Exact candidate and scope

Candidate **`ae6765dd2f7d03544f428338318cc6a6b75eee83c3ad9790bdfa087046104ba5`**, 230 hashed source/test files, based on Git HEAD `edad00dd980cc8535d69a815d1199b82dd0e83cb` plus the preserved uncommitted workspace. [Candidate manifest](candidate.json). Previous finalization candidate: `9997a04dce4de0d2292e9d25ee1d4d7ff833d326a93e15284bd439b7524a9974`. This is a source identity, not a commit or a running/live qualification.

The only changed preexisting application/test/document file is `app/adapters/kalshi_stream.py`. New regression file: `tests/test_kalshi_expiry.py`. [Repair-only diff](repair-only.patch) compares against the actual pre-repair file, including its existing uncommitted work; [original status](git-status-before.txt) and [original diff](git-diff-before.patch) are retained.

The stream keeps one receive task across timer wakeups. The wait is bounded by the nearest recent synchronized book's receipt deadline and the existing 0.5-second lifecycle polling ceiling. Every wake checks expiry before consuming a completed frame; simultaneous expiry/receive readiness emits the expired state and then processes that frame exactly once. Timer wakes neither cancel nor replace a pending receive. Stop, cancellation, consumer close and reconnect cleanup cancel and await the receive before disposing of the connection. Transport-raised timeouts retain their previous continue-without-reconnect behavior.

The threshold remains configured at 30 seconds for the retained collector. Strict `age > stale_seconds` remains unchanged: equality stays recent, with a positive one-microsecond wait to the next representable receipt age. Only a valid native receipt refreshes its market. Unchanged snapshots and zero-delta images still qualify; sibling/control traffic does not. Stale books retain their native receipt/image and emit once per expiry episode. Snapshot/delta reconstruction, subscription sequencing, source-time semantics, connection/message/ingress/output budgets and defaults are unchanged.

## Verification

**212 affected offline checks passed in 66.947 seconds on the final candidate.** [Final log](affected-final.log), [check inventory](checks.json). The initial 211-check pass preceded an added transport-timeout/unchanged-snapshot regression; the full affected selection was rerun after that compatibility edit. No full-suite pass claim.

- Seven new actual-loop tests cover the busy-sibling defect, real event-loop timer operation under continuous sibling traffic, controlled 29.999999/30/30.000001-second boundaries, recovery by changed delta/zero delta/unchanged snapshot, one stale emission per episode, control traffic, simultaneous readiness, pending-receive identity/frame delivery, no concurrent receives, bounded positive waits, Stop and cancellation cleanup. The real-clock fixture uses a small test-only threshold; the exact controlled boundary tests use 30 seconds.
- The pre-repair actual-loop regression fails because the quiet book stays recent while sibling frames arrive at 31 and 32 seconds. [Expected failing evidence](regression-before.log). This new check ran before the implementation; the immutable diagnosis characterization was read, never rerun or modified.
- Existing Kalshi tests cover sequence-gap recovery, timed reconnect, snapshot timeout, finite failed connects, pending-receive cancellation and early consumer close. US stream tests, continuous collection, D2 repair, segmented collection, supervised controls/pacing and finalization lifecycle checks cover refresh, direct Stop, drain, task/stream closure, exact replay, resource limits and consumed-attempt rejection with isolated temporary outputs.
- Saved rational-oracle calculation reconciliation, fees, depth and arbitrage checks pass. No calculation implementation changed.

**Retained native/packet replay is exact:** 6,218 rows, seven verified segment hashes, 1,885 native books plus 149 derived stale books, 4,068 packets, no replay gaps. Every one of the 2,034 historical book emission/receipt timestamps matches the diagnosis; the 112 Kalshi/37 US stale counts remain unchanged. [Replay result](retained-replay.json), [final replay log](retained-replay-final.log). Replay uses recorded observations, never substituted nominal-deadline timestamps. Existing checks also verify the earlier 575-native-book retained history.

The test runner blocks external socket connections and keyring reads/writes. Loopback synthetic fixture servers are allowed. The dedicated retained replay blocks all connections. All collection test output is temporary. No live requests, credential access, beta restart, live rerun, attempt reset, threshold/budget increase, migration, trading, commit, push or publication occurred.

## Preservation

All **2,671 preexisting evidence files / 1,854,921,980 bytes** are unchanged, including the diagnosis scripts/reports and historical session. Of 324 preexisting app/test/doc files, only the authorized adapter file changed. [Preservation verification](verification.json). The initial repair evidence manifest covers 2,623 non-bytecode files; 48 retained bytecode files were verified against their preexisting immutable diagnosis-baseline hashes. Their union equals all evidence outside this new repair directory. Existing uncommitted work in every other file remains byte-identical.

Reports, scripts and logs for this repair live only in this directory, plus the new regression test and Desktop tracker update. [Prior tracker](tracker-before.md) is preserved. Source identity is canonical SHA-256 of the sorted compact JSON file-hash mapping, using the prior candidate's file list plus the new regression file.

## Limits and next action

This is event-loop scheduling, not a hard-real-time guarantee: event-loop stalls, wall-clock adjustments and a paused/backpressured async-generator consumer can still delay observation. The controlled tests demonstrate independence from sibling traffic; no new sustained-capacity qualification or live validation is claimed.

All **44 pre-Stop losses remain explained by recorded receipt-freshness expiry**. Historical emission delay up to 2.343594 seconds remains a historical observation. Upstream delivery behavior and the reason qualifying updates stopped remain unknown. US completeness remains unknown; Short depth remains unsupported; thirty-minute/daily capacity, D2 and full D3 remain incomplete.

The established device-identity recovery findings remain separate and were not rerun: `ReadOnlySurface.test_catalog_reopen_no_activation_and_identity_error` (failure) and `test_offline_guarded_reopening` (error), device 16777234 versus 16777233. This repair makes no claim to resolve them.

**One concrete next action belongs to engineering:** prepare an offline, bounded evidence-capture plan for distinguishing quiet upstream state from delivery loss. Identify an independent time-aligned native state/change reference, correlated raw receive/subscription/health records, exact selection and Stop rules, and unchanged resource budgets. Execution of any new live capture requires separate owner authorization; none is requested or implied by this report.

## Reproduction

Use the existing environment from the repository root; these scripts write only this repair directory or temporary test outputs:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python evidence/kalshi-expiry-repair-20260919/run_checks.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python evidence/kalshi-expiry-repair-20260919/verify_replay.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python evidence/kalshi-expiry-repair-20260919/verify_preservation.py
```

Do not run the historical diagnosis scripts to regenerate evidence against this repaired candidate. Their timer characterization intentionally records the old defect.
