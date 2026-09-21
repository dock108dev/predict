# Predict — data coverage and history delivery plan

Updated September 16, 2026. Corrected delivery order: D1 complete → D2 coverage/control work (still incomplete) → D3a offline history foundation delivered ahead of sustained D2 qualification → mock collector integration delivered → finite sustained-capacity policy delivered → five-minute offline qualification and one isolated finite live validation (thirty minutes deferred) → offline finalization telemetry completion → separately authorized remaining D2 validation/D3 outcomes/settlement → D4 → D5. These slices supersede previous active next-action instructions in the Desktop tracker and product roadmap. E1–E10 and original numbered slices retain their identities and evidence; they are not renumbered or declared complete by this plan.

## Objective and scope

Build continuous, visible prediction-market coverage and usable history on the existing personal beta. Correct original-input calculations remain mandatory; positive opportunities are not a completion criterion. The POC, repeated bounded scans and saved-page research are delivered. The next milestone is the data foundation for daily use, before lead/lag, model calibration or maker research.

Start with Kalshi and Polymarket US NFL pregame full-game winner markets through existing supported access. Inventory each venue independently, including unmatched events and unsupported sides. Matching controls comparison eligibility, not whether an event appears in the catalog. “Complete” means coverage of a declared universe with measured exclusions and gaps; it does not mean every sport, market, venue or upstream update. Broader venues and market types follow demonstrated coverage needs.

No new paid source or sportsbook dependency. Unknown access, depth, fees, timestamps and settlement remain unknown. Preserve original observations, historical evidence and separate manual EV/page research. Polymarket US is not interchangeable with international Polymarket.

## D1 — venue coverage inventory and discovery foundation

Status: **complete — offline inventory tooling and retained/synthetic reports delivered September 16, 2026**. Current full live counts remain unavailable. See [implementation and D2 bounds](data-coverage-d1-report.md). Maps to E6 discovery and the scope definition needed for targeted E10 expansion.

Tasks:
- Inspect the current adapters, discovery, matching, collector and beta data path. Reuse them rather than introduce a second domain model or worker framework.
- Build a reusable per-venue catalog for the initial universe, before intersection or scan selection. Preserve native event/market IDs, canonical identity when resolved, participants, schedule, market type/period, status, supported purchase sides and relevant terms references.
- Represent discovery completeness: pagination exhausted, bounded/truncated, failed or unknown. Retain retrieval time and provenance. A six-game subscription cap must not truncate or masquerade as the full discovery universe.
- Produce a coverage report with per-venue discovered markets/events, in-scope inventory, matched and unmatched records, supported/unsupported sides, active subscriptions when known, and exclusions with reasons. Distinguish event counts, market counts and side counts; provide reconcilable totals.
- Review existing access/adapter evidence and current official documentation for catalog pagination, subscriptions and limits. Distinguish documented capability from observed capability; do not assume an offline adapter is live-qualified.
- Use saved raw catalogs if available and isolated fixtures for missing cases. Record snapshot ages and explicitly state when a current full count cannot be established without new collection.
- Specify the D2 subscription/resource budget and the D3 persistence integration, including whether to extend the current file journal or reuse the existing SQL history. Make one justified recommendation; do not migrate storage in D1.

Deliverable: working offline catalog/report command, focused tests, a saved coverage report with input provenance, and a concise implementation report describing remaining access/coverage gaps and exact D2 scope.

Completion: catalog includes unmatched events; fixtures verify pagination/truncation, duplicate handling, unknown identities, unsupported sides and deterministic exclusion counts. Existing saved math stays unchanged. A report based on old or partial captures must say so and does not establish full live coverage. D1 can complete the inventory tooling with explicitly unavailable current counts; real discovery validation belongs to D2.

D1 boundary: local code, tests and documentation only, plus public documentation research. No authenticated venue requests, credential reads, new market-data collection, running-beta restart, database migration, background job, trading, commits, pushes or publishing. Do not turn the task into another planning-only pass.

## D2 — continuous collection across the declared universe

