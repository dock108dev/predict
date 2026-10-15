# Predict — practical local-use requirements

Updated October 14, 2026 after the owner's further comparison-usability feedback: data is present but difficult to use, Polymarket appears one-sided, Pinnacle uses decimal odds, and EV/Arbs are overloaded. The authenticated October 13 contract is retained in [documentation history](history/next-steps-cleanup-20261014/restored-originals/docs/practical-use-requirements.md). This is the current product acceptance contract. [Next Steps](../../prediction_arb_next_steps.md) owns the remaining slices; [product status](product-roadmap-review.md) records completed work and evidence.

## Finish line

The owner can open Predict and see all observed upcoming NFL winner games together on one page, compare genuinely available Kalshi, Polymarket US, Novig and ProphetX prices, understand EV against a named reference and rank opposing opportunities across games after fees, rule differences and a buffer. Game selection and search are optional local filters, not a required step for each game. The default calculation is a **$1,000 trade/opportunity**, with one **0.5% buffer on deployed capital**. Incoming observations and resulting calculations continue to be saved locally for later analysis.

This is the initial NFL pregame/full-game winner scope. It must work through reusable game/contract adapters rather than a permanently hardcoded demonstration. Source unavailability and no positive opportunity are normal states. Simultaneous fresh four-venue quotes are unnecessary; native calculation integration itself is required.

The sizing, all-games presentation and SQL integration described here supersede conflicting prototype behavior. The earlier mathematical foundations remain useful. Recorded engineering verification does not establish owner acceptance.

## Recorded completion and evidence boundary

EV09-S01, N01, B01 and U01 implement requested sizing, reusable native/reference inputs, saved comparison APIs and distinct screens. Their isolated evidence remains dated. EV09-D04 supplies installed arithmetic, lifecycle, history and a natural saved update. The later [October 14 installed repair](all-games-data-repair-closeout.md) supplies the all-games view, broader bounded native selection, winner-only acquisition, lossless storage, fair calculation waves and working native browser polling. That engineering qualification remains dated. The owner's subsequent actual review identifies required display defects, reopening **U01 comparison usability** and **D04 affected installed delivery** before [Q04 owner acceptance](u6-owner-review.md). B01 supports only a demonstrated read-contract gap; no new source collection is required for the cited examples.

The earlier SQL report mixed singles/pairs and exposed provider-local duplicates; its ceiling optimizer could choose a losing minimum-size portfolio rather than evaluate the requested $1,000. Those corrected behaviors and their historical meanings are recorded in [product status](product-roadmap-review.md) and the [financial contract](requested-trade-financial-contract.md). They are not outstanding implementation slices.

## Current priority: usable price and opportunity comparisons

The owner's latest October 14 feedback is **changes requested**: the available data is difficult to use. The supplied Seattle–Denver, Houston–Jacksonville and Carolina–Philadelphia examples show Polymarket Long inline and a corresponding Short under Native alternatives, while the opposite main row shows a dash. This is evidence of hidden observed data in those examples, not proof that the provider lacks a side. The [retained Arbs observation](history/owner-comparison-priority-20261014/owner-arbs-observation.txt) also shows same-venue pairs and lengthy repeated scenario/clock/funding blocks. No current runtime or provider check is implied by these owner observations.

The next engineering work must deliver these requirements together:

