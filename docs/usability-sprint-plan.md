# Predict major usability sprint plan

October 2, 2026. **U0–U2 local engineering complete. U3–U6 runtime/qualification remain planned. Replacement UI owner feedback and acceptance remain outstanding; status stays REVISE / not user-ready.** This plan is the active work order following the [audit](usability-audit-20261002.md). It supersedes the old card-layout preservation rule, saved-data walkthrough next action, manual-scan product loop and universal history/reopening acceptance requirements. Preserve original evidence and calculations; do not preserve the failed presentation merely because earlier browser checks passed.

## Product outcome

Open Predict and see a familiar, readable sports odds board with data flowing automatically. Games, outcomes, exact lines and venue prices should be understandable without learning collection machinery. Show **both American odds and cents**. Kalshi and Polymarket US are the intended faster native feeds; Novig and ProphetX remain useful slower feeds through a shared, tightly budgeted Odds API path. Trading remains manual outside Predict.

The primary page has sport/league, market, period, venue and game search controls; grouped event/outcome comparisons; concise freshness/availability and material-rule indicators; and useful Details. Start scan, Stop scan, duration, saved scan, imports, acquisition counters, raw JSON and replay/history controls are absent from the ordinary-user flow. A normal user's opening, filtering or viewing Details must not require admin configuration. Filters operate on available data and do not independently launch paid requests.

The owner gets a separate admin surface for source operation, metrics, quota, diagnostics and source issues. New ongoing operation needs no quote-history archive, database migration, history export or permanent bookmark/replay feature. Existing captured data remains intact for tests and engineering. Preferences, source configuration, authorization and quota accounting may use small local durable records; those are operational state, not quote history.

## Governing constraints and authority

- All four comparison venues remain intended participants. Six sports and supported market families remain the roadmap. Full-game winner, spread and total come first. Observed coverage is factual accounting, not a percentage-based gate.
- Missing inputs withhold only dependent outputs. Price comparisons remain useful when EV/net/sizing cannot be supported. Keep raw differences, arbitrage return, model-supported EV and manual What-if separate. EV%-first ordering remains applicable within a supported-EV view; the ordinary odds board need not become a wall of unavailable EV cards.
- Standing owner authorization: “I am apprving all attempts to get the live data in full  as needed.” Necessary new data attempts/retries are authorized within this plan and the subsequent **500/month shared Odds API ceiling**. No renewed per-attempt owner approval question is required. Record fresh candidate/spec/endpoints/attempt/budget identity and derive machine-readable scope from this instruction; never pretend an old approval applies to edited source.
- Preserve spent reservations and consumed markers. Sealed historical packages remain historical. Use a new runtime/attempt namespace, with clear shutdown, concurrency, request/byte/memory and quota limits. Existing finite qualification caps are not silently relaxed to create perpetual collection.
- Use existing credential loaders only when necessary for authorized source data. Keep secrets out of docs/logs. No trade, funding, subscription purchase, plan upgrade, outreach or application-level scheduled follow-up is authorized. In-process automatic data flow while the app runs is the product requirement; an OS background service or unattended recurring Codex automation is separate work.
- Stop paid acquisition on exhausted/unknown contradictory quota, authentication/entitlement failures needing owner action, repeated malformed data, unsafe cleanup or rate-limit conditions requiring backoff. Continue healthy independent sources when possible. Record the affected site and explain the actual problem, without making the owner interpret transport/rules evidence.
- Production/user readiness requires actual useful operation and owner review of the new design. No hosted/shared-user deployment, 24/7 SLA or trading execution is implied.

## Sprint order and status

| Sprint | Outcome | Dependency | Current state |
| --- | --- | --- | --- |
| U0 | Complete IA and presentation contract, with a realistic user-ready design | Audit | Complete local engineering; owner feedback outstanding |
| U1 | Replace the main and Details interfaces with a coherent odds-board experience | U0 | Complete local engineering |
| U2 | Implement compact dual-price data presentation and exact quote-selection semantics | U0; integrates with U1 | Complete local engineering |
| U3 | Automatic native runtime and bounded latest-state storage | U0/U2 contract; U1 consumer | Planned |
| U4 | Cheap shared Novig/ProphetX flow under 500/month | U3 lifecycle/budget ownership | Planned |
| U5 | Separate admin operation, observability and source-issue handling | U3/U4 status contracts | Planned |
| U6 | Integrated live qualification and owner review of the replacement product | U1–U5 | Planned |

