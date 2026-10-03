# Current scope override — October 1, 2026

**Beta/V1: data ingestion and comparison for manual trading. V2: automated trading and execution.** [Current definition](product-roadmap-review.md) and [complete gate reconciliation](full-scope-engineering-reconciliation.md) supersede earlier completion/next-action language below. V1 requires reliable independent four-venue data, correct six-sport/63-cell matching, useful raw comparisons, timestamps/stale/health, settlement differences/supported fee estimates, Details/filters/watches/Start/Stop/history/download/exact reopening, and informational sizing where supported. Pinnacle/DraftKings/BetMGM remain reference-only; Novig/ProphetX aggregate prices require no native trading access.

Account classification, actual fills/positions, execution charges and complete net/EV economics apply only to a displayed calculation that needs them; missing inputs withhold or label that output while preserving valid raw comparisons. The account-document request is inactive as a prerequisite. Automated submission/orchestration, fills/positions synchronization, execution reconciliation and automated-trading timing qualification are V2; direct Novig/ProphetX integration remains deferred. V1 data freshness/source health remain required and are not order-path latency qualification.

No new reproduced defect exists in the October 1 verified supported paths. Completed math/transport/lifecycle/replay/layout and all implementation/evidence remain preserved. Broader actual required coverage remains open. Owner walkthroughs/commercial validation stay deferred. Earlier native provisioning, execution-domain and private-economics gates below are historical where inconsistent with this scope. Existing consumed authorities remain closed; no new acquisition, access or outreach is requested.

---

## Preserved earlier commercial value engineering and evidence

# Predict — engineering for paid usefulness

**September 29 work-order correction:** complete full four-venue/six-sport engineering before owner walkthroughs, usefulness evaluation or customer/payment validation. E1–E5 is a scoped package only. The [full-scope reconciliation](full-scope-engineering-reconciliation.md) records current repairs, requirement-level evidence and externally blocked native implementation. Evaluation suggestions below are deferred; no sizes/thresholds decision or new collection is requested.

Updated September 29, 2026. **E1–E5 LOCAL ENGINEERING COMPLETE. Real-data qualification, beta signoff and customer/payment validation remain pending.** Owner requested this priority after comparing the apps' revenue potential. Complete the package before asking for another general owner walkthrough. This is an engineering work order, not a claim that Predict is already the best business.

## Starting point

Reviewed source HEAD `2d9b509540ce3fab8025828d86ee58d65cbdf975`, clean at entry to this documentation change. The September 28 supervised session demonstrated four games/eight comparisons, ordinary Stop, event links and exact saved reopening. Settlement conflicts and unknown net economics remain. Preserve all original evidence and consumed attempts.

Existing code already supplies fee calculation (`app/fees/`), depth scenarios (`app/depth.py`), shared product calculations (`app/dashboard/product_view.py`), comparison cards, source health and immutable session replay (`app/dashboard/session_history.py`). `app/dashboard/pipeline.py` already calls the depth engine. Reuse these; do not build parallel calculators or call implemented engines missing. Current card Details expose evaluated size and raw settlement data; the work below makes decision support and longitudinal review usable in the ordinary app. No dedicated watchlist/threshold/opportunity-duration implementation was found in the targeted source review; verify integration points while implementing.

The product question is: can a user quickly identify a worthwhile comparison, understand its limits at their intended size, and review whether useful signals recur? Engineering can answer usability and arithmetic questions with retained data. New market observations and actual customer willingness to pay remain separate evidence.

## Ordered engineering package

### E1 — Explain comparability and economics in ordinary Details

Extend the current cards/Details with a concise decision summary: exact event, market, side and period; comparable or conflicting settlement terms; supported versus provisional versus unknown costs; source age/alignment; available quantity; and the specific reason a net result is unavailable. Present known fee components and relevant exceptional settlement branches in plain language before optional raw evidence.

