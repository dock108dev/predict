# Prediction Arb — Next Steps

Updated: September 14, 2026 (UTC; owner review September 13 New York)

## Source of truth and current status

- Project: [prediction-arb](/Users/michaelfuscoletti/Desktop/prediction-arb)
- Supplied technical spec: [PLAN.md](/Users/michaelfuscoletti/Desktop/prediction-arb/PLAN.md), preserved unchanged. Its access, fee and timing assumptions are not automatically verified.
- Current research and corrections: [venue-access.md](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/venue-access.md).
- Corrected Kalshi framing: [data-use assessment](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/kalshi-data-use.md). The [inquiry](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/kalshi-data-use-inquiry.md) is optional and unsent; no mandatory support-letter gate. No project-specific Kalshi approval is claimed.
- Slice 1: [implementation and validation record](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-1.md), [artifact manifest](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-1/manifest.json). **Complete using wholly synthetic fixtures.**
- Evidence: [capture guide](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/phase-0/README.md) and [provenance manifest](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/phase-0/manifest.json).
- **Status: Phase 0 reconnaissance complete; Slice 1 complete; Slice 2 complete for bounded retail ingestion and advertised-window recovery. Public REST, authenticated transport and window replacement are verified. Slice 3 sandbox API/REST and transport recovery verified; unsized probability quotes implemented; quantity sizing and live selection-message qualification pending. Slice 4 qualified for bounded NFL REST, authenticated snapshots/deltas and recovery; Slice 5 implemented and offline-verified; Novig live qualification awaits issued OAuth credentials and wire verification; Slice 6 normalization complete; Slice 7 canonical event matching complete; Slice 8 moneyline market matching complete; Slice 9 versioned outcome-aware fee engine complete; Slice 10 top-of-book arbitrage detection complete; Slice 11 full-depth arbitrage calculation and sizing complete; Slice 12 PostgreSQL historical capture complete; Slice 13 implemented; owner review feedback recorded on the interface loop; capture gaps and status ambiguity remain unresolved. Slice 13B capture/shutdown repairs are locally implemented, but the 250 ms cadence gate remains unmet and 13B is incomplete. Slice 14 has not started.**
- Phase 0 authorized public research and bounded anonymous captures. The later owner instruction authorized local Slice 1 implementation and tests using wholly synthetic fixtures. Slice 1 used no accounts, credentials, sessions, outreach, new market data, paid data, databases, Git operations, publishing or orders.
- No venue is certified ready for reliable continuous scanning. Public accessibility, API entitlement, data-use permission, settlement compatibility and feed reliability are separate gates.

## Current owner review — September 13, 2026 (New York)

**Review outcome: Live prices and details inspected; stopped state observed; saved live session reopened in Historical.** Owner feedback: “seems fine from that perspective.” This is feedback on the reviewed loop, not acceptance of continuous collection, production readiness or the unresolved defects. The owner identified always-on connections, real production streaming and a running dashboard sortable by profit as the desired direction, and asked what should come next. The reply “this?” referred to the stopped status and is not acceptance. Manual Stop behavior is not established: the saved shutdown reasons show automatic backpressure stops, not an owner stop or the 60-second deadline. On-demand depth was not exercised in this review.

Candidate: all 55 files in the Slice 13 manifest match at readiness and after these observations; manifest SHA-256 `35fd07e7a1f8c5284d5d75e5d67fe7630546976c54f06a86cfe1b6863bfaf931`. The existing dashboard and socket-only database were already running. Read-only state now confirms collection stopped. [Review state and saved-session evidence](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-owner-review/20260914T002407Z-readiness-and-saved-sessions.json). Prior technical verification below remains historical evidence, not evidence that this owner run met the same conditions.

Reviewed saved session `ed06c7d1-ae22-4ed8-8b90-bec4e22e2917` started at 8:20:40 PM. Owner-provided Historical view shows four markets, two conditional calculations, zero qualified modeled results, 22 retained observations and 42 stream messages. Both feeds were connected in the active screenshot. The inspected conditional legs cost $0.5600 and $0.4400, giving a $0.0000 raw gap; one entry fee was unknown and the other $0.01 with unresolved applicability. Profit, ROI, settlement outcomes and required sizing/source-time evidence remain unknown. The pricing diagnostic has a missing PMUS ask and size. Zero qualified results is valid and is separate from collection reliability.

**Observed issues:** this session stopped at 8:20:54 PM with “Backpressure: bounded queue filled; capture gap recorded”; saved coverage reports 32 queued observations unprocessed and no continuous coverage. The earlier 8:20:14 PM session `c93f79fe-d2c0-4c33-bf97-7ba5fe61a17f` also stopped for backpressure with 32 queued observations unprocessed. Both session records and the picker say `complete` despite the recorded gaps. This is an observed status/coverage mismatch; root cause is not diagnosed. The inspected details also juxtapose “Saved observations from a live scan” with “Evidence class: current,” a possible wording ambiguity observed by the assistant, not an owner complaint or proof of current eligibility.

Historical explicitly says saved observations only and shows no live connection. Synthetic demo was not used and no synthetic result contributes to these findings. ProphetX partial, Novig unavailable, truncated NFL discovery, unresolved fees/settlement/sizing/source clocks and actual fills remain limitations. Existing source, data and evidence are preserved; only this tracker and new review evidence were written. No app repairs, restarts, Git changes, trading, setup or publishing occurred.

**One concrete next action: scope a Slice 13 follow-up to repair the observed queue-overflow shutdown and misleading complete status, then verify a bounded supervised real-data run including manual Stop and saved reopening.** This is the recommended engineering step, not implementation performed or authorization for unattended collection. The feeds reviewed already used production Kalshi/Polymarket US data. Progress toward sustained streaming should follow measured throughput and recovery verification, with explicit gaps, freshness, discovery refresh and resource limits. Profit ranking additionally needs supported fees, settlement and sizing; unknown net profit must remain unknown and separate from qualified rankings. Owner feedback is now recorded; review closes with the limitations above. App and data remain unchanged. Slice 14 and always-on implementation have not started.

## Current 13B continuation — scope reassessment

