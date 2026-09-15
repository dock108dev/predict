# Current official-source fee review — September 12, 2026 UTC

Retrieval instants and byte hashes are in `sources.json`. Dates printed below are
publication/effective claims, not download dates. Current schedule knowledge is
documentation qualification; actual fills and account arrangements remain unverified.

## Kalshi

[July PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf),
[rounding](https://docs.kalshi.com/getting_started/fee_rounding),
[series](https://docs.kalshi.com/api-reference/market/get-series),
[event changes](https://docs.kalshi.com/api-reference/events/get-event-fee-changes).

The PDF reports July 7 effectiveness, 0.07 taker and 0.0175 maker before
multipliers, and no settlement levy. Its table gives $1.75 for 100 contracts at
.50. Detailed rounding uses six-decimal ceiling then signed balance flooring to
.0001/direct or .01/non-direct, with a capped per-order refund across roles.
The rounding page lacks an effective timestamp; historical use stays conditional.

Current NFL metadata is quadratic-with-maker, multiplier 1. Captured MLB history
changes 1 to .5 at 2026-08-07T04:59:45.131Z. Event overrides take precedence;
null clears each component independently. Combo-maker metadata uses half the
taker coefficient. Flat schedules remain unsupported. FCM charges and negotiated
incentives need separate account evidence. No undocumented minimum/cap is added.

The direct PDF response was 429; `kalshi-pdf-browser.json` retains the successful
browser extraction and original URL. Date-only effectiveness is not assigned UTC
midnight. Historical maker reimbursement language from older schedules is not
applied to this current schedule.

## Polymarket US

[US fees](https://docs.polymarket.us/fees),
[whole-contract policy](https://docs.polymarket.us/learn/trading/basics/fractional-shares).

The exchange-wide schedule starts July 1, 2026 at 00:00 ET (04:00 UTC): .06 taker,
.0125 maker rebate. All rounding is cent half-even. Taker per-fill rounding is
reduced when needed by the cumulative exact-fee ceiling; it is never increased.
Maker rebates are independent per fill. No fee minimum overrides rounding to zero.
For 1,000 contracts at .10/.65/.50, taker fees are 5.40/13.65/15.00 and maker
rebates 1.12/2.84/3.12. The retail guide rejects fractional contracts; fixed-point
schema fields alone do not prove retail fractional eligibility.

Later taker rebates depend on prior-month volume or accelerated placement:
10%/25%/50% tiers, paid weekly. Exact threshold wording differs at $250,000
("over" versus table inclusion); callers must supply eligibility, not infer it.
The engine does not infer a separate settlement levy is zero from its absence.
PLAN.md's .05 is not this version. No sports-specific exception was established.

## ProphetX

[Trading schedule](https://www.prophetx.co/lobby/t-c/trading-fees),
[rebate filing](https://framerusercontent.com/assets/oNmtogNF4ucRmj5pymJVs4DLV4.pdf).

The page identifies version 1.0, updated August 19, 2026: straight-market positive
net gains carry 2%. The filing places collection at market settlement. An update
date does not establish an exact effective instant. Explicit aggregate dollar
cashflows support the formula without interpreting ambiguous native quantity/value.
Market loss offsets, exact rounding, exceptional adjustments and account treatment
need evidence; no cent rule or minimum is invented.

The monthly maker rebate uses marginal volume tiers, not the highest tier on all
fees. Raw arithmetic is supported, but published examples imply truncation:
75,000 volume/1,000 fees gives 66.666… before rounding, versus published 66.66;
7.5m/100,000 gives 49,866.666… versus published 49,860. These do not establish a
general rounding rule. Returned rebate amounts remain unknown; raw estimates
and supplied monthly totals are retained. The August filing's earlier zero-fee
RFQ text does not override the newer parlay schedule. Parlays are unsupported.
No maker/taker distinction is inferred for straight settlement commission.

## Novig

[Developer fees](https://docs.novig.com/fees),
[help schedule](https://support.novig.com/en/articles/16195057-fees-on-novig),
[maker credits](https://docs.novig.com/maker-credit-program).

Pregame straights are free; live/futures/parlay taker coefficients are .03/.06/.10.
Maker fees are zero. The help page exempts golf/tennis futures as of September 10;
coefficient effective instants remain unknown. Ledger rounding is five-decimal
half-up, without a minimum. One payout cent is .01 contracts: at .50 the live
charge .000075 rounds to .00008. A 100-contract live .50 fill costs .75.

Developer per-fill wording conflicts with help-page VWAP aggregation across
matched levels. Multi-fill taker scenarios require an explicit conditional policy.
App parlays require explicit pre-fee inputs; all-in quotes cannot be charged twice.
API taker parlays are unsupported. Winning payouts retain the full stated payout.

Maker credits depend on retained counterparty fees and eligibility; 50% live,
70% NFL/NCAAF futures, cash within seven days and subject to reversals. They are
separate from entry funding. Affiliate/contracted-maker exclusions, notices and
credit rounding remain conditions. Documentation qualification establishes no
Novig live access or ingestion.
