# Trading fee coverage policy

Predict measures trading fees for manual retail trades placed on the venue’s
app or website. Market-data APIs may provide quotes, market terms and reference
odds. The comparison desk is read-only. The current goal is 99% numeric fee
coverage within the configured ordinary scope.

## What counts

- The denominator is every distinct current, displayed-price offer across
  active native and SGO-attributed venues in the configured NFL, NCAAF, NBA,
  NCAAB, MLB and NHL winner, spread and total scope. Historical ProphetX rows
  remain identifiable in the diagnostic inventory. Additional venues are backlog
  work. Include supported periods,
  alternate lines and in-game offers wherever the live desk publishes them.
  Take the census before fee, EV, reference or positive-only filters. Use the
  venue, market and executable side to deduplicate repeated presentations.
- Count an offer once when Predict can show the fee or fee cashflows for the
  documented trade profile, price, size, fill assumption and applicable
  effective terms. An evidenced $0 fee counts. An expired, unknown, partial or
  illustrative-only fee does not. A venue-only fee can count for a profile
  whose charge scope is fully evidenced. It remains partial for an
  intermediated profile with additional unknown charges.
- Use an immediate taker fill for the default comparison. Manual placement
  describes the trading channel. Maker or taker describes each fill. State
  the quantity, unit, fee timing and holding assumption. Distinguish a
  normalized claim from a user-selected order size. Compute rounding at the
  modeled fill or order size before ranking. Show resting-order or split-fill
  results as separate cases when the inputs support them.
- Report the numerator, denominator and missing reasons overall and by venue,
  league, family, period and pregame/in-game state. Report source inventory
  gaps and stale or unpublished prices separately so lost data cannot look
  like improved fee coverage. An empty cohort has no measurable percentage.
  List products outside the configured scope separately.
- Track fee coverage, exact Pinnacle reference coverage, after-fee EV
  coverage and two-leg fee coverage as separate measures. A supported fee
  remains inspectable when the reference is missing. An arb's after-fee
  payoff needs both fees and the same settlement cases on both legs.

## Public estimates and account terms

The [fee-only outcome](../app/comparison/snapshot_fee_outcome.py) owns the
ordinary fee display. Its venue models use the reviewed schedule or an
explicitly labeled estimate. The [renewal state](../app/fees/product_schedules.py)
records effective terms and review deadlines. The [census](../app/dashboard/fee_coverage.py)
counts the resulting current offers. Captured replay retains the original
terms and deadline.

A provider's effective dates and Predict's verification deadline describe
different things. The installed app can withhold a fee when its local review
expires, even while the schedule is still published. The remaining fee work
in `NEXT_STEPS.md` covers reliable change detection, exact-market
applicability and explicit handling of standing terms when a recheck fails.
The current verified and conservative fee counts retain their existing
meaning until that behavior is implemented and qualified.

Use the applicable published fee when it is deterministic. If a public profile
admits several documented possibilities, price each applicable case using
the same order and show the highest modeled fee or lowest net payoff as
appropriate. State the range or assumption. Ignore uncertain rebates in the
conservative comparison. A maximum across documented scenarios only bounds
those scenarios. If a private override or mandatory intermediary charge has
no evidenced bound, show the public scenario with its scope and keep the
personalized result incomplete.

