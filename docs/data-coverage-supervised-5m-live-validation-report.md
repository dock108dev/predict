# Five-minute supervised live validation — one session completed

September 16, 2026. The authorized finite collection, scheduled refresh, direct Stop, drain and exact incremental replay completed. **Collection is inactive; no replacement session ran.** This does not establish thirty-minute/daily capacity, complete D2/full D3, or resolve US completeness. One measurement limitation remains: the reported replay RSS high-water mark precedes serialization of the supplemental validation report; the later process peak was not captured.

Candidate **`7f41489d2c52c5331cacbd076d406c3ab0786291a5feebb5c55cf2fff02e9961`**; session **`aa1a5562-5a5f-4b8c-aee2-6f00eaeabe62`**; profile `predict-supervised-segmented-5m-v1`. [Frozen candidate](../evidence/supervised-5m-live-20260916/candidate.json), [session evidence](../evidence/supervised-5m-live-20260916/attempt/validation.json), [reconciled analysis](../evidence/supervised-5m-live-20260916/analysis.json), [preservation verification](../evidence/supervised-5m-live-20260916/verification.json).

## Entry and offline gates

The starting 225-file candidate exactly matched qualified identity `39017e90b75b0b2ade6fe91ef4bbc9b646c186f87adf8ce470937877976f31b9`. The new `app.collection.supervised_live` command exposes idle `serve`, explicit `start`, `status` and `stop` over an owner-only local Unix socket. It requires a frozen candidate, exclusive new attempt directory, exact established endpoints/credential references and real prediction-only mode. It reuses CoverageOwner, ContinuousSession, segmented persistence and incremental replay. Real sockets reject redirects. Shared ownership and consumed-attempt rejection precede access. Ordinary factories/defaults and beta files remain unchanged; mock validation still rejects real destinations/credentials. No real traffic used mock mode or synthetic provenance.

The frozen policy and every limit remain unchanged. Affected gates passed: **32 entry/bounds/legacy checks, 13 segmented lifecycle/pacing checks, and 20 history/original-replay checks**. [Preflight and exact gate provenance](../evidence/supervised-5m-live-20260916/preflight.json). History checks preceded the final compatibility/control-wrapper corrections; their history/replay dependencies were unchanged. Both affected suites passed on the final candidate. No full-suite claim.

Two diagnosed local failures were retained: a new test used the temporary directory itself as session output, causing its parent to be counted against output reservation; a refactored flag access broke a legacy minimal session stub. Correcting the test directory and restoring optional-attribute access resolved them without weakened assertions or changed budgets. Prior memory/harness failures and the two device-identity recovery findings remain separate historical records.

Before Start: all 11 existing collector locks were available, beta session remained stopped/consumed, free disk was 133,890,859,008 bytes against the 1 GiB floor plus 224 MiB reservation, and the separate control client successfully queried the idle entry. Only established project credentials and read-only Kalshi/Polymarket US access were used.

## Actual coverage and control

| Measurement | Kalshi | Polymarket US |
|---|---:|---:|
| Discovered events / markets, both generations | 32 / 64 | 32 / 32 |
| Selected / requested / acknowledged / ever receiving | 64 / 64 / 64 / 64 | 32 / 32 / 32 / 32 |
| Initially usable | 64 | 32 |
| Usable immediately before Stop | 23 | 29 |
| Usable range in retained final approximately 63-second snapshot window | 15–26 | 28–32 |
| REST attempts / HTTP 200 receipts | 68 / 68 | 78 / 78 |
| Minimum request-start interval | 0.542516 s | 0.564499 s |
| Frames / native books | 559 / 555 | 1,330 / 1,330 |
| Charged REST + frame body bytes | 1,241,006 | 5,031,120 |

The historical 64/32 comparison happened to match current discovery; it was not a target enforced by the entry. Neither generation added, removed or excluded a selected market. Five groups/connections (four Kalshi, one US) survived refresh without reconnect/churn. All 146 REST responses completed; no retry/429 occurred. Verified Kalshi read refill/capacity was 200/600 cost units with default request cost 10; existing conservative pacing remained applied.

Kalshi pagination exhausted for retained events. US independent listings remained contradictory for all 32 retained events, so full completeness is **unestablished**. US has 32 supported Long and 32 unsupported Short sides. Initial usable coverage did not persist: 112 Kalshi and 37 US stale derived book observations were recorded. Native replay reported no sequence gaps, but this does not prove upstream completeness or continuous usable depth. Terminal usable counts correctly became zero.

