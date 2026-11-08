# Continuation implementation and verification

November 7 evening continuation; dated implementation chronology. The [current result](result.md) owns the installed measurements and remaining limits. No commit, push, hosted CI or owner acceptance is claimed. Earlier 18:45 browser timing remains historical evidence.

## Implemented since the E01–E07 delivery

- Retire native catalog metadata only beyond the existing 24-hour past-event retention; unknown and future schedules remain. This removed a measured memory-guard failure without deleting account history.
- Batch native lifecycle withdrawals within the already-received bounded reconstruction batch. Withdrawals commit before later prices can publish; older precomputed images cannot revive them. Repeated inactive images no longer create one SQL transaction per frame.
- Build Kalshi books directly from validated ladders, reuse unchanged immutable level values, and transfer the complete compressed image once with a small scheduling hint. Full image/hash and native YES/NO or Long/Short semantics remain intact.
- Coalesce redundant intermediate Kalshi images inside a contiguous 4,096-frame run under the unchanged 1 MiB batch and 32 MiB receive bounds. Every delta is validated in order.
- Eliminate per-frame copying of the whole active/isolated roster. Move full-book publication decoding off the socket loop; retain the existing transaction byte limit and FIFO/fresh work shares.
- Split reconstruction across two bounded owned children per native source. Kalshi children each validate every global SID/sequence/delta and split materialization by stable market hash. US children validate envelopes and own independent full-image market histories. Parent checks agreement and merges original receipt order; Stop joins both children.
- Move the Coverage census into its existing bounded child runner without taking the ordinary publication scheduling lock. This avoids a large census graph and its garbage collection competing directly with socket callbacks.
- Preserve catalog input-transfer ownership through cancellation and prevent submitting to a closed preparation pool.
- Add source-scoped NCAAF aliases for Sam Houston State Bearkats and Jacksonville State Gamecocks, with official identity evidence. Aggregate provider-local IDs remain unchanged.
- Schedule first aggregate delivery using the actual captured receipt watermark, separate from optional finance visits. Reserve enough turn capacity for oldest work, aggregate, Kalshi and US work.
- Remove the legacy kickoff discovery exclusion only when explicit source sporting evidence establishes live state. Active trading or kickoff alone still cannot establish live. Current live quotes still require their own post-start clock and the 15-second ceiling.
- Integrate the prospective November 7 Kalshi public fee review for all 18 configured series and complete override history. Account membership remains unknown. See [fee dependencies](fee-dependencies.md).

## Measurements, with scope

Controlled retained-data replays, not installed throughput claims:

| Change | Before | After | Population |
| --- | --- | --- | --- |
| Split Kalshi reconstruction | 4.43–4.65 s | 2.63–3.08 s | 1,000 retained ladders, 16,384 controlled nonzero deltas, startup excluded; identical output digest |
| Split US reconstruction | 7.89 s | 5.32–6.53 s | 1,000 retained full images replayed eight times, startup excluded; identical output digest |
| Per-frame roster bookkeeping | 8.93–9.30 s | 0.015–0.025 s | 100,000 operations, 7,262 active plus 102 disjoint isolated IDs; excludes transport and reconstruction |

Before the final split-worker/live-discovery restart, the Orlando–Golden State sampled API path showed the 20:00 aggregate receipt at 01:00:18.811313Z, admission at 01:00:20.352813Z, capture at 01:00:46.820858Z and API visibility at 01:00:51.160472Z: **32.349 s receipt-to-API / 26.468 s admission-to-capture**. Separate native observations on that page were **19.189 s Kalshi** and **13.623 s US** receipt-to-API. These were current-price samples, not browser, numeric-fee, continuous-coverage or whole-slate proof. The load/population differs from the earlier 42.166-second NCAAF browser baseline. The 19:45 Knicks sample took approximately 221 seconds during restart/catalog restoration and policy rebuild; it is retained as a failure, not omitted.

Single-worker runtime samples still showed provider overflow, transport loss and queues reaching their bounds. Census isolation and roster bookkeeping alone did not resolve those failures. The next installed check must establish whether split reconstruction drains the actual selected population and whether explicit live events reach normalized rows and the screen.

## Verification and open work

Focused suites passed: 89 tests plus 7 subtests for decode ownership, native scheduling, discovery and matching; 72 tests plus 6 subtests for reconstruction, native controls, US transport, lifecycle and fee integration; 19 reconstruction tests including split output parity, sequence gaps, isolated malformed images and regressed clocks; 26 census process tests; 9 catalog/recovery codec tests. Earlier disposable SQL publication/withdrawal qualification passed 31 tests plus 4 subtests. Counts overlap and are not a unique total. Failed experiment/fixture logs remain under `.local/native-followup/`.

