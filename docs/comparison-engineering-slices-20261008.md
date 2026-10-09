# Predict comparison, costs and coverage delivery slices

Updated October 8, 2026, America/New_York. Status: **engineering resumed by the owner; P00 software kickoff active**. This is the active engineering work order for the owner's mapping, coverage, fees, ranking and readability corrections. Earlier delivery reports remain dated evidence. The October 7 walkthrough queue is superseded.

[Desktop tracker](../../prediction_arb_next_steps.md) · [Repository plan](../PLAN.md) · [Lead pickup](u6-current-handoff.md)

## Product outcome

Deliver one game comparison with canonical selections, native venue prices, the actual Pinnacle baseline and understandable estimated net EV. Provide separate EV and Arbs rankings, calculated after scoped fees and conservative buffers. Show the two arb legs and their payout scenarios. Keep the board compact; explanations, original values and evidence belong in Details. Show sport/source coverage so an empty market, an unchecked sport and a failed source are distinguishable.

The application remains a read-only local comparison tool. The primary workflow requires no stake entry. Quantity-dependent estimates use a disclosed comparison-size policy; the user can change size in Details. Existing automatic aggregate operation checks NFL, NCAAF, NBA, NCAAB, MLB and NHL every 15 minutes during 09:00 inclusive–23:00 exclusive Eastern while the app runs. Native coverage must be expanded deliberately beyond its current NFL scope, retaining bounded discovery, stream ownership and Stop.

## Pickup facts and evidence boundaries

- Repository: `/Users/michaelfuscoletti/Desktop/prediction-arb`; documentation audit HEAD: `4bafe4532c68fd53ce7ba9236decec46bb872c15` on `main`, with substantial existing uncommitted work. HEAD alone does not identify that working candidate. P00 must record the code/configuration digest and changed-file manifest before implementation. Preserve all existing edits, private settings, credentials, quota attempts, receipts and historical evidence.
- Aggregate six-sport scope and Pinnacle gross proportional no-vig benchmark are implemented. Native discovery remains NFL. Newer incremental projection and changed-event transport are present in the working tree; their bounded evidence is in [incremental updates](incremental-updates-20261008.md). They are a baseline to qualify and preserve, not a reason to restart that work.
- Current `current_overlap.py` still joins only reviewed direct full-game winners using exact league/start/home/away. Lower-level normalized event identities also include schedule fields. Fix both layers; removing one time comparison alone is insufficient.
- A draft `app/fixtures/current-aggregate-occurrences-20261008.json` records the retained Cowboys–Buccaneers provider ID link. It is **not wired into the current associator** and is not qualified as a general identity solution. Treat it as a candidate research input, not a completed repair.
- The same retained Odds API event ID `259b5df9aa0d10257f56de78523495e0` appears with 8:15 and 8:18 p.m. Eastern starts. Native reviewed game ID is `aa6b58bf-4feb-11f1-abca-2c54536568a9`. This is the concrete clock-drift regression; canonical linkage must have provenance beyond team labels and clock proximity. Existing native occurrence evidence is pregame and dated; durable current identity cannot depend forever on that one fixture.
- A read-only audit of latest redacted receipts found Novig/ProphetX rows for NFL 174/90, NCAAF 338/326, NBA 84/0, NCAAB 0/0, MLB 12/12 and NHL 84/54. Receipts were October 8 at approximately 7:52–8:00 p.m. Eastern; these are quote-row counts from separate sport receipts, not simultaneous coverage or future availability. Latest files are mutable. P00/D05 must retain sanitized audit identities before using them as qualification evidence. Novig is not NFL-only; native Polymarket coverage and display visibility are separate gaps.
- Existing fee, depth and state-space engines should be reused. `app/fees/public_bindings.py`, `precision_envelope.py`, `entry_bounds.py`, `engine.py`, `app/settlement.py`, `app/depth.py` and `app/arbitrage.py` contain relevant work. Current live-board adapters do not yet bind complete cost/scenario inputs. Refresh effective rule applicability; do not assume historical rates or account schedules are current.
- `current_benchmark.py` supplies conditional before-fee EV. `current_contract.arbitrage_pairs()` supplies gross pairs and withholds net values. The new path must distinguish Pinnacle benchmark estimates from independent/calibrated model EV rather than pretending the benchmark satisfies the existing model-probability contract.

This planning update performs no implementation, source refresh, runtime restart, order, account reset, commit or release. Future engineers work within the owner's existing read-only operation authorization and accounting limits; this document is not a fresh unlimited acquisition budget.

## Contracts the leads must agree

### Identity and meaning

A canonical event uses an evidenced durable game/occurrence identifier, league and canonical participants with roles. Maintain provider-ID edges and their evidence/conflicts. Scheduled start, original start, live status and reschedule history are versioned metadata. They may corroborate an investigation but may not decide an automatic match or create a new identity solely because the start moved. Repeated opponents, doubleheaders, rematches and replacements must remain distinct; unresolved links stay visible with one concise reason.

A market comparison uses event identity, family, period/overtime scope, participant, exact signed line/threshold and typed predicate. Translate source wording and YES/NO or Long/Short only through evidenced native outcome definitions. Separate semantic comparison from settlement eligibility. Similar prices or labels do not establish equivalent cashflows.

### Cashflows and probabilities

For each relevant joint sporting/venue state, retain the payout of each leg and applicable costs. Full-result states must be feasible, mutually exclusive and exhaustive; overlapping cancellation/postponement/abandonment labels cannot be separate probability buckets merely because their assigned probabilities sum to one. Different rules can produce useful calculations without being declared identical. State-specific and conditional results remain available even when one exceptional state is unresolved. An all-modeled-outcome arb requires a complete state set and sufficient payout evidence for every included state; unresolved exceptional states cannot silently disappear from that category.

