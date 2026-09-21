# D2 replacement validation — partial; D2 remains incomplete

September 16, 2026. One replacement pilot ran; no further attempt was made. It established Kalshi inventory/subscription coverage and browser-independent collection, but exposed a Polymarket US discovery discrepancy and ended at the existing serialized-ingress ceiling. Manual Stop was not exercised. No D3 work or application-source repair was performed in this task.

## Candidate and preflight

All **180 source hashes** matched `evidence/d2-coverage/verification.json`; no differences before or after the pilot. HEAD remained `edad00dd980cc8535d69a815d1199b82dd0e83cb` plus the recorded uncommitted candidate. Reused the recorded 67-check suite; reran **12 D2 checks**, including the repaired pagination path, actual local HTTP/WebSocket end-to-end test, refresh, Stop, resource boundaries and native replay. All passed.

The identified beta was idle, cleanup complete and collector lock unowned. The replacement used the existing `CoverageOwner(pilot_output=...)` mechanism through a retained explicit configuration wrapper; application code and limits were unchanged. Its new `collector.lock` points to the original lock, preserving cross-attempt overlap protection. The original consumed attempt was neither erased nor reset. Startup/restart remained idle.

Attempt directory: `evidence/d2-coverage/replacement-20260916T161440Z-faff4a56/`.
Session: **`97dbc1e0-36c7-49c8-a19b-f4856278e21c`**.

## Observed coverage

Use the two completed discovery generations, not the interrupted third traversal:

| Measure | Kalshi | Polymarket US |
|---|---:|---:|
| Independently discovered events | 32 | 32 |
| Event pagination | exhausted, filtered open universe | exhausted by short-page rule, filtered active/open universe |
| Native markets observed | 64 | **32 embedded; zero returned by separate market queries** |
| Market completeness | exhausted for all 32 retained events | **unestablished; contradictory catalog responses** |
| In-scope / kickoff-eligible observed markets | 64 / 64 | 32 / 32 embedded-only; full denominator unknown |
| Selected / requested | 64 / 64 | 0 / 0 |
| Ever acknowledged / receiving / usable | 64 / 64 / 64 | 0 / 0 / 0 |
| Peak simultaneous usable | 64 | 0 |
| Last sampled active usable (122.54 s) | 19 | 0 |
| Usable after Stop | 0 | 0 |
| REST attempts / cap | 72 / 100 | 83 / 100 |
| Connection attempts | 4 | 0 |

Kalshi's four groups contained 20/20/20/4 markets; each received a matching subscription acknowledgement. All 64 initial snapshots and 427 deltas were retained. All 491 recent synchronized derived books and their exact quote packets replay successfully; no native sequence gaps were reported. There were no reconnects, forced disconnects or fabricated transitions. The runtime classified these 64 markets as lacking counterpart market details and still collected them, demonstrating that matching did not limit subscription selection.

The US event responses retained 32 active full-game winner markets, with 32 supported Long and 32 unsupported Short sides. Each of 32 independent `gameId`/`SPORTS_MARKET_TYPE_MONEYLINE` queries returned HTTP 200 with `markets: []`, repeated on refresh. The candidate incorrectly replaced the embedded inventory with those empty responses and labeled market discovery exhausted. **That runtime flag is not accepted as completeness evidence.** Full US market count remains unknown, with at least 32 observed markets and zero subscribed. All 32 were omitted because of this discovery/projection discrepancy, not because no US listings existed. Separate embedded-only audit projections preserve the observed records without changing originals. Filter behavior/correct request contract remains unresolved; no alternate live queries were attempted.

No type, state or five-minute kickoff exclusions occurred among those observed eligible records. Hidden/unopened/other filtered-out listings remain outside the measured universe. US Short purchase depth remains unavailable.

## Timing, refresh and Stop

Start-to-feed-cleanup duration: **123.557 seconds**, below the 180-second maximum. Journal receipts span **16:15:55.483297–16:17:58.923576 UTC** (12:15–12:17 PM EDT).

The viewing tab showed `running`, was closed, and the tab inventory was empty. An independent loopback status check at **16:16:13.761934 UTC / 18.39 seconds** showed the collector still running with 30 requests per venue; subsequent samples showed continued requests. Reopening the page showed active collection and 64 Kalshi usable books. Browser-independent lifetime is demonstrated for this bounded run.