These are substantial engineering increments, not a sequence of copy tweaks. Do useful independent work when one provider is stuck. A blocked source does not stop the design, board, unaffected native feed, quota work or admin implementation.

## U0 — Product architecture and realistic design

Produce the complete landing-board and Details design together, including populated, connecting, no events, no comparable outcome, partial source, budget-delayed, stale, source error and missing-calculation states. Use Action Network/OddsJam as comparison-pattern references, not a request to copy branding or insert promotions. A compact table/board is the starting pattern; the owner has not accepted a particular mockup.

Define the information hierarchy: game and start time; period/market and exact line; outcomes; fixed venue columns or a clearly responsive equivalent; American odds and cents; a restrained better-quote cue; concise age/state; Details. Restrict default periods to applicable sports and supported offerings. Primary common markets are easy to switch. Broader periods/futures remain available where useful without filling the default filter with irrelevant choices.

Define normal-user versus admin responsibilities and a single latest-state data contract. Resolve product terminology and missing-value treatment before implementation. Support desktop and narrow screens, keyboard and long event names. Preserve useful focus/stable-update behavior.

Deliverable: reviewable realistic design using retained real quotes with historical labeling or clearly isolated fixtures; updated contracts and implementation seams. No default product page silently uses those samples. Review may refine this concrete design; do not restart the rejected walkthrough or ask the owner to design the interface from scratch. No separate permission gate is implied by this review.

Acceptance: a person can identify game, outcome, exact line/period and venue quotes without reading diagnostics. Both price formats are visible without a toggle. No normal-user scan, archive or debug controls remain. Material settlement/freshness limitations have compact understandable labels. The design is ready to implement, with owner feedback distinct from signoff.

## U1 — Ordinary-user board and Details

Replace the landing hierarchy and comparison-card renderer through the ordinary launcher/router, not a separate demonstration dashboard. Group related outcomes under the same exact game/market/period/line; align all intended venue columns; show unavailable cells honestly. Winner sides, Over/Under and signed spread lines must remain unambiguous. Different line prices must never be highlighted as if they were the same contract.

Remove normal-user Start/Stop/Refresh and saved-scan/navigation/import/research/configuration machinery. Reconnection/recovery is automatic when safe; a concise failure state tells the user what is happening. Saved engineering inspection can remain accessible in admin, without entering the ordinary product flow. Optional opportunities/EV views must earn their space with supported outputs and clear labels.

Details becomes a deliberate readable surface: selected event/outcome/line, the exact selected price revision, native quote/conversion, times and ages, rules/fee differences, supported calculations and one clear unavailable reason per dependent feature. Deeper original inputs and transport JSON belong to admin diagnostics. New history/download/permanent bookmarking is deferred.

Acceptance: population, selection, filters and Details work together at desktop/narrow widths with coherent visual hierarchy; no clipping/overflow or focus loss; updates do not move the selected row or silently alter an open price review. Explicitly model ties, empty sources, zero/negative supported results and unavailable metrics. No false profit highlight.

## U2 — Price presentation and quote semantics

Create a display contract over existing normalized source values. Use exact decimal arithmetic; rounding is for display only. For a unit $1 normal-win claim with price `p`, displayed equivalent decimal odds are `1/p`, and American odds derive from that decimal value. For aggregate decimal odds `d`, cents equivalent is `100/d`; American odds are `(d−1)×100` for `d≥2`, or `−100/(d−1)` below 2. These equivalents do not supply fee-adjusted return or exceptional settlement equivalence. Handle invalid/zero/one prices, two-way/three-way outcomes, payout multipliers and unsupported units explicitly; do not force a $1 binary conversion onto an incompatible instrument.

Keep real native cents distinct from aggregate equivalent cents. Put a concise equivalent marker on affected columns/cells; reveal the original decimal/native quote, unrounded basis and source identity in Details. Use consistent display precision and grouping. Source times, receipt times, market state and provider delay are distinct facts.

A better-price cue compares eligible quotes for the exact same displayed selection and displays gross quote advantage only. Missing fees/settlement/depth prevents stronger claims. Tie prices get a neutral tie state; stale/missing quotes are not presented as executable best prices. Rule differences remain visible even if the price can be compared.