| Venue | Manual retail fee policy | Optional facts for a personalized retail result |
| --- | --- | --- |
| Novig | Preserve verified $0 on eligible pregame game lines. Bind the native v3 market fee object and observed phase to live quotes. For ordinary live game lines, the v3 schedule documents a 0.06 taker coefficient applied at fill time. Use the market field and preserve the native quantity unit. If an aggregate quote cannot be bound to that exact market and phase, report the missing evidence. [Novig v3 schedule](https://docs.novig.com/api/concepts/fees) | None for the documented public straight-trade profile. Any negotiated terms or incentive the owner specifically wants modeled need their own evidence. |
| Kalshi | Default to the high side of the published exchange taker schedule. Apply the current market multiplier and the higher charge from the documented direct and non-direct rounding cases at the displayed price and size. Count this exchange-only estimate toward public fee coverage. [Kalshi exchange schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) · [Rounding rules](https://docs.kalshi.com/getting_started/fee_rounding) | None for the public estimate. For a personalized result, verify your membership channel and any mandatory intermediary charges and effective dates. |
| Polymarket US | Use 0.095, the highest published standard taker coefficient, for the conservative retail estimate. Apply it to contracts times price times one minus price, with half-even cent rounding and the documented cumulative order cap. Model the schedule in effect at order insertion and assume zero rebates. [Polymarket US fee schedule](https://docs.polymarket.us/fees) | None for the public estimate. An active tier or an override matters only for a personalized retail calculation. |
| ProphetX | Use ProphetX's official retail straight-contract schedule. NHL taker fees use 0.035 times contracts times price times one minus price, with half-up cent rounding and carry across fills. Other straight markets charge 2% of positive net gains per market. For a new standalone position, show that fee in the winning settlement cashflow. [ProphetX retail schedule](https://www.prophetx.co/lobby/t-c/trading-fees) · [Straight-contract PDF](https://framerusercontent.com/assets/0PR4FR5AUuNv0xMjMRGkbz8GZ0.pdf) | None for the public standalone-position estimate. Existing positions matter if the user wants their combined market commission modeled. |

**Owner input.** The manual retail milestone needs no private account terms.
If a personalized retail calculation is requested later, use existing
evidence first and request only the missing fact and its effective dates.
Keep credentials and private account evidence out of repository fixtures.

**Kalshi high-end rule.** Use the linked schedule's standard taker formula
`0.07 × multiplier × contracts × price × (1 − price)`, with the fee type,
multiplier, waivers and scheduled changes for the exact market. Compare the
published rounding cases and use the higher exchange charge for the modeled
fill. At multiplier 1 and a price of $0.50, this gives $0.02 for one contract
and $1.75 for one fill of 100 contracts. Calculate each at its own size.
The public estimate can ship with unknown membership. Disclose that an
intermediary may charge separately. Any supported account-specific calculation
uses verified terms. [Kalshi PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) ·
[Current changes](https://kalshi.com/fee-schedule)

## Schedule inventory and expansion rules

Reviewed against the published sources on November 9, 2026. Preserve each
schedule's product, channel, role, price and quantity units, applicability
time, fee basis, rounding, fee timing, exemptions, credits, and source
revision. Separate fees debited on a fill, fees built into quoted prices,
commissions at settlement, and credits paid later. Preserve those distinctions
in the payoff and ranking. Record effective dates separately from retrieval
dates. Recheck rates and exceptions before enabling a new market family.

### Novig

- **Game lines.** Eligible pregame straight fills are fee-free. Live
  taker fills use the exact v3 market `fee` object and event state at match
  time. The documented game coefficient is 0.06 while live. Maker fees are
  $0. Keep the v3 one-cent payout unit and the retail dollar-normalized unit
  explicit. The documented fee is rounded half up to $0.00001 per fill.
  The retail Help Center gives a conflicting 0.03 multi-price example and
  describes volume-weighted pricing. The v3 reference documents 0.06 and
  fill-level pricing. Use the v3 basis for an evidenced one-fill scenario
  with an exact market and phase binding. A transition that clears the book
  requires a fresh quote. Verify retail split-fill treatment before offering
  it as exact.
  [v3 trading fees](https://docs.novig.com/api/concepts/fees) ·
  [Retail fee schedule](https://support.novig.com/en/articles/16195057-fees-on-novig) ·
  [Event lifecycle](https://docs.novig.com/api/concepts/event-lifecycle)
- **Futures and maker credits.** The v3 docs describe 0.06 taker fees on
  eligible futures in all phases, including the six configured sports.
  They list PGA, ATP, WTA, UFC, F1, NASCAR and series winners as fee-free
  under their market schedule. Use the exact market field because the
  retail Help Center lists narrower exceptions. Track the documented maker
  cash credit of 25% of the fee collected on eligible live game fills and
  50% on eligible futures fills. Credits can take up to seven days and
  depend on eligibility and collection of the original fee. Keep these
  separate from the default estimate.
  [v3 product scopes](https://docs.novig.com/api/concepts/fees) ·
  [Maker Credit terms](https://docs.novig.com/maker-credit-program)
- **Parlays and requests for quotes.** Retail parlay quotes already include
  the fee. Record the quote as all-in. The separate RFQ formula has a 0.10
  taker coefficient on the combined stake and collateral, applied on
  execution, with no maker fee or credit. Preserve the quote basis and
  product before enabling combo comparisons.
  [Retail parlay terms](https://support.novig.com/en/articles/16195057-fees-on-novig) ·
  [RFQ schedule](https://docs.novig.com/fees)

### Kalshi

- **Event contracts.** Preserve the public 0.07 base taker coefficient
  and the applicable market multiplier, fee type and waiver. For eligible
  maker-fee markets, preserve the 0.0175 base maker coefficient and its
  multiplier. Other resting maker fills carry no exchange trade fee where
  the effective schedule supports that. Model trade-fee rounding, the
  account precision grid and cumulative per-order rounding refunds. Keep
  the high-end exchange estimate available with unknown membership.
  [Exchange PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) ·
  [Current fee changes](https://kalshi.com/fee-schedule) ·
  [Rounding mechanics](https://docs.kalshi.com/getting_started/fee_rounding)
- **New series, futures and combos.** Reuse the event-contract engine only
  with exact terms. The PDF includes nonstandard series and a separate
  combo entry with an uncorrelated NFL exception. Resolve combo fee type,
  maker multiplier and exceptions from current product metadata and
  terms before enabling. The PDF also carries separate perpetual-futures
  maker and taker volume tiers. Treat perps as a separate product and
  revalidate current tiers, notional and funding before any expansion.
  [Exchange PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) ·
  [Perps fee documentation](https://help.kalshi.com/en/articles/16071417-perps-fees-explained)
- **Other costs.** The exchange PDF lists no settlement or membership fee.
  It separately describes ACH, card, wire, crypto and alternate payment
  rails. Keep those costs and any intermediary fees separate from the
  ordinary exchange trade fee.
  [Exchange PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf)

### Polymarket US

- **Standard contracts.** The November 6, 1 p.m. Eastern cutover publishes
  taker coefficients 0.095, 0.085, 0.075 and 0.0695 at volume thresholds of
  $0, $10,000, $50,000 and $250,000. Keep 0.095 as the conservative
  standard retail estimate. The coefficient follows order insertion.
  Preserve half-even cent rounding, the cumulative fee cap across fills,
  the acquired side's actual cost and explicit zero fees when rounding
  produces zero. Record the previous standard schedule and the former
  table-tennis exception by effective date for replay and expansion.
- **Personalized tiers and rebates.** Record the 30 completed Eastern
  calendar-day volume basis, daily tier changes, first-fill onboarding,
  the November transition for existing accounts, and overrides as
  eligibility evidence for future work. Maker rebates are separate
  fill-time credits with four tiers. Taker rebates have six tiers from
  0% to 30% and pay weekly. Preserve the maker and taker volume bases
  separately. The conservative retail estimate assumes zero rebates.
- **Combos.** The November 9 schedule uses
  `C × p × [0.0695 × (1 − p) + 0.085 × (1 − p)^4]`.
  The announced November 11, 1 p.m. Eastern change uses the applicable
  taker coefficient in the first term and 0.06 in the fourth-power term.
  Verify activation before applying it. At 100 contracts and a combo price
  of $0.50, the November 9 schedule yields $2.00. The announced schedule
  at the 0.095 standard tier yields $2.56 for the same fill. The calculation
  uses the complete combo price. Combo fills carry no maker rebate, and
  an eligible taker rebate applies to the collected fee.
  [Official fee schedule and dated changes](https://docs.polymarket.us/fees)

### ProphetX

- **Retail straights.** NHL uses 0.035 for takers and 0.01 for makers in
  `coefficient × contracts × price × (1 − price)`. Apply half-up cent
  rounding per fill with the remainder carried per order. Other straight
  contracts charge 2% of positive net gains per market at settlement.
  Keep standalone and whole-market position scenarios separate. Capture
  the relevant order-time schedule and verify how the quoted stake treats
  the NHL fee before comparing funding requirements.
  [Retail straight-contract PDF](https://framerusercontent.com/assets/0PR4FR5AUuNv0xMjMRGkbz8GZ0.pdf)
- **Retail parlays.** The taker rate per dollar staked is
  `0.021 × (1 − p) / (0.25 + p) + 0.006`. Multiply by the trade cost,
  round half up to cents per order and apply the $0.01 minimum. Retail
  parlay makers pay $0. Verify the quote basis, size and rounding with
  the official $0.92 example for 100 contracts at $0.65.
  [Retail parlay PDF](https://framerusercontent.com/assets/VsAbQWl7oaM7Pi1ZpLn0abo32I.pdf)
- **Position exits and channel differences.** Treat an early close as its
  own priced action. ProphetX documents a separate API close fee on
  profit. Use applicable retail exit terms or an actual retail preview
  before modeling that action. Negotiated API fills remain a separate
  future product.
  [Retail fee index](https://www.prophetx.co/lobby/t-c/trading-fees) ·
  [Documented API position-close rules](https://docs.prophetx.co/docs/positions)

### Expansion order

After the active 99% milestone, open separate slices for maker and split
fills, expanded straight markets and sports futures, and combo or parlay
products. Give each new scope its own source census, effective-time
fixtures and payoff checks before adding it to the coverage denominator.
Qualify early exits and optional account programs as separate scenarios.
Track deposits, withdrawals, payment-rail costs, intermediary charges,
funding and taxes separately from trade EV. Expand into other asset
classes only with their own terms and risk model. Preserve original prices,
terms and credits in replay even when current schedules change.