- **Both observed Polymarket directions inline.** Resolve each Long/Short quote to its exact observed participant/predicate; show the opposing supported Short in the main price comparison with a short **Short** label. A buyer must not expand Native alternatives to discover an already observed opposing price. Do not invent an absent side, relabel Short as opponent YES, or erase tie/refund differences. Keep other non-equivalent alternatives and full wording in Details.
- **One price format.** All main venue and selected benchmark prices use signed American odds, including Pinnacle fair prices. Label de-vig fair odds as **Fair**; keep original offered Pinnacle prices, exact decimal inputs and decisive probabilities inspectable. Display conversion changes no probability, fee, policy or calculation. Never silently substitute offered/vigged odds for the fair benchmark.
- **Cross-venue Arbs only.** Positive, All comparisons and Rule-sensitive hedges on the Arbs page all exclude pairs whose execution venue identity is the same. Compare leg venues, not the shared aggregate provider: Novig and ProphetX remain different venues. Visible comparison counts and empty states reflect the filtered cross-venue set. Preserve those saved portfolios in immutable history/Details or an explicit diagnostic route. This is the requested product selection rule, not a mathematical claim that same-venue arbitrage can never exist.
- **Compact views instead of repeated reports.** Odds groups a game once with aligned teams/venues. EV and Arbs use concise comparable rows, shared game headings and global ordering. Keep selection(s), venue(s), American price(s), the relevant buffered return/dollars, and pair allocation visible. Put long scenario tables, exact residuals, repeated source/result clocks, probabilities and funding/fee breakdowns in Details. Keep one short visible stale/pending/conditional or material risk note; simplification cannot make a hedge look guaranteed or an old result current.
- **Useful defaults and controls.** Positive opportunities lead; zero positive opportunities gives a clear empty state. An explicit All comparisons remains available for compact signed/history inspection. The coverage summary is brief and shown once, with operational diagnostics in Admin. All games remains the default, and local filters/settings/focus/history survive ordinary arrivals.

## Three distinct screens

| Screen | Main question | Required ordinary content |
|---|---|---|
| **Odds** | Where is the best available price for this selection? | All observed upcoming games, each with two team rows, venue columns, common American odds and a visibly separate reference column. Native alternatives remain accessible. No opposing-pair report. |
| **EV** | What is this bet worth against the selected benchmark, after costs and rule adjustments? | Cross-game ranking with game/selection, venue/price, named fair benchmark, net estimated EV %, estimated dollar profit at the trade amount and Details. Positive results lead; All results exposes signed/conditional values. No unrelated pair report. |
| **Arbs** | Which opposing purchases produce a positive margin after costs and buffer, and how do I split the trade amount? | Cross-game ranking with game identity, both selections on distinct venues, American prices, each allocation, combined amount and net margin in dollars/percent. Distinguish complete modeled-outcome positives from rule-sensitive hedges. Show material adverse outcomes beside a rule-sensitive result; full scenario math is in Details. |

Use a clear empty state such as **No positive EV found** or **No estimated arbitrage found** when the selected filter has no opportunity. Do not fill the ordinary Arbs page with losing minimum-size portfolios. Keep negative comparisons available through an explicit All/comparison control or Details.

American display odds are a common price format, not a declaration that native payouts are identical. Original decimal odds, contract prices, YES/NO/Long/Short, units and full wording remain in Details; an observed opposing Short also remains visibly labeled inline. A NO contract must not silently become opponent YES. Odds highlighting and EV ranking are separate.

The default slate includes every observed upcoming NFL game once. Local game selection/search can narrow it without fetching each game separately. Matched venue records share an occurrence; spread/total listings do not masquerade as extra winner games. Conflicting/unmatched records remain inspectable without being silently merged.

## Financial meanings and requested amount

The ordinary input is **Trade amount ($)**, initially $1,000. For a single, size acquisition/stake plus modeled mandatory upfront fees and required holds within that funding amount. For a pair, both legs share that one amount. Use as much of the requested amount as feasible under supported or explicitly modeled quantity increments; report actual deployment and a specific residual/limit when it cannot be used. Never force a purchase or pretend displayed depth supports a fill.

The requested-amount calculation mode is versioned. Retain the old maximum-ceiling/minimum-spend behavior for historical readers or an explicitly selected advanced mode. Recalculate fees, rounding, quantity grids, depth/residual assumptions and settlement cashflows at the final allocation. Never multiply a $25 result to invent a $1,000 result.

The common calculation is:

1. Capture the selected quote and matched reference with their original clocks/units.
2. Derive the named decisive probability from the two-way reference, removing its overround consistently.
3. Compute per-outcome net cashflows at the funded quantities, including entry fees, winning commissions, refunds/holds and the contract's modeled rule differences.
4. For EV, weight those net cashflows under the disclosed probability/settlement assumptions.
5. Deduct `deployed capital × 0.005` once from the relevant opportunity estimate. Return uses actual deployed capital.

For an arb, balance the two opposing net decisive payouts within the requested funding amount and show the buffered decisive margin separately from probability-weighted EV. A positive EV bet is not automatically an arb. A tie or cancellation assumption cannot make a losing outcome guaranteed profitable. Fully modeled positive minimums and conditional/rule-sensitive hedges need distinct concise labels; unknown exceptional states remain explicit.

Pinnacle is the default reference and never an execution leg. A selected alternative observed sportsbook benchmark may be used with its own two-sided prices, source name, overround treatment, scope and clock. The implemented adapter validates original two-sided Pinnacle, Novig or ProphetX inputs; a benchmark change remains an explicit user choice. Benchmark choice and requested-size policy revision enter snapshot/result/request/cache identity. Never silently switch the benchmark or present a model-only probability as observed Pinnacle data.

Published/versioned fee and payout models, provisional NFL priors and disclosed quote-price liquidity assumptions support estimates now. Unknown actual account fees, fills and venue grades remain unknown. Missing units, ambiguous identity or contradictory source facts are real blockers; an actual-vs-modeled distinction alone must not suppress an otherwise supported estimate.

### Diagnostic example from the owner's screen

At decimal prices **2.30 Denver / 1.75 Seattle**, a fee-free, continuous-size $1,000 decisive balance allocates about **$432.10 / $567.90**. Either decisive result loses about **$6.17 before fees/buffer**, or **$11.17 after a $5 buffer**. This is a sizing/filter regression vector, not a current trade recommendation or an assertion about venue fees, grids or tie payouts. The ordinary Arbs view should report no positive opportunity for that vector; the exact losing comparison remains inspectable. This explains why the prior −$0.2811 at roughly $25 is not the requested-size comparison.

## Native inputs and saved results

The reusable occurrence bundle uses existing SQL observations and EV02 matching seams. Preserve every source-local identity, native contract, reference original and immutable envelope. Native and sportsbook settlement descriptors can differ while sharing the same decisive event/reference; apply differences through their cashflows rather than rewriting their contracts to force equality.

Use actual native participant, predicate, scheduled-phase and quantity metadata. Attach a qualified occurrence-bound two-way reference with explicit source/role/period/evidence checks. Reuse EV04 content/consumer and EV05/EV06 engines. The selected NFL model's time horizon must be versioned and appropriate for the evaluated game; neither dates nor old evidence are extended silently.

A change to any member quote, source state, occurrence binding, applicable model or reference invalidates the appropriate occurrence result. Capture a coherent snapshot, publish only its matching latest pointer and preserve old complete results. Expose reusable SQL-backed board/read models with all price, benchmark, EV and pair values needed by the three screens. The browser formats server calculations; it does not independently price fees or settlement rules.

Freshness is checked against each single/pair's actual dependencies. One stale native alternative or unrelated quote must not withdraw healthy sportsbook/native calculations in the same combined game. A mixed-age game can contain current and as-of results; stale numbers remain inspectable but do not rank as current opportunities.

## Ordinary controls and explanations

Use plain labels: **Trade amount $1,000**, **Buffer 0.5%**, **Updated 9 minutes ago**, **Details**. Settings and Restore apply consistently across views. Use normal cents and sensible percentage precision on the main screens; preserve exact fractions/unrounded values in the saved calculation.

Details starts with the selected result, quantities and a readable reconciliation: price/gross value → rule adjustment → expected fees → net estimate → buffer. Then show a short outcome table and the important assumptions. Exact original contracts, raw payloads and evidence IDs belong in a collapsed advanced section. Historical inspection is labeled as-of; opening Details on a current saved result must not incorrectly imply that current inputs have expired.