Define a versioned current-state API with quote ID, exact identity, native value/units, display values, revision, source/receipt/local times, state, calculation eligibility and concise reasons. Freeze a selected revision for open Details in a bounded in-memory lease. If expired/restarted, say the selection expired; never substitute a new quote under an old identity. No durable saved-cutoff guarantee is required for the new ordinary flow.

Acceptance: meaningful unit/boundary tests and original-input reconciliations for each supported quote type; no rewriting frozen oracle values. Fixtures cover same-line versus different-line spreads/totals, complementary native sides, aggregate equivalents, ties, missing inputs and mixed-cadence views. Price formatting never changes arithmetic or promotes references to legs.

## U3 — Native data that flows automatically, lightweight state

Introduce a service-owned runtime alongside the retained finite qualification owner. One collector per process/runtime scope owns acquisition; browsers subscribe to a shared projection. Multiple tabs, filter changes and Details do not create collectors. Reuse transport, matching, source state, cancellation and guarded credential resolution where applicable.

On ordinary app launch, load valid operational configuration and standing authority, acquire current native listings/books and publish updates automatically. A missing credential or source failure produces a site-specific status; no user scan task. Rediscovery, subscriptions, sequence resynchronization and bounded reconnect/backoff are explicit. No infinite tight retry, duplicate subscription or inherited spent allowance. Close/quitting must cancel tasks, close sockets and release ownership cleanly.

Separate the latest-state runtime from archival journal guarantees. Bound resident event/catalog/quote state, ingress, connections and selected-price leases. Use a small versioned operational configuration and authorization record; no ongoing quote archive by default. Keep a rolling, bounded sanitized admin error/metrics buffer. Preserve old capture writers/readers for qualification and testing. No new database or history pipeline.

Do not merely remove journal writes from `ContinuousSession`: current projection/error recovery assumes acknowledged durable records. Factor shared normalized admission/projection from the sink; provide explicit ephemeral ordering/revision/commit semantics. A malformed/incomplete observation never replaces a valid quote. App restart acquires current state afresh; expired cached quotes are not current fallback.

Native updates should arrive as promptly as the provider route supports. Measure source→receipt, receipt→projection, projection→browser and visible age separately. SSE heartbeat or repeated identical values is not newly priced data. Define operational thresholds from measured evidence and user-visible harm, not an invented universal freshness SLA.

Acceptance: controlled long-running operation spans rediscovery/reconnect and exceeds old 180-second test-session lifetime; bounded memory and quote-history disk growth; no duplicate collectors across tabs; independent provider failures; source-time/sequence honesty; no runaway retries; clean shutdown. Qualify actual Kalshi and Polymarket **US** separately under fresh recorded attempts. Record native gaps; the owner's expectation is not evidence.

## U4 — Shared Odds API flow within 500/month

The nominal allowance is **500 total usage credits per month**, reported by the owner, shared by Novig/ProphetX and optional reference use. Actual remaining quota and reset date must come from fresh provider headers during authorized operation; older recorded balances do not establish today's allowance. No purchase/upgrade is authorized.

Use the provider's [official request-cost contract](https://the-odds-api.com/liveapi/guides/v4/). Named bookmakers can share one region-equivalent. Common full-game winner/spread/total should use a shared sport-wide response when supported; current per-event polling amplifies cost. Return Novig and ProphetX from one request, normalize independently, and keep any included reference books reference-only. Broader event-period/futures calls are separately budgeted.

| Planning scenario | Credits, before extra calls |
| --- | --- |
| One sport, three markets, hourly, 30 days | 2,160 |
| Six sports, three markets each, hourly, 30 days | 12,960 |
| One total three-market batch slot every six hours, 31 days | 372 |
| One sport, three markets, two hourly updates per attended day, 31 days | 186 |

Engineering starting policy: keep a **50-credit reserve** inside the 500 ceiling, and pace the remaining operating allowance over the provider reset window. This is an engineering default, not a separately owner-chosen reserve. A six-hour global batch slot is an affordable upper bound only when actual remaining quota permits it; rotate useful supported sports within that shared allowance. It is not six-hour polling for all six sports. Hourly can be used in short attended windows if the same monthly budget allows it. Avoid paid idle/background refreshes, and do not charge once per tab/venue/filter/event by default. Prefer the most useful available common markets; record what did not fit the budget.

