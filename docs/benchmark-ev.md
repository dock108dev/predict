# Calculation basis and benchmark EV

The app keeps gross benchmark EV, modeled after-cost EV, actual net EV and
opposing-leg arbitrage separate. A positive, zero or negative value is valid;
missing inputs withhold only the calculations that depend on them.

## Pinnacle benchmark

The shared aggregate request includes Pinnacle as a reference alongside Novig
and ProphetX. Pinnacle is never an execution venue or arbitrage leg. For a matched
two-way market, proportional margin removal gives:

```text
probability = (1 / selected decimal odds) / sum(1 / both decimal odds)
gross EV % = 100 × (probability / normalized acquisition cost − 1)
```

Original values and exact fractions determine the result. Details discloses the
reference odds, clocks, method and assumptions. Event, participant/predicate,
market, period, line and orientation must match. NO is not automatically opponent
YES. Incomplete references do not disable otherwise admitted venue prices.

Reference and comparison source clocks must be known, nonfuture and within the
30-minute benchmark window; native source eligibility is also required. Receipt
time never renews the original price age. Whole lines requiring push probability
are withheld. This is a conditional win/loss benchmark before fees, excluding
ties, pushes and exceptional settlement, not a calibrated probability model.

## Costs, size and funding

Comparison sizing defaults to a $100 prefunded capital ceiling, taker execution,
standalone portfolio and already-funded balances. An optional Details override
recalculates dependent results. Actual deployed capital is the return denominator;
unused ceiling residual is not treated as an expense. Unit grids, legal price
ticks, minimum quantities and shared liquidity constrain sizing.

Conservative estimates use explicit adverse-price and fee assumptions. Pregame
source age is limited to 900 seconds and live age to 15 seconds for the comparison
cost policy; the gross benchmark uses its separate 1,800-second window. These are
admission rules, not guarantees of execution or predictive accuracy. Missing depth
cannot establish executable size. Returned holds, consumed charges and acquisition
cash are counted separately, once.

Direct-site modeled estimates disclose their fee channel, probability condition
and assumed charges. A modeled zero additional charge cannot establish known total
costs. Actual net calculations require applicable payout terms, mandatory charges,
fees, timing, probability and depth. Unknown values remain unknown.

`collection/current_benchmark.py` owns gross reference binding;
`comparison/costs.py`, `buffers.py`, `cashflows.py` and the net metric modules own
cost policy, funding and dependent calculations. See [architecture](architecture.md),
[data limitations](market-data-gaps.md) and [interface design](ui-design.md).