The historical missing fixtures remain explicit verification gaps: `derived-awards-32.json`, the native NYI–TOR `run-spec.json`, and `evidence/slice-4/public-20260912/report.json`. No substitute fixture is asserted to cover them.

Current engineering: verify installed split-worker throughput, exact native/Pinnacle population, supported live source-to-screen behavior and per-game capture under competing work; continue internal fixes as needed. Account-specific fee dependencies and the aggregate 15-minute cadence are separate constraints. No owner review gate has been introduced.

Protected records were rechecked at each restart: original 18 uncertain attempts, 49 credits, digest `a6e691b659621146176ccfa13aa16615263b47a9043f6974059895f72a2b60ea`. Routine active reservations are separate. Both November 7 429 exceptions remain consumed.

## 20:45 continuation (not a closeout)

Installed US documented response debouncing for current-mode initial and changed groups; unchanged source clocks and full-image validation remain binding. Moved discovery page decoding, fingerprints and compact listing encoding off the socket loop after the running owner sample identified synchronous compression. Reconstruction children now load before sending a subscription; this removed the startup ordering defect, but the first installed warm-worker check still overflowed Kalshi. Neither warm startup nor debouncing alone is reported as resolving throughput.

A four-worker replay did not consistently improve on two (2.89/3.42 s versus 2.63/4.00 s); four-worker support was removed. Fast serialization of validated native images preserves existing hashes, exact decimal strings and full retained images. A full-roster controlled 2,048-image profile fell from 1.209 to 0.901 seconds; this is a profiler/replay comparison, not running throughput. The faster path is being integrated.

New focused checks: 35 tests + 4 subtests for subscription commands; 57 traversal/catalog checks; 44 tests + 2 subtests for warm worker startup; 58 tests + 6 subtests for reconstruction/native/US integration. A broader Kalshi run had 49 passes + 4 subtests and four missing-fixture failures: the previously missing public slice-4 report and three checks requiring `evidence/slice-4/recovery-20260912/report.json`. Missing fixtures remain unavailable; logs are retained.

## 21:00 continuation: explicit bounded native coverage

The installed full-roster fast-codec/warmed-worker check still failed: Kalshi selected 7,402 markets and reported provider subscription overflow; US selected 8,240 and lost transport. Those failures remain in `integrated-runtime.jsonl`. Lower measured processing cost alone did not establish a repair.

Current implementation retains complete discovery and catalog membership, but subscribes to at most 2,048 markets per source. Half the slots prioritize nearby games round-robin across league/family/event; half rotate the remainder every 120 seconds. Every deferred member receives a turn for a stable catalog. The first bound is an engineering trial informed by the retained 2,048-image replay, subject to installed queue evidence. Every rotation closes and joins its receive/reconstruction owner, revokes continuity, advances generation and requires fresh images. Deferred coverage is explicitly partial in synchronization, source detail and the source panel. No source clock, freshness ceiling, connection/byte cap or paid schedule changed.

Publication now binds each game component only to the sources actually present in that component. An unrelated source reconnect no longer invalidates its exact incremental capture. Relevant authority, controls and membership remain binding. Optional finance uses the remaining overall turn budget instead of starting another full budget after capture; at least one oldest job advances.

US event discovery uses the documented `startTimeMin` lower bound of 24 hours ago, with no upper future cutoff. The bound remains fixed across incomplete checkpoint recovery and advances only after complete publication. Unknown/absent events keep existing conservative retention semantics. This avoids repeatedly traversing historical listing rows without reducing the agreed future scope. Official source: https://docs.polymarket.us/api-reference/events/get-events.md .

Focused checks: 87 passed + 2 subtests for prioritization, native worker controls, traversal, synchronization and service; 9 final rotation/selection/synchronization checks passed after adding the explicit rotation reason. The exact unrelated-source SQL capture oracle passed (PostgreSQL 14 compatibility, not primary PostgreSQL 16 qualification). Component/publication SQL suite previously passed 29 + 4 subtests. Fixed-window restart and 24-hour retention SQL checks passed 2. Retained failures: missing historical selector/native fixtures and PostgreSQL 14 lacking `pg_stat_force_next_flush()` for the TOAST turnover test. Neither is claimed covered by unrelated passes.

Installed bounded-coverage and per-game timing verification remains active.

First installed cohort check found and repaired a status-contract regression: adding `subscription_coverage` to ordinary source state violated the existing serializer's explicit field set after SQL admission. The extra field was removed; the supported reason text and runtime source-panel metrics preserve visible active/deferred counts. A full CurrentStore projection regression test now exercises prioritized books. First cohort transport itself had 400,704 Kalshi frames with no retries/overflow through the first rotation boundary; this is transport-only evidence, not successful end-to-end publication. The failed installed result remains retained.