Persist only small quota/accounting/next-due state so process restart cannot reset spending. Reserve the worst-case cost before dispatch and reconcile provider headers afterward; ambiguous charges remain reserved. Include all diagnostic/retry requests in the same ceiling. Provider remaining, local reservations, reset period and rate limits bound dispatch; missing/contradictory accounting pauses metered work. No blind retries or historical API acquisition.

UI labels should say how old the aggregate observation is and indicate slower/budgeted updates. A connected browser does not make hourly data real time. Keep delayed values available for inspection while excluding unsupported fresh/guaranteed/EV calculations. Native feeds continue independently when quota is unavailable.

Acceptance: fake quota tests cover near-exhaustion, out-of-band account use, ambiguous charged failure, concurrency, multiple tabs, restart and reset; no spend above the shared allowance. Fresh small live checks verify both venue records and actual header costs. Cadence and available markets are reported, never presumed. Current `refresh_seconds≤300` and per-session budgets must be replaced in the new runtime contract without loosening sealed historical policy.

## U5 — Admin observability and site issues

Provide a separate owner/admin surface for source configuration/lifecycle, health, last source/receipt update, reconnect/backoff, subscription/discovery status, match/exclusion reasons, latency/backlog, memory, bounded log growth and Odds API used/remaining/reserved/reset/next-due information. Operator stop/pause/recovery controls belong here. Keep local-only security boundaries; moving to `/admin` is organizational separation, not authentication for hosted use.

Site issue record: source and provider website; endpoint class without secrets; attempt/candidate/time; sanitized status/code and observation; affected sport/market; impact on comparisons; successful independent paths; retries/backoff/charged credits; next engineering action; exact owner input only if needed. Distinguish provider failure from missing entitlement, no current offering, budget delay, identity mismatch and local defect. Novig/ProphetX through The Odds API should identify both provider and affected venue. International Polymarket does not replace US coverage.

Acceptance: an owner can find why a site is unavailable and what must happen next. Ordinary users see only concise actionable availability/freshness messages and relevant rule limitations. No secrets or raw operational noise on the price board. Automatic operation remains controllable from admin and application shutdown.

## U6 — Integrated qualification and readiness decision