Times below are relative to the collector's Start monotonic clock `58479.033348125`, including credential startup and discovery. Start action UTC was `20:56:25.725159`; first journal observation was `20:56:25.841648`. Generation-relative wall timestamps are aligned using the recorded Stop UTC/monotonic pair.

- Generation 1 published at **24.583 s**, applied US/Kalshi at **24.726/24.765 s**.
- One refresh began at **120.001 s**; generation 2 published at **154.487 s**, applied at **154.557/154.565 s**.
- Independent supervisor invoked the explicit entry-point Stop at **240.006805 s**. The entry received it at **240.177964 s**, UTC `21:00:25.905415`, and closed intake synchronously. Command startup/IPC accounts for the approximately 171 ms difference. [Direct Stop receipt](../evidence/supervised-5m-live-20260916/direct-stop-response.json).
- Feeds/tasks closed and admitted work drained at **240.266868 s**, **0.087891 s** after the collector Stop request. The independent 300-second safety cutoff was not reached.
- Exact replay took **5.039341 s**. Final result preparation ended at **245.315483 s**, UTC `21:00:31.042951`, **5.048615 s** after closure; supplemental file writing followed. The process then exited successfully. The inherited outcome `seconds=245.189697` includes waiting for collection, not just finalization.

## Resources, replay and accounting

Collection high-water RSS before replay was **108.406 MiB**; measured high-water through replay was **126.016 MiB**. Final supplemental-report serialization was not followed by another RSS sample, so 126.016 MiB is not asserted as the entire process lifetime peak. Observed live/replay retained-state peaks were **12,638,362 / 15,073,386 bytes**; sampled warm live range was 2,297,574 bytes. Queue peak **15 objects / 559,650 bytes**. Rolling-second maxima: **422 rows, 109 frames, 1,141,180 encoded / 5,310,637 expanded bytes**. No resource stop occurred.

Seven segments contain **6,217 logical admissions**, **6,232 physical records**, **14,920,265 encoded / 52,336,725 expanded ingress bytes**, and **15,940,835 physical journal / 52,340,411 expanded physical bytes**. These consume 9.49% logical, 7.87% frame, 8.89% encoded and 9.75% expanded allowances. Final attempt output is **18,252,086 bytes / 224 MiB** (7.77%); finalization headroom was not needed for collection. Manifest traffic was eight writes totaling 17,436 bytes; the final manifest is 3,272 bytes. Reconciling retained files plus replaced history manifests gives **18,266,250 application file-write bytes**, well below 256 MiB; this excludes OS filesystem metadata. Two exact-identity chunks occupy 99,472 bytes. Supplemental analysis/control artifacts are outside the attempt and the overall task remains about 20 MB.

**Received 6,232 = accepted 6,217 + rejected 15; accepted = durable = drained 6,217.** Pending, unresolved and durable-not-queued are zero. The 15 rejections are cleanup observations after intake closure. Physical records equal 6,217 admissions + 14 segment controls + one terminal. Ingress `write_attempted=6,229` includes 12 rotation writes; physical `journal_write_attempted=6,232` additionally includes the initial header, terminal and final seal. These counters have different scopes, not three missing admissions.

The finalizer's output counter **16,083,883** precedes the **2,168,203-byte supplemental validation file**; their sum exactly equals final attempt output. This difference is retained rather than silently normalizing the original counters.

Incremental replay verified session/unique ingress identity, clock order, catalog dependencies, **1,885 exact native books**, **149 derived health books**, and **4,068 packets** across 2,034 book observations. Four additional frames are Kalshi acknowledgements. Sequence digest: `f7664666f749ca2552d101fcfb492c3d3fd518a833cf8946c53243268f08a73f`. Both feeds and every group task finalized, shared ownership released, control socket removed, and a reconstructed owner rejected another Start as consumed.

All **2,589 preexisting evidence files / 1,830,778,050 bytes** are unchanged. The frozen candidate remained identical through closeout. The existing beta retains its prior stopped session. No additional session, restart, increased budget, trading, new feed, paid access, migration, original-evidence modification, commit, push or publishing occurred.

**Next concrete task:** add and offline-verify finalization-wide resource telemetry through the supplemental report write, including post-write RSS and reconciled output/write counters. Preserve this session unchanged; that task authorizes no live rerun. Thirty-minute/daily capacity and remaining D2/D3 work stay unqualified.