EV is probability-weighted net profit divided by the disclosed deployed capital basis. Pinnacle proportional no-vig probabilities are a market benchmark. A two-way quote does not supply a tie or push probability. Use a researched estimate with its provenance, or show conditional benchmark EV with its condition. Never invent a missing probability to fill a ranking. Cancellation/refund may be a disclosed scenario rather than an arbitrarily assigned probability.

### Fees, buffers and quantity

Separate evidenced public/account fees, estimated fee bounds, execution-price buffers, quantity/depth limits and prefunded liability. Each input has applicability, version, basis and units. Estimate missing costs with a sourced bound or explicit scenario; an arbitrary buffer cannot replace an unknown fee rule. Choose routine conservative pilot defaults autonomously, document them and make them adjustable. Do not globally block the board on an account-only fact that affects one venue or calculation.

Distinguish a standalone hypothetical market fee from incremental commission on an existing market portfolio. Missing positions can use a labeled standalone assumption, never an observed account fee. Exclude uncertain rebates/credits from conservative defaults; contingent or later credits remain separate, and cash required before their receipt must be funded.

Round on the actual fee unit/order/market basis. Quantity and fragmentation can change net percentages. Choose one disclosed comparison-size/risk policy before ranking; estimates at different sizes or fee bases must not be presented as directly comparable. Acquisition capital, refundable reserves and settlement charges must not be double counted. Reuse the existing engine's capital-plus-prefunded-liability treatment where applicable.

### Presentation and rankings

Default odds board: Selection | Kalshi | Polymarket US | Novig | ProphetX | Pinnacle | Est. net EV. Pinnacle is a reference, not a tradeable venue or arb leg. Display actual selected-side American odds with original decimal odds and both-side no-vig calculation in Details. Only show a native side label in the cell when it resolves a meaningful ambiguity.

Default cell: odds and, where needed, one short status. Avoid repeating equivalent cents, age, freshness paragraphs, EV and fee explanations in every cell. Shared venue/batch age may appear once in a header; heterogeneous quotes keep their own short age/status. Details always retain exact clocks. A dash has a short accessible explanation; source failure differs from an absent selection.

EV view ranks selection/venue opportunities by signed estimated net benchmark EV at the disclosed comparison size, with Pinnacle odds and short estimate/conditional status. Complete-state and conditional EV use separate ranking categories or an explicit basis filter; the board compares best EV only among candidates with the same conditioning/probability and size basis. Arbs ranks paired opportunities by buffered worst-case net return over the included modeled scenarios; conditional pairs are separately selectable and their limiting state is visible. Positive, zero and negative results remain inspectable. Profit in dollars, risk capital, assumptions and depth are secondary details. Sorting must update without losing selected Details or causing disruptive continuous reordering.

## Execution order and slice status

P00 is **in progress** for the resumed software-lead kickoff. R01–R08 and retained D05 preparation are queued after its baseline gate; other slices remain **not started**. Leads can parallelize independent work in each wave; dependent work starts only after the required artifact is reviewable. A slice can complete offline while live qualification or owner feedback remains pending, provided its evidence class is explicit.

| Wave | Slices | Primary handoff |
|---|---|---|
| 0: establish baseline | P00 | Exact working candidate and current gap ledger |
| 1: research and design | R01–R08 in parallel after P00 | Versioned source, payout, fee, probability and display decisions |
| 2: identity and useful coverage | D01–D07; honor individual dependencies | Canonical event/outcome links and measurable source scope |
| 3: calculation inputs | D08–D10, S01–S03 | Bound baseline, cost, scenario and estimate contracts |
| 4: net calculations and interfaces | S04–S11; independent UI work may use authored fixtures | Sortable net estimates, clean board and drill-down |
| 5: qualify and hand back | Q01–Q04 | Exact-candidate checks, bounded live evidence and owner review |

## Baseline slice

### P00 — Candidate, gap ledger and integration boundaries

**Lead:** software, with research/data review. **Depends:** none.

**Work:** Re-read this plan, tracker, current handoff and actual worktree. Record HEAD plus current source/configuration hashes, uncommitted edits and relevant retained evidence. Map existing fee/settlement/probability/current-store interfaces. Record what is implemented, drafted, dated, observed or absent; resolve conflicting older queue text. Identify the ordinary runtime without changing it.

**Done when:** A sanitized candidate manifest and integration map identify exact entry points, all owner-reported regressions and the distinction between six-sport aggregate scope and NFL native scope. No secret or private full payload enters the plan. Existing attempts, due times and editable work are preserved.

**Handoff:** `docs/comparison-p00-baseline.md`, a gap ledger with one owning slice per gap, and ready-state entries for R01–R08. A path or account blocker affects only dependent work; independent retained-data research continues.

## Lead research slices

### R01 — Source and market coverage contract

**Lead:** research; data reviews. **Depends:** P00.

**Work:** Review official documentation and existing public contracts for Kalshi, Polymarket US, Novig, ProphetX and Pinnacle/Odds API. Build sport × venue × family × period coverage, distinguishing documented support, selectors, configured scope, observed offerings and unresolved access. Separate Polymarket US from other Polymarket products. Confirm API versus website/account distinctions.

**Done when:** All six supported sports have cells, sources, retrieval dates and explicit query/response meanings. An empty or failed sample is not labeled unsupported. No guessed endpoint is introduced. Each expansion has a documented selector and bounded discovery need.

**Handoff:** `docs/comparison-r01-coverage.md` plus a machine-readable coverage definition proposal for D05/D06. No broad collection campaign to complete the matrix.

### R02 — Winner and YES/NO payout meanings

**Lead:** research. **Depends:** P00.

