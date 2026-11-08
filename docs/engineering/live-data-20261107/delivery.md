# November 7 engineering integration

**November 7 evening continuation:** the [installed result](continuation/result.md) supplements this E01–E07 delivery with native throughput/matching, supported live prices, per-game scheduling and maintenance changes. Use that record for current coverage and latency; the earlier measurements below remain dated evidence.

Final continuation evidence: both native pregame/Pinnacle comparisons reached the browser; Kalshi and US source-evidenced live prices reached the browser with unavailable live economics kept separate. Final native cohorts are 256/source, rotating every 20 seconds, with complete discovery and explicit deferral. The 22:30 NBA winner population (nine in-horizon games) reached capture 6.1–41.8 seconds after admission and the sampled API 13.5–48.3 seconds after receipt. See the linked continuation for exact population, clocks, tests, retained failures and fee facts.

Work remains in the original checkout on `main`, uncommitted and unpushed. This record separates implementation, installed checks and specific product limits. The earlier observation report remains historical evidence.

## Later replay and cleanup

The 23:00 Eastern capture preserved 10,281 offers at their original clocks. The
replay inspector shows per-offer fee terms, eligibility gaps, saved venue rules
and settlement cashflows. Both local archives are byte-identical across the
November 8 cleanup. The app is running with the saved collection Stop active.

