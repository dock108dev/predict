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

**Odds** opens on All games, grouping covered upcoming NFL winner games into
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

**Arbs** groups opposing legs with their shared funding and named buffered margin
or return. Every ordinary filter requires distinct venues. Rule-sensitive hedges
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

## October 17 interface review

Adapted the shared Glass Starter 02 requirements (September 23): cool light
surfaces, slate text, restrained blue actions, system typography and 44px primary
controls. No gallery/runtime dependency was added. Reviewed the current source
scanner, Odds and selected Details; historical installed screenshots are separate.

- Scanner and Odds now share navigation, brand treatment, control sizing and focus
  styles. Scanner includes the existing Coverage destination. Routine checked
  status is quiet only when evaluation is complete with no errors; pending,
  partial, expired, stopped and unavailable messages remain visible.
- Odds places six common filters in one desktop row and Details settings beside
  its heading. Identical shared/selected settings are stated once; differing
  policies still show both. Scanner keeps scope filters visible and groups its
  optional minimum-size/edge and source restrictions under Size & sources. Applied
  restrictions remain named in the collapsed summary. These are existing controls,
  with one additional reveal for those optional restrictions, not new capabilities.
- First use leads with a single source-setup action instead of zero-count coverage
  disclosures. Result counts use ordinary catalog wording. Single-metric Details
  fills its available width rather than leaving an unused metric column; funding,
  precise residuals, reconciliation and original clocks remain. A future source
  clock warning no longer repeats the word Source during age updates.

Matched offline Chromium screenshots use identical repository fixture data and
clocks at 1280×900 and 390×900. At desktop width the first Odds game moves from
658px to 438px; at 390px it moves from 877px to 707px. The first scanner result
moves from 392px to 345px on desktop and 783px to 619px on narrow screens. Narrow
first use moves from 517px to 206px. These measurements describe composition,
not actual source coverage, performance or new-user success.

Evidence is under `test-results/interface-review-20261017/`: paired
`before-{scanner,odds,details,empty,failure}-{1280,390}.png`, corresponding `after-`
images, review harness and JSON observations. Screenshots were visually inspected.
The final intercepted browser pass also checks optional-filter keyboard access,
invalid-input feedback/reset, local search, a settings draft surviving refresh,
Details focus containment/return, long names and 125% text without document
horizontal overflow. All browser traffic is intercepted; no ordinary SQL, owner
state or providers are used to populate these screens.

Eight affected JavaScript suites, seven Python asset/contract tests, generated
asset drift, JavaScript syntax and documentation/whitespace checks pass. Existing
synthetic preview AppKey warnings remain. Full SC04/SC05 performance campaigns,
installed/live acceptance and independent new-user testing were not run. The
working source assets were rebuilt; no ordinary process restart, publication,
commit or release was performed. Visual conclusions apply to the inspected
synthetic states and remain provisional for owner/customer use.
