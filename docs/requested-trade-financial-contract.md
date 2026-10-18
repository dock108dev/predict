# Financial calculation interfaces

The server uses shared policy, benchmark, funded single and opposing allocation
owners. This contract describes their exact inputs, output meanings and limits.
See [calculation basis](benchmark-ev.md) for the user-facing explanation.

## Persistence boundary

Ordinary reads build transient typed inputs from current rows, keep shared
definitions once and expand only selected Details. Complete profile/scenario
graphs are not persisted per quote, poll or calculation. Current board and client
identities bind those same inputs; see the [board contract](comparison-board-api-contract.md).

## Invoke the owners

```python
from app.comparison.estimated_policy import RequestedTradePolicy
from app.comparison.source_inputs import produce_two_way_benchmark
from app.comparison.estimated_ev import evaluate as single
from app.comparison.estimated_pair import Leg, evaluate as pair

policy = RequestedTradePolicy(capital_ceiling_usd='1000', buffer_rate='0.005',
                              benchmark_venue='novig')
benchmark = produce_two_way_benchmark(original_typed_outcomes, venue='novig',
    receipt_sha256=original_receipt_sha256, source_revision=original_observation_revision)
s = single(quote, profiles, at=original_applicable_instant, event=event, group=group,
           policy=policy, benchmark=benchmark, details=True)
legs = [Leg(q, g, profiles, event, original_applicable_instant,
            policy=policy, benchmark=benchmark) for q, g in opposing_members]
p = pair(legs, policy=policy, details=True)
```

The two benchmark rows contain original `CanonicalSelection.to_dict()`, `decimal_odds`, `book_at`, `market_at`, `received_at` and `revision`. They must be genuine moneyline selections from the named supported sportsbook (Pinnacle, Novig or ProphetX), one decisive home win and one decisive away win, in one occurrence/provider event/market, full game including overtime, with coherent clocks and receipt evidence. The source revision identifies their common observed frame. No book discovery, side relabeling or missing-book substitution occurs here. The combined-input adapter supplies admitted selections and the authentic original frame association. The producer validates the typed originals; it does not certify source authenticity independently of that association.

A benchmark can instead be attached as a content-addressed `reference` profile using `produce_two_way_benchmark`'s exact payload. The financial owner consumes it through the same validator. The legacy reference producer and Pinnacle v1 reader retain their old wire meaning. Execution tie/completion predicates and payout scopes remain separate from the benchmark's decisive win weights. NO/not-win never becomes opponent YES.

`DEFAULT_POLICY` is `predict-estimate-policy-3`; `EstimatePolicy()` and `LEGACY_POLICY` remain explicit v2 ceiling policies. `EstimatePolicy.from_dict` dispatches by version and checks the complete wire shape and revision. New-policy `sizing_mode='ceiling'` allows a separately identified ceiling comparison; v2 never changes semantics. `capital_ceiling_usd` is the funding owner's retained wire field and equals `requested_amount_usd`.

## Results and filters

Use the explicitly named fields in `financial_metrics` to select the financial meaning. The compatible `buffered_profit_usd` alias retains its conditional meaning. Values are exact decimal/rational strings; percentage denominators are deployed capital. Rich and compact single/pair owners preserve these groups:

| Group/field | Meaning |
|---|---|
| `sizing_mode`, `requested_amount_usd`, `residual_funding_usd` | Settings and actual unexplained/unspent funding; residual has a search/grid reason. |
| `funding` | Requested/deployed/residual USD; per-leg quantity, units, acquisition, upfront fees and independent funding; support is modeled unless observed. |
| `benchmark` | Actual selected venue/method, revision, both originals, original clocks/evidence and missing-reference reason. |
| `financial_metrics.gross_benchmark_ev_usd` | Decisive probability times offered gross payout minus acquisition, before charges/exceptional rules. |
| `net_modeled_ev_usd`, `buffered_ev_usd` | Complete disclosed probability partition's modeled net profit, then one deployed-capital haircut; null when full EV is unknown. |
| `conditional_net_ev_usd`, `conditional_buffered_ev_usd` | Separately named decisive conditional expectation when calculable. |
| `decisive_opposing_margin_usd`, `buffered_decisive_opposing_margin_usd` | Pair minimum across the two decisive winners. Independent of a benchmark. |
| `complete_modeled_minimum_usd`, `buffered_complete_modeled_minimum_usd` | Minimum over every declared joint state, including asymmetric terminal grades; null if any cashflow is unknown. |
| `rule_adjustment_usd` | Exact reconciliation adjustment for exception probability/payouts, refunds, holds and consumed allowances, under the explicitly declared reconciliation condition. |
| `expected_settlement_fee_usd` | Probability-weighted separately payable charge under the full partition, never a maximum charge. A conditional reconciliation charge has its own field. |
| `classification` | Complete positive pair, rule-sensitive hedge, positive single EV, conditional or nonpositive/unavailable; adverse/unknown outcomes and a simple reason. |
| `model_versions`, `dependency_revision`, `revision` | Policy, sizing, probability/content/financial contracts and original reference identities. |

