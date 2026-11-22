# Fair odds, expected value, and arbitrage

## Pregame Opportunities

The primary dashboard uses complete current calculations from the affected-game
path described in [Current pregame](current-pregame.md). Every venue for the same
exact bet uses the eligible complete same-book pair with the lowest unrounded
no-vig win probability. Eligible books are FanDuel, DraftKings, BetMGM and
Caesars; that order breaks exact probability ties. At least two distinct trusted
books must each offer a complete opposing pair for this exact line. Untrusted
books, incomplete pairs and different lines do not count toward that minimum. The policy
is `lowest-no-vig-two-trusted-books-2`, calculation version `predict-current-pregame-6`.
It minimizes EV among those sportsbook estimates for the selected long bet;
it does not establish the true probability or a statistical lower bound. Match the occurrence, full-game period,
market, exact line and opposing outcome identities before arithmetic. Genuine
identity, scoring or outcome contradictions exclude the comparison. Main/alternate
classification keeps the established source and fixed-priority line evidence,
independently of which book supplies the conservative probability.

For two decimal reference prices `a` and `b`, fair probability is
`(1/a) / ((1/a)+(1/b))`. Choose using the full same-book pair, not one posted price or a pair assembled
across books. For UCLA −33.5, FanDuel −110/−110 gives 50%; DraftKings and BetMGM
−105/−115 give 903/1846 ≈ 48.9166%. Novig +115 with zero fees therefore has
+5.17% EV instead of +7.50%, and a rounded score of 450 instead of 652.
Preserve original prices and timestamps. Historical proof
reconstruction and execution depth are not routine calculation prerequisites.

Posted-price cashflows use an internal **$100 maximum upfront comparison basis**
where fees, quantity increments and rounding require an amount. It is a
normalization, not a stake control or proposed order. Use the largest legal
quantity under the basis, without execution fill-tolerance eligibility.

For committed cash `C` and net receipt `R[s]`:

```text
after-fee decimal odds = R[win] / C
Net EV = sum(p[s] * (R[s] - C)) / C
expected dollar profit = C * Net EV
Opportunity Score = 10,000 * max(0, Net EV / (after-fee decimal odds - 1))
```

The tested score engine also handles supported nonbinary cashflow models. Use
exact fractions until display rounding. Winning commissions reduce winning
receipts; entry fees increase committed cash. A supported zero remains numeric
`$0.00`. Missing mandatory fee terms exclude an opportunity and retain an internal
reason. [Fee applicability](fee-coverage-policy.md)

Group equivalent exact bets before pagination, select their highest Net EV venue,
and rank by the selected unrounded metric, Net EV and stable identity. Venue
comparisons sort by Net EV. Main-line evidence, rather than payout or EV, controls
default line eligibility.

### Default ranking: Kelly growth

Kelly growth is the default. The original
Opportunity Score remains available as **Kelly fraction**. Let `p` be the stored
reference win probability, `b = R[win]/C − 1`, `l = R[loss]/C − 1`, and
`f = Opportunity Score/10,000`. The read-time growth index is:

```text
Growth = 10,000 × [p × ln(1 + f×b) + (1−p) × ln(1 + f×l)]
```

Its unit is natural-log basis points, not win probability or expected profit
percentage. A zero-probability outcome contributes zero. PostgreSQL numeric
arithmetic evaluates the full-cohort logarithms before pagination; displayed
rounding is never an ordering input. This compares isolated modeled bets; it
does not optimize a correlated portfolio or prescribe stakes.

**Rank by** also exposes Net EV, Kelly fraction, **Balanced**
(`10,000 × Net EV / sqrt(b)`, an experimental heuristic), and **Probability edge**
(`100 × [p − (−l/(b−l))]`, in percentage points). Every choice retains the same
eligibility, exact-bet grouping, best-Net-EV venue, reference inputs and fees.

## Indicative sportsbook estimate

The current dashboard has one posted-price calculation model. The reference,
fee and cashflow inputs travel together in the committed row; there is no
calculation-mode selector. Source timestamps stay in details and pregame prices
do not expire solely because they are old.

The financial bases below describe separate historical, research and Scanner
contracts. They do not gate ordinary pregame display.

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

## Coherent research baseline

The per-bet conservative screen remains `lowest-no-vig-two-trusted-books-2`.
It can choose different books for opposite bets, so its outputs are not a single
complementary event distribution. Current version seven also retains
`first-complete-trusted-pair-proportional-1`: one complete same-book pair selected
in fixed FanDuel, DraftKings, BetMGM, Caesars order, preserving both outcomes.
The optional `same-book-betonline-first-1` adds a reference capability and
excludes the evaluated book. Neither policy is an empirical accuracy claim.

`app/research/calculation.py` freezes exact source and fee inputs, policy version,
quantity/rounding, settlement assumptions and results. `app/research/records.py`
keeps append-only prospective populations, causal horizon captures, independent
sporting outcomes and frozen Brier/log-loss/calibration reports. Record counts
and distinct events are reported separately. Missing/excluded cases are retained;
actual trades remain in the separate optional journal. Run
`python -m app.research --help` for declaration, replay, capture and evaluation.