**Work:** Research direct winner, team YES, team NO and US Long/Short meanings. Capture win, loss, draw/tie, half payout, refund, void and fair-value clauses from applicable primary sources/retained instruments. Identify when two ways of phrasing a bet have the same predicate and when they only have conditional overlap.

**Done when:** Dallas YES/normal moneyline and Dallas NO/opponent moneyline have explicit state tables. A tie payout difference changes the cashflow row rather than blocking all comparison. Exact native side IDs and clause applicability accompany examples.

**Handoff:** `docs/comparison-r02-winner-states.md` and reviewed authored state examples for D01/D03/D04/S01. Missing exceptional decisions remain local unknown states.

### R03 — Spread, total, period and equality semantics

**Lead:** research. **Depends:** P00.

**Work:** Define signed handicap orientation, combined versus team totals, strict/inclusive operators, integer push, half-line equality, regulation/overtime and supported periods. Review native score binding and sporting-result adapters before adding new semantics. Include negative handicaps, anchor reversal and alternate lines.

**Done when:** “wins by more than 8.5,” team −8.5 and their complementary side map through the same score predicate when justified. At integer 8, native NO ≤8 remains distinguishable from a sportsbook bet that pushes at 8. Full game and first half cannot merge.

**Handoff:** `docs/comparison-r03-lines-periods.md` with controlled test vectors for D01/D03/S01. Unsupported families remain scoped out of this pilot.

### R04 — Event lifecycle and exceptional settlement

**Lead:** research; data reviews. **Depends:** R02/R03.

**Work:** Review postponed, rescheduled, suspended, cancelled, abandoned and corrected results, including venue timing windows and discretionary settlement. Define game continuity versus replacement and identity evidence that remains valid pregame/live/completed. Separate game identity from effective payout terms.

**Done when:** The existing dated Cowboys fixture is a regression input, not permanent authority. A schedule shift preserves a documented game; a replacement/rematch requires a separate occurrence or evidenced supersession. Each exceptional state has a sourced payout, bounded estimate or local unknown, without suppressing known normal-state results.

**Handoff:** `docs/comparison-r04-lifecycle.md` to D02/D04/D07/S01; identify precise unresolved provider facts rather than a global “ties cannot compare” gate.

### R05 — Applicable fee schedules for all execution venues

**Lead:** research; software reviews. **Depends:** P00.

**Work:** Audit existing public fee bindings against current primary rules for Kalshi, Polymarket US, Novig and ProphetX. Cover maker/taker, event/market exceptions, fee base, minimums, caps, order/market aggregation, rounding, settlement fees and account/API differences. Pinnacle contributes benchmark prices only; its betting fee is not an execution leg here.

**Done when:** Each venue has a reproducible applicability table and example at at least two sizes. Existing successor/legacy bindings stay versioned. A negotiated or account-specific rate is not replaced by an unrelated public website rate. Unavailable exact fees identify a defensible bound or clearly named estimate input. Portfolio net-gain fees distinguish standalone assumptions from incremental fees on existing positions; conditional rebates do not reduce default funding requirements.

**Handoff:** `docs/comparison-r05-fees.md` and versioned binding updates proposed for D09/S02. Stop the unsupported fee claim, not unrelated venue displays.

### R06 — Comparison size and conservative buffer policy

**Lead:** research and software jointly. **Depends:** R05; R01 scope.

**Work:** Choose the pilot comparison size/risk basis and documented defaults for adverse movement, rounding uncertainty, quote age and visible-depth shortfall. Separate conservative cost bounds from probability distributions. Explain how fees and order fragmentation change the result. Specify when to decline a bounded estimate rather than fabricate one.

**Done when:** One size policy permits zero required user input, is visible beside rankings, and yields comparable risk-capital denominators across contract and sportsbook units. The same fee or reserve is counted once. Increasing a cost buffer cannot improve an otherwise unchanged estimate. Defaults have a reason and sensitivity examples.

**Handoff:** `docs/comparison-r06-estimate-policy.md` to D09/S02/S03/S04/S05; optional size editing belongs in Details, not an entry gate.

### R07 — Pinnacle benchmark, tie and push probability policy

**Lead:** research; software reviews. **Depends:** R02/R03; can start from P00.

**Work:** Specify supported two-way and explicit three-way de-vig methods, source alignment, reference age, and estimated tie/push inputs. Review available documented evidence and existing score-lines probability work. Distinguish market benchmark estimates, conditional decisive-outcome probabilities and independent calibrated models.

**Done when:** Two-way odds cannot silently create a third probability. Complete scenario probabilities sum to one over a feasible, mutually exclusive, exhaustive state space. Equal probability sums do not excuse overlapping outcome buckets. Unknown tie/push probabilities leave a useful conditional estimate with its condition. Changing a reference or assumption invalidates dependent EV. Both Pinnacle original prices are retained and selected side is explicit.

**Handoff:** `docs/comparison-r07-probabilities.md` to D08/S04. A provisional probability is labeled estimated with provenance and sensitivity, never falsely independent.

### R08 — Product layout and reading-order decisions

**Lead:** software; research/data review language. **Depends:** P00; incorporate R01–R07 before final handoff.

**Work:** Produce a low-fidelity annotated wireflow for Odds, EV, Arbs, Details and Coverage using the owner's Toronto and Cowboys examples. Agree short statuses, what is shown once, the default odds format, default sort and stability while prices update. Include narrow-screen behavior and a no-opportunity case.

**Done when:** A user can find the game, venue price, actual Pinnacle number, best estimated net EV and arb legs without reading a paragraph in each box. Tie and fee details are accessible once. No stake entry is required. The layout accommodates unavailable individual sources without blanking the game.