The cleanup makes sporting-state clock selection depend on the exact game and
schedule before it can affect the poller. Wrong-game observations and malformed
rows no longer suppress valid entries. The installed replay filter keeps a
reversed start window in the panel with an inline error. The focused checks
covered 120 Python cases and 25 disposable PostgreSQL 16 cases, plus the isolated
history check and wheel contents. Exact holds and zero provider requests were
verified after reload. See the [development guide](../../development.md#frozen-replay)
for the current entry point. Hosted CI and live collection verification remain
separate from this local cleanup.

## Implemented results and evidence

| Workstream | Result | Verification and limits |
| --- | --- | --- |
| E01 | Existing prices can remain current during an exactly owned request, including the short interval between positive accounting completion and the next heartbeat. The next-dispatch guard remains independent. Failed transport, unknown exposure, Stop, source pause and lost ownership still revoke authority. Per-league receipts remain visible. | Unit transitions and disposable SQL authority tests pass. The 18:00 trace showed 12 current offers during owned accounting at 18:02:12. This is a checked NCAAF page, not whole-slate freshness. |
| E02 | Atomic response accounting removes redundant ledger rewrite work. Bounded delivery clocks distinguish receipt, decode, normalization, admission, first recorded capture, recapture and publication; session history adds display time. First aggregate delivery gets a scheduling slot alongside fair rotation and native work. Catalog enrichment reuses event preparation; complete-book compression runs in the ordered child rather than the socket loop. | Exact catalog output hashes match; preparation 33.18 → 23.45 s on the same saved population. Isolated accounting median 2.124 → 1.251 s. Parent storage of 200 actual saved images 30.94 → 0.77 ms, exact decoded equality; child compression cost still exists. Polymarket US restoration 300.22 → 210.03 s on the checked restarts; still slow. First league publication and delivery of an individual page are separate. |
| E03 | Admin distinguishes owner outage, restoration stage, acquisition, waiting, pause, failure and stale prices. Recovery exposes exact eligible completed-5xx incidents and preserved exposure; no new 429 exception. Presentation assets no longer change acquisition identity. Exact zero-charge alternate-event 404 withdraws only that event/route. Inactive native markets no longer restart every other market. Receive backpressure retains the existing byte bound and ordered frames. | Loaded-status pressure 1,684,011 → 662,201 bytes, with quota, coverage and controls equal. Controlled tests cover suspension/resumption on one socket, burst ordering, oversize failure and cancellation. The actual 404 repair was performed with the owner stopped and preserved all attempt/account records. Retained Kalshi error frames identify provider error 25, “Subscription buffer overflow”; the runtime now reports that specific safe category. Backpressure prevents local buffer overflow but does not establish sustained upstream throughput. US backlogs, validation failures, keepalive timeout and transport loss remain separately visible. |
| E04 | Source-evidenced lifecycle states, post-start price retention, explicit time zone/start-window/game-state controls. Stale sibling quotes cannot shorten an already evidenced event's storage lifetime. Conflicting US game IDs stay unknown. | SQL pregame → post-start retention, old-price rejection, 15-second expiry and lifecycle fixtures pass. [Source matrix](source-lifecycle.md) states provider limitations. Fifteen-minute aggregate collection cannot provide continuous current live odds with a 15-second ceiling. Kalshi contract trading status alone does not establish sporting live state. Live fee/reference economics remain unavailable under the pregame models. |
| E05 | The served desk defaults to reviewed trade fees and separately exposes before-fee and conservative estimates. Exact Pinnacle identity and supported ranking remain required. Inspection retains full evidence; explicit latest adoption rechecks a coherent revision. | Financial fixtures check rounding, quantity, risk denominator, effective interval and exact reference binding. Novig received a new prospective public-schedule review. The actual Sam Houston winner inspection independently matched +7.63%: offered decimal 7.41, exact Pinnacle pair 6.65/1.13, normalized probability 113/778, zero reviewed pregame trade fee and risk 100/741. Polymarket US's November 6 account-tier change prevents renewing a universal 0.0695 rate. ProphetX account terms and Kalshi account/instrument authority remain independently required. Missing facts never become zero. |
| E06 | Bounded browsing sessions retain membership/order and revalidate evidence; removed rows have explicit placeholders. Active sessions use LRU retention. Matchup labels use captured participant facts, with original source titles disclosed. Counts distinguish held membership from current-filter counts. | Browser held outcomes 26–50 through updates, preserving focus. The selected inspection held its 18:15 receipt through refreshes and restart, then explicitly adopted the 18:30 receipt, source clock, capture and exact reference. Escape returned keyboard focus to the same offer. Mobile check at 390×844 had no horizontal overflow. Exact API fixtures cover insertion, reorder, removal, session expiry and filter changes. Current participant labeling repairs the general title-family mismatch; the original Brown–Yale historical payload was not available for a new source receipt. |
| E07 | Tab-local diagnostic history covers filter/page scope, source/collection state, original clocks, material price direction, unchanged confirmations, withdrawal, display departure and visibility gaps. Expandable entries and JSON export are available. | Browser downloaded and parsed a 107-event session; independent JavaScript tests cover direction, confirmation, withdrawal, gaps and bounds. Limits are 1,000 events and 2,000 keys. Sampled first/last observations never claim continuous opportunity duration. |

## Measured receipt-to-screen population

The 18:00 NCAAF receipt was 23:00:11.299507 UTC. Its first recorded capture was 23:00:22.223639 and first publication write 23:00:25.503845. The requested all-family page first showed its current offers at 23:02:12. These are different observations; the earliest league publication does not prove every game was delivered then.

The 18:15 NCAAF receipt was 23:15:11.183185 UTC, normalized at 23:15:12.764134 and admitted at 23:15:16.008611. The checked all-family page showed current scheduled-receipt offers at 23:17:11.836973. That page delay remains material; these restarts also required catalog restoration and policy-bound component rebuilding. No uninterrupted steady-state latency claim follows from them.

## Financial evidence boundary

The newly fetched [Novig fee schedule](https://support.novig.com/en/articles/16195057-fees-on-novig) still supports zero maker/taker fees for pregame straight trades in app/web and API. Its live coefficient differs between the table and VWAP example, so this review grants no live fee authority. The review begins at its actual fetch time and retains the existing 24-hour engineering review window; expired history is unchanged.

The current [Polymarket US fee schedule](https://docs.polymarket.us/fees) documents account taker tiers effective November 6 at 13:00 Eastern, including onboarding and overrides. The exact account coefficient at order insertion is missing; old public product metadata or the legacy table cannot establish it. Reviewed estimates are withheld with that specific reason. The official bytes and hashes are retained in the November 7 fee fixtures.

## Local qualification

Focused Python/SQL/JavaScript checks cover the changed authority, accounting, recovery, lifecycle, financial, browsing and history behavior. PostgreSQL checks used disposable databases; the available local server is PostgreSQL 14.20 compatibility qualification, not hosted PostgreSQL 16 CI. Hosted CI, commit/push and owner acceptance were not performed. The consolidated changed-path run passed 232 tests and 29 subtests. A later delivery-worker/reconstruction run passed 39 tests, including persistent ingress pressure, Stop/deadline cleanup and the exact provider overflow diagnostic. Three additional exact-event absence SQL tests passed. JavaScript syntax, diagnostic-history behavior and whitespace checks passed.

One broader existing raw-binding test could not run because `evidence/v1-coverage-comparison-20261001-v1/derived-awards-32.json` is absent. The changed full-catalog path was instead compared against the pre-change implementation using the actual retained catalogs and identical full-output hashes. That missing historical artifact is a test-fixture limitation, not provider permission or owner acceptance. A broader native run passed 83 tests and 17 subtests; two existing transport-policy tests require another absent historical fixture, `evidence/native-nyi-tor-20260930-v3/run-spec.json`.

## Evidence files and reproduction

- [Accounting benchmark](accounting-timing.json), [catalog parity](catalog-parity.json), [image queue benchmark](image-queue-timing.json), [status pressure](status-pressure.json), [exact 404 repair](event-repair.json), [active financial arithmetic](active-financial-proof.json), [browser latest adoption](latest-adoption-browser.json), [cycle timings](cycle-timing.json).
- [18:00 scheduled trace](scheduled-trace-1800.jsonl), [18:15 scheduled trace](scheduled-trace-1815.jsonl), [browser-exported session](browser-session.json). The earlier failed trace is retained separately.
- Use [the updated how-to](../../usability/2026-11-07/how-to.md) in the [running app](http://127.0.0.1:8783/). No additional paid acquisition is caused by list refresh, pagination, inspection or history export.

## Final delivery-pressure repair

The 18:30 Sam Houston winner check exposed an additional delay: ordinary publication turns took 94–99 seconds while capture/calculation/sealing required about seven seconds. The parent paused the publication child while native receive buffers remained above the ingress pressure threshold. The same backlog that needed diagnosis therefore withheld delivery of unrelated, already-admitted aggregate receipts.

Ordinary publication now runs in its existing separate bounded process at lower OS CPU priority. It no longer waits for native socket pressure to clear. Optional census/legacy finance work still yields; child memory/deadline/Stop, socket capacity, source freshness and accounting guards are unchanged. Persistent-pressure process tests prove progress and owned cleanup on Stop/deadline. Installed verification below distinguishes this repair from unresolved native transport throughput.

The completed 18:15 cycle made 129 requests (six featured batches, six census reads, 117 alternate event reads), all positively accounted, charging 240 credits. First dispatch to final receipt was 592.695 seconds: 118.625 dispatch-to-receipt and 474.070 between requests. The earlier 995.40-second cycle is a different population/load and does not constitute a controlled causal benchmark.

A proposed parser preflight optimization was measured slower and rejected; the original parser remains. Its failed measurement is retained in `parse-timing.json`.

## Installed closeout

The final data owner started at 18:39:40 EST. Kalshi restored 7,219 markets in 54.98 seconds; Polymarket US restored 8,240 in 222.73 seconds. These are measured startup delays, not instant restoration. The data process remained healthy through the checked scheduled refresh. Native queues still reached their existing bounded capacity and Kalshi reported `provider_subscription_buffer_overflow`; complete, continuously fresh native coverage is **not established**. The checked Sam Houston native offers remained expired/unmatched, while Novig/ProphetX source prices were current.

With the final publication scheduling code, the 18:45 NCAAF receipt arrived at **18:45:08.399**, was normalized at **18:45:09.618**, admitted at **18:45:10.621**, first captured for the league at **18:45:15.665**, and first published for the league at **18:45:19.857**. The selected Sam Houston–Jacksonville State winner component was captured at **18:45:43.451** and appeared in the browser at **18:45:50.565**: **42.166 seconds receipt-to-display**. Its checked API page had four current aggregate offers. This improves the checked delivery population but still leaves roughly 33 seconds from admission to that game capture; it is not a whole-slate latency guarantee. Completed sampled publication turns ran in roughly 7–9 seconds with zero ingress pauses.

[Final display clocks](final-display-timing.json), [installed runtime samples](installed-delivery.json), [18:45 trace](scheduled-trace-1845.jsonl), and [293-event browser export](browser-session-final.json) retain the evidence. The export revealed that null/restored calculation availability was labeled as a material change even when the price was unchanged. The final history implementation now records calculation availability separately, retains unchanged-price confirmations, and still records actual odds/reference-value changes; the regression check passes. The pre-fix export is retained and explicitly identified, not rewritten.

Admin's Sources page visibly showed saved-catalog restoration; Spending showed **49 credits / 18 uncertain attempts**, no current accounting blocker, and no new eligible recovery incident. All 18 protected attempt records still hash to `a6e691b659621146176ccfa13aa16615263b47a9043f6974059895f72a2b60ea`. Stop is false and source pauses are empty at this observation; no user Stop choice or protected hold was cleared. The ordinary scheduled acquisition remains running under its existing limits.

Remaining product limits are concrete: native throughput/reconnects and exact matching/freshness are incomplete for the checked game; API-to-game publication still has a measurable rotation delay; aggregate cadence cannot supply continuous 15-second-fresh in-game coverage; missing account/instrument fee facts withhold unsupported calculations. These are not owner-acceptance or hosted-CI prerequisites invented for this work. The completed changes and local checks do not claim those gaps are solved.

The [18:50 closeout state](closeout-state.json) rechecks the original protected records separately from a normal active request reservation. An in-flight two-credit request can temporarily show 51 pending credits/19 attempts; that is not a new abandoned hold. The latest sampled native failures were Kalshi provider subscription overflow and Polymarket US keepalive timeout. The final small-screen inspection also resets its scroll position on opening so its title is visible; this was visually verified.
