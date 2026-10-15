# Predict: approved financial design and dated foundations

**Approved design · October 11, 2026; current scope reconciled October 14, 2026.**

This document preserves the agreed financial foundations, worked examples and amendment history. [Practical requirements](practical-use-requirements.md) govern the current requested-amount, all-games NFL winner product. [Product status](product-roadmap-review.md) records completion; [Desktop Next Steps](../../prediction_arb_next_steps.md) is the only remaining queue. The [October 14 repair](all-games-data-repair-closeout.md) retains its dated engineering evidence. Subsequent actual owner feedback reopens U01 comparison-usability and affected D04 installed delivery before Q04 owner decision; the financial foundations remain unchanged.

Earlier Bills/Rams illustrations, ceiling/minimum-spend results and EV08 pickup text describe their dated boundaries. They are not a current game selection or new execution instruction. The original authenticated document is retained in [history](history/next-steps-cleanup-20261014/restored-originals/docs/predict-estimated-value-plan-20261011.md). Strict one-/two-second targets remain unpassed follow-up rather than personal-use gates.

**October 13 product correction, subsequently implemented:** the owner requested distinct Odds/EV/Arbs, a named benchmark and requested-$1,000 sizing in the SQL-backed product. The successor quantities/fees/cashflows are implemented through EV09-S01/N01/B01/U01 and installed D04; the October 14 all-games repair supplies the later source/loading/storage correction. [D03](ev09-d03-storage-closeout-20261013.md) and [Q03](q03-ordinary-continuity-closeout-20261013.md) retain their collection/retention and scoped-arithmetic qualification. [Next Steps](../../prediction_arb_next_steps.md) now contains U01 comparison-usability repair, affected D04 verification and Q04 owner decision. Earlier ceiling allocation, examples, model assumptions and qualification evidence keep their dated meanings.

Predict should put each game in one place, compare the economic value of its bets across venues, and show an understandable estimate after fees, settlement differences, and a small buffer. The default comparison budget becomes **$1,000**. Estimates can use sensible, disclosed assumptions immediately; collecting settlement history and calibrating those assumptions is later work.

The arithmetic should be reproducible and correct for the stated inputs. The probabilities, unobserved execution conditions, and some settlement inputs can remain approximate. Their approximation should be visible and easy to replace.

The owner approved this design as the priority on October 11. [Desktop Next Steps](../../prediction_arb_next_steps.md) owns the complete remaining execution plan; [repository status and backlog](product-roadmap-review.md) owns completed work and deferred expansion. Approval is not implementation or owner acceptance. The source baseline reviewed is Git commit **297bc9d93e3f9c33e2931c6355b1c520d9c8c0d1**. At that documentation baseline, $100 remained the implemented default. The subsequent [EV01 closeout](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-policy-closeout.md) records the local successor policy and sizing foundation; the subsequent [EV02 closeout](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-occurrence-closeout.md) records local identity/display implementation; the [EV03 closeout](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-shared-inputs-closeout.md) records shared inputs, supported-slate coverage and selected projection. [EV04 content integration](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-content-closeout.md) is implemented with authored/local verification, including the follow-up closing all 20 previously blocked HTTP cases. [EV05 funded single-trade estimates](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-ev-closeout.md) are locally implemented and verified. [EV06 opposing allocation and settlement stress](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-allocation-closeout.md) are locally implemented and verified. [EV07 board/ranking adoption and required qualification](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-interface-qualification.md) are locally complete. [EV08 bounded repairs](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-runtime-bootstrap-closeout.md) implement retained-price bootstrap, admission outcomes, owned temporal reconstruction, immediate withholding and Stop. The owner now prioritizes practical ordinary-app use and collection; the historical delivery prompt is superseded by the installed handback. Strict timing and broad representative qualification remain follow-up rather than personal-use gates. Those source/delivery gates were later closed for the bounded local goal; owner acceptance remains pending. The design approval itself changes no source authority.

### Navigation