**Handoff:** `docs/comparison-r08-wireflow.md` with fixed authored examples for S07–S11 and Q04. Do not publish or redesign unrelated product surfaces.

## Lead data engineering slices

### D01 — Canonical market, outcome and payout vocabulary

**Lead:** data; research/software review. **Depends:** R02/R03; P00.

**Work:** Define a versioned canonical schema for durable event reference, family, period/overtime, participant/role, signed line, score operator and native side provenance. Represent semantic predicate separately from payout profile and price units. Define explicit equality/unknown-state descriptors.

**Done when:** Moneyline, team binary, spread and total examples retain exact original meaning. Labels and side words do not determine canonical identity. Different overtime/push scopes cannot merge accidentally. Rational/decimal originals survive serialization without display rounding.

**Handoff:** `docs/comparison-d01-domain.md` plus authored schema fixtures for D02/D03/D04/D08 and software consumers. Version current contracts without rewriting sealed historical records.

### D02 — Durable event identity and provider-ID crosswalk

**Lead:** data. **Depends:** D01/R04.

**Work:** Replace time-based current association with evidenced provider-ID links to a durable game occurrence. Audit `current_overlap.py`, `current_occurrence.py`, `current_normalized.py` and sport `event_key` implementations; distinguish current identity migration from frozen historical identity. Store link provenance, confidence class, conflict and supersession. Define a bounded review path where no shared ID is exposed.

**Done when:** The same provider ID with 8:15→8:18 metadata keeps one current game and selection revision lineage. Identical teams/start/type with a different occurrence never auto-merge. Doubleheaders, rematches, swapped roles, conflicting IDs and replacements have explicit rejection/continuity tests. No automatic fallback uses time proximity alone. Manually reviewed links are labeled as such.

**Handoff:** `docs/comparison-d02-event-links.md`, portable link fixtures and a migration note to D03/D04/D07/D08/D10. Invalid crosswalk evidence blocks that match only; prices remain visible.

### D03 — Source phrasing and native-side adapters

**Lead:** data. **Depends:** D01/D02/R02/R03.

**Work:** Adapt Kalshi YES/NO, US Long/Short and sportsbook outcome lines to canonical typed predicates. Reuse structured participants, exact native IDs, documented market types and source score operators. Preserve original wording and instrument IDs. Map a complement only when its payout meaning supports that comparison category.

**Done when:** Direct team win phrasing unifies correctly; team NO is never silently opponent YES. Half-point equivalent spreads/totals join across different wording and anchor orientation. Integer equality, different line, different period and unresolved participant stay distinguishable. Duplicate source instruments cannot produce duplicate preferred quotes or fake opportunities.

**Handoff:** `docs/comparison-d03-outcome-adapters.md` and portable matrix fixtures to D04/D08/D10/S01. No ad-hoc team-name regex becomes final evidence.

### D04 — Settlement-profile and joint-state input binding

**Lead:** data with research. **Depends:** D01/D03/R04.

**Work:** Bind applicable venue clauses to a versioned payout profile and exact selection. Produce joint states for selected legs, including ordinary result and relevant exceptional cases. Carry source/effective-date and estimated/unknown flags to the calculation adapter. Use bounded shared profiles rather than copying large rule documents into every quote.

**Done when:** Different tie payouts appear in the same scenario table without claiming rule equivalence. Unknown cancellation treatment marks that state unknown. Profiles cannot attach to a sibling instrument or stale rule version. Full-result joint state coverage is feasible, mutually exclusive and exhaustive; contradictory combinations and overlapping labels are rejected. A rules amendment advances dependent calculation revision.

**Handoff:** `docs/comparison-d04-payout-inputs.md` and authored state matrices to S01/S04/S05; no numeric zero substitutes for unknown payout.

### D05 — Sport/source coverage and precise gap diagnostics

**Lead:** data. **Depends:** R01/P00; independent of D02.

**Work:** Instrument each sport/venue discovery, book and aggregate admission stage with last check, configured scope, observed games/markets/quotes and exact exclusion reason. Separate not checked, no offerings returned, filtered out, unresolved mapping, rejected payload and failed source. Retain bounded sanitized evidence and last-success context.

**Done when:** NFL-only native configuration is visible and aggregate NHL/NBA rows are counted independently. An empty NCAAB result retires prior stale offerings with the correct reason. Query-specific absence does not become global provider non-support. Counts reconcile to the displayed filtered inventory, including why a game is not shown.

**Handoff:** `docs/comparison-d05-coverage-diagnostics.md` and coverage API proposal to D06/D07/S11/Q03. Reads and UI filters never trigger provider acquisition.

### D06 — Bounded native discovery across supported sports

**Lead:** data. **Depends:** R01/D05; D01 terminology.

**Work:** Expand documented Kalshi/US sport selectors beyond NFL with bounded pagination, fair per-sport/family selection, refresh rotation and explicit catalog completeness. Inventory all configured sports even where nothing is offered. Reuse existing request/byte/market caps; design sharing before proposing any resource-policy change.

**Done when:** Controlled catalogs exercise all six sports, multiple pages and empty/out-of-season cells. A crowded sport cannot starve another or exceed the global bound. One target per first page is not reported as complete coverage. A concrete cap/access failure is isolated and reported. Expanded scope has a reviewable request and retained-memory budget.

**Handoff:** `docs/comparison-d06-native-discovery.md` with budget arithmetic, authored paginated fixtures and remaining live targets for D07/Q03. Do not raise caps merely to make a failing broad listing pass.

### D07 — Stream lifecycle, retirement and event continuity

**Lead:** data. **Depends:** D02/D05/D06/R04.

**Work:** Reconcile selected inventory against owned subscriptions, initial books, reconnects, retired markets and pregame/live transitions. Make schedule and status changes metadata updates while preserving linked game identity where evidenced. Separate discovery eligibility from payoff-profile eligibility and quote freshness.

