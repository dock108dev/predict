# SportsGameOdds reviewed reference scope

**Scope clarification, November 11:** The initial sportsbook EV mode selects
the highest payout on the chosen outcome among FanDuel, DraftKings, BetMGM
and Caesars via SportsGameOdds. Each eligible book supplies both sides of
the exact full-game market and line in the same current frame. Proportional
de-vig uses the selected sportsbook's two implied probabilities. EV before
fees is the selected no-vig probability multiplied by the offer's decimal
payout, minus one. The result is conditional on a decisive outcome and is
shown separately from qualified reference and fee results. Native offers
require exact cross-source matching. The labeled SGO fair odds and book
consensus remain available with their own line and timing disclosures.
See the [active plan](../NEXT_STEPS.md).

**Running verification, November 11:** The live named Pinnacle path checks
the offer's live lifecycle and fresh post-start price, plus both original
reference clocks. Both reference clocks must be post-start and at most 15
seconds old when evaluated. The 10:09 p.m. desk showed qualified Polymarket
US fees and zero qualified EV. The retained SGO database had no Pinnacle
rows. [SGO lists Pinnacle for Pro and higher](https://sportsgameodds.com/bookmakers/pinnacle-odds-api).
The account is Rookie. A named result still requires exact occurrence and
settlement and a fresh two-sided pair from an entitled source. See the
[post-reload evidence](sgo-paid-observation-20261111.md).

The initial reviewed multi-book calculation is limited to an NBA full-game,
two-sided moneyline and a completed, normal decisive outcome including
overtime. It does not establish a probability for voids, cancellation,
postponement, early termination or any other exceptional settlement. The
reviewed source profiles are:

- [DraftKings West Virginia general rules](https://sportsbook.draftkings.com/help/general-betting-rules/general-rules): a two-way moneyline includes overtime; sport- and market-specific provisions can override general rules.
- [FanDuel New Jersey rules, July 30, 2026](https://d38ayms4az88sz.cloudfront.net/SB/NJ/2026-07-30T12-49-55.html): the NBA basketball rules include overtime unless a market states otherwise.
- [Fanatics New York house rules](https://sportsbook.fanatics.com/legal/ny/house-rules): basketball two-way moneyline includes overtime, subject to specific market rules.

The rules are evidence about these particular products and jurisdictions, not
evidence that an SGO bookmaker ID or quote represents one of them. In
particular, DraftKings' general rules distinguish two-way moneyline from other
markets; this review does not extend its scoring policy to spreads or totals.
DraftKings' linked page is jurisdiction-sensitive; the review used its West
Virginia rules, and another page view may resolve to a different jurisdiction.
The sources have different interruption and void provisions. Their inclusion in
a decisive-only median does not assert equivalent complete settlement or
independent estimates.

`sgo-reviewed-market-rules-20261110.json` records the limited reviewed policy.
`sgo-reviewed-jurisdiction-bindings.json` is deliberately empty: no reviewed
source evidence currently connects a specific SGO event, odd, frame, venue and
jurisdiction to these market terms. A valid binding is a separately reviewed,
hash-checked retained evidence record, with an effective interval and the exact
market identity. Current implementation binds each review to a response frame;
it therefore needs new reviewed evidence when that frame changes. A more
durable market-level jurisdiction binding requires provider or direct-venue
evidence that establishes its validity across subsequent observations.

The SGO reference policy tries an independently qualified named Pinnacle pair,
then a median of at least three separately qualified bookmaker pairs. The
evaluated venue is excluded. Each pair is proportionally de-vigged before the
median; source and frame clocks, receipt evidence, contributors, exclusions,
rule versions and exact input revisions are retained. A changed contributor or
expired source withdraws the result. Rules do not establish occurrence identity:
the native and SGO event must have a non-estimated shared-ID or reviewed-edge
match, and the native normal-scoring evidence must agree. If an input is absent
or ambiguous, source prices remain visible and reference/EV are unavailable.

The rules and fixture calculations are not a live entitlement check, calibration
study, verified quote-jurisdiction mapping or proof of executable liquidity.
