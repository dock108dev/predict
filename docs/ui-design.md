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

**Dashboard** at `/` shows separate positive EV and arbitrage sections, ranked
by their own exact supplied percentages. It distinguishes current positives,
evaluated no-positive, partial, unavailable and last-known states. Nonpositive
research sorts least negative first; conditional, hypothetical and gross results
retain separate labels. Filters narrow already collected results.

**Odds** defaults to All games and restores a valid saved game/filter selection,
grouping observed supported games into
compact game/team rows with venue columns. Search and game selection are optional.
Observed Polymarket US Long and Short appear inline with their actual participant,
side and predicate. Keep NO/Short distinct from opponent YES/Long and bookmaker
wins, including material tie/refund differences. Missing offers remain unavailable.

Distinguish **Pinnacle raw American** from **Pinnacle fair American** after the named
no-vig treatment. Fair odds are a derived reference, not an executable offer.
Exact originals, probabilities, method, conditioning and clocks are inspectable
in Details. A missing selected reference is not replaced implicitly.

**EV** at `/ev` reads All comparisons and leads with the EV outcome, followed by
ranked labeled research. Complete-state, conditional decisive and gross benchmark
values have separate meanings. Supported older inputs appear as **Last-known**
estimates and cannot enter current-positive results. Missing references,
unsupported inputs, calculation failures and evaluated no-positive states remain
distinct. Older inputs from different times do not establish a simultaneous
historical trade.

**Arbs** at `/arbs` is the stored opposing-comparison view, with Positive as its
initial filter and separate All comparisons and rule-sensitive research.
**Advanced Scanner** at `/scanner` ranks supported covered-outcome, conditional
and EV opportunities globally and supports manual tickets and observed episodes.
Its venue filters require both execution legs. Rule-sensitive hedges stay separate
from pairs positive across every modeled state. One short material status/risk
note remains visible; full fee and scenario reports belong in Details. A complete
evaluated no-positive scope is a normal result; unavailable evaluation is different.

Defaults are **$1,000 requested funding, one 0.5% buffer on actual deployed capital
and Pinnacle reference**. A pair shares funding across both legs, modeled upfront
fees and required collateral. Reduced deployment and residual funding have stated
reasons. Actual fills, charges and grades remain unknown unless observed; fee,
liquidity and probability models retain their labels. See the
[financial contract](requested-trade-financial-contract.md) and
[benchmark meaning](benchmark-ev.md).

## Current Details and updates

Details binds the selected game and instrument or pair to its input-dependency,
policy and engine revisions. Original-price Details leads with the exact selected
price and captured peer when available, native position, simple age and comparison
meaning. Financial Details starts with exact positions and original prices, then
the supplied metric and its complete, conditional or hypothetical meaning.
Optional funding, quantities, reconciliation, models and technical source evidence
remain inspectable without dominating ordinary discovery.

Use a bounded transient context or explicitly report that the comparison changed,
was removed or expired. Never silently replace the clicked selection or show new
source ages beside old financial values. Refuse crossed/delayed responses. Ordinary
Details uses revision-bound contexts and bounded selection leases, with no legacy
history/envelope controls or permanent result IDs. A surviving leased frame keeps
captured inputs inspectable across replacement while withdrawing current eligibility.

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

Common game/search filters stay visible. Optional **Details settings** uses an
expandable disclosure for amount, buffer and reference, with Apply and Restore
defaults. Shared discovery keeps its server policy; selected settings do not
rerank the slate. Dashboard and EV keep settings secondary to the outcome.
Polls preserve drafts and focus, and navigation keeps Stop available. Source
clocks use at least 12px text while game/team names and prices carry the main
visual hierarchy.

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
with prices and meaning, followed by the supplied metric where available; funding,
reconciliation, modeled outcomes and technical evidence remain inspectable.
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

## October 23 interface refinement

The current Dashboard → Odds → Details journey keeps the cool light palette,
system typography and restrained blue actions from the shared design requirements.
Navigation and Stop use the same 44px control family on desktop and narrow screens.
Dashboard filters remain readable; a healthy refresh does not leave a redundant
Reload button. When positive results are unavailable, Browse available prices
precedes the separate arbitrage/EV availability panels. Unknown is never zero.

Odds groups diagnostic counts and comparison readiness under one Price coverage
& availability disclosure. Current and last-known groups retain their own aligned
venue headings. Original prices, native sides and source ages stay visible.
Selected Original Inputs states comparison unavailability once, preserves the
captured-frame reminder, and keeps complete wording, exact clocks, reasons and
depth in Source details & observed depth. Selected sizing stays secondary in a
full-width Details settings control with retained drafts.

EV research rows explicitly place identity, metric and Details at each breakpoint;
team names use full mobile width rather than inheriting a narrow desktop column.
Footer links stay grouped. Existing captured selection leases preserve original
evidence across updates; changing current inputs withdraw eligibility without
silently replacing the selected evidence.

Matched intercepted fixtures were visually reviewed at 1280px and 390px, including
populated Odds, unavailable estimates, Original Inputs, empty and failed reads.
Expanded conditional results, financial Details, enlarged text and long names were
also inspected. These are presentation checks, not owner or new-user acceptance,
current source qualification or commercial readiness.