The owner raised that the initial live-stream version is becoming too precise. Cadence tuning and remaining qualification are paused pending a simpler acceptance decision; no new threshold is approved and 13B is not marked complete. [Continuation report](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13b-cadence-repair/README.md), [current results](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13b-cadence-repair/summary.json), [verification and unfinished checks](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13b-cadence-repair/verification.json).

Current source identity: `c0cebb70c08b449b76f338ca3d0be86e3b670ff4e51e6b7f84cbe20b1d7812c5`. The separate immutable-snapshot compute/view writer is implemented locally; the frozen 250 ms gate still fails. All 28 supported capture ledgers and 18 fault-accounting/outcome checks pass; 365 offline tests pass. Final broader qualification remains pending. Existing evidence is preserved, disposable clusters are removed, and no owner app restart, owner database access, live verification or 13C work occurred. Earlier 13B figures below describe the previous candidate.

## Slice 13B — capture/shutdown repairs saved; incomplete

Updated September 14, 2026 UTC. **13B is incomplete: the frozen 250 ms view-refresh gate remains unmet. Stop before 13C and all live verification.** Local implementation and finite disposable-PostgreSQL verification were authorized; no owner app/database or venue connection was used.

[Repair report and reproduction](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13b/README.md), [final gate results](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13b/summary.json), [verification](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13b/verification.json), [fresh manifest](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13b/manifest.json). Exact final source-identity SHA-256: `c2939e0598cb77bb159a83b4ba6e59b44f8fdbe447e48b4a2347558252a2144f`; frozen fixture remains `54eaf221ebbd0c5eb32c091076468f14c50bef53f094ec74bee648369f74dd26`.

Receipt persistence is separated from full evaluation; unchanged snapshot/artifact work is reused; book/receipt state rolls back with its transaction. Capture has priority over one tracked depth request. The queue is finite at 48 items and 1 MiB of recursively measured retained item bytes. Stop preserves its first timestamp/reason/initiator, closes producers, drains accepted work, settles depth and database work, finalizes once, and prevents restart until settled. Fresh readback and sanitized journals retain durable receipt bindings and unprocessed/rejected accounting. Only necessary backend shutdown outcomes were implemented; shared saved-status projection, legacy interpretation and UI wording remain 13C.

The final 28-session matrix preserves all 41 books in each frozen in-flight/40-book burst at both two and four markets per venue, twice: **82 side receipts plus 8/16 bootstrap; zero rejected and zero unprocessed**. No-delay 40-book throughput is **83.8–92.6 books/s at two markets and 27.3–33.0 at four**, exceeding 8/s. Supported shutdown peaks at **7.73 seconds**; producer closure meets 2 seconds. Ordinary receipt-only book service is 4.6–5.4 ms, with full views measured separately. Eighteen real-storage fault scenarios reconcile, including Stop during depth, limits, rollback and database/finalization failure. Two additional beyond-envelope drain-expiry runs settle in 8.52/8.55 seconds and explicitly retain 12/11 unprocessed items. No clean completion is inferred for them.

**Unmet gate:** active view-completion intervals reach **309 ms / 455 ms**, and four-market calculation/persistence latency reaches **267 ms**, against 250 ms. Full evaluation averages about 49 ms / 178 ms in the ordinary repeats, but receipt and view work still share one worker. Repeated work and scheduling were repaired; cadence was not silently relaxed. Coalesced intermediate evaluations are counted, while every accepted supported-envelope observation is retained. These synthetic measurements do not diagnose the historical owner-run cause or qualify production throughput.

**Final verification: 354 offline tests, 38 PostgreSQL integration tests, all twelve existing examples, JavaScript syntax, 319 exact saved calculation replays and 3,896 exact detector-input receipt checks passed.** The source identity matches across final matrix/integration/fault runs. All 610 pre-existing evidence/PLAN artifacts in the preservation snapshot remain unchanged. Isolated clusters were removed; owner app/data remain untouched. No credentials, venue requests, live scans, trading, publishing, commits, pushes, 13C–13E or Slice 14 work occurred.

**One concrete next action: continue 13B by removing the measured serialized view-refresh bottleneck with immutable receipt-bound compute snapshots, then rerun the frozen cadence/capture gates. 13C remains blocked. Once 13B passes, the concrete 13C task is one shared lifecycle/coverage projection for the session picker and saved details, including the two legacy complete-with-backlog cases.**

## Historical 13A handoff — complete before 13B


[Detailed slices, tasks, solutions and acceptance gates](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-13-follow-up-plan.md).

**13A completed September 14, 2026 UTC: real disposable-PostgreSQL reproduction and accounting gates passed.** [Reproduction guide](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13a/README.md), [baseline report](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13a/baseline-report.md), [full measurements](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13a/baseline/measurements.json), [reconciled counts](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13a/summary.json), [verification](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13a/verification.json), and [fresh artifact manifest](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13a/manifest.json). Final candidate source-identity SHA-256: `324ad7de79b0873fe09099b3278d58bda4cdc805d9e4131ad98020a4f839397a` (measured baseline source: `b918fb0a8b49452151819f8a1f7d025d19f8f0a8250108675d7459e6e89781a0`); fixture SHA-256: `54eaf221ebbd0c5eb32c091076468f14c50bef53f094ec74bee648369f74dd26`.

The 24-session matrix used wholly synthetic book/control inputs at two and four markets per venue. All four expected-overflow trials reproduced **41 offered = 33 accepted + 8 rejected; 33 accepted = 1 processed + 32 explicitly unprocessed**, with each durable side receipt bound to its item or bootstrap identity. Independent readback distinguishes attempted, rolled-back and committed writes. Ordinary book service averaged 86–104 ms at two markets and 241–255 ms at four; full calculation/view work consumed about 93%/98% of item service. At four markets the 24-item burst left 12 accepted items unprocessed after the fixed quiet interval. These known defects remain present; the passing tests assert reproduction and accounting, not repair. Verification: **345 full offline tests and 35 PostgreSQL integration tests passed**, plus all 24 independent ledger checks and JavaScript syntax validation. Final review corrected only diagnostic rejection labels (first overflow versus later acceptance-closed offers); **24 focused offline/dashboard tests and all 35 PostgreSQL tests passed again**, including both market-size reproductions. The original measured ledger and timings are preserved; the report identifies the label correction and both exact source candidates.

