# Fair odds, expected value, and arbitrage

## Sportsbook estimate

The default Pregame basis is **Sportsbook estimate**. For an exact full-game
winner, signed spread, or total, Predict chooses the highest payout on the
selected side among qualifying FanDuel, DraftKings, BetMGM, and Caesars pairs.
Ties follow that order. Both sides must be from the same book and a coherent
observation. Both original source clocks must be within 15 minutes, with a
kickoff cutoff. The evaluated offer has its own source and lifecycle checks.

For the selected book's decimal odds `a` on the outcome and `b` on its opposite:

```text
decisive probability p = (1/a) / (1/a + 1/b)
fair decimal odds      = 1 / p
gross return percent   = 100 × (p × offered decimal odds − 1)
```

For a normal $1 claim costing `c`, the last expression is `100 × (p / c − 1)`.
The selected book's opposite side supplies the other half of the calculation.
Matching teams alone is insufficient. A different line, period, or outcome
changes the bet. The estimate conditions on a decisive result and uses before-fee
prices. An offer can be available when its fair odds or return is unavailable.

The desk can use exact pregame public-board and SportsGameOdds inputs.
The shared book order and exact arithmetic live in
[`sgo_reference.py`](../app/comparison/sgo_reference.py). Open the quote to see
the originals and the selected book. [Coverage and freshness](broad-coverage.md#freshness-and-verification-window)

## Financial bases

| Desk setting | Meaning |
| --- | --- |
| Sportsbook estimate | Indicative, before-fee comparison against the exact two-sided sportsbook pair. |
| Before-fee scenario | A separate comparison under the applicable captured reference and settlement assumptions. |
| Conservative after-fee EV | A modeled fee case with its applicable payout and input assumptions. |
| Verified after-fee EV | A full-state calibrated model with verified market and fee evidence, a current qualified quote, and at least 99% model confidence under the product policy. |

Market and settlement identity are separate checks. Native NO and Short maintain
their native predicates and collateral requirements. A tie, push, refund, or
void can change a payoff. Impossible, missing, or expired inputs withhold the
dependent result. A recent calculation, receipt, or browser refresh does not
renew an original quote's age.

Reviewed SportsGameOdds profiles currently cover normal decisive NBA full-game
moneyline outcomes. Exact event, sportsbook, jurisdiction, market, and receipt
evidence is also required. The packaged jurisdiction binding list is empty.
An indicative sportsbook estimate can qualify without the evidentiary basis
required for a verified result. [Reviewed profiles](../app/fixtures/sgo-reviewed-market-rules-20261110.json) ·
[Jurisdiction bindings](../app/fixtures/sgo-reviewed-jurisdiction-bindings.json)

The public desk excludes the legacy Pinnacle reference. The versioned finance
engine and retained readers document their named benchmarks and assumptions
separately. [Requested-trade contract](requested-trade-financial-contract.md) ·
[Novig NFLWIN model](novig-nflwin-modeled-basis.md)

## Arbitrage and funding

The ordinary desk uses a default $100 comparison funding amount. An arbitrage
comparison pairs exact opposing outcomes and ranks the minimum modeled net
return across the supported joint settlement states. The legs share funding,
including applicable modeled fees. The drawer can size the selected pair for
another amount. Residual cash is separate from deployed funding.

A positive modeled minimum applies to the listed cases and sizing assumptions.
Observed liquidity, actual fills, private charges, and execution qualification
have separate evidence requirements. A positive single-offer estimate does not
establish an arbitrage pair. Stale or stopped inputs lose current eligibility
while pinned or archived evidence can remain inspectable. [Arbitrage evaluation](../app/comparison/ordinary_arb.py) ·
[Fee coverage](fee-coverage-policy.md) · [Data limitations](market-data-gaps.md)
