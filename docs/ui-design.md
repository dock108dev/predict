# Predict boards

## Current comparison interface

Predict uses the approved Gamebook composition and Prism visual style: spacious
individual pick cards, plum/violet surfaces, locally packaged Sora typography,
and semantic green/red values independent of the selected brand palette.
The main object changes with the task:

| Route | Main content and order | Opening a row |
| --- | --- | --- |
| `/` and `/ev` | Positive complete main-line bets, ranked by Probability edge by default | Exact-pick market and sportsbook comparisons |
| `/browse-odds` | Games ordered by kickoff, with main winner, spread and total markets together | All available main and alternate lines for the game |
| `/game?game_key=...` | Complete main and alternate bets for one game | Exact-pick comparison |
| `/arbs` | Two-sided market/market and market/sportsbook price candidates, ranked by after-fee paired return | Both allocations and modeled outcome receipts |
| `/about` | Calculation assumptions, execution limits, data credit and references | Links to official documentation and fee sources |

Search, league, market and venue filters apply before pagination. Arb filters also
select pair type and sportsbook. A filtered or empty result preserves the chosen
sportsbook. Responses for an older filter selection cannot replace newer state.

EV lists complete positive calculations. Browse also retains authentic prices with
unavailable EV and its actual reason. Empty results and failed reads are distinct. Failed refreshes preserve displayed data and show an error. Failed
update polling is visible; a successful poll clears its own error without hiding
a failed full read. The notice **Odds may be delayed** remains visible. Source
and receipt clocks are available in inspection details. First-load failure shows
one actionable notice. Empty and one-page results hide pagination; additional
pages remain reachable. Refresh feedback describes the read, not provider freshness.

There are no unit-size, calculation-mode or execution-depth controls in the
ordinary board. Current rows do not depend on research publication or saved
capture readiness. [Data flow and API](current-pregame.md)

## Composition and responsive behavior

Use Sora for picks, context and values, with tabular figures for prices. The
main shell has a 74px navigation rail, a broad search field, a collapsed **Filters**
control and the existing **Rank by** methods. Filters expand in the normal page
flow on desktop and mobile. Ranking remains visible while secondary filters
are closed. Opportunities keeps individual picks separate, including two picks
from the same game. Each card shows the source quote, effective after-fee
American odds and Net EV in that order. Ranking and source/reference ages stay
with the selection. Fair/no-vig odds are separately labeled in comparison.

At widths of at least 1100px, exact-pick comparison opens beside the interactive
list. It is a nonmodal, sticky panel with its own scrollable content; selecting
another row updates the panel. At narrower widths it becomes a native modal
with a fixed Close control. Crossing the breakpoint preserves the selection.
All game lines remain a modal, with Back to game preserving the exact line and
scroll position. Calculation popovers close before an enclosing comparison on
Escape, and closing restores focus to the current list control by identity.

Browse odds alone groups by game, with winner, spread and total columns where
space allows. Negative EV and unavailable calculations remain visible. Arbitrage
retains both native/available quotes, effective after-fee odds, source ages and
paired return; instantly fillable size remains unknown. My Bets opens on placed
trades, with open trades first, performance across recorded trades and separate
Saved research and Opportunity log views. Exports and operational settings
remain reachable.

Theme previews offer 15 starter palettes, custom primary/secondary colors and
light, dark or system appearance. Cancel restores the saved theme; Apply persists
through the private same-origin `/api/appearance` endpoint for this single-owner
application. Browser storage caches appearance and editable journal drafts, while
journal entries and preferences persist in separate private SQLite files. Palette
colors never determine the sign of EV, warning or error values. NCAA themes are
deferred.

Completed Arb scans reuse qualified pairs across ordering, league, market, venue,
pair-type and sportsbook changes. Reuse requires the same database, cohort/source
revision, look-ahead, source-age and search context, and stops at eligibility
deadlines. Retained-cohort cursors track their own positive generation and
relevant current withdrawal, closure, route and queued-work authority; unrelated
public price revisions do not invalidate a frozen snapshot. Negative additions
and removals still invalidate immediately, and earlier known public starts
shorten its refresh deadline. Actual new cohort captures require a fresh scan.
First reads with league, market or search filters keep their SQL filters. Broad reads retain every price/alias witness, but defer full financial
records until exact-line templates or the unchanged pre-fee pair test need them.
Hydration verifies the whole price payload, game and expiry in the same source
snapshot; it never selects an older profitable alias over a newer losing one.
Sparse indexes cover explicitly unavailable current quotes/offers and
expired lines, allowing reads to check negative authority without fetching every
positive witness. Missing or unknown evidence stays unknown; original clocks,
fees and cashflows remain unchanged. These mechanisms do not establish deployed
cold-read latency; that requires measurement after the migration is installed.
Book metadata is expanded once per quote, retaining the original full facts for
qualification. Its query skips measured JIT compilation and restores the caller
setting. Cold whole-slate Arb reads have a 30-second server/35-second client
bound, calibrated to observed 16–21-second complete scans; each SQL statement
retains its 8-second bound and filter changes cancel superseded work. Repeated
filters project completed scans rather than repeat those cold reads.
Background journal sampling shares its existing revision and 15-second cadence
between web and collector roles, so duplicate samplers do not compete with board
reads for the same retained evidence.