Database names, snapshot IDs, journal backlog, provisional-prior dumps, transport counters and storage limits belong in Admin or advanced Details. Main screens need only useful source-age, missing-price/reference and material rule/size notes. Collection controls remain available in the ordinary app/Admin without cluttering every price row.

The same flow must be readable on desktop and one narrow screen. Main prices/results cannot require deciphering raw IDs or invisible clipped columns. Preserve search, selection, focus, settings and Details through incoming updates. Reads/filters/settings do not acquire data.

## Continuing data and delivery

Observation collection, journal rollover and SQL retention are implemented and Q03-qualified. Preserve that work and its original records. Continue native NFL full-game winner collection and scheduled NFL `h2h` aggregate collection under the existing owner authority. Reduce needless sport/family acquisition and duplicated stored payloads without deleting original observations, calculation history or accounting. Persist new calculations with their input/model/binding versions so later analysis can reproduce them. The owner can Start/reopen, Stop, inspect source age/status and reopen saved history through existing supported operations.

Use the approved 8 GiB total journal, 256 MiB segments, 8 MiB records, 2 GiB SQL soft ceiling, 1 GiB free-disk floor and existing 768 MiB process guard. No new benchmark campaign or repeated two-cycle accounting proof is needed. Engineering may perform the necessary owned code handover and affected preservation checks. Leave the useful installation available and collection running where its schedule/source conditions permit.

Initial collection means original quotes/catalogs/books, source clocks, calculation snapshots/results and existing accounting observations. Sporting outcomes, actual venue settlement/fees, calibrated priors, strategy backtesting, more sports/markets and hosted operation are later work.

## Acceptance

Engineering closes the revised goal when the full observed upcoming NFL slate is visible and globally ranked, and at least one authentic upcoming winner occurrence exercises the unified inputs, native modeled singles and a mixed-venue opposing calculation; requested funding/fees/rules/buffer reconcile independently; the three ordinary pages display their distinct values; a relevant ordinary arrival updates and saves the correct result; changed controls/lifecycle behave correctly; loading makes visible progress; memory/storage stay within the approved limits during required verification; and original data/accounting survive delivery. Actual venue/reference coverage and missing inputs must be understandable across the slate. Numeric modeled/conditional and historical results are legitimate evidence when labeled accurately. A positive live opportunity or simultaneous four-venue freshness is not required.

The latest actual owner review remains **October 14 — changes requested**, now including the concrete price-format, hidden-Short, same-venue Arbs and information-overload defects above. Revised U01 and affected D04 must pass before a new Q04 decision. U01 closes only when the cited observed sides are inline, all displayed reference prices use American odds, no same-venue pair appears anywhere in Arbs, compact desktop/390px views keep material status/risk readable, and exact Details/history/arithmetic remain intact. No revised implementation, installed verification or acceptance is claimed by this documentation update. Required work belongs in Next Steps; optional ideas belong in the repository backlog.

## Measured limits and deferred scope

The recorded 28-game default reads take 3.288–3.701 seconds. Those engineering measurements do not establish owner usability acceptance and do not pass or erase the original one-/two-second EV08 benchmark targets. Strict timing/distributions and broad representative qualification remain [optional backlog](product-roadmap-review.md#backlog), as agreed October 12. A newly demonstrated freeze, incorrect calculation/identity/clock, unsafe lifecycle or failed saving remains a required defect.

Native discovery uses the first bounded listing page and existing global/event/market limits. At the final recorded frame Kalshi covers five games and US three; two further US offers lack exact season/stage witnesses. Missing prices or benchmarks are not fabricated. Finite storage may pause saving at its guard; unlimited retention and additional collection scope are outside this goal. Actual account fees, fills, venue grades and calibrated probabilities remain unknown or explicitly modeled. These limits are part of owner review.