Initial discovery published at **16:16:19.888219 UTC**. The first scheduled refresh began at approximately 60 seconds and published at **16:17:19.155048 UTC**, with the same 32 events/64 Kalshi markets and the same US discrepancy. No subscription churn, new/departed/closed/rescheduled market or live reconnect was observed. Those transition capabilities retain offline evidence only.

**Manual Stop is unverified. I did not issue the requested prompt around 120 seconds.** Independent status shows the collector still active at 120.52 seconds. The second scheduled refresh had begun when the unchanged ingress cap stopped collection at 123.56 seconds. The run was not extended and no additional pilot was launched. This missed manual-Stop step is a validation failure, not a passed safety check.

The interrupted third traversal must not replace the last complete denominator: final runtime status mixes partial inventory (Kalshi 32 events/6 markets; US 25 events/25 embedded markets) with previous eligibility/selection. Only 20 of those US events have native responses in the journal; the final five came from the rejected response retained in memory before journal admission. The last complete generation remains the coverage basis above. This partial-refresh publication/accounting defect is recorded for repair; originals remain unchanged.

## Resources, gaps and finalization

Stop reason: **`session_ingress_cap`**. Serialized ingress reached **16,774,233 / 16,777,216 bytes**; the next record was rejected. **1,869 ingress records** were accepted and durably acknowledged, with **one rejected**, zero unresolved writes and an empty drained queue. The 1,870-record journal, including its terminal record, is **17,079,701 bytes**. Pilot directory including manifest/report: **19,181,257 bytes**. No ceiling was increased.

Native bytes charged: Kalshi **1,579,941**, US **915,411**. Queue high-water: **13 records / 464,163 bytes**. Collection RSS peak observed by status: **135,938,048 bytes**; post-finalization process high-water **216,121,344 bytes**, below 256 MiB. Maximum concurrent connections: four. Requests, frame/body, queue, connection, disk/output and journal bounds remained in force. Added spend: **$0**.

HTTP journal contains 72 Kalshi and 82 US responses, all HTTP 200; US accounting records 83 attempts because the last response hit the ingress ceiling before journal admission. Preserve that difference rather than claiming every request body was retained. Source timestamps were missing on 64 snapshots; subsequent book states recorded 50 first, 330 advanced and 47 repeated source times. There were 81 stale-book health derivations. Observed per-market receipt intervals: median **0.952 s**, maximum **87.420 s**; quiet markets lost freshness. These are observed cadence/gaps, not delivery guarantees. Upstream/lost-update totals remain unknown.

Both producers finalized with no cleanup errors; Kalshi disconnected, US never opened a socket. The shared collector lock was free and no external TCP connections remained. After an idle-only restart of the same configuration, status was `idle`, no session/collector was active, Start was unavailable, and the consumed replacement outcome was retained. No database, paid access, new feed, scheduling, trade, commit, push or publishing occurred.

## Evidence and next task

[Verification](../evidence/d2-coverage/replacement-20260916T161440Z-faff4a56/verification.json) · [independent audit](../evidence/d2-coverage/replacement-20260916T161440Z-faff4a56/audit.json) · [pilot manifest](../evidence/d2-coverage/replacement-20260916T161440Z-faff4a56/97dbc1e0-36c7-49c8-a19b-f4856278e21c/manifest.json) · [native replay](../evidence/d2-coverage/replacement-20260916T161440Z-faff4a56/97dbc1e0-36c7-49c8-a19b-f4856278e21c/replay.json). The attempt directory also contains preflight, browser/status observations, exact source comparison, embedded-market audit projections, socket/idle checks and prior-evidence hash comparison.

Journal chain: `db0dca7dcf13b5839f9fc3323e090648f749aa9f664de04fbc1255482341609d`.

**D2 remains incomplete. Next concrete task:** repair and test US contradictory-catalog handling and atomic publication of partial/failed refreshes using these saved responses. Preserve all 32 embedded listings and explicit unknown completeness. Any subsequent live validation, including manual Stop and US subscriptions, requires a new finite authorization; do not increase these limits or advance to D3.