- [Product decisions](#1-product-decisions)
- [Deep-dive findings](#2-what-the-deep-dive-found)
- [Unified games and contracts](#3-one-game-several-economic-contracts)
- [$1,000 and buffer policy](#4-the-1000-policy-and-buffer)
- [Settlement estimates](#5-settlement-estimates-now)
- [Fees](#6-fees-as-first-class-inputs)
- [Calculation contract](#7-shared-calculation-contract)
- [Worked examples](#8-worked-examples-for-implementation)
- [The finished interface](#9-what-the-app-should-look-like)
- [Expandable architecture](#10-architecture-that-can-expand)
- [Size, freshness, and reference](#11-size-support-freshness-and-reference-behavior)
- [Performance](#12-scale-and-responsiveness)
- [Implementation slices](#13-implementation-slices)
- [Acceptance checks](#14-acceptance-checks)
- [Expansion and settlement history](#15-expansion-and-later-settlement-data)
- [Decision log](#16-decision-and-amendment-log)

## 1. Product decisions

| Decision | Approved successor behavior |
|---|---|
| Default trade size | $1,000 total funded budget per opportunity, including upfront fees and required collateral. |
| Arb size | $1,000 across the complete pair or portfolio. Each leg receives its calculated allocation. |
| Main value | Estimated profit in dollars and percent after modeled fees, settlement adjustments, and the buffer. |
| Starting buffer | **0.5% of actual deployed capital**, approximately $5 on $1,000. Configurable, applied once per opportunity. |
| Execution assumption | Taker, funded balances, standalone position, held to settlement. |
| Missing settlement history | Use versioned provisional assumptions and useful sensitivity calculations. |
| Same game across venues | One comparison card, with native contracts and their payout differences retained underneath. |
| Rule differences | Convert them into scenario cashflows and estimated value adjustments where practical. |
| Missing depth | Show a quote-price estimate with “Size unverified”; also show supported size when observable depth exists. |
| Fees | Calculate published applicable components; disclose assumed channel, rounding, and additional charges. |
| Result sign | Positive, zero, and negative results are valid and remain available. |
| Later calibration | Replace assumption providers with historical estimates without rebuilding the calculation or UI layers. |

The owner’s October 11 direction supersedes earlier restrictions that prevented provisional settlement probabilities from contributing to ordinary estimated rankings. It also introduces a discretionary buffer. Preserve the older rules for historical results and any separately qualified calculation; publish a new estimate-policy version for this behavior.

### 1.1 Historical first-delivery fixture

The original October 11 design used **Buffalo Bills at Los Angeles Rams** as its validation game and called for one game containing Bills and Rams winner comparisons, venue prices, the Pinnacle reference, and estimated net value. Kickoff is **Monday October 12, 2026, 8:15 p.m. ET, SoFi Stadium** ([official NFL Week 5 schedule](https://www.nfl.com/news/nfl-how-to-watch-week-5-2026-schedule-london-game-details-and-more)). Source metadata must establish exact occurrence and contract identity; the schedule does not do that. A useful tie or cancellation difference should affect the calculation and its explanation within the comparison.

The owner replaced Eagles/Jaguars because it had kicked off. Its screenshots, frozen source observations and prior $100 results remain historical regressions. If implementation finishes after Bills–Rams kickoff, retain authentic pregame observations as clearly labeled historical replay; the owner selects a replacement for any current pregame walkthrough. Do not manufacture new clocks or extend expired applicability.

The initial delivery should work for ordinary NFL full-game winner contracts across the sources already available locally. It should use shared components that can subsequently support the existing other sports, spreads, totals, periods, and additional venues.

### 1.2 Work deferred

Automated trading, positions/account imports, a new paid data provider, public hosting, a new database, and a complete statistical settlement model are separate future work. Historical data collection does not block the first estimated-value delivery.

## 2. What the deep dive found

These findings describe the source and research reviewed October 11. EV01–EV07 and later EV09/all-games integration address the listed implementation gaps; the table records the design rationale rather than outstanding defects.

| Finding | Evidence and implication |
|---|---|
| Same-game matching is too narrow | The ordinary occurrence annotation uses several sealed reviewed fixtures. The Eagles/Jaguars proof expired October 10 and only includes a narrow Polymarket US mapping. Native records can consequently fall back to source-local event IDs. General matching needs to replace one-game fixtures as the normal product mechanism. |
| Settlement details influence visible grouping | The current normalized group identity incorporates result policy and period-boundary details. Two team binaries can therefore become separate Winner sections. Display grouping and payout-contract identity need separate responsibilities. |
| Estimates are often gated by stronger evidence requirements | The strict net path expects bound payout, fee, probability, quantity, and other profiles. An already implemented direct-site modeled calculation demonstrates that estimates can coexist with those requirements, but it is narrowly scoped and rarely the main visible value. |
| “Binding capacity” is an internal limitation | Shared dependency storage permits 128 profiles and 2 MiB total. A saved authentic snapshot from this session reached exactly 128 profiles across 121 events and 1,202 quotes; many later facets were deferred. Researching more fees alone cannot fix this. |
| Capacity handling can erase independent inputs | Initial normalization can clear a quote’s proposed references on overflow. Later attachment preserves already-referenced profiles and defers additional facets. Large slates can starve later quotes. |
| Estimate notes lose meaning | Broad reason matching converts distinct problems into “Fee needed,” “Reference needed,” or “Binding capacity.” It gives the user little information about the value or the actual assumption. |
| $100 is duplicated | The server policy, browser defaults, comparison views, and modeled helper defaults each contain size assumptions. A single literal replacement would leave inconsistent behavior. |
| The shared math is useful | Existing modules already support joint payout states, estimated payout cells, exact cashflows, provider fees, sizing, scenario minimums, and dependency revisions. Extend these seams. |
| Loading needs separate attention | Earlier reads during this conversation took roughly 24 seconds for the page, 9 seconds for Admin, and 17 seconds for the approximately 11 MB price snapshot. These are dated observations, not a fresh benchmark or a proven diagnosis. Larger calculations must avoid making this worse. |

The saved capacity observation was evaluated at **2026-10-11T12:51:34.918680Z**. It describes that retained snapshot, rather than the present running slate.

### 2.1 Main implementation seams

| Responsibility | Existing source to extend |
|---|---|
| Event identity and cross-source association | [current_occurrence.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/collection/current_occurrence.py), [current_overlap.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/collection/current_overlap.py), [event_links.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/event_links.py) |
| Canonical contracts and group assembly | [domain.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/domain.py), [current_normalized.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/dashboard/current_normalized.py) |
| Payout states and portfolio cashflows | [payouts.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/payouts.py), [cashflows.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/cashflows.py), [settlement.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/settlement.py) |
| Fees and funded sizing | [fees/engine.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/fees/engine.py), [costs.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/costs.py), [net_costs.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/net_costs.py) |
| EV and opposing allocations | [net_ev.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/net_ev.py), [net_arbs.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/net_arbs.py) |
| Existing modeled calculation pattern | [public_retail.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/public_retail.py) |
| Shared inputs, versions, and publication | [current_dependencies.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/current_dependencies.py), [current_metrics.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/comparison/current_metrics.py), [current_comparison_inputs.py](/Users/michaelfuscoletti/Desktop/prediction-arb/app/collection/current_comparison_inputs.py) |
| Main board, rankings, and Details | [comparison-board.js](/Users/michaelfuscoletti/Desktop/prediction-arb/app/dashboard/opportunity_static/current/comparison-board.js), [comparison-view.js](/Users/michaelfuscoletti/Desktop/prediction-arb/app/dashboard/opportunity_static/current/comparison-view.js), [current.js](/Users/michaelfuscoletti/Desktop/prediction-arb/app/dashboard/opportunity_static/current/current.js) |

## 3. One game, several economic contracts

Separate three concepts:

1. **Sporting occurrence:** which actual game this is.
2. **Comparison group:** which sporting result the user wants to compare.
3. **Native contract:** exactly what a particular venue offers and pays.

~~~mermaid
flowchart LR
  A[Venue records] --> B[Shared game identity]
  B --> C[One game comparison]
  A --> D[Native contract and payout rules]
  C --> E[Shared scenario calculations]
  D --> E
  F[Reference probabilities] --> E
  G[Fees and estimation policy] --> E
  E --> H[Estimated EV and arb views]
~~~

### 3.1 Reusable game matching

Keep a durable canonical occurrence ID and a versioned list of source identities. Match in this order:

1. Shared provider/game identifiers where present.
2. Previously reviewed source-ID associations and explicit continuity links.
3. A unique metadata candidate using normalized participants, league, season/stage, and schedule context.
4. A local reviewed override when metadata remains incomplete.

For a metadata match, store its method, supporting fields, conflicts, and estimated-match status. Do not claim a numeric confidence percentage without a calibrated confidence model.

A unique, internally consistent metadata match may support modeled comparisons and hedges with an “Estimated match” note. Promotion to a stronger identity status is independent. Conflicting or ambiguous candidates remain excluded from the affected calculation.

Time helps disambiguate a match and can change when a game is rescheduled. It should not be the sole permanent identity. Repeated opponents, doubleheaders, neutral-site games, replacement games, and separate periods require explicit cases.

An ambiguous candidate remains unresolved. The app can show the candidate association in Details or Coverage; it should avoid computing a cross-game hedge while the ambiguity remains.

### 3.2 Display grouping

Use canonical occurrence + market family + period/scoring scope + line as the display comparison group.

Keep full-game including-overtime and regulation-only markets distinguishable. Their different decisive outcomes can require a richer joint-state model; the first release should not silently combine them under one identical market label.

Tie, refund, cancellation, and fee differences usually belong in the contract’s payout/cost model. They should not create another game card.

For winner comparisons:

- Bills and Rams each receive a row in the initial validation case.
- Team YES and the opposing market’s NO can be economic alternatives within that row.
- LONG/SHORT interpretation follows the selected instrument metadata and cashflows.
- A contract that additionally benefits from a tie keeps that difference.
- If multiple contracts exist at one venue, choose the best modeled value for the main cell and make the alternatives accessible.
- Preserve both original identifiers and original wording in Details.

The visible economic label can say “Bills — tie differs” when appropriate. The actual predicate and payout remain precise beneath it.

### 3.3 Equivalent and approximately equivalent

Contracts can be:

| Relationship | Treatment |
|---|---|
| Same normal and exceptional payouts | Direct economic comparison after fees and sizing. |
| Same decisive winners, different tie/push payouts | Shared row with explicit modeled adjustment and scenario difference. |
| Same decisive winners, uncertain exceptional payouts | Estimated or conditional comparison with an explicit assumed payout/range. |
| Different period or overtime meaning | Distinct market scope until the joint sporting-state model supports comparison. |
| Uncertain game or instrument orientation | Preserve prices; withhold the affected cross-venue calculation until resolved. |

A spelling difference is a matching problem. A tie-payout difference is an economic input. Resolve each at its own layer.

## 4. The $1,000 policy and buffer

### 4.1 Funded capital

For a single opportunity, deployed capital includes acquisition/stake, unavoidable upfront fees, and independently required funded collateral or holds.

For an arb portfolio, sum those amounts across every leg. The complete portfolio must fit within $1,000.

Contract face payout, number of contracts, and American-odds payout are separate quantities. None is automatically the trade budget.

Choose a valid quantity within the budget. Recalculate fees at that quantity rather than multiplying a $100 result by ten. Show unused budget caused by quantity increments or fee rounding.

Use actual deployed capital as the ROI denominator. If $999.80 is deployed, calculate the return on $999.80. Show the $1,000 ceiling alongside it.

### 4.2 A simple initial buffer

Approved initial default:

    buffer_rate = 0.005
    buffer_usd = actual_deployed_capital × buffer_rate
    buffered_estimated_profit = modeled_expected_profit − buffer_usd

The buffer is a product-policy haircut for residual uncertainty. It is not an actual venue charge, a refundable cash hold, or a statistical confidence bound. It does not certify that settlement or execution losses are limited to $5.

Apply it once to the whole opportunity. Do not charge it to each leg and then charge it again to the pair.

Use the same rate on EV and arb views. Allow 0%, 0.25%, 0.5%, and 1% as convenient sensitivity options, plus a custom rate in Settings/Details. Use the exact unrounded amount internally and display cents.

The estimated lane should not automatically stack the existing one-cent-per-dollar-face adverse-price stress on top of this new buffer. Preserve that older stress as a separately named sensitivity. Observed depth consumption and its actual modeled price impact remain part of acquisition cost.

### 4.3 Default and overrides

One server-owned, versioned policy supplies the initial budget and assumptions to every view. Browser code reads that metadata.

The default is global. A Details override applies consistently to the inspected calculation and identifies its size. A global budget change updates every comparison. An optional custom cash buffer can be added later without changing the result contract.

## 5. Settlement estimates now

The initial model should use a small number of understandable, mutually exclusive terminal scenarios:

- Team A wins.
- Team B wins.
- Tie/push, if feasible under the market scope.
- Noncompletion or other exceptional settlement.

Separate additional exceptional scenarios only when they produce meaningfully different joint payouts. A delayed game that eventually settles normally is a path condition. Cancellation, abandonment, and terminal postponement can describe the same effective noncompletion outcome and must not receive duplicated probability mass.

### 5.1 Payout profiles

Every contract gets a versioned payout profile with one value or explicit range for each applicable state.

| Payout treatment | Model |
|---|---|
| Dollar-face binary win/loss | $1 or $0 per dollar-face unit. |
| Half settlement | $0.50 per dollar-face unit. |
| Stake/collateral refund | Return the actual relevant acquisition collateral. Fee refunds are separate. |
| Tie loss | $0. |
| Last fair market price | Use the available mark; otherwise a named mark proxy and stress range. |
| Unknown exceptional decision | Preserve the unknown fact and provide conditional calculations or explicit estimated scenarios. |

Each value carries a basis: selected terms, published template, provisional assumption, or historical estimate.

### 5.2 Initial NFL rules

Current general Kalshi football terms include overtime and pay both YES and NO $0.50 on a tie when no Tie strike is listed. If a Tie strike is listed, team YES contracts settle to zero on a tie. The selected catalog must distinguish those branches. The no-Tie branch can be a **provisional template** while its selected applicability remains unresolved. [Kalshi football terms](https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf).

Polymarket US documents $0.50 settlement for winner markets without a tie outcome. ProphetX’s NFL mainline filing describes returning collateral on a final tie. These can be compared in the same winner group after converting their payouts to dollars on the selected size. [Polymarket US sports rules](https://docs.polymarket.us/faqs/sports-faqs), [ProphetX NFL filing](https://framerusercontent.com/assets/3xBUPoodNIUMWAauxaaccjNRSo.pdf).

The result can be the same across two venues. Apply a zero differential when their supported payout profiles agree.

### 5.3 Approved provisional probabilities

To ship a useful first model, introduce explicit starting knobs for **NFL regular-season, pregame, full-game winner**:

| Input | Central assumption | Sensitivity range | Basis |
|---|---:|---:|---|
| Completed tie probability | 0.5% | 0%–1% | Uncalibrated product prior; approved starting value. |
| Terminal noncompletion/exception probability | 0.1% | 0%–0.5% | Uncalibrated product prior; approved starting value. |
| Relative probability of the two decisive winners | Matched Pinnacle proportional no-vig probabilities | Alternative models later | Existing market benchmark. |

These numbers are approved provisional engineering defaults. They are not measured NFL rates, event-specific predictions, or claims about the screenshots. They can be changed without code changes once the policy exists.

For a two-way decisive win probability c, tie probability t, and noncompletion probability u:

    P(A wins) = (1 − t − u) × c
    P(B wins) = (1 − t − u) × (1 − c)
    P(tie) = t
    P(noncompletion) = u

Validate nonnegative probabilities, t + u ≤ 1, and the correct disjoint state partition.

Do not reuse this prior for live games, regulation-only hockey, half-game markets, spreads, totals, playoffs, or other sports. A live tie prior can depend strongly on score and time; the initial live view should use a clearly conditional estimate or scenario sensitivity until it has an appropriate live model.

A rule-supported impossible tie receives probability zero under the corresponding exact completed-game scope. Whole-number spread/total push probability needs its own model. Half-point lines can make an integer-score push infeasible.

### 5.4 Uncertain cancellation values

Fair-price settlement differs from a stake refund. Where a fair settlement mark is unavailable, the first central estimate can use the entry mark as an explicit **neutral exceptional-settlement proxy**. Keep paid nonrefundable fees consumed unless the template says otherwise.

Also show adverse payout scenarios. For dollar-face contracts, $0–$1 is a possible scalar payout range where the governing terms allow it; it is not an expected-probability distribution. Respect any known shared constraints between contracts when forming joint states.

A proxy supports a modeled number. It does not establish the actual contract’s cancellation price. If even a reasonable proxy cannot be defined, show conditional EV and the relevant settlement stress instead.

### 5.5 Valuing the difference

The difference between two otherwise comparable contracts is the probability-weighted difference in their **net cashflows at the evaluated capital/quantity**.

For a contract bought at $0.24, a $0.50 tie payout produces $0.26 gross profit per contract. A refund of its $0.24 cost produces zero gross profit. At the provisional 0.5% tie prior, the difference is:

    0.005 × ($0.50 − $0.24) = $0.0013 per contract

This comparison fixes the contract quantity and fee treatment for illustration. Re-evaluate the actual quantities and capital to compare two $1,000 opportunities.

## 6. Fees as first-class inputs

Use the existing provider fee engines. Do not use a universal “subtract 2%” rule.

Published schedules reviewed October 11, 2026:

| Venue | Initial estimated direct-site taker model | Important treatment |
|---|---|---|
| Kalshi | General coefficient 0.07 × multiplier × contracts × p × (1−p), with scoped overrides. | Schedule effective July 7. Preserve provider rounding/accumulation and channel balance precision. Direct venue schedule states no settlement fee. [Schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf), [rounding](https://docs.kalshi.com/getting_started/fee_rounding). |
| Polymarket US | Standard single-contract coefficient 0.0695 × contracts × p × (1−p). | Effective October 7 at 10 a.m. ET. Half-even cents and cumulative taker order cap. Exclude contingent/account rebates. Combos and table tennis have separate schedules. [US fee schedule](https://docs.polymarket.us/fees). |
| Novig | Prefer selected v3 market fee metadata. Normal live game coefficient 0.03; NCAAF/MLB/NHL 0.06 live from October 8. | WHEN_LIVE pregame fee is zero; unknown phase can use the live rate as a labeled assumption. Native v3 face is one cent; preserve half-up per-fill precision. [v3 fees](https://docs.novig.com/api/concepts/fees). |
| ProphetX | 2% of positive net gains per market under current direct-site straight-trade terms. | Charge by settlement state and market portfolio. Default standalone. Public rounding is unspecified; cent-ceiling rounding can be a declared modeled assumption. [Trading fees](https://www.prophetx.co/lobby/t-c/trading-fees). |
| Pinnacle | Reference only. | Supplies benchmark odds and their market meaning; no execution allocation. |

The [Polymarket clearing notice](https://polymarketexchange.com/files/clearing-notices/Clearinghouse%20Notice%20-%20Fees%20(2026.05.18).pdf) currently declares no fees on clearing members. This does not establish every retail channel’s total charges. The initial funded direct-site model may explicitly assume zero additional settlement/channel transaction charges while preserving their actual applicability status.

### 6.1 Resolution order

1. Current selected-market and account/channel terms, when available.
2. Applicable published venue/product schedule.
3. A named venue/product/phase template.
4. A disclosed provisional fee assumption or conditional result where a usable model exists.

An explicit conflicting scoped fee does not get overwritten by an unrelated general schedule. Preserve both the observed conflict and the assumed scenario.

For aggregate Novig and ProphetX quotes, distinguish the modeled direct-site channel from an independently qualified native API regime. An aggregate price alone does not prove exact API units, commissions, or selected payout treatment.

### 6.2 Fee components

Represent entry fees, winning-profit commission, settlement charges, other mandatory transaction charges, and rebates separately.

Entry fees consume funded budget. Winning commission is calculated in the winning state. A charge already withheld from payout is not subtracted again. Known refundable holds increase required capital and return in their applicable states.

Default maker rebates, volume rebates, and promotion credits are absent. They can become separate explicit scenarios later.

Funded balances avoid a new deposit charge in the default trade model. If the user asks for a deposit-to-withdrawal calculation later, funding costs receive their own input and label.

## 7. Shared calculation contract

For each terminal scenario s:

    profit_s =
        total settlement receipts_s
        + returned funded holds_s
        − total upfront acquisition, fees, and funded holds
        − additional consumed outcome charges_s

For a complete modeled probability partition:

    estimated_profit_usd = Σ P(s) × profit_s
    estimated_return_percent = 100 × estimated_profit_usd / deployed_capital
    buffer_usd = buffer_rate × deployed_capital
    buffered_profit_usd = estimated_profit_usd − buffer_usd
    buffered_return_percent = 100 × buffered_profit_usd / deployed_capital

For a conditional model, apply the same arithmetic on the named condition and label it explicitly.

### 7.1 EV output

Retain these values:

- Gross decisive benchmark before costs.
- Central modeled profit after fees and settlement assumptions.
- Buffered modeled profit and return, used for the main estimate.
- Sensitivity range under declared priors/payout proxies.
- Per-scenario profit and worst modeled settlement result.
- Actual deployed capital, target budget, and size-support status.
- Selected venue/contract and every input/policy version.

A sensitivity range is a scenario range. Do not describe it as a confidence interval without a statistical model.

### 7.2 Arb output

Search allocations against **net scenario cashflows**, including fees, under the combined $1,000 budget.

Ordinary fee-free two-outcome balancing is a useful seed, but winning commission and asymmetric payouts can change the best stake ratio. Round to native quantity/stake increments and evaluate the final feasible allocation again.

Use explicit allocation objectives:

- For **Estimated hedge** candidates, maximize the minimum fee-adjusted profit across the two decisive winner states under the funded ceiling. Both opposing legs must have meaningful positive exposure on valid quantities; report the achieved balance and any grid/depth limitation. Compute expected value and exceptional losses on that allocation.
- For **Positive across modeled outcomes** candidates, separately maximize the minimum profit across the complete modeled state set. Require both legs and complete scenario coverage; publish the best evaluated feasible allocation and its search limits.
- Keep these objectives separate from single-selection EV. Maximizing unconstrained expected value can otherwise produce a large outright bet with a token opposing leg.

Use the existing bounded search machinery and disclose a best evaluated allocation when global optimality has not been established.

Show:

| Value | Meaning |
|---|---|
| Profit when A wins | Pair net cashflow for A’s result. |
| Profit when B wins | Pair net cashflow for B’s result. |
| Tie/push result | Pair net cashflow in that state. |
| Exceptional result/range | Pair settlement stress under its assumptions. |
| Estimated profit after buffer | Probability-weighted modeled value, less the one opportunity buffer. |
| Minimum modeled profit | Lowest included scenario profit, with the scenario named. |
| Size support | Observed depth-supported allocation or quote-price model. |

Use two readable result categories on the Arbs page:

- **Positive across modeled outcomes:** positive minimum after the declared buffer across a complete modeled state set.
- **Estimated hedge:** useful expected value or decisive-result margin with a loss in at least one modeled scenario.

Completeness, estimated payouts, and size support remain visible. A probability assumption changes expected profit; it cannot turn a losing scenario into guaranteed profit.

Keep all results inspectable. Positive-only filtering should use the appropriate category’s metric and should be optional.

## 8. Worked examples for implementation

These are independently calculated, synthetic examples. Their prices and priors specify expected behavior; they are not current opportunities or exact venue-contract claims.

### 8.1 Single $1,000 trade

Assume an even-money wager, $1,000 stake, decisive win probability 53%, 2% commission on standalone winning profit, a tie refund, and an exceptional refund. Upfront additional charges are zero in this example.

Use the proposed pregame NFL priors t = 0.5% and u = 0.1%.

| Scenario | Probability | Net profit |
|---|---:|---:|
| Selected team wins | 52.682% | +$980.00 |
| Opponent wins | 46.718% | −$1,000.00 |
| Tie | 0.5% | $0.00 |
| Noncompletion | 0.1% | $0.00 |

| Breakdown | Amount |
|---|---:|
| Conditional decisive gross EV | +$60.00 |
| Settlement probability adjustment to gross EV | −$0.36 |
| Expected winning commission | −$10.5364 |
| Central modeled EV | +$49.1036 |
| 0.5% buffer | −$5.00 |
| **Main displayed estimate** | **+$44.10 · +4.41%** |

The expected commission is probability-weighted. Subtracting the full $20 winning commission from every outcome would give the wrong EV.

### 8.2 A pair with a small edge and a tie mismatch

Assume dollar-face contracts:

- A costs $0.24, pays $1 if A wins, and loses on a tie.
- B costs $0.74, pays $1 if B wins, and returns its $0.74 acquisition cost on a tie.
- Each leg has an invented flat $5 entry fee.
- Cancellation returns acquisition cash; the $10 entry fees remain consumed.
- Both use whole contracts.

The maximum equal quantity fitting the $1,000 budget is:

    Q = floor(($1,000 − $10) / ($0.24 + $0.74)) = 1,010

| Item | Amount |
|---|---:|
| A acquisition | $242.40 |
| B acquisition | $747.40 |
| Entry fees | $10.00 |
| Deployed capital | $999.80 |
| Unused budget | $0.20 |
| Profit if A wins | +$10.20 |
| Profit if B wins | +$10.20 |
| Profit on tie | −$252.40 |
| Profit on cancellation | −$10.00 |

Using t = 0.5% and u = 0.1%:

    EV = 0.994 × $10.20 + 0.005 × (−$252.40) + 0.001 × (−$10)
       = $8.8668
    buffer = 0.005 × $999.80 = $4.999
    buffered EV = $3.8678

The displayed estimate is **+$3.87 · +0.39%**, with **Tie result −$252.40** and category **Estimated hedge**. The unbuffered estimated return is approximately 0.886857%.

At the fixed 0.1% cancellation prior, the buffered estimate breaks even at approximately **1.9729% tie probability**. Details can show this threshold so the user can judge whether the assumed tie rate is reasonable.

### 8.3 Same price does not mean same fee cost

For a $0.50 acquisition price and 1,000 dollar-face contracts, the unrounded standard entry-fee curves produce $17.50 for Kalshi at multiplier 1 and $17.375 for Polymarket US. Apply the respective rounding and aggregation rules. Those are **1,000 contracts costing $500 before fees**, not a $1,000 trade. [Kalshi schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf), [US fee schedule](https://docs.polymarket.us/fees).

The size solver must calculate how many contracts the $1,000 funded budget actually buys at each venue.

## 9. What the app should look like

### 9.1 Odds board

One card per matched game. One section per meaningful market/period/line scope. Venue columns stay easy to compare, with Pinnacle shown as the reference.

Board-wide policy line:

> Estimates use a $1,000 total budget, standard taker fees, and a 0.5% buffer. Settlement assumptions are provisional.

Main estimate cell, illustrative:

> **+$18.40 · +1.84%**
>
> ProphetX · after fees and buffer
>
> Tie adjustment estimated

A row can show only its most material note; shared defaults belong in the policy line and Details.

For a negative value, show the negative value. A fee that removes the edge should appear as “Fees remove the edge” when useful.

The best raw odds and best estimated value can belong to different venues. Highlight each according to its own meaning.

### 9.2 EV page

Default rank: buffered estimated return on the common $1,000 target-size model. Show dollar profit, venue, size support, and the principal assumption. Dollar-profit sort remains available.

Keep complete modeled and conditional estimates in clearly identified categories. Their conditions differ, so the app should not silently present a conditional number as a complete-state estimate.

Where known depth supports less than $1,000, show both:

- The $1,000 target-size model, consuming known levels first and labeling any residual price/liquidity assumption.
- A separately labeled supported-size calculation, with actual capital and return.

### 9.3 Arbs page

Name both purchases, both venues, and allocations. Lead with the category-appropriate result:

- Positive-across-modeled-outcomes rows lead with minimum buffered profit.
- Estimated-hedge rows lead with buffered expected profit and a visible adverse-state loss.

Place the scenario table and capital/fee breakdown in Details.

### 9.4 Details

Use a consistent order:

1. Main result and optional size override.
2. Deployed capital, quantities, and price assumptions.
3. Gross value → settlement adjustment → fees → net estimate → buffer → displayed result.
4. Outcome table and break-even/sensitivity.
5. Short explanation of provisional assumptions and observed size.
6. Original contracts, prices, clocks, matching basis, and source links.

Some modeled fees are state-dependent. The arithmetic breakdown must reconcile to the full expectation; its component labels should identify expected rather than maximum charges.

### 9.5 Replace generic estimate notes

| Current note | Proposed ordinary behavior |
|---|---|
| Fee needed | Calculate the published/template fee when practical; note “Published taker fee assumed” or the exact missing charge. |
| Reference needed | Reuse the matched same-game reference. If absent, say “No matched Pinnacle reference”; preserve prices and scenario calculations. |
| Binding capacity | Diagnose/fix internal capacity in Admin. A genuine temporary calculation failure says “Estimate temporarily unavailable.” |
| Probability needed | Use the applicable provisional prior or a named conditional estimate; show the assumption. |
| Payout needed | Use a disclosed template/proxy where supported; preserve the original unknown fact. |
| Depth needed | Show the modeled value with “Size unverified,” and supported size where available. |
| Too old / age unknown | Retain the as-of estimate and actual age; exclude it from current rankings under the age policy. |
| Legal size needed | Use a continuous-size/declared-grid hypothetical if units are understood, with a size note. An unknown price/unit conversion remains a real blocker. |

## 10. Architecture that can expand

Keep one server-side calculation path. The browser formats results and presents explanations.

### 10.1 Logical components

| Component | Responsibility | Expansion seam |
|---|---|---|
| Occurrence resolver | Canonical game and provider links. | New sports and provider IDs. |
| Contract adapter | Native side, units, sporting predicate, and economic orientation. | New venues and products. |
| Payout provider | Versioned state cashflows and estimated/known provenance. | Exact selected rules and observed settlement. |
| Probability provider | Conditional reference, provisional priors, later calibrated distributions. | Better priors and live models. |
| Fee resolver | Scoped schedule, channel assumptions, per-state charges. | Account terms, maker execution, portfolios. |
| Size allocator | Funded ceiling, legal grids, observed or assumed liquidity. | Larger portfolios and better depth. |
| Estimate evaluator | Calls shared cashflow/fee math, applies buffer, produces sensitivity and notes. | Additional metric categories. |
| Current projection | Publishes coherent input/result revisions efficiently. | Larger slates and event batches. |

Possible new modules, under the existing comparison package, are estimated_policy.py, estimated_inputs.py, and estimated_value.py. Introduce them only where they create a clear responsibility. Reuse existing payout, fee, settlement, and cashflow functions.

### 10.2 Policy contract

Illustrative shape; this is a design proposal:

~~~yaml
version: predict-estimate-policy-2
capital_ceiling_usd: "1000"
execution_role: taker
portfolio_basis: standalone
funding_basis: already_funded
holding_period: to_settlement
buffer:
  basis: actual_deployed_capital
  rate: "0.005"
  treatment: model_haircut
probability_defaults:
  nfl_regular_season_pregame_full_game_winner:
    tie:
      central: "0.005"
      low: "0"
      high: "0.01"
      basis: provisional_prior
    terminal_noncompletion:
      central: "0.001"
      low: "0"
      high: "0.005"
      basis: provisional_prior
missing_depth: quote_price_model_with_size_note
contingent_rebates: excluded
~~~

Fee and payout templates are separate versioned records, rather than long lists embedded in this policy.

### 10.3 Result contract

Each estimate should include:

| Field group | Contents |
|---|---|
| Identity | Occurrence, comparison group, selected contract/legs, matching basis. |
| Size | Target budget, deployed capital, quantities, unused cash, supported/assumed depth. |
| Values | Base EV, buffered EV, percentages, per-state profit, minimum, sensitivity. |
| Classification | Modeled complete, modeled conditional, or unavailable; arb/hedge category. |
| Cost breakdown | Entry, expected winning/settlement charges, assumed additional charges, buffer. |
| Assumptions | Rule template, probability prior, fee channel, rounding, liquidity, exceptional mark. |
| Revisions | Source quotes, reference, rule, fee, prior, policy, sizing, and result revision. |
| Timing | Original source times, evaluation time, freshness status. |
| Notes | Structured type/severity, short user text, and Details explanation. |

Keep observed unknowns alongside their assumed replacements. A modeled zero fee and a verified zero fee are different input statuses.

Use exact decimal/rational input handling. Round for display and venue rules, rather than repeatedly rounding intermediate EV calculations. Financial values crossing the API remain decimal strings or the existing exact-number representation.

### 10.4 Historical compatibility

New policies create successor versions. Existing captured inputs, receipts, fee histories, and historical results retain their old versions and meaning.

The estimate evaluator can consume either provisional or later calibrated providers. It must not promote a modeled input merely because a more complete profile is now possible elsewhere.

## 11. Size support, freshness, and reference behavior

### 11.1 Liquidity

Consume observed depth when present. Shared liquidity cannot fund two legs twice. If observed depth stops short of $1,000, report that fact.

Where depth is absent, the ordinary estimated lane can assume the displayed quote price for the target budget. This supports comparison while labeling size unverified.

A known price ladder showing worse prices should be used; it must not be replaced by a more favorable top-quote assumption.

If known depth ends below the target, a full-size model must consume that ladder first. For the remaining quantity, the initial assumption can extend the last observed acquisition price, explicitly labeled “Remaining size assumed at last visible price,” with an adverse-price sensitivity. This does not establish that quantity is available. If no reasonable residual assumption is selected, omit the full-size value and retain the separately labeled supported-size result.

Unknown native minimums or increments can support a continuous/declared-grid hypothetical when the economic units are understood. Unknown units, unsupported short collateral, or a contradictory conversion require a local refusal.

### 11.2 Age

Retain original source times. Receipt, heartbeat, and successful connection do not renew prices.

Keep the existing distinctions initially: 900-second pregame and 15-second live comparison policy, and the 1,800-second gross benchmark window. Reconsider these later with measured data.

Stale or unknown-age values can remain inspectable as as-of estimates. Current rankings should apply their freshness eligibility and show how many rows are excluded. A buffer does not make an old quote current.

### 11.3 Reference

Keep the two original Pinnacle odds, their source clocks, selection orientation, market scope, and proportional no-vig method.

A refund-on-tie two-way reference supplies decisive-result relative weights; it does not identify tie mass. Combine it with the applicable provisional prior as described above.

If an exact usable reference is missing, retain portfolio scenario profit and arb calculations that do not require probabilities. EV can remain conditional/unavailable for that local reason. The current requested-size product also supports explicitly selected Novig or ProphetX two-way benchmarks, with their original clocks and applicability as specified in [practical requirements](practical-use-requirements.md).

## 12. Scale and responsiveness

The October 11 source reached its 128-profile cap at ordinary slate size. EV03 and later installed read/storage repairs address that representation and scheduling gap. The design responsibilities below explain the completed bounded architecture; strict distribution/timing qualification remains deferred.

Design responsibilities:

1. Intern reusable policy, fee, rule, and probability templates once.
2. Keep quote-level attachments small; separate reusable templates from selected quote context.
3. Avoid duplicating source evidence and selected audit detail in every board row.
4. Project a compact board result; load large evidence/detail graphs when needed.
5. Recompute only results whose quote, reference, policy, rule, or age eligibility changed.
6. Process large slates in fair bounded event batches without starving later events.
7. Preserve a coherent published revision when calculations complete in batches.
8. Profile event-loop CPU and serialization separately before choosing a repair.
9. Retain resource bounds, original clocks, and latest-only browser updates.

If compact representation still requires new capacity limits, version and justify them from a representative measured slate. Do not silently remove bounds or merely increase 128 to another arbitrary number.

Original engineering targets (strict timing/full-scale qualification remains deferred and unpassed):

- A visible loading state appears immediately.
- First useful retained-data board content within 2 seconds on the development Mac.
- Ordinary board/detail requests generally finish within 1 second for a representative retained slate.
- A representative 150-game / 2,000-quote case receives fair estimation coverage.
- Working-set memory stays within the existing 768 MiB application ceiling.
- A late venue or missing input does not delay otherwise useful rows.

The owner changed priority on October 12 to personal use now. The two-second and one-second targets remain follow-up engineering targets, not personal-use blockers or current performance claims. Correct calculations/identity/clocks, bounded resources, useful visible progress and working Stop still apply. Fix demonstrated freezes or unusable selected workflows; do not defer owner use for a 1.037-second benchmark miss.

## 13. Implementation slices

The table maps design responsibilities to stable slice IDs; it is not a second status queue. [Desktop Next Steps](../../prediction_arb_next_steps.md) specifies all remaining work, engineer types, dependencies, completion checks and deliverables. EV01–EV07 implementation, ordinary source/account-safe integration and a bounded EV09 actual-app check support personal use; Q04 is owner use/feedback. Remaining strict EV08 and broad qualification are follow-up. Formal source-cycle evidence may continue alongside use. EV10/EV11 are deferred in the [repository backlog](product-roadmap-review.md#backlog). Local fixtures and retained inputs are sufficient for most engineering work.

| ID | Work | Completion evidence |
|---|---|---|
| EV01 | Publish successor estimate policy, $1,000 semantics, default 0.5% buffer, and explicit provisional-prior class. Inventory duplicated defaults. | The server and all views obtain the same policy; hand-calculated positive/zero/negative and sizing vectors agree. |
| EV02 | General occurrence matching and display grouping independent of payout identity. | Bills/Rams forms one card; repeated games and conflicting candidates remain correctly distinct. |
| EV03 | Share templates and repair capacity starvation. Establish compact input/result projection. | Representative large slate does not turn healthy supported facets into generic capacity gaps; memory/latency measured. |
| EV04 | Adapt current published fee schedules and provisional NFL payout/exception templates into the modeled input path. | Every execution venue has a fee/cashflow breakdown, applicability note, and version; actual unknowns remain retained. |
| EV05 | General modeled EV evaluator, funded $1,000 sizing, provisional state probabilities, and buffer. | Independent vectors reconcile; incomplete states produce useful conditional output; missing depth has an explicit size note. |
| EV06 | Opposing-contract allocation with fee-aware stake ratios and settlement stress. | Combined allocation fits $1,000; per-state profit, expected profit, minimum, and hedge classification agree. |
| EV07 | Main estimate column, unified cards, EV/Arbs ranking, and consistent Details. Replace broad reason text. | Desktop/mobile walkthrough shows useful numbers, fees, buffer, and material notes without requiring stake entry. |
| EV08 (follow-up) | Preserve implemented bounded runtime repairs; improve latency where real use identifies pain. | Original benchmarks remain recorded; strict timing and broad qualification no longer gate personal use. Correct clocks/revisions/resources/Stop still apply. |
| EV09 | Final local verification and preparation of the actual-app walkthrough. | Required engineering checks and actual desktop/narrow inspection pass on the final candidate; Q03 source evidence is linked and the Q04 owner handoff is reviewable. |
| EV10 (deferred) | Expand sport/market templates after the winner workflow is useful. | Each addition has its own state/fee/probability cases and coverage counts. |
| EV11 (deferred) | Add optional settlement observation and later calibration. | Historical outcomes improve assumption providers without rewriting original predictions. |

Historical dependency design: EV02 and fee/rule adaptation accompanied EV01; shared representation feeds EV05, and the UI binds to that evaluator. These implementation dependencies are now complete for the bounded local goal.

### 13.1 Completed implementation and current reading order

EV01–EV07, Q03 and the required EV09 S01/N01/B01/U01/D04 integration are complete at their recorded boundaries. The [installed all-games/data repair](all-games-data-repair-closeout.md) supersedes the earlier report, loading and source-scope defects. Use [requirements](practical-use-requirements.md), [operating instructions](all-games-operating-instructions.md) and [owner review](u6-owner-review.md). Current source identity and verification are in that closeout; older candidate manifests and failed benchmark results remain historical.

The reusable design responsibilities in the table above are preserved IDs, not unfinished tasks. [Next Steps](../../prediction_arb_next_steps.md) contains reopened U01 → D04 → Q04 after the owner's actual usability review. Existing B01 read fields support this repair; additional backend work is limited to a demonstrated missing field. EV08 strict benchmarks, EV10 expansion, EV11 calibration and hosted/distribution work remain [backlog](product-roadmap-review.md#backlog). Preserve original policies, observations, clocks, native predicates and saved results when any later work is selected.

## 14. Acceptance checks

These are the original financial-design acceptance cases. The current [practical requirements](practical-use-requirements.md) supersede the named-game presentation and strict timing pickup below; completed verification is indexed in [product status](product-roadmap-review.md). Owner acceptance still requires Q04.

### 14.1 Game and contract meaning

- One Bills/Rams game contains the matching native and aggregate quotes where genuinely offered; historical replay retains its original as-of label.
- Separate team binaries share the same display Winner group.
- YES/NO/LONG/SHORT economic orientation comes from metadata and cashflows.
- A tie-benefiting NO can receive a different value from opponent YES.
- A matching spelling difference does not create a second game.
- Repeated opponents, game numbers, and incompatible periods do not collapse incorrectly.
- Reschedules preserve supported occurrence continuity while keeping changed metadata.

### 14.2 Math and estimation

- The worked examples above reconcile independently.
- Fees or buffer can turn a positive gross result into zero or negative net value.
- Tie-half, tie-refund, and tie-loss treatments produce their intended cashflows.
- Cancellation retains/refunds fees according to the selected assumption.
- Probabilities cover the intended disjoint partition and sum to one.
- Fee aggregation, price scales, contract face, and quantity units do not introduce 100× errors.
- $1,000 means one funded trade or one complete pair; upfront fees fit inside it.
- Higher buffer lowers fixed-allocation dollar value by the exact added haircut.
- Different percentage denominators are disclosed; resizing is a new calculation.
- A modeled fee is deducted once; returned holds and contingent credits are treated correctly.
- A positive expected hedge with a negative tie outcome remains an Estimated hedge.

### 14.3 Interface and runtime

- Odds, EV, Arbs, and Details show the same policy and calculation revision.
- The estimate column shows useful modeled values where supported.
- Notes identify fees, tie assumptions, exceptional proxies, size, and age clearly.
- Best raw price and best estimated value are distinguishable.
- Positive, zero, negative, conditional, and unavailable results remain inspectable.
- A missing reference or failed venue leaves other prices/scenario calculations usable.
- A representative large slate receives fair estimates within resource bounds.
- Price, fee, prior, payout, size, buffer, identity, and freshness changes invalidate dependent results coherently.
- Browser filters, views, and size changes do not create extra paid acquisition.
- Local Stop and source/accounting behavior remain intact.

Extend existing calculation and browser regression suites with independent vectors for these changes. Avoid duplicating the evaluator as its own oracle. A plan-only document does not need application tests.

## 15. Expansion and later settlement data

### 15.1 Expansion order

1. NFL pregame full-game winner comparisons across existing venues.
2. Other existing full-game winner sports with explicit completed-game and exception templates.
3. Half-point spreads and totals, then integer lines with their own push model.
4. First-half/regulation periods with matching reference and scope.
5. Additional venues and products through adapters.
6. Live state-dependent priors and better execution estimates.
7. Portfolio-aware fees/positions, if requested.

Every extension supplies game identity, native conversion, payout profile, fee model, probability/conditioning policy, quantity basis, and validation cases. The main UI can remain the same.

### 15.2 Observation schema

Later, an optional bounded settlement log can store:

- Canonical game and selected contract IDs.
- Decision-time source quotes and references, or their exact retained snapshot references.
- Rule, fee, policy, and prior versions.
- Estimated scenario payouts and probabilities.
- Actual sporting result.
- Actual venue grade and payout, where authentically available.
- Observed fee/refund amounts and corrections, where available.
- Prediction timestamp and later observation timestamps.
- Data-quality and missing-field indicators.

A public sporting result establishes the game result, not the exact venue settlement or the user’s fee. Preserve those distinctions.

### 15.3 Calibration path

Begin with transparent counts/rates by sport, scope, stage, and rule regime. Use prior smoothing when samples are sparse. Track tie/push frequency, exceptional-settlement frequency, venue payout deviations, and fee/price model errors separately.

Backtest on information available at prediction time. Split training and evaluation chronologically. Avoid using later settlement clarifications to improve an earlier prediction retrospectively.

A calibrated provider publishes a new version and central/range estimates. Keep the old prediction unchanged. Compare predictive error, sign/ranking stability, and settlement stress before promoting the new provider.

The 0.5% buffer can eventually become venue/phase-specific based on measured residual error. That is a later policy upgrade; the first delivery uses the simple configurable constant.

## 16. Decision and amendment log

Keep the following fields stable so this plan can expand without rewriting its foundation:

| Item | Current decision | Later amendment |
|---|---|---|
| Default budget | $1,000 total funded capital. | Optional custom/global sizes. |
| Buffer | Approved initial 0.5% of actual deployed capital. | Measured residual-error policy. |
| Initial probability model | Pinnacle decisive weights plus explicitly provisional NFL pregame priors. | Historical and live-state models. |
| Exceptional payout model | Selected terms first; published templates and named proxies otherwise. | Actual venue settlement observations. |
| Fee channel | Published standard direct-site taker scenario. | Selected account/channel/portfolio terms. |
| Depth policy | Observed ladder when available; otherwise clearly marked quote-price model. | More complete native depth and execution modeling. |
| Main display | One game, market comparison rows, buffered dollar/percent estimate. | Additional products using the same contract. |
| Historical treatment | Immutable source observations and versioned successor calculations. | New providers preserve prior versions. |

Each future amendment should record the date, changed decision, reason, affected slice IDs, input/policy version, and acceptance cases.

**Historical approved first milestone:** a reusable Bills/Rams comparison displaying $1,000 estimated values, fee deductions, tie/exception assumptions, the 0.5% buffer and opposing-leg scenario results. General matching, representative slate coverage, local source/runtime verification and actual owner feedback complete the bounded NFL winner workflow before expansion.

### October 11 approval and validation amendment

The owner approved the design and made it the priority, subject to real prerequisite work. Bills at Rams on October 12 replaces the kicked-off Eagles/Jaguars example for single-game validation. EV09 supplies engineering readiness and walkthrough preparation; existing Q04 assigns the actual feedback/acceptance decision to the owner. Existing Q03 source/accounting qualification remains required final integration evidence, not a demand for perfect actual-net inputs. EV10/EV11 remain later work. These amendments change the design/handoff documents only; frozen source observations and prior qualification evidence are preserved.

EV07 interface implementation and required actual-browser/HTTP qualification are locally complete in [the successor report](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-interface-qualification.md). Original incomplete records remain historical. Strict EV08 qualification remains incomplete in [the preserved runtime report](../test-results/ev09-d04-installed-20261014/repair6-workspace/docs/estimated-runtime-bootstrap-closeout.md). The October 12 owner direction makes [ordinary-app delivery](estimated-runtime-ev08-next.md) first: Q03 integration/collection -> EV09 minimum actual-app verification/handback -> Q04 use/feedback. Broad performance, whole-slate and browser distributions remain follow-up; formal source evidence can be gathered alongside use. No original failed check is marked passed.

### October 14 owner comparison-usability correction

The owner requests required presentation changes after the installed all-games handback: both observed Polymarket Long/Short directions directly visible with accurate native labels, Pinnacle/fair prices in American odds, concise EV/Arbs comparisons instead of repeated detailed reports, and distinct-venue-only Arbs under all filters. Fair-vs-offered meaning, native predicates, original inputs, funded arithmetic and one buffer remain intact. Long scenario tables move to Details with material risk/status retained on the compact row. U01 frontend/UX executes first, with B01 read-contract support only where demonstrably needed; D04 qualifies the changed installed flow, and Q04 remains the owner's actual decision. This amendment updates requirements/planning only and does not declare the correction implemented or accepted.
