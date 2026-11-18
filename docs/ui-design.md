# Predict boards

## Current comparison interface

Predict uses a compact flight-board layout with porcelain surfaces, ink text and
rust accents. The main object changes with the task:

| Route | Main content and order | Opening a row |
| --- | --- | --- |
| `/` and `/ev` | Positive complete main-line bets, ranked by Kelly growth by default | Exact-pick market and sportsbook comparisons |
| `/browse-odds` | Games ordered by kickoff, with main winner, spread and total markets together | All available main and alternate lines for the game |
| `/game?game_key=...` | Complete main and alternate bets for one game | Exact-pick comparison |
| `/arbs` | Two-sided market/market and market/sportsbook price candidates, ranked by after-fee paired return | Both allocations and modeled outcome receipts |
| `/about` | Calculation assumptions, execution limits, data credit and references | Links to official documentation and fee sources |

Search, league, market and venue filters apply before pagination. Arb filters also
select pair type and sportsbook. A filtered or empty result preserves the chosen
sportsbook. Responses for an older filter selection cannot replace newer state.

Only complete qualifying calculations appear. Empty results and failed reads are
distinct. Failed refreshes preserve displayed data and show an error. Failed
update polling is visible; a successful poll clears its own error without hiding
a failed full read. The notice **Odds may be delayed** remains visible. Source
and receipt clocks are available in inspection details. First-load failure shows
one actionable notice. Empty and one-page results hide pagination; additional
pages remain reachable. Refresh feedback describes the read, not provider freshness.

There are no unit-size, calculation-mode or execution-depth controls in the
ordinary board. Current rows do not depend on research publication or saved
capture readiness. [Data flow and API](current-pregame.md)

## Composition and responsive behavior

Use Manrope for picks, context and values, with tabular figures for prices.
The palette is porcelain `#f4f5f7`, white rows, ink `#20252c`, charcoal column
headings and rust `#974221`. Hover/focus adds a pale rust tint. The wordmark has
a small rust square. Fonts and assets are packaged locally.

Opportunities uses League, Start (ET), Pick/Game, Venue, Price, After fees,
Fair odds/reference, Net EV and Score columns. Compact desktop rows use roughly
15px pick text and 12px matchup text. The **Rank by** dropdown selects Kelly
growth, Net EV, Kelly fraction (the original Score), Balanced or Probability edge.
The selection persists locally and applies before pagination. The final column
and its calculation popover follow the selected metric, including its units.
Changing the ranking resets pagination and keeps the other filters. A failed read
retains the previous rows and metric heading. Browser labels and explanations
come from the generated backend catalog.
Browse odds retains kickoff order. Kickoff is shown
explicitly in Eastern time. Below 1140px the row becomes a compact layout, and
phone widths use separate cards. There are no ticket perforations or persistent
inspector columns.

Browse odds groups the available main markets in one game row/card and retains
all available main lines, including nonpositive EV. Each exact line shows the
best available venue, price, after-fee price, fair reference and Net EV. The
venue label stands alone on the overview. Expanded game lines identify Main or
Alternate because both kinds are present there. Missing markets are not invented.
Game grouping precedes pagination, so a page boundary cannot split a game.

Arb rows show the game, both picks/venues and paired return. Each leg places
Posted and After fees in adjacent columns. Native cents, payout multiples and
percentage equivalents stay compact; American odds appear underneath. Legs align
at the top. Phone cards stack the legs as horizontal comparison rows. The detail
dialog uses two leg columns on desktop and one on phones. It shows committed
cash, both modeled receipts/profits, source clocks, fee math and allocation math.
Arb rows have no sportsbook fair odds, EV or Opportunity Score.

## Prices and calculations

Fair odds sit above `Book (posted odds)`, preserving the distinction between the
observed price and a derived reference. The reference is the lowest no-vig win
probability among eligible complete exact sportsbook pairs; book priority breaks
ties. Main/alternate evidence is independent of reference selection.
[Calculation policy](benchmark-ev.md)

Polymarket US shows payout multiples and percentage prices; Kalshi shows cents
and payout multiples. Both retain American equivalents in parentheses. After-fee
values use adjusted payout multiples and American equivalents. Aggregate-feed
conversions are identified in the quote explanation; they do not establish native
ticks, available size or current execution availability.

Price, After fees, Fair odds, Net EV and Score expose calculation popovers by
hover, keyboard focus or tap. Explanations use the inspected row's stored inputs,
including fee formula, rate, rounding, cashflows and reference probabilities.
Arb calculations use exact fee-qualified prices independently of probabilities.
Instantly fillable size is explicitly unknown, and the internal $100 allocation
is illustrative. Pushes, voids and other exceptional settlements are outside the
displayed two-state arb minimum.

## Row interaction and comparison

A native button in the pick/game heading extends its hit area across its row.
Hover and keyboard focus highlight the row. Enter, Space, pointer and touch open
the same inspection. Game links and math controls remain independent controls
above the row hit area; there are no nested buttons or role-button wrappers.

Exact-pick comparison uses compact market and sportsbook tables. The open
comparison follows current stored rows; a withdrawn line clears its prices and
save controls. Saving freezes the displayed quote at click time. Pending saves,
their feedback, expanded calculations and focused controls survive redraws.
An earlier saved quote is distinguished from a newer displayed quote.
Additional matching sportsbook prices have their own source clocks. Only
recognized cash sportsbooks appear in the sportsbook table; unknown venues,
exchanges and sweepstakes products are excluded. Six books appear initially,
with additional books under More sportsbooks.

Escape closes an active calculation popover before its comparison. Closing an
inspection restores focus to the corresponding current row or the results if
that row disappeared. Expanded games retain context while opening an exact-line
comparison. Kickoff closes expired inspections and refreshes the board without
waiting for another provider response. Reduced motion removes animation.

## About, replay and diagnostics

About this board appears beside the delay notice, under More and in the footer.
It explains the sportsbook benchmark as a hypothesis, no-vig math, conservative
EV, arb math, order/liquidity risks, exact-line and settlement differences, and
venue verification. It credits SportsGameOdds and links official order/fee
documentation and relevant research. The provider credit uses SGO's official
site until an actual affiliate URL and disclosure are supplied.

Practice and saved captures remain separate research views, reachable under
More. Simulated examples are labeled. Saved captures retain original evidence.
Admin owns collection controls and operational failures. Account connections and
verified live execution size require separate capabilities.

## Verification

Use the focused checks in [Development](development.md#focused-checks) and
[CI](CI.md#selecting-local-cases). Browser fixtures cover row and math actions,
nested-dialog focus, empty/failed reads, late filter responses, retained filters,
update-check failures, price formats and narrow layouts. SQL cases use disposable
PostgreSQL for grouping, exact matching, reference independence, fee expiry,
recovery and withdrawal. Fixtures do not prove live liquidity or venue execution.

[Snapshot development](local-ui-development.md) supports real captured-data UI
inspection without starting local collectors. Check populated and failed states,
long names, keyboard/touch, reduced motion and increased text at supported sizes.
A rendered screenshot establishes appearance at that state, not usability-study
results or live trading availability.
