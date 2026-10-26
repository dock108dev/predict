# Calculation basis and benchmark EV

Original-price comparison supports the configured multi-sport universe. Financial
estimates have narrower, input-specific applicability: the legacy dated recipes
cover NFL pregame full-game winners; strictly bound financial profiles and the
public Novig NFLWIN model have the separate rules described below. A league or
market appearing in Odds does not imply a usable EV model. Calculations do not
establish actual fills, final grades or known total account charges.

## Policy and requested funding

`RequestedTradePolicy` defaults to `predict-estimate-policy-3`, $1,000 requested
funding, `pinnacle` and `proportional_no_vig`, with one 0.5% haircut on actual
deployed capital. Novig and ProphetX are alternative named benchmarks. Amount
must be positive and at most $100,000; buffer rate is 0–1. HTTP buffer values are
rates (`0.005`); the UI displays percentages (`0.5`). Settings do not acquire data.

Requested funding includes acquisition and upfront modeled charges. A single uses
its largest supported legal quantity; a pair shares the request across both legs.
Legal grids, minimums and depth can leave residual funding with an explicit reason.
Unused cash is not an expense or return denominator. Observed depth and a modeled
remainder are labeled separately; an assumed grid does not qualify execution.

Explicit v3 `sizing_mode=ceiling` supports sensitivity calculations. Saved v2
policies retain their original ceiling optimization. Do not silently apply requested
funding semantics to a historical policy. See [financial contract](requested-trade-financial-contract.md).

## Named benchmark

Both original home/away moneyline outcomes must come from the selected sportsbook,
common occurrence and original provider frame, with coherent evidence and clocks.
`TwoWayBenchmark` validates that basis for finance and board display. Missing or
expired selected data stays unavailable; another book is not substituted.

For decimal odds `a` and `b`:

```text
home decisive probability = (1/a) / (1/a + 1/b)
away decisive probability = (1/b) / (1/a + 1/b)
fair decimal price = 1 / decisive probability
```

These probabilities condition on decisive winners. They do not supply tie,
noncompletion or settlement equivalence. Default provisional priors are 0.005 for
tie and 0.001 for terminal noncompletion, subject to scoped applicability; they
are not calibrated NFL rates. Complete EV stays unavailable when a full terminal
partition cannot be bound, while separately labeled conditional EV may remain.

The benchmark requires known nonfuture source clocks within its 1,800-second
window. Execution/content eligibility has additional original-clock, kickoff and
expiry requirements. Receipt or calculation time never refreshes a source price.
Native NO is not automatically opponent YES, and Short keeps its own collateral
and original-price interpretation.

## Financial meanings

| Value | Meaning |
| --- | --- |
| Gross benchmark EV | Decisive probability × offered gross payout − acquisition, before fees and exceptional rules |
| Net modeled EV | Expected net profit over the complete disclosed state partition; null if that partition is unknown |
| Conditional net EV | Separately named expectation over decisive outcomes |
| Decisive opposing margin | Minimum pair profit across the two decisive winners; does not require a probability benchmark |
| Complete modeled minimum | Minimum across every declared joint settlement state; null if a cashflow is unknown |
| Buffered value | Relevant net EV or scenario profit minus buffer rate × deployed capital, once |

Exact decimal/rational strings carry the calculations. Details reconciles gross
value plus rule adjustment minus upfront and expected settlement fees to the
stated net estimate, then one buffer. Already-withheld charges remain in net
receipts; joint-market commission is assessed on pooled gain rather than summing
standalone maximum fees. Percentages use deployed funding.

Complete positive pairs, rule-sensitive hedges, positive single EV and
conditional/nonpositive/unavailable results remain separate categories. Singles
never establish an arb. Positive expected value cannot override a losing scenario,
and positivity across modeled states does not establish a guaranteed real fill.

## Applicability and limits

`app/fixtures/estimated-content-v1.json` supplies versioned, dated model recipes
with effective intervals and expiry. They are not an automatically updated rules
feed. Original contracts, quantities, fees, source/reference clocks and content
horizons must match; expired or conflicting inputs withhold affected estimates.
Other sports' prices do not extend this NFL model. Pair allocation uses a bounded
local search, not proof of a nonlinear global optimum. Actual-net and offline
research engines keep their own stricter dependencies and meanings.

See [data limitations](market-data-gaps.md), [combined inputs](combined-occurrence-input-contract.md),
[API](comparison-board-api-contract.md) and [configuration](configuration.md).

## Bound financial profiles

The dated NFL recipes above retain their original October 16 expiry. No fee,
quantity, settlement or model horizon was renewed. Ordinary funded results can
also use the existing strictly bound shared cashflow/cost/probability owners via
`bound_finance`: this path has no NFL prior and admits only exact applicable
profiles. It preserves fees/funding, computes one selected deployed-capital
haircut, and distinguishes full EV from conditional EV and complete joint minima
from winner decisive margins. Generic line portfolios use a separately named
listed-known-state minimum. Their bounded allocation search is not a global
optimality proof. Unknown mandatory cashflows remain unknown at probability zero.

The ordinary producer's conditional benchmark metadata is accepted as a basis annotation, with exact original weights/receipt checks; it is never parsed as a complete independent probability model.

The financial identity adapter retains validated native scoring and
supported equality descriptors. Completion and payout/fee qualification remain
separate. Where no funded size can be established, a separate
`gross_decisive_benchmark` companion can still report exact winner benchmark
expectation per $1 normal claim, with its own original source/reference clocks.
This is before fees, has no executable size, supplies no exceptional probability,
and never contributes to the net-EV/arb availability or positive filters. A
winner reference cannot qualify spread/total probabilities.

Availability counts the selected input/result scope before positive filtering.
Empty and pending scopes are not evaluated no-positive. Missing inputs,
unsupported inputs and actual calculation failures remain distinct. Conditional
numbers with unavailable full EV are partial; old numbers are last known.
Changed/removed contexts and pending selected Details return not-evaluated
availability rather than a fabricated calculation failure.

## Public NFLWIN product model

Novig aggregate NFL pregame full-game winners now use the reusable
[`novig-nflwin-public-model-20261022-2` basis](novig-nflwin-modeled-basis.md).
Original two-sided references support conditional net EV; a separately disclosed,
uncalibrated tie/void sensitivity supports full modeled expected value. The UI
names the assumption basis. This is not calibrated EV or execution qualification.
Hypothetical USD risk does not require account membership or observed depth.
Actual void receipts and the complete minimum remain unknown even though the
model supplies an expected receipt within that bucket. Other venues, markets and
native NO/Short sides retain their existing financial dependencies.