Use existing rule assessments and retained source references. Separate missing evidence from fixable integration defects. Bind supported rules to exact native IDs and effective versions. The retained Kalshi 48-hour versus US two-week postponement conflict must remain visible and must prevent unsupported equivalence claims. Do not remove conflicts, invent zero charges, or convert owner-accepted provisional fees into verified economics. Raw price comparisons remain useful and visible.

Done when ordinary live-shaped fixtures and saved sessions explain supported, provisional, missing and conflicting cases consistently; exact saved inputs reproduce the same explanation and calculations. Close locally supported wiring/propagation defects found along the way. Record only the remaining specific external evidence dependencies.

### E2 — Make intended-size comparison useful

Connect or extend the existing size/depth calculations in ordinary Details so a user can compare a few explicit contract sizes or a manually entered spending ceiling. Show each venue's modeled acquisition cost, supported fees, combined committed cash, conditional net/return and depth limit. Where the existing finite-depth solver can support it, show its best size within the supplied depth and evaluated search domain; disclose incomplete searches and shared liquidity.

Preserve quantity increments, fractional units, price levels, fee rounding and partial-fill assumptions. A top quote with unknown deeper liquidity cannot support a larger order. If native depth or material economics is unavailable, show the specific limitation and only supported arithmetic. A modeled acquisition is not a fill guarantee or an order instruction. Reuse the shared engine; keep supported EV% ranking, separate arbitrage return, and raw comparison ordering unchanged.

Done when independent hand-calculated examples cover fee rounding, multiple levels, insufficient depth, fractional quantity and zero/negative returns; ordinary UI and saved reopening agree with engine results. Verify the newly connected path, not just existing standalone solver tests.

### E3 — Saved watchlists and in-app signals

Add saved market/venue filters and explicit user thresholds for raw gap, supported arbitrage return or supported EV, keeping each metric separately labeled. Evaluate against observations already admitted to an explicitly started session. Surface changes in the app with deduplication and a clear reason/time; avoid repeated notifications on every poll. Unknown or stale required inputs must suppress qualified signals, and a previously valid signal must visibly expire when its basis stops qualifying.

Watchlist persistence must not restore collection authority. Saved replay is historical review and must not issue fresh live signals. Implement no email, messaging, OS push, background scheduler, auto-start collection or trading. Preserve current stable card layout and open Details; use a small secondary watchlist/history surface.

Done when threshold crossings, recovery, stale/disconnected sources, repeated identical observations, Stop, restart and historical reopening behave deterministically in fixtures. Observe existing resource caps; derive compact events without duplicating full journals.

### E4 — Opportunity history and evidence of usefulness

Build a read-only summary from retained journals and the shared calculation path: distinct candidate identities, first/last qualifying observed cutoffs, changes in gap/return/size, number of qualifying observations, and reasons comparisons were excluded or ceased qualifying. Separate raw comparisons from supported net calculations and distinguish real retained observations from simulations.

Report observed spans and data gaps honestly: sampled quotes do not prove continuous availability between samples. Never sum repeated snapshots or overlapping/shared-liquidity alternatives into profit. Do not label modeled returns as realized P&L, infer fills, or use later outcomes/terms to improve earlier decisions. Preserve effective calculation/fee versions and original saved outputs; derived new-version analysis must be labeled separately and must not rewrite source evidence.

Provide ordinary-app drilldown to the exact saved cutoff and a compact downloadable report of the summary, assumptions and coverage. A session with no qualifying opportunities is a valid result. The short existing sessions can test the machinery but cannot establish typical opportunity frequency or profitability.

Done when synthetic known timelines and retained real sessions reconcile to their original records, deduplication survives reopening, gaps break continuity, and every summary item can be traced to its original inputs.

### E5 — Complete integrated delivery and list only external blockers

Exercise E1–E4 together in the ordinary app using isolated synthetic data and retained journals. Verify relevant math, identities, grouping, threshold transitions, history, exact replay, source-failure isolation, bounded resources and Stop. Run required repository checks and affected browser checks; preserve existing data and the accepted readable layout. Record the final source identity and package result, with local checks distinguished from historical live evidence.