**Done when:** Adding/removing a market creates/closes exactly the needed owned work. Catalog churn does not duplicate streams or keep retired prices current. Unchanged-price complete-book confirmation does not alter original exchange time. Stop revokes dispatch before cleanup. A dated fixture expiring does not silently become generic authority or erase unrelated markets.

**Handoff:** `docs/comparison-d07-stream-lifecycle.md` and bounded lifecycle tests to D10/Q02/Q03. Preserve existing recovery ownership and consumed attempts.

### D08 — Exact Pinnacle reference joins and age policy

**Lead:** data. **Depends:** D02/D03/R07.

**Work:** Bind the exact Pinnacle game/type/period/line/outcome to current selections. Retain both sides or an evidenced explicit three-way set, originals, selected index, receipt hash and independent source clocks. Use the shared aggregate request; a display feature must not acquire another feed.

**Done when:** All matched venue selections can reference the same correct baseline even when source phrasing differs. Different line or missing opposition cannot attach. Receipt/heartbeat never refreshes price age. Reference-only changes and expiry invalidate EV while preserving venue prices. Original selected Pinnacle odds are accessible directly for display.

**Handoff:** `docs/comparison-d08-pinnacle.md`, reference fixtures and compatibility note to S04/S07/S08/S10. Incomplete references disable affected EV, not the game.

### D09 — Fee, estimate and comparison-size input registry

**Lead:** data with software. **Depends:** R05/R06/D01.

**Work:** Bind cost versions, source/account applicability, assumptions, estimate bounds, size policy and unit conversions to each leg. Keep execution-provider facts distinct from aggregate delivery metadata. Define estimate provenance, expiry, override precedence and privacy boundaries; no full account secrets in quote payloads.

**Done when:** The same amount has unambiguous currency/contracts/risk/payout units. Public versus account schedules never substitute silently. Size changes and fee updates invalidate net metrics. Defaults are usable without required owner entry; a missing bounded input produces a short local reason and retains gross/conditional outputs. Absent market positions select a disclosed standalone hypothetical fee scenario; contingent rebates/credits remain distinct from immediate cash requirements.

**Handoff:** `docs/comparison-d09-cost-inputs.md` and controlled cost fixtures to S02/S03/S04/S05/S10. No observed fee claim without evidence.

### D10 — Latest-state revisions, cache invalidation and transport

**Lead:** data/software jointly. **Depends:** D02–D04/D07–D09.

**Work:** Extend latest-only group projection and changed-event responses for identity, payout, reference, fee, quantity, buffer and probability revisions. Share bounded immutable profiles rather than repeat evidence graphs. Preserve atomic validation, cursor fallback, removal tombstones and source-clock ageing.

**Done when:** Any changed dependency refreshes all affected estimates exactly once; unaffected groups reuse equivalent results. Schedule correction alone does not create duplicate games. Retired quotes disappear; old cursors recover through a full snapshot. Unknown/future clocks remain unknown/ineligible. Age-driven fee/reference/quote eligibility changes cannot reuse stale calculations.

**Handoff:** `docs/comparison-d10-current-state.md` with full-versus-incremental equality and resource evidence to S06/Q01/Q02. No quote-history database is required; any persistence proposal must justify restart utility and retention bounds.

## Lead software engineering slices

### S01 — Scenario cashflow adapter

**Lead:** software. **Depends:** D04/R02–R04.

**Work:** Adapt current selections and joint payout profiles to existing settlement/state-space engines. Replace any global identical-rules prerequisite for scenario calculations with explicit per-state cashflows. Keep the stricter complete-state requirement for the all-modeled-outcome arb category.

**Done when:** Win/loss/tie/push/void scenarios produce independently checked profit for each leg and the combined pair. Differing rules produce useful conditional results. Unknown states remain unknown rather than zero. A hedge positive in ordinary outcomes but negative on a tie cannot rank as all-outcome profitable. Full-result states must be feasible, mutually exclusive and exhaustive; incompatible combinations and duplicate lifecycle states are rejected.

**Handoff:** `docs/comparison-s01-cashflows.md` and portable scenario tests to S04/S05/S10. Preserve original shared engine consumers and historical meanings.

### S02 — Fee arithmetic, rounding and net capital

**Lead:** software. **Depends:** D09/R05/R06/S01 input contract.

**Work:** Integrate existing fee engines with current quote scenarios at the comparison size. Support applicable upfront, transaction and settlement/net-gain charges, rounding, fee grids, split fills and order/market aggregation. Reuse reserve/prefunding semantics and distinguish estimated bounds from exact inputs.

**Done when:** Independent examples check at least two sizes, tiny prices, minimums and rounding boundaries for each supported fee schedule. A known fee change reverses a marginal opportunity when appropriate. Each charge is applied on its proper base once. Fees and risk capital are inspectable without exposing private account data. Test standalone versus existing-position incremental commission separately. Uncertain rebates stay excluded; later credits cannot fund an upfront cash requirement.

**Handoff:** `docs/comparison-s02-net-costs.md` and exact-input golden vectors to S03–S05/S10. An unbound account schedule stays estimated or unavailable for that result.

### S03 — Conservative buffer and depth sensitivity

**Lead:** software. **Depends:** S02/R06/D09; D07 quote evidence.

**Work:** Apply the agreed movement, stale/delayed-input, rounding and depth buffers at a disclosed size. Reuse depth allocation and liquidity/reserve rules. Show base estimate, conservative estimate and supported size where useful. Treat absent execution depth as an estimation limit rather than fabricated liquidity.

