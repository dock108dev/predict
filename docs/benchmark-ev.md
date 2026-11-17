# Fair odds, expected value, and arbitrage

## Pregame Opportunities

The ordinary ticketboard ranks qualified main-line offers at the user's
selected maximum upfront cost. It uses the first eligible reference book in
FanDuel, DraftKings, BetMGM, and Caesars order. The reference is a complete,
coherent set of prices for the same market from one book. Each fair probability
is its implied probability divided by the sum across that set. Matching the
venue bet to the reference also requires applicable market and settlement rules.

The unit model sizes a supported fill and applies its documented fee, reserve,
and settlement terms. If `C` is the actual cash committed and `R[s]` is the
net cash returned in state `s`, effective decimal odds are `R[win] / C` and
Net EV is `sum(p[s] × (R[s] − C)) / C`. A push or refund needs its own probability
and cash flow when it materially affects the model. Keep the observed quote and
any supported fee visible when a required valuation input is missing.

For each exact bet, the board chooses the qualified marketplace offer with the
highest Net EV. Positive offers sort by Opportunity Score, then Net EV and
stable bet ID. The score is the positive modeled Kelly fraction in basis
points. The comparison drawer sorts venues by Net EV. Both use unrounded
metrics. [Selected-unit examples](examples/pregame-board-1/README.md)

## Indicative sportsbook estimate

**Sportsbook estimate** is an indicative comparison available outside the
selected-unit board. For an exact full-game
winner, signed spread, or total, Predict chooses the highest payout on the
selected side among qualifying FanDuel, DraftKings, BetMGM, and Caesars pairs.
Ties follow that order. Both sides must be from the same book and a coherent
observation. Both original source clocks remain visible. The desk keeps the
committed pregame estimate with its original price until authoritative kickoff,
replacement, or withdrawal of a required input. The evaluated offer has its own
source and lifecycle checks.

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
An SGO event frame can supply sportsbook odds for a game even when that frame
contains only conventional sportsbooks. The frame must match the league,
kickoff, and canonical home and away teams. Conflicting or ambiguous event
evidence withholds the cross-source reference. Reviewed college aliases are
scoped to the provider and league that used them.
The shared book order and exact arithmetic live in
[`sgo_reference.py`](../app/comparison/sgo_reference.py). Open the quote to see
the originals and the selected book. [Coverage and freshness](broad-coverage.md#freshness-and-verification-window)

## Financial bases

| Desk setting | Meaning |
| --- | --- |
| Sportsbook estimate | Indicative, before-fee comparison against the exact two-sided sportsbook pair. |
| Before-fee scenario | A separate comparison under the applicable captured reference and settlement assumptions. |
| Conservative after-fee EV | A modeled fee case with its applicable payout and input assumptions. |
| Verified after-fee EV | A separate model classification governed by its reference, evidence, and calculation policy. |

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

The ordinary Arbitrage desk uses a default $100 stake budget before fees. An arbitrage
comparison pairs exact opposing outcomes and ranks the minimum modeled net
return across the supported joint settlement states. Total committed cash
includes the purchase costs, entry fees, and required reserves. Each state
credits returned cash and released reserves and subtracts its settlement
charges. The ordinary drawer uses the same published allocation as the list.

A positive completed-game minimum applies to the listed outcomes and sizing
assumptions. Unverified exceptional states remain visible in details.
Observed liquidity, actual fills, private charges, and execution qualification
have separate evidence requirements. A positive single-offer estimate does not
establish an arbitrage pair. Stale or stopped inputs lose current eligibility
while pinned or archived evidence can remain inspectable. [Arbitrage evaluation](../app/comparison/ordinary_arb.py) ·
[Fee coverage](fee-coverage-policy.md) · [Data limitations](market-data-gaps.md)