Do not rerun the completed thirty-minute offline campaign or start a performance project without a concrete regression. The 250 ms target remains aspirational. Optional predictive models, KenPom, MoneyPuck and NHL analytics do not become prerequisites. Reconcile supplied Novig/ProphetX contracts only if actual new evidence is available; speculative adapters are not part of this package.

Done when all five items have implemented behavior and retained completion evidence, or a specific externally blocked subitem is explicitly separated while all independent local work is complete. Missing native facts must not stop watchlist/history or explanation work. The handoff must distinguish **engineering complete**, **real-data qualification pending**, and **customer/payment validation pending**. No automatic claim of profitability or number-one commercial ranking follows.

## Work order and boundaries

Start E1 in the ordinary shared app, proceed through E2–E5, and resolve routine reversible implementation choices without another broad planning exercise. Inventory already implemented behavior once and complete only genuine integration/new-feature gaps. The September 29 request authorized this local implementation; completion evidence is recorded below.

After local engineering completion, prepare the smallest useful market-observation evaluation that can measure supported signal frequency, observed persistence and size. If exact native terms/access are still missing, name those blockers instead of fabricating an executable proposal. New credential access, market collection, provider outreach, spending or trading requires its own applicable authorization; earlier consumed attempts remain closed. Existing withdrawal of Kalshi/US outreach remains in force. This documentation change starts no live session, automation, commit, push or publication.

Preserve the later all-four-venue, six-sport beta scope in the [product definition](product-roadmap-review.md). Commercial prioritization does not silently reduce that scope. Owner review of the retained eight-card session remains available but is not a prerequisite to this local engineering package.

## September 29 implementation record

E1–E5 behavior is implemented in the ordinary app. [Detailed delivery and external dependencies](commercial-value-handoff.md) · [retained verification evidence](../evidence/commercial-engineering-20260929/README.md). Final verification passed: 707 repository Python tests plus JavaScript checks, 108 fee/depth/arbitrage checks, 12 connected commercial workflow tests, ordinary browser checks and two retained-session audits. Delivered source identity: `064363b81bb09841eaa62fb6a398a50ad11d0df4b7173b0a68789faa1a997a94` over 448 files at base HEAD `2d9b509540ce3fab8025828d86ee58d65cbdf975`; all manifest files rechecked unchanged after verification. The 12 connected tests are included in the 707 repository count; these totals are not additive.

The original work order and pre-existing documentation edits were copied and hashed at entry. The shared fee, depth-consumption, product calculation, source-health and immutable replay paths are reused. Watch definitions and derived reports are separate from original journals. The existing readable card layout and ranking remain in place.

The explicitly bounded size search is among user-entered sizes; native fractional execution and a complete native depth domain are not fabricated. History distinguishes sampled spans from continuous availability, counts dropped details/skipped cutoffs, and provides exact-cutoff links for excluded candidates as well as qualifying observations. Current UI sampling and complete-within-budget historical reconstruction are labeled separately.

Latest retained session `860107f6-56ff-44fe-9fd0-088ceaabe2a6` preserves exact original snapshot, calculations and native replay; its report evaluates 1,148 cutoffs with zero skipped cutoffs. Earlier session `b2391410-91d5-4c1a-aa19-cf5c94f6ae87` evaluates 1,082 cutoffs and traces all 56 summary items. All 49 audited original files and both pre-existing roadmap edits remain unchanged. No selected watch qualified in these retained reports; unavailable economics remain explicit. Browser verification covered sizes/ceiling, persisted watches, historical download, exact cutoff navigation, open Details and Stop-response isolation.

The package is locally complete within the stated native-evidence and size-domain limits. Specific external dependencies and the smallest useful next evaluation are in the handoff; no new collection or customer/payment validation is inferred.