The 2,048-market cohort resolved the observed socket backlog over successive generations (both sources zero retries), but derived queues still reached roughly 40 seconds. The next installed bound is **512 active / 30-second rotation**: one quarter the continuous update population with the same 61,440 planned initial images per source/hour as 2,048/120. Planned 120 connections/hour remain under the existing 240 cap; failures and other connections still consume that same cap. No byte/memory, freshness, paid schedule or financial guards increase. The active cohort is smaller and deferred coverage remains explicit. Stable full-roster revisit is approximately 14 minutes for 7,400 markets; individual markets can have observation gaps throughout that period.

Catalog continuity fix: a complete discovery changing only deferred members retains the exact active cohort without sending additional subscriptions. An active member's changed/removed material still takes the existing resynchronization path. The installed failure that motivated this was two changed unselected Kalshi IDs and 34 additions, followed by 89.681 seconds of catalog adoption while the healthy cohort was disconnected. Focused qualification passed 52 tests + 4 subtests, including both sources, unchanged active membership, active material change, cancellation and explicit deferral.

## 21:30–22:00 continuation

The installed cohort is now 512 markets per source with 30-second rotation. Real Kalshi and Polymarket US San Antonio–Portland exact Pinnacle comparisons reached the browser; Kalshi live Brooklyn–Atlanta prices also reached it with calculations separately unavailable. The 21:30 per-game measurement exposed a 119-second admission-to-capture tail. Publication scheduling now overlaps native reservations with first aggregate delivery and tracks reference-only captures. Maintenance no longer holds the publication lock during read-only bloat scans or recovery packing. The [current result](result.md) retains failed trials, exact populations, final installed verification and external fee facts; earlier planned/trial settings above are historical.

## 22:05 US sporting-state integration

A single documented public league-events request supplied current live NBA state, correcting the earlier provider-gap hypothesis. The new small state owner interleaves 20-event pages every 15 seconds across started/imminent leagues through the existing native client and guards. Exact event/game/start binding, monotonic source state, atomic derived withdrawal and original-book reprocessing are separate from full catalog material and native socket generations. The slow catalog merges newer retained state evidence instead of overwriting it. Focused checks passed 76 tests plus 2 subtests; subsequent scope checks passed 31 plus 2 subtests and 5 pure/ownership checks. One disposable SQL test proves atomic withdrawal, exact retained clocks and source-state provenance. Counts overlap. Installed owner 90488 began at approximately 22:05; the current result owns the final source-to-screen check.

The first state-refresh installation exposed a second internal gate: discovery had copied `event_excluded:kickoff_reached` onto market rows, which survived event enrichment. Both full annotation and the lightweight patch now retire exactly that copied refusal for explicitly live games. All other exclusions and source clocks remain binding. The focused regression set passed 49 checks; two disposable SQL checks passed. The initial installed no-US-live result is retained, not reported as provider incapability.

## 22:22 final cohort and 22:25 US live browser proof

After the copied kickoff-gate fix admitted more live markets, the 512 cohort's derived p95 rose to 14.48 seconds (Kalshi) / 12.37 seconds (US), before capture/display. Reduced the explicit cohort to 256 with 20-second rotation: 46,080 planned initial images and 180 planned connections/source/hour, both within existing guards; catalog changes/errors still consume the same connection allowance. All deferred markets remain cataloged and fairly rotated. The final priority/state/scheduling suite passed 14 tests; data owner 25201 started at 22:22:09. App owner 10233 had already loaded the state engine-binding update at 22:15. Protected records hash unchanged before the restart.

The final browser list showed current US Houston–Phoenix Over 201.5 and Over 225.5 at 22:25:08. The corresponding API has six current US offers; Over 201.5 receipt→capture is 4.822 seconds. It expired before the inspection opened, and the pinned drawer retained the same clocks. Current list text, subsequent expiry screenshot and exact API evidence are linked in [result](result.md).

Final 22:30 measurement: all nine in-horizon NBA games with new aggregate winner offers reached capture in 6.110–41.768 seconds and first sampled API appearance in 13.510–48.334 seconds after receipt. Four December events and a spread/total-only Knicks–Cavaliers event explain the other five admitted events. Five retained first-capture traces separate selection/capture/sealing; their queue residence remains the largest tail. All six league requests are recorded (MLB zero). Final 22:31:52 owner sample has 20/23 native connections and zero retries; original 18 uncertain records/49 credits hash unchanged. Temporary observers stopped; app and data remain running. No commit, push, hosted run or owner acceptance.

The high-volume `priority-observation.jsonl` and `integrated-runtime.jsonl` are local traces. The smaller per-game summaries and retained failure examples carry the reviewed results.