Diagnostic code is opt-in tooling around the unchanged controller/pipeline; production app behavior, queue size, calculation cadence, shutdown and status are preserved. Only isolated temporary PostgreSQL clusters were used and removed. Owner data, saved review evidence, `PLAN.md`, existing source and historical manifests are unchanged; the old Slice 13 manifest remains 54/55 matching with only this mutable tracker differing. The historical owner-run arrival timing, upstream losses and exact bottleneck remain unknown. Synthetic bootstrap does not measure venue discovery, serialized queue bytes are not heap size, and unknown-sizing depth does not qualify full sized searches. Detailed timer overhead was noisy (−1.3% / +9.0% versus timing-disabled wrappers), so absolute rates are instrumented local baselines. No live requests, credentials, owner database access, app restart, trading, publishing, commits, pushes or 13B–13C repairs occurred.

| Follow-up | Tasks / proposed solution | Required result |
|---|---|---|
| 13A — Reproduce and measure | Complete: bounded synthetic fixture tooling, stage timing and durable item/receipt ledger. | Real-storage overflow and all 24 accounting gates pass; baseline and proposed 13B targets saved. |
| 13B — Capture and Stop repair | Preserve observations, reduce measured redundant work, bound queue bytes/items, prioritize capture over depth, close producers then drain within a fixed budget. | Clean stops save accepted work; overload/failure accounts for every known omission. |
| 13C — Status and coverage | Separate lifecycle from coverage; preserve first stop reason; derive truthful legacy labels; persist session-specific counts; clarify saved provenance. | Database, API and dashboard agree; old gap sessions cannot look clean. |
| 13D — Regression qualification | Burst/Stop/failure tests, real disposable storage, exact replay, browser checks and fresh artifact manifest. | Identified candidate passes required offline/database/UI checks. |
| 13E — Supervised verification | Proposed maximum three live starts of at most 60 seconds each: deadline, manual Stop, depth and saved reopening. | Bounded production evidence and separate owner-review handoff; collection left stopped. |

These labels subdivide the Slice 13 repair; **Slice 14 remains Crypto.com and has not started.** The completed request authorized 13A local diagnostics and disposable-storage benchmarks only; 13B–13E implementation and new live collection were not performed. Sustained collection and profit sorting are separately described follow-on work in the plan. Unknown fees, settlement, sizing and profit remain unknown.

**One concrete next action: separately authorize Slice 13B to reduce repeated calculation/artifact work and implement bounded capture-priority drain against the [frozen 40-book burst envelope and acceptance targets](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-follow-up/13a/13b-targets.md). Stop before 13B in this task.** Historical next-action lines below describe prior handoffs only.

## Historical technical handoff — Slice 13 complete