**Done when:** Increasing any cost buffer weakens or preserves the net result. A buffered negative edge is not ranked positive. Depth-qualified results respect shared book liquidity and fee fragmentation. An unused refundable reserve is not treated both as an expense and retained capital. An adjustable default works with no mandatory stake input.

**Handoff:** `docs/comparison-s03-buffers.md` with monotonicity and sensitivity vectors to S04/S05/S08/S09/S10. No promise that a buffer guarantees fills.

### S04 — Estimated net EV and conditional benchmark path

**Lead:** software. **Depends:** D08/S01–S03/R07.

**Work:** Add a deliberate Pinnacle benchmark estimate path alongside existing model EV. Compute state-weighted net profit at the agreed size/capital basis, retaining gross decisive-outcome benchmark as a useful subordinate result. Bind probability, fee, buffer, payout and reference revisions.

**Done when:** Independent exact examples cover positive, zero and negative net EV; fees can change the sign. Complete probabilities sum to one over feasible, mutually exclusive and exhaustive states; two-way conditional odds are not used as unconditional tie/push probabilities. Missing third-state probability leaves a clearly conditional result. Reference expiry withholds that ranking value without hiding prices.

**Handoff:** `docs/comparison-s04-net-ev.md`, result schema and golden vectors to S06/S08/S10. Label outputs “estimated net benchmark EV” unless a separately qualified model path is used.

### S05 — Buffered arb scenarios and stake allocation

**Lead:** software. **Depends:** S01–S03/D03; independent of R07 probabilities.

**Work:** Calculate cross-venue paired cashflows and bounded stake allocation at the comparison risk size, fees and available depth. Rank by minimum net return over the declared scenario set. Keep conditional pairs separately available with their limiting/unknown states. Declare candidate-pairs-per-group, allocation-evaluation and returned-result limits before search; report truncation and “best evaluated allocation” when the bound is reached. Preserve negative/zero diagnostic pairs and exact source legs.

**Done when:** Independent vectors include ordinary profitable pairs, fees wiping out profit, unequal payouts, tie loss, integer push, refund and missing exceptional state. A complete-state positive pair outranks by buffered worst-case return; a conditional pair does not inherit that category. Partial-fill/one-leg exposure is separate from the fully acquired portfolio estimate; buffer assumptions never imply synchronized fills. Arb requires no probability or manual stake entry. Pinnacle is never an execution leg. Crowded groups and shared-liquidity alternatives respect the declared pair/search bounds; truncated evaluation does not claim a global optimum.

**Handoff:** `docs/comparison-s05-net-arbs.md` and allocation vectors to S06/S09/S10. Avoid guaranteed realized-profit language before actual fills.

### S06 — Metric API and deterministic ranking contract

**Lead:** software. **Depends:** S04/S05/D10.

**Work:** Expose separate gross, estimated net, conservative/worst-state results, estimate class, size, capital denominator and dependency revisions. Define stable filter/sort semantics for EV and Arbs, ties and missing values. Use exact decimal/rational inputs; display rounding cannot determine ranking.

**Done when:** Positive, zero, negative, unavailable and conditional values sort predictably without coercing unknown to zero. Venue filters recalculate the chosen best opportunity and retain the actual selected venue. Same quote/size/assumptions yields the same result across board, rankings and Details. Conditional and complete-state EV are not sorted together as equivalent estimates; row best-EV selection respects one conditioning/probability/size basis. Candidate generation, allocation evaluation and returned results remain bounded, with truncation visible. Requests use current state and never acquire provider data.

**Handoff:** `docs/comparison-s06-metrics-api.md` plus contract tests to S07–S11/Q01. Version API consumers coherently.

### S07 — Compact odds board and visible Pinnacle number

**Lead:** software. **Depends:** R08/D08/S06.

**Work:** Render canonical selections in one game/market grid with four venues, selected-side Pinnacle odds and estimated net EV. Reduce repeated cell text. Group complementary native contracts in a concise expandable presentation when they need separate cashflow meaning. Preserve venue filters and keyboard selection.

**Done when:** The Cowboys start discrepancy yields one linked game where valid; direct win sides align, while distinct NO meaning remains accessible without three indistinguishable Winner tables. Toronto shows readable venue odds and actual Pinnacle odds. Heterogeneous ages are truthful; narrow layout remains usable. Missing one source does not blank the row.

**Handoff:** `docs/comparison-s07-board.md` with desktop/narrow screenshots and authored-data check to Q01/Q04. Equivalent cents and long caveats move into Details.

### S08 — EV ranking view and stable updates

**Lead:** software. **Depends:** S04/S06/R08.

**Work:** Add a dedicated EV view ranking selection/venue opportunities by estimated net EV, with sport/type filters, selected odds, Pinnacle reference, size policy and concise estimate class. Define when updates reorder results, preserving the active inspection and reading position; provide a deliberate refresh/re-sort affordance if needed.

**Done when:** Results sort correctly beyond rounded display values. Positive, zero and negative values are available; conditional estimates are clearly selectable in their own category or explicit basis filter, without mixing probability/conditioning bases. Changing a filter/size recalculates the ranking basis coherently. A reference/fee/price revision updates the selected result without replacing it with a different opportunity.

**Handoff:** `docs/comparison-s08-ev-view.md`, behavior checks and screenshots to Q01/Q04. Do not conflate best displayed American price with best net EV.

### S09 — Arbs view with worst-case net ranking

**Lead:** software. **Depends:** S05/S06/R08.

**Work:** Replace unsorted gross pair cards with a ranked two-leg presentation: selections, venues, odds, buffered net return and limiting-state/category. Details carry stake split, dollars, capital, scenario outcomes and depth. Offer gross/conditional inspection without crowding the default cards.

