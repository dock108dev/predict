# Interface design

Predict presents collected prices, EV and cross-venue comparisons across the
supported leagues, markets and periods. Background financial owners calculate
shared results; the browser validates their context and renders them. Ordinary
reads consume current SQL publications, while selected Details can size an item. See
[architecture](architecture.md) and the [board API contract](comparison-board-api-contract.md)
for storage and transport boundaries.

Sports/test history is disposable. Ordinary use does not require old results,
snapshots or full provider responses to survive reset or restart. Current inputs
support the comparison loop; calculation reports are not persisted.

## Compact views and financial meaning

**Odds** opens on All games, grouping observed supported games into
compact game/team rows with venue columns. Search and game selection are optional.
Observed Polymarket US Long and Short appear inline with their actual participant,
side and predicate. Keep NO/Short distinct from opponent YES/Long and bookmaker
wins, including material tie/refund differences. Missing offers remain unavailable.

Distinguish **Pinnacle raw American** from **Pinnacle fair American** after the named
no-vig treatment. Fair odds are a derived reference, not an executable offer.
Exact originals, probabilities, method, conditioning and clocks are inspectable
in Details. A missing selected reference is not replaced implicitly.

**EV** uses dense rows grouped by game and team/instrument, placing each venue's
price and after-cost, after-buffer dollars/return together. Complete-state EV and
conditional decisive EV have separate labels. Positive is the default; All
comparisons includes concise signed current results and explicit unavailable states.
Supported older inputs appear as **Last-known** estimates in All comparisons and
are excluded from current Positive and Hedges. The board distinguishes those
results from missing references, unsupported inputs, calculation failures and
evaluated results with no positive value. Older inputs from different times do
not establish a simultaneous historical trade.

**Scanner**, available at `/` and `/arbs`, ranks supported covered-outcome,
conditional and EV opportunities globally, with named funding and buffered metrics. Every ordinary filter requires distinct venues. Rule-sensitive hedges
stay separate from pairs positive across every modeled state. One short material
status/risk note remains visible; full fee and scenario reports belong in Details.
No positive opportunity is a normal result.

Defaults are **$1,000 requested funding, one 0.5% buffer on actual deployed capital
and Pinnacle reference**. A pair shares funding across both legs, modeled upfront
fees and required collateral. Reduced deployment and residual funding have stated
reasons. Actual fills, charges and grades remain unknown unless observed; fee,
liquidity and probability models retain their labels. See the
[financial contract](requested-trade-financial-contract.md) and
[benchmark meaning](benchmark-ev.md).

## Current Details and updates

Details binds the selected game and instrument or pair to its input-dependency,
policy and engine revisions. It leads with the supplied complete or conditional
percentage, source status and buffered dollars, then requested/deployed/residual
funding and quantities. Reconciliation explains gross value, rule adjustment,
modeled fees, net estimate and one buffer. Native terms, exceptional outcomes,
assumptions and selected current original inputs follow in expandable sections.

Use a bounded transient context or explicitly report that the comparison changed,
was removed or expired. Never silently replace the clicked selection or show new
source ages beside old financial values. Refuse crossed/delayed responses. Ordinary
Details uses current contexts, with no legacy history/envelope controls or
permanent result IDs.

Apply and Enter submit the same settings; Restore returns to calculation defaults.
Navigation and updates preserve useful filters, settings, scroll, focus and
disclosures. Withhold results from mismatched dependencies or policy. A source
clock remains distinct from receipt, calculation and read time; none of those
later clocks makes an old quote fresh.

Keep bounded reads with one request in flight and no request per game. The roughly
500-game bound uses pages of at most 50 games with a shared revision; changed
revisions discard the partial collection. All games labels and counts describe
the complete covered in-scope set.
Reads and Details never acquire data or restart collection; Stop remains reachable.

## Accessibility and states

Use light surfaces, slate text, restrained blue actions, readable body text and
comfortable controls at least 44px high. Preserve visible focus, wrap long names
and financial strings, respect reduced motion and supplement color with text.
Desktop venue columns align; 390px layouts label values without page-level clipping
and support increased text size. Dialogs support a focus loop, Escape/Close and
focus return to the opening row or a useful fallback. Collapsed sections do not
leave hidden controls in the tab sequence.

Common game/search filters stay visible. Calculation settings use an anchored
expandable panel, with applied funding, buffer and reference always shown.
Opening it reveals the existing fields, Apply and Restore defaults without moving
the comparison rows. Escape or an outside click closes the panel while retaining
its draft. Polls preserve drafts and focus, and sticky navigation keeps Stop
available. Source clocks use at least 12px text while game/team names and prices
carry the main visual hierarchy.

First use offers Admin source status when no game is available. Positive empty
states offer All comparisons. Failed reads offer Retry with a useful reason;
pending, stopped and unavailable-saving states remain distinct. Source clocks and
one concise material note stay on ordinary boards; quota, recovery and storage
diagnostics belong in Admin. Sports reset is separate from protected configuration,
credentials and provider account/quota/audit/attempt/hold records.

Healthy routine status prose stays out of the price rows; actual source times
remain beside prices and shared native limitations appear once per displayed
slate. Empty first use shows one source-setup action. Failed reads lead with
Retry/Admin guidance and retain technical reasons in a disclosure. Details leads
with the supplied complete or conditional estimate, then separate funding and
reconciliation; modeled outcomes and original inputs sit in named disclosures.
Opposing Details shows the supplied modeled minimum or its explicit unknown state.
Ordinary negative results use neutral copy; material uncertainty retains caution
styling. These presentation choices do not alter financial or protocol guards.

[Development](development.md#frontend-sources) describes the readable frontend
modules, generated public assets and verification boundaries.

## Layout and interaction

Scanner and Odds share navigation, 44px primary controls and visible keyboard
focus. Scanner keeps core scope filters visible and groups optional size, edge
and source restrictions in a disclosure whose summary names active restrictions.
Odds groups league/game/market filters and keeps Details settings beside its
heading. Identical shared and selected settings appear once; differing policies
remain explicit.

First use offers source setup. Pending, partial, expired, stopped and unavailable
states stay visible; a complete checked zero can be quiet. Details uses available
width while retaining funding, residuals, reconciliation and original clocks.
Narrow layouts must preserve value labels, focus containment/return and readable
long identities without horizontal page overflow. Synthetic browser fixtures test
these interactions; they do not establish current source availability or full-scale
performance. See [scanner usage](scanner-usage.md) for the user workflow.