[Local dashboard](http://127.0.0.1:8765/), [workflow and boundaries](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-13.md), [verification](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13/verification.json), [artifact identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13/manifest.json).

The owner can launch, start a bounded current NFL scan, inspect prices/fees/outcomes/exclusions and on-demand depth, stop, and reopen the saved session. Live, Historical and Synthetic demo remain separate. Kalshi and PMUS use current discovery and existing adapters/Keychain access; ProphetX partial and Novig unavailable remain visible. Unknown settlement, fee applicability, sizing, source clocks and actual fills still prevent qualified live results.

Final 60-second live session `ecb8e401-cb51-46fb-8542-0347ea0c5950`: 22 stream messages, 64 retained observations, four comparisons, two conditional calculations and zero qualified opportunities. Deadline shutdown left zero queued observations unprocessed. All 34 saved calculation audits replay exactly. JavaScript syntax, 340 offline tests, 32 PostgreSQL integration tests and all twelve examples pass. Browser verification covered desktop/narrow layouts, controls, updates, filters, details, depth, errors and saved navigation. Technical/browser verification is not owner acceptance.

The loopback app and socket-only project PostgreSQL are left running for review, with scanning stopped. Launch `scripts/dashboard start`; stop app `scripts/dashboard stop`; stop database separately `scripts/project-postgres stop`. No auto-resume, global service, external deployment or trading. Stop scans before database maintenance/examples; bounded lock waits fail safely with coverage recorded.

**One concrete next action: owner review of the local Live → inspect → Stop → Historical loop. Stop before Slice 14 implementation.** Historical stop instructions below describe earlier runs only.

## Historical handoff — Slice 12 complete

[Slice 12 workflow and boundaries](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-12.md), [verification](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-12/verification.json), [PostgreSQL tests](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-12/integration-tests.txt), [bundle and backup restore](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-12/restore-verification.json), [artifact identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-12/manifest.json).

A dedicated socket-only PostgreSQL 14.20 database supports finite preserved-capture ingestion, exact raw content, Decimal quote/book observations, immutable matcher/rule/fee snapshots, saved detector/depth replay, coverage, candidate history and self-contained export. Real bundle and pg_dump restores into separate disposable project databases rerun the saved calculations. The runtime is stopped after verification; project data is preserved. No login service or public TCP listener was created.

**321 offline tests, all eleven prior examples, the new storage example and 26 real PostgreSQL integration tests pass.** Separate restore/outage verification covers corruption rollback and an actual terminated persistence connection with local failure-journal recovery. Original PLAN.md and 547 prior implementation/test/evidence files remain unchanged; credentials were not read or changed.

Default capture limits are 1,000 receipts, 60 seconds, 16 MiB per raw/normalized image and 128 MiB raw receipt input; the historical demo declares 300 seconds for processing. Synchronous writes provide bounded backpressure. Full supplied images and candidate diagnostics are retained; each receipt remains distinguishable despite shared payload hashes. No automatic retention deletion runs. Candidate histories are discrete and censored: zero proven observed-duration seconds between samples, no invented survival across gaps. Stream reconstruction and every-exchange-event recovery are not claimed.

Ten historical production structural pairs still yield twenty related candidate combinations and zero qualified opportunities. Settlement, fee, sizing, venue qualification and actual-fill limits are unchanged. Synthetic positives remain separate. No live capture, account activity, trades, funds, purchases, contacts, commits, pushes, publishing, dashboard or unattended scanner occurred.

**One concrete next project action: Slice 13 — simple live dashboard. Stop before Slice 13 in this task.**

## Historical handoff — Slice 11 complete

[Slice 11 API and limits](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-11.md), [readable results](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-11/report.md), [complete offline example](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-11/depth-example.json), [verification](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-11/verification.json), [artifact identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-11/manifest.json).

**321 offline tests (287 existing plus 34 depth tests), all ten existing examples and the new depth example pass.** Calculator `depth-1` walks supplied acquisition levels, preserves fractional venue grids/minimums, and evaluates equal and unequal allocations against every material outcome. Maximum worst-case profit, maximum ROI, maximum deployment above explicit thresholds and minimum-known-outcome diagnostics are separate. Zero allocation is the no-trade alternative. Cash limits are explicit hypothetical inputs.

Small domains are exhaustively evaluated with independent arithmetic checks. Larger domains use a deterministic bounded search; the default 4,096-allocation budget, full domain size, grid, evaluations and limit status are disclosed. Results never label a limited search globally optimal. Every positive leg uses the actual fee engine with one new order and one assumed fill per consumed level; fragmentation-sensitive charges remain conditional with no conservative bound asserted. The exact multi-price refund extension is versioned `fees-1-refunds-1`; ordinary `fees-1` results remain unchanged. Unknown fees, settlement, ProphetX native sizing and Novig live qualification remain separate constraints.

The synthetic real-fee example selects 3/3 contracts for $1.73 maximum profit versus 6/6 for largest deployment above 10% ROI. Incompatible venue grids support a 4/3 allocation with $1.52 modeled worst-case profit, improving on the equal-grid baseline. Other cases show disappearing depth profitability, partial final levels, grouped rounding, nonmonotonic ROI, binding cash, refunds, unknown outcomes/fees and no profitable allocation. These are invented books/rules, not production opportunities. The sole fee stub is isolated in a qualification-branch test.

All ten production structural pairs remain settlement-UNKNOWN. Twenty candidate combinations yield zero qualified current opportunities. Retained books preserve the single 1.0100 two-ask diagnostic; unavailable books, units, fee contexts and reconstruction evidence are not fabricated. Candidates share liquidity and capacities cannot be summed.

PLAN.md and all historical evidence are preserved. Credentials were not read or changed. No live collection, account access, trades, funds, purchases, contacts, commits, pushes, publishing, continuous collection, database, dashboard or execution work occurred.

**One concrete next project action: Slice 12 — PostgreSQL historical capture. Stop before Slice 12 in this task.**

## Historical handoff — Slice 10 complete

[Slice 10 API and policies](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-10.md), [readable detector report](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-10/report.md), [complete example](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-10/detector-example.json), [verification](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-10/verification.json), [artifact identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-10/manifest.json).

**287 offline tests (247 existing plus 40 detector tests), all nine existing examples and the new detector example pass.** Detector `top-of-book-1` refreshes current parent/moneyline decisions, consumes adapter asks, deduplicates repeated observations, and evaluates equal visible or explicit hypothetical quantities through the existing fee engine. Pricing diagnostics, conditional cashflows and qualified modeled arbitrage remain separate. Every material outcome, fee assumption, sizing/clock/state/lock limitation and exact source/decision identity is retained. Positive model profit assumes both legs fill at the stated asks; it is no fill or actual-profit guarantee.

All ten production structural pairs remain settlement-UNKNOWN. They produce 20 candidate leg combinations, not independent liquidity counts; zero qualify. Actual historical books supply one two-ask diagnostic: 1.0100 sum, with 6194.036398 seconds of receipt skew. Missing markets are not assigned invented books. Twelve synthetic examples include positive/zero/negative outcomes, fees eliminating a raw gap, exceptional settlement loss, unknown fees/size, stale/skewed data, inactive markets, duplicates and maker-dependent exclusion. Even the positive real-fee example retains unresolved fee/account conditions. A test-only synthetic fee stub verifies positive qualification cannot become a current production opportunity.

Local screening defaults are 30-second receipt age, 5-second inter-leg receipt skew and 30-second source snapshot age, all inclusive and configurable. Last-change age is not latency or disconnection; known source problems remain explicit. Cash-denominated ROI uses required entry cash plus any separate reserve. Equal quantity can miss unequal-stake profit; no deeper levels are walked. PMUS short acquisition asks remain unavailable where its adapter has no supported transformation. ProphetX native sizing and Novig live verification remain separate dependencies.

PLAN.md, prior implementation/tests and historical evidence are preserved; credentials were not read or changed. No live requests, onboarding/research expansion, account activity, trading, funds, purchases, messages, commits, pushes or publishing occurred.

**One concrete next project action: Slice 11 — full-depth arbitrage calculation and sizing. Stop before Slice 11 in this task.**

## Historical handoff — Slice 9 complete

[Slice 9 coverage and API](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-9.md), [fee examples](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-9/fee-example.json), [verification](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-9/verification.json), [artifact manifest](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-9/manifest.json).

**247 offline tests (213 existing plus 34 fee tests) and all nine examples pass.**

Engine `fees-1` and local schedule registry schema 1 implement Decimal acquisition/fill scenarios, historical selection, scoped Kalshi fee changes/null clearing, cumulative US order rounding, market-level ProphetX settlement commission, Novig product/unit distinctions and separate credits. Exact context and registry snapshots make calculations reproducible. Unknown charges remain null. Formula support, applicability, rounding and account assumptions are separate; actual fill reconciliation remains unverified throughout.

Current official sources were reviewed and preserved. Novig multi-fill aggregation conflicts remain conditional; ProphetX settlement rounding and native quantity conversion remain unverified; Kalshi account precision must be explicit; PMUS retail fractional contracts are unsupported and an independent settlement levy is not established by the trading schedule. These scoped conditions do not leave the implemented slice unfinished.

Slice 8's ten production settlement-UNKNOWN pairs are unchanged. No onboarding, Novig credential work, accounts, trades, funds, purchases, contacts, commits, pushes or publishing occurred. PLAN.md, adapters, shared models and historical evidence are preserved.

**One concrete next project action: Slice 10 — top-of-book arbitrage detection. Carry independent settlement and fee-applicability constraints into it; never replace unknown charges with zero. Stop before Slice 10 in this task.** ProphetX sizing and Novig live qualification remain independent constraints.

## Historical handoff — Slice 8 complete

[Slice 8 policies, coverage and verification](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-8.md), [artifact manifest](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-8/manifest.json), [offline moneyline report](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-8/moneyline-example.json), [pair-specific rule questions](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-8/research/findings.md).

**213 offline tests and all eight examples pass.** Matcher `moneyline-matcher-1`, profile `moneyline-rules-1`, comparator `settlement-comparator-1`, market store schema 1. Current Slice 7 event confirmation is required; historical linkage alone cannot qualify a pair. Stable scoped market/side identities, source hashes, normalization/event versions, rule versions, explicit reasons and immutable decision revisions are retained in the local atomic store. Changed rules or parent decisions re-evaluate qualification; identical replay is idempotent.

All five confirmed production event pairs have captured moneyline coverage: Atlanta–Pittsburgh, Baltimore–Indianapolis, Buffalo–Houston, Chicago–Carolina and Cleveland–Jacksonville. Fifteen native markets (ten Kalshi team-specific contracts, five Polymarket US long/short markets) form five canonical moneylines and ten cross-venue structural pairs. They expose ten same-exposure and ten opposing-sporting-outcome relationships; those are not counts of independent liquidity or arbitrage opportunities. The report separately excludes 1,680 captured spreads/totals with native IDs, period taxonomy and reasons.

**Production settlement: zero qualified, ten UNKNOWN, zero demonstrated INCOMPATIBLE pairs.** Fractional ties alone do not establish complementarity under postponement, resumption, forfeits, shortened games, cancellation, source/review deadlines or independent fair value. Exact missing conditions and retained listing/general-source evidence are visible per pair. Synthetic refund/fraction, differing postponement windows, unknowns, discretion and review scenarios remain separately labeled. No owner approval is fabricated. Three bounded public official rule/schema downloads were made; no new market captures were needed.

**One concrete next project action: Slice 9 — fee engine. Stop before implementing Slice 9 in this task.** Pair-specific rule uncertainty carries forward with the mappings. ProphetX quantity/clock/live-selection limitations and Novig-issued credentials/live qualification remain separate dependencies; neither is a whole-project stop gate. PLAN.md, credentials, existing implementation/tests and historical evidence are preserved. No trading, funds, purchases, outreach, commits, pushes, publishing, fee engine, arbitrage calculator, simulator or dashboard occurred.

## Historical handoff — Slice 7 complete

[Slice 7 policies, coverage and verification](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-7.md), [exact artifacts](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-7/manifest.json), [offline matching report](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-7/matching-example.json).

**176 offline tests and all seven examples pass.** Matcher `event-matcher-1`, store schema 1. Slice 6 normalization feeds deterministic candidate generation, all-pairs scheduling/role constraints, stable persisted canonical IDs, immutable source observations, mapping revisions and reasoned local schedule review. Default scheduling tolerance is 900 seconds inclusive across timezone-aware instants, with no same-UTC-date rule. This is implementation policy, not proof of identity.

The 47 capture observations have 47 distinct scoped native references, not 47 established games. Fifteen production listings form 10 canonical events: five Kalshi/Polymarket US pairs (Atlanta–Pittsburgh, Baltimore–Indianapolis, Buffalo–Houston, Chicago–Carolina, Cleveland–Jacksonville) and five unmatched singletons. ProphetX sandbox remains separate: 28 ambiguous listings across 14 repeated-listing pairs and four singletons. Synthetic MLB doubleheaders and schedule corrections are labeled test evidence; no owner override or live MLB/Novig coverage is claimed. Event identity does not establish market equivalence, settlement or tradability.

**One concrete next project action: Slice 8 — moneyline market matching. Stop before implementing Slice 8 in this task.** ProphetX quantity/clock/live-selection limitations and Novig-issued credentials/live qualification remain separate dependencies. No onboarding, venue contact, live collection, commits, pushes or publishing occurred. PLAN.md, credentials, adapters, models, normalization and historical evidence are preserved; exact checks are in the Slice 7 evidence directory.

## Historical handoff — Slice 6 complete

[Slice 6 behavior, coverage and verification](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-6.md), [exact artifacts](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-6/manifest.json).

**151 offline tests and all six examples pass.** Registry `2026-09-12.1` has 32 NFL and 30 MLB teams verified against current official directories. It stores 20 Polymarket US production team mappings and 55 ProphetX sandbox team mappings (28 teams), plus their two league mappings. Separate immutable enrichment resolves 94 participant occurrences across 47 actual captured NFL events, preserving raw observations, participant order, explicit roles and mapping/extraction provenance. Unknown, ambiguous and conflicting evidence stays explicit. MLB has no captured-event coverage; Novig examples are synthetic only; NCAAF/NBA/NHL remain planned and unsupported. No cross-venue event equivalence is constructed.

**One concrete project next action: Slice 7 — canonical event matching**, consuming normalization output without duplicating identity logic. Stop before implementing Slice 7 in this task. Novig-issued credentials remain a parallel external dependency; no onboarding or outreach was performed. PLAN.md, credentials, existing adapter/model code and historical evidence/manifests were preserved.

## Slice 5 implemented, live qualification pending

[Novig Slice 5 handoff](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-5.md) and [exact artifact identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-5/manifest.json).

**138 offline tests and all five examples pass.** Novig implements bounded pregame discovery, CASH payout-cent books and native sized probability bids, individual-order replacement/aggregation, status and locks, lifecycle drains, OAuth renewal, bounded retries, market-specific streaming/recovery and cancellation cleanup. The 28 new tests use synthetic fixtures, with a local loopback protocol Ping/Pong check. Raw evidence, unknown depth, unknown source clocks and unknown ordering guarantees remain explicit.

**Actual Novig access:** dedicated QA and production Keychain client ID/secret entries are absent. Current official documentation requires Novig-issued OAuth credentials. No QA/production private requests or live data were obtained. The initial WebSocket book envelope is not completely documented; the REST DTO compatibility branch is implemented and synthetic-tested but needs wire confirmation. No full live qualification is claimed.

**Parallel Novig external dependency:** obtain the venue-issued QA OAuth pair and provisioned access instructions, enter it through the documented hidden Keychain prompts, then run the finite verifier. The optional [access request](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/novig-access-request.md) is unsent. This dependency blocks Novig live qualification only; it does not block independently authorized Slice 6 normalization. Slice 6 has since completed; this dependency does not block Slice 7.

**Kalshi Slice 4 remains qualified for bounded NFL REST, authenticated snapshots/deltas and recovery.** Its prior evidence, implementation and tests are preserved. [Kalshi handoff](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-4.md). ProphetX sizing/clock/live-selection limitations remain deferred and do not block independent work.

Slice 5 authorization covered official account/API setup, dedicated credentials, local work and bounded read-only verification. No orders, funds, purchases, external messages, Git initialization, commits, pushes or publishing occurred. PLAN.md and historical evidence are unchanged.

## Product target

Build a read-only, event-driven sports moneyline scanner that matches equivalent contracts across venues, applies actual versioned fees, evaluates available depth, and captures opportunity duration and replay evidence. Begin with pregame markets. Initial venues are Kalshi, ProphetX, Polymarket US, and Novig; secondary work covers Crypto.com and Fanatics.

The private tool supports the owner's own potential trading on Kalshi and other venues. Historical capture and replay serve those personal trading decisions; starting read-only does not imply a separate non-trading purpose. No redistribution, resale, third-party trading service or commercial data product is planned. The first useful result is evidence of opportunity frequency, size, duration and survival under simulated latency. Automated execution remains a later decision.

Latest follow-up (September 12 UTC): existing sandbox session/key reused; ten additional HTTP-200 requests, deliberate disconnect/refresh/resubscription/cancellation succeeded. Both authorized event scopes match `19458`; eight frames comprised six handshake and two unclassified other frames. Zero `market_selections` frames and zero market-ID-filtered messages; live reconstruction remains unverified. Safe transport counters and sanitized-capture regression added. **80 tests and all three examples pass.** [Latest evidence/artifact identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-3/sandbox-followup-20260912/manifest.json). Prior captures and PLAN preserved. Cumulative 42 HTTP attempts, six connections, twenty frames. Quantity/value and clock definitions remain unresolved; the optional venue clarification remains unsent. These unknowns did not block the independently completed Kalshi Slice 4.

## Current Slice 3 — sandbox access verified; price quotes work; sizing/feed data incomplete

[Current handoff](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-3.md), [78-test results](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-3/sandbox-qualification-20260912/tests.txt), [fresh artifact identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-3/sandbox-qualification-20260912/manifest.json).

**Sandbox API entitlement is confirmed.** The existing signed-in Chrome session showed API Integration and an existing key. The supplied sandbox credential was moved from `.env` to the designated project Keychain entry; plaintext sandbox values were removed. Authentication, catalog, event discovery, valid-price ladder, V4 markets and explicit refresh returned HTTP 200. No new login, key generation, funding or venue intervention was needed for access.

**What works:** one discovered NFL event, Chicago Bears at Carolina Panthers (`19458`), yields 447 distinct leaf strikes. Fixed native market-ID reuse across strikes/events and empty optional subtype handling. Pregame timestamp/status eligibility was already consistent with actual REST and UI; it was not relaxed. American odds are corroborated by five native/UI prices and converted with Decimal into shared ask probabilities. Native data remain preserved; unknown quantity ownership keeps sizes unavailable. REST `active` maps to ACTIVE; other unverified states remain UNKNOWN.

**Transport separately verified:** returned Talaria WSS host, event registration/signin/subscription, deliberate disconnect, HTTP-200 refresh, reconnect/resubscription and cancellation all succeeded. Two bounded runs on the same event received twelve handshake frames total but **no market-selection messages**. Resting liquidity exists, and REST captures show natural level removal between runs. This does not establish live stream delivery/reconstruction. There was no expanded scan or order-generated activity. Total work used 32 HTTP attempts across the catalog, two repaired REST failures and two transport runs; all returned HTTP 200 and each run stayed within its explicit limits.

**Remaining:** Trading V4 quantity/value ownership and units; timestamp units/meaning; further market-status definitions; actual event-channel selection delivery and reconstruction. Price normalization is no longer wholly unknown. Sized books, settlement compatibility and production liquidity remain unqualified. Production credentials/access were not exercised. All 78 tests and three examples pass; Slice 2, PLAN.md and historical evidence are preserved. That Slice 3 capture preceded the separately completed Slice 4; see the current Kalshi handoff above.

**ProphetX disposition:** retain partial qualification; quantity sizing, additional clock/state semantics and live selection reconstruction remain unavailable where unverified. The request is optional and unsent. Kalshi Slice 4 proceeded independently and is now qualified within its bounded scope.

## Slice 2 — complete within bounded scope

Polymarket US REST, authenticated transport, advertised-window replacement/recovery and source-time/status/depth hardening are qualified. The latest pre-ProphetX baseline was 50 tests and both examples passing. [Handoff](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-2.md), [qualification identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-2/review-20260912T002420Z/manifest.json).

Partial depth, REST cache/source disagreement, unobserved natural halts and continuous reliability remain explicit constraints. They do not reopen bounded Slice 2 qualification. Earlier account/setup next actions are superseded; historical evidence remains in the linked handoff and evidence directories.

## Corrected permission framing and Slice 1 completion

The [Kalshi assessment](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/kalshi-data-use.md) now distinguishes the published own-trading data-use allowance from third-party sharing requirements and actual membership/API conditions. Applying that allowance to the clarified personal-trading purpose is an interpretation, not venue approval. Unnamed implementation details do not create a mandatory advance permission-letter requirement. The support inquiry is optional and unsent. Actual access, membership and applicable account terms remain unverified.

Slice 1 was separately authorized and is **complete with wholly synthetic fixtures**. It implements shared models, Decimal values and units, timezone-aware provenance, optional canonical mappings, unknown states/depth/synchronization, pairwise settlement compatibility and an async read-only adapter contract. A finite synthetic adapter and example exercise discovery, snapshots, rules and updates. No Phase 0 venue samples are used by the implementation or tests.

Implemented files: [models](/Users/michaelfuscoletti/Desktop/prediction-arb/app/models/core.py), [interface](/Users/michaelfuscoletti/Desktop/prediction-arb/app/adapters/base.py), [synthetic adapter](/Users/michaelfuscoletti/Desktop/prediction-arb/app/adapters/synthetic.py), [fixture](/Users/michaelfuscoletti/Desktop/prediction-arb/app/fixtures/moneyline.json), [example](/Users/michaelfuscoletti/Desktop/prediction-arb/app/example.py), [model tests](/Users/michaelfuscoletti/Desktop/prediction-arb/tests/test_models.py), [adapter tests](/Users/michaelfuscoletti/Desktop/prediction-arb/tests/test_adapter.py), [project metadata](/Users/michaelfuscoletti/Desktop/prediction-arb/pyproject.toml) and [run instructions](/Users/michaelfuscoletti/Desktop/prediction-arb/README.md), plus package initializers.

Validation on Python 3.14.5: **16 tests passed; example exited 0**. The complete synthetic adapter contract passed with socket creation blocked. [Validation record and limitations](/Users/michaelfuscoletti/Desktop/prediction-arb/docs/slice-1.md); [exact file identities](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-1/manifest.json). PLAN.md and existing Phase 0 evidence remain unchanged. No live reliability, fee, settlement or trading claim follows from synthetic success.

## Phase 0 — completed public work and remaining gates

Verified September 11, 2026. See the research document for direct official links, publication/effective dates, unresolved conflicts and exact dependencies.

- [x] Reviewed official sources for all four initial venues and recorded verification dates.
- [x] Documented public, sandbox and production paths; separated documented capability from observed behavior and authenticated unknowns.
- [x] Investigated discovery, depth, units, streaming, limits, timestamps, suspensions and data-use restrictions. Missing guarantees remain explicit rather than assumed.
- [x] Researched current fees, exceptions, rounding, settlement charges, rebates and official examples; unresolved details remain open.
- [x] Researched NFL/MLB settlement conditions and recorded incompatibilities/unknowns.
- [x] Established that Novig has a documented authenticated live-depth path; historical downloads are not live qualification.
- [x] Preserved PLAN.md and recorded verified corrections separately.
- [x] Rechecked and corrected Kalshi personal-trading API-use framing; removed mandatory inquiry gate and kept an optional unsent draft.
- [x] Saved eight anonymous production JSON responses and five official PDFs with endpoint, retrieval time, identifiers, evidence class and hashes.
- [x] Identified a two-venue NFL candidate: Tampa Bay–Cincinnati, September 13, 2026. Settlement compatibility is **UNKNOWN**, not approved.
- [ ] Complete representative live event/market/rule/book capture across all four venues. Kalshi and Polymarket US NFL samples exist; ProphetX/Novig and live MLB books do not.
- [ ] Verify actual venue-specific membership/API/account conditions and owner-authorized authenticated access; apply the corrected Kalshi purpose framing without inventing a permission-letter requirement.
- [ ] Demonstrate streaming snapshot/update synchronization, gap/reconnect recovery, depth completeness, suspension handling and observed latency.
- [ ] Resolve exact account/event fee applicability and candidate settlement equivalence.

| Venue | Public result | Exact remaining dependencies |
|---|---|---|
| Kalshi | Slice 4 public NFL REST and authenticated production snapshots/deltas/recovery/cancellation verified; 110 tests pass | Bounded native depth only; ongoing market-status/exchange-pause eligibility, continuous reliability, MLB live coverage, effective fee/account rounding and settlement compatibility remain unqualified. Production key is in project Keychain. |
| ProphetX | Official authenticated V4 REST and event WS documented; no live payload | Sandbox API enablement after signup/2FA; separate production approval/keys; current post-migration feed configuration; depth/units, rate/timestamp/status/recovery verification; fee netting/rounding and moneyline rules |
| Polymarket US | Public REST and authenticated US stream captured; 50 tests pass | Retail access, advertised-window replacement and bounded recovery verified; 50 tests pass. Remaining separate limits: full exchange depth, stale REST discrepancy, live halt behavior and settlement compatibility. Institutional access is distinct. |
| Novig | Official NBX QA/production REST depth and WS documented; no live payload | Venue-issued OAuth credentials and read-only entitlement/terms; reconcile hosts and conflicting limits; live catalog/depth/latency/reconnect/lock evidence; fee aggregation/eligibility and exact listing rules |

Important corrections: Polymarket **US** current taker coefficient is .06, not .05; Kalshi uses dynamic series/event fees and account-aware rounding, with observed MLB series multiplier .5; ProphetX production onboarding is separate and its NFL tie refunds differ from .50 settlement; Novig is not historical-only, and zero pregame fees do not apply to every product.

**Completion boundary:** public reconnaissance is complete. Authenticated access and all-venue sample/reliability qualification are not. The four-venue target has not been silently reduced to the two publicly accessible venues. Phase 0 itself did not authorize implementation; the later explicit instruction authorized synthetic Slice 1 only.

Verification: source links were checked against official pages/indexes; local links resolve; all 13 captured-source hashes match; JSON parses and credential/account-field scans are clear. Candidate IDs and depth counts match the raw data. The supplied plan hash is unchanged.

## Build sequence

Use the practical slices in plan §77 as the roadmap. **Slices 1–2 and 4 are complete within their recorded bounds; Slice 3 remains partial; Slice 5 is offline-verified with live qualification pending; Slices 6–12 are complete within their documented scopes. Slice 13 is implemented with owner-review defects; 13A diagnostics are complete and 13B is the next separately authorized engineering implementation. Slice 14 has not started; trading remains deferred.**

| Slice | Scope | Completion evidence |
|---|---|---|
| 1 | Shared models and read-only adapter interface — complete, synthetic only | Validated immutable models, explicit units and unknowns, raw JSON envelope, async contract and invented adapter; 16 tests and example passed. See Slice 1 record above. |
| 2 | Polymarket US ingestion — complete within bounded scope | Official full-window semantics, 42-frame live replay, omission removal and recovery qualified; focused hardening verified with 50 tests. Freshness/depth remain separate. See current Slice 2 handoff. |
| 3 | ProphetX ingestion — partial; remaining capabilities deferred | 80 tests and three examples pass. Unsized American-price quotes implemented. Quantity sizing, timestamps and actual selection-message delivery/reconstruction remain incomplete; production unverified. See current handoff. |
| 4 | Kalshi ingestion — complete within bounded scope | 110 tests and four examples pass. Public NFL REST, authenticated snapshots/deltas, shared-SID sequences, timed reconnect/resubscription and cancellation verified. Decimal quotes, rules and fee metadata captured; see Slice 4. |
| 5 | Novig data-access solution — implemented, offline-verified | Live OAuth/wire qualification pending as a parallel venue dependency; see Slice 5 handoff. |
| 6 | Team/league normalization — complete | Registry 2026-09-12.1; 32 NFL / 30 MLB teams; scoped venue mappings, immutable enrichment and explicit unresolved results. 151 tests and six examples pass; see Slice 6 evidence. |
| 7 | Canonical event matcher — complete | Matcher event-matcher-1; 176 offline tests and seven examples pass. Five production cross-venue pairs; atomic local store, revisions, reschedule reviews and environment isolation. See Slice 7 evidence. |
| 8 | Moneyline market matcher — complete | Structural matching and explicit UNKNOWN settlement; see Slice 8 handoff. |
| 9 | Fee engine — complete within documented scope | Versioned calculations and explicit applicability limits; see Slice 9 handoff. |
| 10 | Top-of-book arb detection — complete | Outcome-aware detection, unknown propagation and exclusion evidence; see Slice 10 handoff. |
| 11 | Full-depth calculation — complete within documented scope | Bounded sizing/search and explicit grid/fee limits; see Slice 11 handoff. |
| 12 | PostgreSQL historical capture — complete | Durable observations, exact calculation replay and restore evidence; see Slice 12 handoff. |
| 13 | Simple live dashboard — implemented; 13A complete | Diagnostic gates passed; 13B capture/shutdown repair next, then 13C–13E status and qualification. |
| 14 | Crypto.com adapter | Verified access/limits and targeted polling; coverage and update latency shown explicitly. |
| 15 | Fanatics investigation/adapter | Access path and liquidity independence verified before counting it as a separate executable leg. |
| 16 | Execution replay/simulator | Reproducible latency scenarios, depth loss, missing legs and partial-fill outcomes; no orders placed. |
| 17+ | Actual trading | Deferred pending measured research results and separate authorization. |

Raw payload preservation starts with each adapter; Slice 12 implemented durable PostgreSQL history and Slice 13 implemented the Python async dashboard. Redis remains a planned option, not an implemented prerequisite. Earlier no-database boundaries describe their original runs; the dedicated project database was introduced in Slice 12. This planning review did not start, stop or modify the app or database.

## Research and expansion milestones

- [ ] **Moneyline scanner:** complete Slices 1–13 with traceable calculations, reliable books, and explicit venue coverage.
- [ ] **Historical analysis (plan Phase 5):** collect multiple sporting cycles, including busy NFL/NCAAF weekends where available. Report collection dates, coverage gaps, opportunity counts by venue pair, ROI, depth, duration, deployable hypothetical capital, and theoretical returns.
- [ ] **Spreads and totals (plan Phase 6):** after the moneyline baseline, add line/period/push handling and cases such as -3 versus -3.5 and 8 versus 8.5. Track this as its own work item without renumbering the practical slices.
- [ ] **Simulation (plan Phase 7 / Slice 16):** evaluate 50, 100, 250 and 500 ms, 1 second, and approximately 5-second manual response scenarios. Retained book observations support estimates, not proof of actual fills.
- [ ] **Assisted execution decision (plan Phase 8):** only if duration evidence supports it; exact market links and proposed quantities remain separately scoped.
- [ ] **Automated execution decision (plan Phase 9):** assess opportunity frequency, fee accuracy, latency, partial fills, capital requirements, and venue rules before authorizing any order integration.

## Requirements to carry through every slice

- Keep ingestion, matching, fee calculation, detection, and execution separate.
- Use Decimal monetary calculations; retain fee versions and source evidence with results.
- Prefer deterministic mappings. LLM/fuzzy matching only proposes candidates; preserve confidence and human approval where required by the plan.
- Require exact or explicitly approved compatible settlement rules for strong alerts. Include relevant settlement outcomes in profitability reasoning.
- Separate pregame from live markets, and immediate taker/taker opportunities from maker-dependent opportunities.
- Reject uncertain books after disconnects until resynchronized. Derive freshness thresholds from observed feeds; the plan's example values are provisional.
- Separate raw gap, modeled net ROI, depth-adjusted results and execution reserves. Modeled guaranteed payout assumes compatible settlement and successful fills of both legs.
- Keep secrets out of files, logs, raw captures and the UI. Read-only collection remains separate from trading functionality.
- Tests and simulations establish technical evidence; they do not establish actual profitability, fill guarantees, owner acceptance, or permission to trade.

## Updating this tracker

For each completed slice, record the date, exact revision or artifact identity, changed scope, checks and outcomes, evidence paths, remaining limitations, and one concrete next action. Keep unavailable venue dependencies visible. If a required gate fails, record it before declaring the dependent capability complete; continue independent authorized work. Do not turn venue-specific limitations into a project-wide stop.

## Completion record and preservation

- Documentation setup and Phase 0 research are complete; original plan and captured sources remain preserved.
- Slice 1 is complete with synthetic validation; Slice 2 is complete within its bounded scope.
- Latest Slice 3 follow-up: 80 tests and all three examples pass; sandbox REST/transport verified, economic sizing and live selection reconstruction partial. See the current Slice 3 record above for exact evidence.
- Current completion: Slices 6–12 are complete within their recorded scopes; Slice 13 is implemented with owner-review queue/coverage defects. 13A reproduction/accounting is complete; the next separately scoped implementation is 13B using the measured envelope above. ProphetX partial qualification and Novig live credentials remain independent venue limitations. Slice 14 has not started.

Historical run details and immutable artifact manifests remain in the per-slice handoffs and evidence directories. Historical approvals, stop points and next actions describe their original runs and are not current work instructions.