Status: **one isolated five-minute live session completed; D2 remains incomplete.** [Live-validation report](data-coverage-supervised-5m-live-validation-report.md). Candidate `7f41489d2c52c5331cacbd076d406c3ab0786291a5feebb5c55cf2fff02e9961`, session `aa1a5562-5a5f-4b8c-aee2-6f00eaeabe62`: actual 64 Kalshi/32 US markets initially usable; refresh began at 120.001 s and generation 2 applied coherently. Independent explicit Stop invoked at 240.007 s, received at 240.178 s; closure/drain at 240.267 s; exact replay in 5.039 s. Usable counts before Stop were 23/29; US completeness and Short depth remain unresolved/unsupported. Collection is inactive, ownership released, attempt consumed, prior evidence and beta unchanged. Measured collection/replay RSS was 108.406/126.016 MiB; post-supplemental-report lifetime peak was not sampled. Complete that telemetry offline before further live authorization. Previous journal-efficiency, capacity, replacement and repair reports remain historical evidence; no thirty-minute/daily or full-D3 completion follows.

Tasks:
- Validate independent live discovery using existing authorized access; report the actual denominator, limits and exclusions before claiming full coverage.
- Replace the sample-selection collection policy with subscriptions to the supported in-scope universe, subject to verified limits. Where limits prevent this, explicitly report partial coverage and the chosen prioritization; rotation is not simultaneous full coverage.
- Refresh discovery/subscriptions for new, rescheduled, closed and departed pregame markets. Define the kickoff cutoff and unsubscribe policy; preserve metadata needed for later outcome lookup.
- Separate collector lifetime from browser lifetime. Provide explicit Start/Stop, one collector owner, visible per-venue health and a declared startup/autoresume policy. Start idle by default unless a later instruction authorizes autoresume.
- Capture available native depth updates and source/receipt timestamps, with explicit missing timestamps and gaps. On disconnect, mark books unusable until resynchronized.
- Apply finite queue, subscription, memory and disk budgets. Measure practical coverage, observed update cadence, gaps and resource use without imposing a blanket 250 ms target.

Completion: a separately authorized finite live pilot demonstrates discovered-versus-subscribed counts, newly discovered fixture markets, reconnect/resynchronization, browser closure independence and manual Stop. Preserve a report of actual duration and gaps. One pilot does not establish unattended reliability.

Boundary: D2's implementation prompt must specify live access, duration and resource limits. Do not enable indefinite/unattended collection merely by implementing the feature. Reuse current journaling during the pilot; minimum durability and disk bounds precede any live run.

## D3 — durable history, outcomes and settlement

Status: **D3a foundation, mock integration and one finite real segmented replay delivered; full D3 remains incomplete.** The [live validation](data-coverage-supervised-5m-live-validation-report.md) preserved 6,217 admissions across seven segments and exactly replayed 1,885 native plus 149 derived health books and 4,068 packets. Original [D3a](data-coverage-d3a-report.md) and [mock integration](data-coverage-d3-mock-integration-report.md) evidence remains unchanged. Outcomes, distinct venue settlement, backfill and broader retention enforcement remain deferred. No migration or sustained-capacity qualification follows from this finite session.

Tasks:
- Implement the selected persistence path without duplicating histories or silently replacing original evidence. Retain raw observations and normalized links, available depth, source/receipt times, terms/fee versions, coverage transitions and gaps.
- Segment long runs, record interrupted runs and resume from an explicit new boundary. Define disk limits, retention and safe shutdown behavior; do not delete old evidence as routine cleanup.
- Preserve final metadata for markets leaving pregame coverage. Link sporting results separately from venue-specific settlement, payout, void/refund/cancellation and pending/unknown status, using supported read-only sources.
- Assess historical backfill availability and cost separately. Import only where separately authorized, label source granularity and missing intervals, and do not imply snapshots reconstruct every book change.
- Make a saved calculation reproducible from its exact original observations and applicable assumptions after restart.

Completion: restart/replay retains exact original values; injected interruption/gaps stay visible; outcome and settlement fixtures remain distinct; an authorized real sample is reconciled where available, with unresolved results explicit. Storage growth and retention behavior are documented.

## D4 — live coverage and opportunity dashboard

Status: pending D2 and usable D3 history. Maps to the existing personal beta/E5 presentation.

Tasks:
- Show each venue independently, with concise discovered/subscribed/usable coverage and last-update status. Include unmatched markets in an inspectable coverage view, outside cross-venue opportunity ranking.
- Feed supported comparisons into the existing calculation engine continuously; retain original-input math and exclusions. Show both venue legs and unsupported purchase sides clearly.
- Support sorting/filtering, stable detail selection, explicit Stop and saved history. Keep live, stale/disconnected, historical, manual EV and retrospective research distinct.

Completion: browser walkthrough demonstrates both venues, coverage reasons, live updates, disconnect state, Stop and saved reopening; focused arithmetic regression checks show no changed economics unless a separately evidenced defect was fixed.

