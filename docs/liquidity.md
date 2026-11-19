# Liquidity assessment — November 18, 2026

The board cannot establish how much can be acquired at a displayed SportsGameOdds price. Its quantities are explicitly unknown. Thin attractive Novig quotes remain a plausible concern, but the observed Novig prevalence does not prove it. An independent native Novig sample does establish meaningful displayed size: Seattle’s best acquisition price supported about **$481.84**, with a $500 commitment crossing one deeper level. That evidence applies to the captured native book, not to the aggregate board’s earlier price.

## Evidence and limits

Research used the private server dump completed November 18 at 9:28:59 p.m. Eastern, evaluated at 9:38:52 p.m., plus three bounded, unauthenticated read-only Novig public API requests at 9:39–9:40 p.m. No collector, configuration, pause, financial record or order was changed. Raw responses, receipts and exact calculations remain outside Git in `.local/usability-sprint/liquidity/`.

The captured configuration selects SportsGameOdds for all four venues, with direct Novig, Kalshi and Polymarket US disabled. `current_policy.price_routes()` also selects SportsGameOdds for Novig. No native Novig offers were retained in this snapshot. Existing native depth from other venues is separate evidence and must not be attached to these aggregate prices.

## What reaches the board

SportsGameOdds documents Novig as a bookmaker-specific `byBookmaker.novig` price within its ordinary events response. Its public schema supplies odds, line, availability and bookmaker update time, but the reviewed documentation does not establish whether the Novig scalar is a best executable acquisition, last trade or another observation. It supplies no size guarantee. The app’s `quote_side='buy'` is a normalization choice, not provider confirmation of executable ask semantics. [SportsGameOdds Novig feed](https://sportsgameodds.com/bookmakers/novig-odds-api), [odds schema](https://sportsgameodds.com/docs/data-types/odds).

The actual path is:

1. `sportsgameodds_adapter.py` reads each bookmaker’s `odds`, exact line, `lastUpdatedAt` and `available`. It retains the original source-clock string. No quantity, depth, trade history or account limit enters the parsed quote.
2. `sportsgameodds_current_rows.py` preserves American odds and timestamps, sets `quantity_units='unknown'`, and labels execution/depth unverified. A $1 normalized payout basis is a price conversion, not a native quantity unit.
3. `sportsgameodds_reference.py` stores these observations and original clocks in revisioned facts. `current_pregame.py` stores the fee-qualified price and probability calculation. Neither manufactures size.
4. `current_pregame_read.py` chooses the highest modeled Net EV venue for each exact pick before pagination; the selected ranking then orders those picks. Browse/inspection can retain authentic prices with unavailable EV. Source timestamps stay unchanged.
5. API/UI prices therefore support inspection and modeled calculations, not a stake maximum. Neither ranking nor the arb allocator walks aggregate depth. The illustrative $100 arb allocation has `instant_fill_max_usd=null` and `execution_qualified=false`.

Historical traded volume, currently resting size and account-specific limits are distinct. None is available for the aggregate Novig row. Native catalog `volume`/`openInterest` fields observed during this research are not order-book capacity or account limits.

## Why Novig dominates this capture

These are eligible main exact picks, including price-only rows where EV is unavailable, evaluated against the same frozen source data and clock:

| Venue | Main picks with prices | EV available | Positive EV before cross-venue selection | Selected positive board picks | Median quote age | Median winning fee / committed cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Novig | 598 | 510 | 63 | 61 | 157.1 min | 0% |
| ProphetX | 418 | 380 | 27 | 9 | 169.9 min | 1.87% |
| Kalshi | 738 | 427 | 3 | 0 | 158.7 min | 3.20% |
| Polymarket US | 557 | 378 | 0 | 0 | 157.4 min | 4.35% |

There were 93 positive venue rows across 70 unique exact picks; 21 picks had multiple positive venues. Highest-Net-EV selection removed two Novig rows, 18 ProphetX rows and three Kalshi rows. The resulting board had **61/70 Novig picks (87.1%)**. An earlier sample had 71 total; kickoff eligibility can change even with frozen data.

Supported explanation: Novig has more eligible coverage than ProphetX, more positive modeled estimates than every comparator, and wins the explicit Net EV selection on 61 picks. Its stored pregame schedule charges zero; competing modeled fees reduce their after-fee receipts. The current official Novig schedule confirms zero fees for pregame straight trades. This is consistent with a fee advantage, but no counterfactual experiment isolates its contribution to venue counts. [Official Novig fees](https://support.novig.com/en/articles/16195057-fees-on-novig).

Coverage alone is insufficient: Kalshi has more priced picks than Novig. Freshness superiority is not demonstrated: every sampled main quote was older than 15 minutes, with similar venue medians. Thin size cannot explain the ranking mechanically because size never enters it; whether individual winning prices are thin remains unknown.

## Native Novig amount example

The official native API describes resting orders as bids; buying an outcome uses the complement of the opposing bid. Native `qty` counts whole contracts, each paying **1¢** if it wins. Thus cost in dollars is `price × qty / 100`, not `qty` dollars. Prices must respect the venue grid. These native units must never be assigned to aggregate `quantity_units='unknown'`. [Odds-screen integration](https://docs.novig.com/affiliates/odds-screens), [native monetary units](https://docs.novig.com/api/concepts/money).

A captured public book for **Seattle Seahawks at San Francisco 49ers, November 29, 4:25 p.m. Eastern**, had sequence 1138 and pregame status. HTTP receipt time was November 18, 9:40:08 p.m. Eastern. The book supplied no exchange update timestamp; its response allowed five seconds of caching plus five seconds of stale revalidation. This is a displayed-depth observation, not a fill assurance.

Seattle acquisition levels were 43.5% for 110,767 cent-contracts, then 45.5% for 200,000, then 48% for 102,497. San Francisco’s best acquisition price was 61.5% for 213,200 cent-contracts, supporting $1,311.18 before moving deeper. Orders at the same price were combined. The market charged fees `WHEN_LIVE`; this pregame example uses the documented zero-fee straight-trade schedule.

| Outcome | Maximum commitment | Contracts acquired in captured book | Cash spent | Unspent cash | Total winning payout | Average acquisition price | Effective American odds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Seattle | $25 | 5,747 | $24.99945 | $0.00055 | $57.47 | 43.5000% | +129.885 |
| Seattle | $100 | 22,988 | $99.99780 | $0.00220 | $229.88 | 43.5000% | +129.885 |
| Seattle | $500 | 114,758 | $499.99550 | $0.00450 | $1,147.58 | 43.5696% | +129.518 |
| San Francisco | $25 | 4,065 | $24.99975 | $0.00025 | $40.65 | 61.5000% | −159.740 |
| San Francisco | $100 | 16,260 | $99.99900 | $0.00100 | $162.60 | 61.5000% | −159.740 |
| San Francisco | $500 | 81,300 | $499.99500 | $0.00500 | $813.00 | 61.5000% | −159.740 |

Seattle’s $500 case consumes all 110,767 contracts at 43.5% ($481.83645) and 3,991 at 45.5% ($18.15905). The $0.00450 remainder cannot buy another whole contract. Its break-even probability rises by about 0.0696 percentage points. San Francisco’s examples stay within the best level. Winning profit is payout minus cash spent; losing the chosen decisive outcome returns zero. Both outcomes here are alternatives, not an arbitrage pair.

The same game/start appears in the stored aggregate sample at Seattle +127 and San Francisco −156, timestamped 5:59:36 a.m. Eastern. These differ from the later native prices. The research did not qualify an exact native-to-aggregate execution binding or simultaneous price match, so none of the native sizes qualifies those aggregate rows. Nor is there a synchronized, qualified native fair-probability input for this book: amount-adjusted EV is unavailable. The market also reports `voids='FMV'`; exceptional-settlement treatment was not qualified.

## Independent Kalshi contrast

A separate native read of Colorado’s `KXNHLGAME-26NOV18COLUTA-COL` market found 19,753.26 contracts supporting the 50¢ YES acquisition price, derived from opposing NO bids. These contracts pay **$1**, unlike Novig’s native 1¢ contracts. Displayed top-level purchase capacity was $9,876.63 before fees. The current series has `quadratic_with_maker_fees`, multiplier 1; the reviewed fee-change histories supplied no applicable override. The calculation below uses the app’s whole-contract quantity model, a 7% quadratic taker coefficient and cent balance precision. Native fractional capacity is retained separately. [Kalshi order-book interpretation](https://docs.kalshi.com/getting_started/orderbook_responses), [official fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf), [fee rounding](https://docs.kalshi.com/getting_started/fee_rounding).

| Budget | Whole contracts | Purchase | Acquisition fee | Total committed | Unspent | Winning receipt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| $25 | 48 | $24.00 | $0.84 | $24.84 | $0.16 | $48.00 |
| $100 | 193 | $96.50 | $3.38 | $99.88 | $0.12 | $193.00 |
| $500 | 966 | $483.00 | $16.91 | $499.91 | $0.09 | $966.00 |

All three fit the first captured level; price deterioration is zero, while fees increase committed cash. Its reported 125,772.25 traded contracts measure historical volume, not available size. This is another independent native observation, not a synchronized arbitrage pairing or size evidence for a stored aggregate quote. The market’s rules also specify fair-price settlement for cancellation or a delay beyond its permitted window; the completed-game payout table does not cover that case. Raw receipts and exact outputs are in `liquidity/kalshi-native-amounts.json` under the private evidence directory.

## Recommended next slice

Add a read-only, source-bound amount comparison using existing depth and exact cashflow components. Start with a venue whose book identity, quantity units, fee applicability and sequence can be qualified. Show the best-price-supported commitment, then selectable $25/$100/$500 effective acquisition price, payout, fees, unspent cash and depth shortfall. Preserve separate original source time, book receipt time, sequence and explicit unknowns. Recompute EV only against the same exact pick and auditable probability inputs; never extrapolate a top level or borrow another feed’s size.

For arb inspection, size both legs together. Their supported quantities and legal grids constrain the paired allocation; the smaller supported hedge can limit the whole pair. A one-leg partial fill leaves directional exposure. Independently observed books can move between reads, and push/void/tie rules can invalidate completed-game payout assumptions. The next slice should display these limits and amount-supported modeled payouts, without order execution.

**How much can someone actually acquire at these odds, and what happens to the edge at a meaningful amount?** The aggregate board cannot answer yet. In one independent native Novig snapshot, Seattle supported $481.84 at its best price; a $500 commitment worsened average price from 43.5% to 43.5696%. San Francisco supported more than $1,300 at its best price. Actual fills, account limits and an amount-adjusted positive edge remain unestablished.