`gross + rule_adjustment - upfront_fee - reconciliation_expected_settlement_fee` equals the declared complete or conditional net estimate. The buffer is subtracted once after that estimate and once from each inspected scenario, never charged to funding. Already-withheld charges stay inside attached net receipts; pooled payable commissions are charged at the joint market gain rather than summing standalone maxima.

Use `classification.main_positive_eligible` for the main positive list. Singles never establish an arb. Use `positive_rule_sensitive_eligible` for a separate hedge list and show its adverse/unknown states. A positive expected value or a zero exceptional probability cannot override a losing scenario. Losing results remain inspectable. Current dependency aging/stopping withdraws positive-list authority. These are modeled economic categories; actual fills, charges and grades remain unknown.

## Identity, storage and limits

`effective_policy` accepts exact `amount` (or compatible `ceiling`), buffer, sizing mode and benchmark venue/method. Conflicting amount aliases reject. Current board, slate and Details reads bind their calculation context to that policy revision without a durable saved result. Attaching/changing either original reference changes the dependency/reference/result revision. The selected benchmark and shared model versions remain exact transient dependencies; the calculation context binds those revisions. Full saved combined profiles are not required.

The engine binding includes sizing, policy, benchmark and metrics owners plus source/domain validation. If a legacy fixture/result is deliberately retained, its engine/policy meaning stays original. It need not survive a sports reset. Never relabel an old result as current or silently bind mutable current inputs to an old immutable snapshot ID.

Requested pair sizing uses at most 24 local balance iterations / 192 balance probes and a 5×5 legal neighborhood. It balances allocation-specific net decisive cashflows and funding, then selects the closest balance, using greater funding to break equal balance. It retains the $25 exposure floor and 20% share constraint. It does not prove a global optimum for nonlinear fees/depth. A diagnostic continuous grid is expressly hypothetical; actual/native or declared grids are evaluated separately. Single sizing preserves the existing maximum-funded legal search and next-quantity proof or specific limitation. Observed depth is consumed before a labeled residual at its last price; no modeled remainder claims observed liquidity.

Result schemas are [policy v3](contracts/predict-estimate-policy-3.schema.json), [generic result v2](contracts/predict-estimate-2.schema.json), [single v2](contracts/predict-funded-single-2.schema.json), [pair v2](contracts/predict-funded-pair-2.schema.json) and [benchmark v1](contracts/comparison-two-way-benchmark-1.schema.json). Older schemas remain readable under their declared versions.

## Last-known evaluation and availability

Requested-trade calculations separate retained-price calculability, current
model/fee/rule applicability and current positive eligibility. They may consume
aged original two-sided reference weights for labeled inspection. Missing
originals, unknown/future/conflicting clocks, unresolved Short collateral and
unsupported models or sizing remain unavailable. Strict benchmark consumers
retain their default freshness refusal.

For ordinary transient reads, `at` is the captured read/evaluation instant.
`calculation_instant` checks original quote clocks and returns that boundary; it
does not backdate a quote into an old model interval or advance into a future
model. Content, selected fee/rule/quantity/identity/reference validity and
occurrence/pregame guards apply at the same boundary. Models can expire while
prices remain visible. A mixed-time dependency set does not establish a
simultaneous historical trade.

`evaluation_frame` records that boundary and the original clocks. The response's
`calculated_at` records actual calculation completion. Structured result and
metric `availability` distinguishes supported inspection values from current
positive eligibility. A numeric pair margin can coexist with null complete EV
when the probability partition is incomplete. Board and Details use the same
server-derived percentage fields and deployed-capital denominators. See the
[board availability contract](comparison-board-api-contract.md#calculation-availability)
for transport states and summary semantics.

## Scanner input readiness and classification

The [readiness schema](contracts/predict-scanner-readiness-1.schema.json) describes
execution clocks, depth, source availability, mandatory identity/fee/quantity/
payout/settlement facts, and optional EV references. A structurally ready pair is
neither an arb classification nor an EV result.

The scanner separately classifies covered-outcome, conditional and EV results.
Cashflow qualification uses current mandatory contract facts independently of
optional EV references, every required feasible state, observed legal allocations
and one deployed-capital buffer. Neutral refunds and losing zero-probability
states remain in the complete minimum. A bounded nonqualifying sizing search
cannot establish evaluated-zero unless exhaustive. Existing board/slate/Details
wire versions retain their meanings. See the [scanner contract](scanner-projection-contract.md)
and [financial examples](scanner-qualification-decisions.md).