## D5 — targeted expansion, then evidence-led research

Status: deferred until initial coverage/history are useful. Maps to targeted E10 expansion and later E7–E9.

Tasks:
- Choose the next venue, sport or market type using measured missing coverage, access, usable sides/depth, matching/settlement effort and independent liquidity. Keep ProphetX live sizing/reconstruction and Novig access/wire gaps explicit.
- Add reference data only when it answers a specific EV/research need. Prediction prices alone do not establish an independent fair probability.
- Link sufficient event-level histories and outcomes before calibration; use chronological held-out evaluation. Lead/lag additionally needs adequate timing evidence; maker research needs explicit fill uncertainty.

Completion: each expansion has its own coverage denominator and focused validation. Research reports may conclude insufficient evidence or no useful edge. Trading remains a separate decision and scope.

## Tracking and immediate handoff

- [x] D1: independent catalog and coverage report (offline complete; live counts unavailable).
- [ ] D2: finite live discovery/refresh/direct Stop and exact segmented replay demonstrated; usable-coverage gaps, US completeness and remaining criteria stay explicit.
- [x] D3a: bounded segmented history/incremental replay delivered; one finite live session replayed exactly, with no sustained-capacity qualification.
- [x] Mock-only integration: shared ContinuousSession/CoverageOwner, busy refresh/Stop and incremental finalization; production selection unchanged.
- [x] Finite supervised capacity policy and offline qualification design; first-stage retention is stop-before-limits with no automatic deletion. Design only; no production change.
- [x] Five-minute `predict-supervised-segmented-5m-v1` offline implementation delivered; production/D2 selection unchanged.
- [x] Five-minute offline qualification: 59 selected checks and busy 240-second Stop/300-second deadline pass under frozen budgets. Collector peaks 113.05/109.81 MiB. Prior failures preserved; thirty-minute qualification deferred.
- [x] One authorized finite live session completed through isolated entry; refresh/direct Stop/drain/replay passed, with post-report RSS measurement limitation. Ordinary production selection remains unchanged.
- [ ] Immediate next task: offline finalization-wide telemetry through supplemental report writing; no live rerun.
- [ ] Remaining D3: result and settlement linkage/backfill and implemented retention enforcement, deferred.
- [ ] D4: integrated live coverage dashboard.
- [ ] D5: targeted breadth and subsequent research.

Mock integration is delivered: the existing owner/collector passed busy refresh and active Stop across segments with 758 exact books/1,516 packets. A separate fixture exhausted four segments at 4,092 logical ingress before intended Stop. Failed rotation remains incomplete without a terminal. 146 selected checks pass in separate fresh processes; two established environmental recovery failures remain. Original 575-book evidence and all 2,269 preexisting evidence files are unchanged. See [integration results and exact candidate](data-coverage-d3-mock-integration-report.md).

Five-minute scope supersedes the earlier thirty-minute immediate target: [policy](data-coverage-sustained-capacity-policy.md), [measurement basis](data-coverage-sustained-capacity-measurements.md), [frozen budgets](../evidence/supervised-5m-20260916/frozen-budgets.md), [handoff](data-coverage-sustained-capacity-prompt.md). `predict-supervised-segmented-5m-v1` was qualified offline and subsequently used in one explicitly authorized isolated live validation. Qualified scope: 300 seconds including discovery, 64 Kalshi/32 US markets, initial + scheduled refresh at 120 seconds, active Stop at 240 seconds and an independent 300-second deadline. US completeness remains unknown. Ordinary production selection remains unchanged; the live-validation result below supersedes the earlier offline-only disposition.

**Current disposition: the one authorized finite live session is complete; stop after its report.** [Live-validation report](data-coverage-supervised-5m-live-validation-report.md). All 2,589 preexisting evidence files remain unchanged; no additional session/restart, policy increase or beta change occurred. The explicit Stop, exact replay, accounting differences and final resource-measurement limitation are recorded there. Next: add and offline-verify resource telemetry through the supplemental report write, including post-write RSS and reconciled output/write counters. No further live access is authorized.

The qualified offline candidate `39017e90b75b0b2ade6fe91ef4bbc9b646c186f87adf8ce470937877976f31b9`, prior combined-process memory failures, pacing/stub failures and both device-identity recovery findings remain historical evidence in the [qualification report](data-coverage-supervised-5m-qualification-report.md). The frozen policy was not edited. Thirty-minute/daily capacity, US completeness and full D3 remain incomplete.
