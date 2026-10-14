# Calculation basis and benchmark EV

The ordinary saved-board model evaluates NFL pregame full-game winners. It uses
original source prices, a selected two-way sportsbook reference, scoped fee/payout
recipes and disclosed provisional exceptional-outcome probabilities. It does not
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