**Done when:** All-modeled-outcome and conditional pair categories are distinguishable. Sorting follows exact buffered minimum return. Both leg revisions are visible in inspection; mixed old/new calculations do not survive an update. Duplicate orientations of the same pair do not flood results. Negative/zero cases and empty results remain useful.

**Handoff:** `docs/comparison-s09-arbs-view.md`, pair/ranking checks and screenshots to Q01/Q04. No orders or automatic execution.

### S10 — Details: one readable explanation of the calculation

**Lead:** software. **Depends:** S01–S06/R08.

**Work:** Organize Details by selected bet, Pinnacle baseline, net calculation, fee/buffer/size breakdown, scenario cashflows and expandable original evidence. Show venue-native wording alongside its canonical meaning. Retain both baseline odds, no-vig method, original clocks, input versions and optional size controls.

**Done when:** A user can explain why net EV or arb differs from gross, see the worst state and adjust size without leaving the comparison. Unknown inputs have a specific short explanation. Long clauses and technical IDs are collapsed. Details update coherently with the selected opportunity and preserve keyboard focus, selection and user-entered optional size.

**Handoff:** `docs/comparison-s10-details.md` with readability and live-revision behavior evidence to Q01/Q04.

### S11 — Coverage summary and readable Admin diagnostics

**Lead:** software. **Depends:** D05/D06/S06/R08.

**Work:** Add a compact coverage summary across six sports and four venues, separating configured/checked, offerings, admitted quotes and mapping gaps. Keep detailed lifecycle/quota/resource diagnostics in Admin, with short explanations and exact sanitized evidence available on expansion. Reuse current state; views share acquisition ownership.

**Done when:** The NFL-only native limitation is understandable; empty NCAAB differs from failed Polymarket and a filtered NHL view. Last check never masquerades as quote freshness. User can see why a source/selection is absent. Opening multiple views performs no extra paid refresh and does not require reading internals to compare prices.

**Handoff:** `docs/comparison-s11-coverage-ui.md` plus reconciled-count and browser checks to Q03/Q04. Preserve Stop and existing accounting display.

## Qualification and delivery slices

### Q01 — Portable integration and owner-example regressions

**Lead:** software; data/research review expected answers. **Depends:** D01–D10/S01–S11 as each is ready.

**Work:** Build a small maintained authored/retained fixture matrix for the owner's exact problems and independently calculated golden answers. Integrate with affected current, fee, settlement, client and ranking checks. Keep historical payload-dependent tests distinct from portable gates.

**Done when:** Time-shift same-ID, rematch, role conflict, YES/NO meanings, half/integer lines, different periods, tie/push/refund, fee rounding, quantity, negative buffered edges, stale reference, retirement and incremental invalidation pass. Board/API/Details agree at the same input revision. No test merely duplicates the production formula as its oracle.

**Handoff:** `docs/comparison-q01-controlled-validation.md` with exact candidate, check results and remaining limitations. Controlled results are not live coverage or owner acceptance.

### Q02 — Bounded updates and recovery qualification

**Lead:** software/data. **Depends:** D07/D10/S06/Q01 affected gates.

**Work:** Verify resource behavior with a fixed bounded workload and multiple update cycles across the expanded inventory, including reconnect and cursor recovery. Compare full versus incremental output, changed-event payload size and process memory growth. Use retained/authored inputs before any ordinary live soak.

**Done when:** The declared 768 MiB ceiling, bounded queues and latest-only retention remain enforced; no silent cap increase. Candidate-pair enumeration, allocation evaluations and returned-result bounds hold under crowded groups and shared-liquidity alternatives, with honest truncated-search status. Unchanged groups avoid repeated large graph allocation. Changed fees/scenarios do not create an unbounded history. Stop/reopen preserves ledger spend, reservations, consumed authority and due times. Any uncertain charge retains accounting evidence.

**Handoff:** `docs/comparison-q02-runtime-validation.md` with workload, duration, actual measurements and pass/fail boundary to Q03. A short run does not establish indefinite stability.

### Q03 — Ordinary source coverage and net-input evidence

**Lead:** data; research/software review. **Depends:** R01–R07/D05–D09/Q01/Q02.

**Work:** Observe the existing ordinary scheduler/native operation for bounded declared windows. Verify configured queries, actual offerings/admission, canonical links, Pinnacle references, fee applicability and charged headers. Reuse retained responses and existing due cycles; record an explicit purpose/budget before any additional diagnostic acquisition.

**Done when:** Every configured sport has a checked/empty/failed/unresolved outcome, with exact observation times and counts. At least one available meaningful cross-venue example exercises the implemented net/scenario path. Unavailable offerings are reported honestly; simultaneous all-six-sport/four-venue quotes and a positive edge are not fabricated gates. Spend/remaining/reservations reconcile and no duplicate cycle occurs.

**Handoff:** `docs/comparison-q03-live-evidence.md` with exact code/configuration, sanitized source evidence, actual costs and remaining gaps. A failed source pauses only its dependent acquisition, preserving healthy comparisons.

### Q04 — Owner walkthrough, correction and final handback

**Lead:** software coordinating research/data. **Depends:** Q01–Q03, with scoped gaps explicit.

**Work:** Update tracker/plan/handoff to implemented status, leave the ordinary local app open when the owner resumes implementation/testing, and guide a short session: find a game → compare prices/Pinnacle → inspect net EV → inspect arb scenarios → understand coverage → Stop. Record the owner's words; repair concrete confusion within its owning slice.

**Done when:** Owner feedback and engineering/live evidence remain distinct. The actual delivered default comparison size, costs, conditional categories and sort behavior are documented. Unaccepted items stay pending. No claim of positive opportunity, all-source completeness, public release or owner signoff is inferred from passing tests.