## Prices and calculations

Fair odds sit above `Book (posted odds)`, preserving the distinction between the
observed price and a derived reference. The reference is the lowest no-vig win
probability among eligible complete exact sportsbook pairs; book priority breaks
ties. Main/alternate evidence is independent of reference selection.
[Calculation policy](benchmark-ev.md)

The posted-price adapter preserves supplied units and values. An American price
appears once; supplied cents, probability or decimal/payout units keep their
source meaning and add the stored American equivalent in parentheses. When an
aggregate feed supplies only normalized American odds for a marketplace, show
those odds with **Native format unavailable**. Never derive a venue percentage
from its name and present it as an original source quote. After-fee American odds
come directly from the authoritative stored cashflows. Fair odds remain a
separate probability benchmark. Display text never becomes a calculation input.

The maximum source-age filter checks the quote clock and every selected
reference input clock, excluding unknown or future timestamps when the filter
is active. The earliest source/reference age deadline schedules the next read.
Arbitrage checks the original clocks on both legs independently of EV references.

Price, After fees, Fair odds, Net EV and ranking expose calculation panels only
by explicit click, tap or Enter. Panel content is created on first opening rather
than adding hidden explanation trees to every board row. Hover and focus do not
open overlays. Each panel
has an explicit Close control, bounded internal scrolling and a position below
the inspection header so the main exit remains reachable. Scroll or Escape
dismisses the panel; focus restoration never reopens it automatically. Explanations use the inspected row's stored inputs,
including fee formula, rate, rounding, cashflows and reference probabilities.
Arb calculations use exact fee-qualified prices independently of probabilities.
Instantly fillable size is explicitly unknown, and the internal $100 allocation
is illustrative. Pushes, voids and other exceptional settlements are outside the
displayed two-state arb minimum.

## Row interaction and comparison

A native button in the pick/game heading opens inspection. Background row clicks
use event delegation that skips actual links, buttons and disclosures. No
invisible stretched button covers other controls. Enter, Space, pointer and touch
remain supported without nested buttons or role-button wrappers.

A normal game-link click from EV opens all game lines on the same board; the
canonical link still supports deep linking and modified-click navigation. The
inspector shows all markets and venues for the event while leaving the board
filters untouched. Its opening data cohort and source-age limit stay pinned,
including child comparisons and retries.

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
that row disappeared. List redraws preserve the focused quote or game control
by identity, falling back to results when it disappears, and leave focus in
dialogs and filters alone. Only one inspection dialog is visible at a time. From all game lines, an
exact-line comparison replaces the visible dialog. **Back to game** restores the
exact line, focus and game scroll even when a delayed game response arrived in
the meantime. **Close** exits directly to the board. Fixed headers keep Back and
Close reachable; narrow screens use the full viewport. Collection settings keep
Save in a fixed footer outside the scrolling form body. Kickoff closes expired inspections and refreshes the board without
waiting for another provider response. Reduced motion removes animation.

## About, replay and diagnostics

About this board appears beside the delay notice, under More and in the footer.
It explains the sportsbook benchmark as a hypothesis, no-vig math, conservative
EV, arb math, order/liquidity risks, exact-line and settlement differences, and
venue verification. It credits SportsGameOdds and links official order/fee
documentation and relevant research. The provider credit uses SGO's official
site until an actual affiliate URL and disclosure are supplied.

Practice navigation and production synthetic replay are retired. Authentic saved
captures remain reachable under More and retain original evidence.
Admin owns collection controls and operational failures. Account connections and
verified live execution size require separate capabilities.

## Verification

Use the focused checks in [Development](development.md#focused-checks) and
[CI](CI.md#selecting-local-cases). Browser fixtures cover row and math actions,
single-layer game/comparison return, empty/failed reads, late filter responses, retained filters,
update-check failures, price formats and narrow layouts. SQL cases use disposable
PostgreSQL for grouping, exact matching, reference independence, fee expiry,
recovery and withdrawal. Fixtures do not prove live liquidity or venue execution.

[Snapshot development](local-ui-development.md) supports real captured-data UI
inspection without starting local collectors. Check populated and failed states,
long names, keyboard/touch, reduced motion and increased text at supported sizes.
A rendered screenshot establishes appearance at that state, not usability-study
results or live trading availability.