Baseline maintenance is already complete locally: the latest [CI portability follow-up](history/ci-repair-20261002.md#follow-up--aggregate-checks-portable-without-local-archives) records a full clean-export pass without ignored aggregate archives. Do not queue that repair again. Hosted Linux CI/fresh locked installation remains unverified. The recorded local checks qualify their own revision; affected verification for new sprint changes is still required.

Run appropriate affected route/owner/security/matching/math/browser checks after each implemented seam. Update tests that encode the superseded ordinary-user scan/history layout; preserve tests for retained archive readers, once-consumed qualification, economic/identity rules and security. Do not lower assertions merely to achieve a green suite.

Verify desktop and narrow product screens with realistic mixed venue states, long names, exact spread/total lines, price updates, source disconnect/resync, open Details, keyboard focus, and one unavailable venue. Explicitly check both price formats and independent native/aggregate cadence. Use temporary local controls for fault cases, separately from fresh provider evidence. Source-specific live failures get issue records; no universal coverage-count gate.

Qualify a finite representative automatic run long enough to observe native updates, lifecycle/reconnect and bounded resources. Record duration and coverage actually seen. Qualify aggregate requests conservatively inside current monthly budget; an hour-plus provider cadence is not simulated as real evidence by speeding a clock. No arbitrary all-day burn or 24/7 SLA.

Acceptance for the new product: owner can open, find a useful same-selection comparison, read both prices, narrow it, inspect understandable Details and judge manual usefulness without operating a scan. Routine live flow does not require historical storage or replay. Admin metrics and site issues remain inspectable. Negative, zero, missing and delayed states remain honest. Explicit owner acceptance comes after this replacement UI is ready; until then status is **REVISE / not user-ready**.

## Concrete next action

Proceed next with **U3**, following the [concrete provider/service handoff](u3-current-handoff.md), [U1/U2 evidence and exact identity](../evidence/u1-u2-integration-20261002/README.md), [predict-current-1 contract/schema/examples](contracts/predict-current-1.md) and [integration map](u0-integration-map.md). The ordinary board, exact current serializer and bounded immutable selection store are implemented. Native acquisition and quota work remain follow-on scope under the standing grant and documented limits. U1/U2 performs no source attempt.

Implementation handoff must include the exact source identity, sprint status, changes/checks, actual provider observations, quota use, outstanding site issues and owner decision. Update this plan and the Desktop tracker after each completed sprint. This audit/planning pass itself ran no provider attempt and made no application change.

## U0 completion record — October 2

Complete local U0 design and contracts, with an ordinary-launcher `--u0-preview` seam and `/preview/u0` route; the ordinary default has not yet been replaced. All fixtures, IDs and matches are explicitly synthetic. Desktop and narrow rendering, all required state cases, local filters, exact lines, keyboard focus, held revision/newer adoption, expiration/restart, mixed cadence and zero/negative manual results were exercised. The versioned payload/schema, original-input Decimal rules, bounded lease/service/sink/quota/admin interfaces and exact U1–U5 reuse/replace/factor map are delivered. No unresolved U0 design blocker remains; owner feedback is outstanding and does not add an approval gate.

Entry HEAD `b2e7ad28…` and canonical digest `893a457d…` (649 files) matched. Final source identity is recorded in the evidence manifest; HEAD unchanged, no commit. Incoming dirty documentation was preserved. Affected Python checks: 42 pass; exact browser arithmetic assertions pass. Preservation checks: 109/110 pass; the sole normalization-registry-disagreement eligibility assertion also fails on untouched starting HEAD. Economic/identity/security/replay assertions remain intact. No fresh provider acquisition, credit use, credentials/watch/capture edits, deployment, recurring jobs or history/database expansion occurred. Completed CI portability work was not reopened. At U0 closeout, U1–U6 implementation/qualification and owner acceptance remained ahead.


## U1/U2 completion record — October 2

Ordinary `/` now opens the grouped board and readable Details; default current provider is honestly unavailable without archive or synthetic fallback. Preserved engineering inspection is `/admin/retained`; `/preview/u0` remains isolated. Shared keyed rendering retains local filters, exact group lines/periods, native alternatives, both price formats, concise mixed source states, scroll/focus stability and an inert narrow Details dialog. Current server serialization preserves exact original financial strings and binds all 15 venue-filter comparison contexts. Independent engine outputs and explicit-assumption What-if remain separate. Atomic bounded commits/notices, age transitions, slow-consumer limits and immutable reviews handle runtime/revision changes, TTL, explicit adoption/release, failed adoption and capacity without eviction.

Entry HEAD/digest matched the requested `b2e7ad28…` / `cfdf61033…`, 656 source files. Final HEAD remains `b2e7ad28b5b35e04d0f8d608e37b150aa40a89bc`; canonical digest `e093350e0da58a749f9ee148ef4dcd85e0a6e3c04f623b97d833b9dbe47a70b1` over 663 application source files. Exact identity/manifests, test logs, final wheel SHA, screenshots, browser coverage and isolated populated workflow are in [the evidence package](../evidence/u1-u2-integration-20261002/README.md). Five existing application files were factored/hardened for integration; 651 entry files match their hashes, with seven new interface/serializer/provider assets. Incoming U0 and unrelated work remains preserved.

Final affected checks: 69 + 19 tests pass in separate bounded processes; retained routes 49, isolated product integration 1, security hardening 9 pass. Seven browser/client scripts pass. Contract examples pass structural/timestamp and exact semantic reproduction checks, with U0 structural compatibility; source-checkout and isolated packaged routes/assets pass. Preserved invariant/replay checks: 165/166 pass; the unchanged normalization-registry-disagreement baseline failure remains separately recorded. Combined-process RSS cap failures and an intermediate test invocation error are retained; final isolated checks keep the original caps/assertions. Initial exact-zero scenario and browser scroll/focus defects were repaired and reverified.

No provider request, source entitlement check, credit use, credential/watch/capture/consumed-authority edit, trading, deployment, recurring job, history/database expansion, commit or push occurred. Live access/cadence, source-owned freshness facts, U4 quota, U5 admin operation, U6 qualification, owner acceptance and product readiness remain outstanding. Stop at U1/U2; [U3 handoff](u3-current-handoff.md) is delivered for the next sprint.