**Handoff:** `docs/comparison-q04-owner-handoff.md`, updated Desktop tracker, PLAN, lead handoff and owner guide, with one specific next unresolved action or completed local delivery status.

## Shared completion and stop rules

Each slice records owner, dependencies, input versions, exact working candidate, changed paths, artifacts, evidence class, tests/independent checks, limitations and next receiving slice. Mark not started → in progress → blocked on named dependency or complete for its stated evidence class. Do not mark downstream live/owner checks complete from upstream research or authored fixtures.

At an unsupported identity, probability, fee or payout fact, preserve the input and scope the unavailable output to that dependency. Continue known state calculations and healthy sources. At a concrete quota/ownership/credential/resource stop, preserve charges, uncertain reservations, due times and consumed attempts; use existing safe recovery rather than reset. Avoid repeated opaque paid probes. No extra purchase, outbound message, public hosting, trading or release is part of these slices.

## Lead kickoff instructions

**Research lead:** Start P00 review, then R01–R03/R05/R07 in parallel using existing primary-source bindings and retained evidence. Complete applicability/effective-date review before proposing numeric fees or probabilities. Deliver concise machine-usable tables and independently checkable examples; route only the genuinely account-specific missing facts to the software/data leads.

**Data lead:** Start P00 inventory and D05 gap measurement from retained responses while research proceeds. Implement D01/D02 only once vocabulary/lifecycle inputs are reviewable; fix current identities as well as the cross-source associator. Expand documented native coverage through D06/D07 with bounded fair discovery. Preserve source originals and historical records.

**Software lead:** Own P00 and R08. Prepare small authored board/EV/Arbs/Details examples while research/data contracts settle. Reuse existing fee/settlement/depth engines for S01–S05; integrate typed inputs before displaying estimated net numbers. Follow S06 contract into the clean views, then qualify the exact candidate through Q01–Q04. The owner has resumed engineering. The initial parallel package is P00, R01–R08 and retained D05 preparation; follow the individual artifact gates before dependent implementation.

## Implementation and verification entry points

These are pickup locations, not prescribed implementation literals. Reuse the shared engines and preserve their existing consumers. P00 confirms the exact seams before changes.

| Slices | Existing locations to inspect | Focused verification starting points |
|---|---|---|
| R01/D05/D06/D07 | `app/collection/public_contracts.py`, `current_native.py`, `current_policy.py`, `current_aggregate.py`, `current_admin.py`, `native_selectors.py`, `native_scope_discovery.py`, `native_scope_bindings.py` | `tests/test_current_native.py`, `test_current_aggregate.py`, `test_current_admin.py`, documented selector/catalog fixtures |
| R02–R04/D01–D04 | `app/collection/current_occurrence.py`, `current_overlap.py`, `current_sink.py`, `v1_comparison.py`, `native_score_binding.py`, `app/dashboard/current_normalized.py`, `app/normalization/score_lines.py`, sporting `event_key` modules and `app/resolution/core.py` | `tests/test_current_occurrence_october8.py`, `test_current_revision.py`, current normalization/score tests; new portable rematch/operator/lifecycle vectors |
| R05/R06/D09/S02/S03 | `app/fees/public_bindings.py`, `engine.py`, `precision_envelope.py`, `entry_bounds.py`, `app/collection/native_fee_metadata.py`, `app/fixtures/public-contracts-v1.json`, `fee-schedules-v1.json`, `app/depth.py` | `tests/test_fees.py`, `test_native_fee_metadata.py`, maintained depth/fee allocation tests and independent rounding/size vectors |
| R07/D08/S04 | `app/collection/current_benchmark.py`, `current_aggregate_admission.py`, `current_overlap.py`, `app/dashboard/current_contract.py::calculation_outputs`, `app/reference/research_loop.py` | `tests/test_current_benchmark.py`, `test_current_contract.py`, independent probability/cost/scenario vectors |
| D04/S01/S05 | `app/settlement.py::portfolio`, `app/arbitrage.py`, `app/depth.py::explicit_allocation`, `app/opportunities/percentages.py`, `app/dashboard/current_contract.py::arbitrage_pairs` | `tests/test_math_reconciliation.py`, maintained settlement/depth tests and complete-versus-conditional cashflow fixtures |
| D10/S06/Q02 | `app/dashboard/current_incremental.py`, `current_state.py`, `current_contract.py`, `multi_game_server.py`, `app/collection/current_sink.py`, `current_confirmation.py`, `current_quota.py` | `tests/test_current_incremental.py`, `test_current_state.py`, `test_current_service.py`, `test_current_quota.py`, `test_current_ssot.py` |
| R08/S07–S11 | `app/dashboard/opportunity_static/u0/board.js`, `board.css`, `app/dashboard/opportunity_static/current/index.html`, `current.js`, `current-client.js`, `arbs.js`, `arbs.html`, current Admin assets and routes | `tests/test_current_client.cjs`, `test_u0_comparison.cjs`, `test_board_security.cjs`, authored browser flows/screenshots, focus/selection/sort behavior checks |
| Q01–Q04 | `docs/CI.md`, `docs/u6-owner-review.md`, `docs/u6-current-handoff.md`, `PLAN.md`, Desktop tracker, `scripts/opportunity-board` | Exact-candidate affected checks, bounded resource report, sanitized ordinary operation evidence and actual owner feedback |

Qualify resource use over at least two ordinary eligible aggregate cycles with native updates and Odds/EV/Arbs views open, after controlled resource checks pass. Declare a bounded observation window and maximum cycles before starting; default local evidence can target two cycles within 35 minutes. If the operating window prevents that, retain controlled results and leave the live item pending rather than inventing an extra scheduled or paid cycle. Record payload sizes, highwater/RSS measurements, inventory, queue limits, actual updates and accounting; do not imply long-duration stability.
