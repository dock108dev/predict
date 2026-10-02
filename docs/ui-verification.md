# Predict UI verification

## October 1, 2026 — saved-review presentation cleanup

Current source only, following the three maintenance passes. The frozen beta
candidate and original review evidence remain unchanged. Main journeys reviewed:
compare results, choose a saved scan and open a game. Saved selection is now
visible, while settings and watch/history share one panel with independent
disclosures. Group labels and unavailable reasons use familiar words; game
headers show saved times and keep exact IDs inside the saved-time disclosure.
No calculation, ranking, eligibility, permission or persistence contract changed.

Matched Chrome desktop 1440×900 and narrow 390×844 screenshots use the same
isolated `b2-fixture` journal, three synthetic reference inputs, query, saved
cutoff and 100-contract size. Before assets come from unchanged HEAD UI files;
both versions run against the same current router. The first result means the
first displayed return or price, not the later raw-comparison group.

| Screen / first result top | Before | After |
| --- | --- | --- |
| Desktop list | 754.5px | 663.5px |
| Narrow list | 1112.6px | 1055.6px |
| Desktop game | 442.2px | 442.2px |
| Narrow game | 631.5px | 610.3px |

Saved-scan selection no longer requires opening settings; settings and watches
still each take one disclosure action. Desktop results appear earlier in the
first viewport. Narrow list results still require scrolling; type and 44px
controls were preserved. These are measured positions, not usability percentages.

Matched screens: [desktop before](../evidence/ux-cleanup-20261001/before-desktop.png)
/ [after](../evidence/ux-cleanup-20261001/after-desktop.png),
[narrow before](../evidence/ux-cleanup-20261001/before-narrow.png)
/ [after](../evidence/ux-cleanup-20261001/after-narrow.png),
[game before](../evidence/ux-cleanup-20261001/before-game-narrow.png)
/ [after](../evidence/ux-cleanup-20261001/after-game-narrow.png).
[Browser checks and measurements](../evidence/ux-cleanup-20261001/checks.json)
include matched loading, empty, failed/recovery, disabled Start and simulated
running/Stop states. Stop requests in this comparison are intercepted synthetic
responses; they do not qualify collector behavior. Both widths also passed
keyboard disclosure activation, invalid sizing/recovery, watch expansion, open
Details/focus surviving refresh and 200% CSS magnification with no page overflow.
Game saved-time disclosures expose the exact retained ID. No page errors occurred.
In-app browser desktop/narrow inspection also confirmed the current hierarchy.

Nine existing JavaScript checks pass: dashboard failures, board security, concise
dashboard, source details, native comparisons, aggregate UI, commercial UI,
session controls and source settings. Updated assertions cover new recovery
labels, saved timestamp/ID placement and display-only translations. Nineteen
Python dashboard-security/SSOT tests, changed-JS syntax, preview Python compilation,
documentation links and diff checks pass. Before/after API rows, comparisons,
reference inputs and cursor match exactly.

The collector-backed comparison preview timed out waiting for its two synthetic
connections; the existing discovery follow-up remains separate. The saved-data
preview instead used temporary storage, an isolated history catalog and watch
path, with collection disabled. The reusable comparison fixture now also excludes
the default retained catalog and owner watch path. No live/provider access,
owner mutation, ordinary app restart, full CI, packaging or release occurred.
CSS magnification does not establish native browser zoom or screen-reader
support; Safari and physical-device checks were not run. Owner acceptance remains
pending.

Two bounded suggestions remain outside presentation scope: investigate the
collector fixture timeout in a fresh disposable root; and review whether raw
prices should precede numerous return cards in the combined feed. In this fixture,
the first raw price is around y=3087 on desktop despite the earlier return result.
Changing group priority would change the accepted ranking/product contract and
needs a separate decision.

## September 23, 2026 — ordinary experience cleanup

Source presentation review, based on `5dd3407044be476a16f5c796034bd39412049449`
plus this working-tree change. The existing `docs/market-data-gaps.md` edit was
preserved. No frozen evidence, installed build, provider access, live collection,
commit, publication or release was changed.

The current game list and saved-game page were reviewed using a separate
`tests.integrated_browser_preview` instance with four synthetic venue roles,
loopback feeds, disposable storage and a guarded secret loader. Before/after
screens use the same saved API data, saved game, quantity, fee scenario and viewport.
The selected pair now appears first; all pairs remain available. Main tasks retain
their existing actions and steps.

| Matched screen | Before | After |
| --- | --- | --- |
| Desktop list, 1440 × 900: first row top | 909px | 638px |
| Phone list, 390 × 844: first row top | 1139px | 838px |
| Desktop game: first net result top | 796px | 620px |
| Phone game: first net result top | 1289px | 707px |

The desktop list now shows the first comparison in the initial viewport; the phone
game shows its net result there. The phone list still needs scrolling to read the
first comparison. Total desktop list length is essentially unchanged because
readable text and every blocker remain; the improvement is earlier access to the
task, not a claim that all content is shorter.

Matched screenshots: [desktop before](../evidence/ui-cleanup-20260923/before-saved-1440.png)
and [after](../evidence/ui-cleanup-20260923/after-saved-1440.png);
[phone list before](../evidence/ui-cleanup-20260923/before-saved-390.png)
and [after](../evidence/ui-cleanup-20260923/after-saved-390.png);
[phone game before](../evidence/ui-cleanup-20260923/before-game-390.png)
and [after](../evidence/ui-cleanup-20260923/after-game-390.png).
[Measurements](../evidence/ui-cleanup-20260923/after-measurements.json) and
[interaction checks](../evidence/ui-cleanup-20260923/interaction-checks.json)
are local review artifacts, not release qualification.

Checked in Chrome 152: populated, idle, running, filtered-empty, connection-error,
disabled-Start/locked-fee, game and what-if states at both matched sizes, with no
page exceptions or page-level horizontal overflow. Keyboard disclosure activation,
visible focus, filters, reference disclosures across refresh, selected-pair opening,
zero-probability persistence, saved-time navigation and Refresh recovery passed.
At 320px, 390px and 1440px, 200% CSS magnification was checked and wrapping repaired;
no page overflow remains. Start/Stop were exercised on the disposable synthetic
session. Reference-import missing-file and zero-count success messages were checked
with a mocked response. No real imports were made. Synthetic saved-page research
correctly remains unavailable; a populated historical research browser review was
not run.

49 focused Python tests passed: dashboard security, SSOT policy, multi-game,
opportunity board, math reconciliation, multi-page and page-estimate tests.
Five existing JavaScript checks passed: failure clearing, escaped identifiers,
concise-dashboard/persistence, stable source disclosures and research drilldown.
Changed JavaScript syntax, Python dashboard compilation and diff whitespace checks
passed. The complete saved calculation response equals the before response,
including original inputs, candidates and values. Full CI, real-source qualification,
Safari, assistive-technology and physical-device review were not run. CSS
magnification is not a claim of native browser-zoom or screen-reader certification.

### Keyboard-focus follow-up — complete

The previously reproduced focus loss is fixed in `dashboard.js`. Refresh restores
row-summary/link and source-reference focus by stable identity, after restoring
open disclosures. This includes the research renderer. Changed row order or cutoff
URLs do not change the focused control; a removed/hidden control, changed capture,
or deliberate move to another control does not receive stale focus. Restoration
uses `preventScroll`.

The original [failure reproduction](../evidence/ui-cleanup-20260923/focus-followup.json)
remains unchanged. New [browser checks](../evidence/ui-focus-20260924/browser-results.json)
exercise the real polling/render path with synthetic retained responses at 1440px
and 390px, including changed links, reordering, nested references, removed rows,
capture changes, research disclosures and focus moved during an in-flight request.
The extended source-details regression and the other four existing JavaScript
checks pass. JavaScript syntax and diff checks pass. No layout or calculation
change was made in this follow-up; the screenshots and Python results above remain
attributed to the earlier presentation pass. No live collection or release check
was run.

The README, design note, portable template requirements and development checks now
reflect the active labels, assets and focus behavior. Older UI reports are marked
historical and point here; their original evidence and outcomes remain unchanged.

Technical and visual verification does not establish owner acceptance or beta signoff.

## Historical glass adoption verification

September 21, 2026 · source implementation and engineering review only.

Existing dashboard failure and concise-dashboard checks passed. Browser preview uses the isolated B4 loopback fixture, never real feeds. Desktop (1440px) and phone (390px) layouts were inspected. The mobile scan-button wrap issue and an inherited primary-metrics background conflict found during review were repaired. A six-second synthetic scan saved two rows; both the populated dashboard and saved-game details were rechecked at desktop/phone widths, with no page overflow.

## Retained review

This is a historical browser review record, not current-checkout visual evidence.
Browser specimens used local fixtures or isolated startup states. Representative
1440px/390px layouts, page exceptions and page-level horizontal overflow were
checked; the review did not cover every state, contrast pair, screen reader,
browser, installed build or physical phone. Current styling conventions are in
[UI design](ui-design.md).

No owner acceptance or release qualification is inferred. Rebuild/relaunch the appropriate source application to see the change; installed or frozen copies remain their original versions.


## September 28 presentation cleanup

Current working-source verification, after the error-handling and security changes.
Existing review builds and consumed live attempts remain unchanged. Used the
ordinary application with `tests/comparison_feed_preview.py`, a fresh temporary
output root and loopback-only synthetic providers. This was not an owner-data or
live-source review. The prior screenshots in this document remain historical.

Matched saved simulation: four games/eight price comparisons, same original saved
session and cutoff. At 1440×900 the first dashboard price moved from y=813.7 to
711.4; at 390×844 from y=1431.0 to 1212.2. The game-detail first price moved from
y=563.4 to 441.2 on desktop. These are element positions, not usability percentages.
All eight comparisons remain; prices, quantities and raw evidence are preserved.
Narrow-screen prices still require scrolling past the visible controls. Secondary
card text is 13px, and comparison disclosures now have 44px minimum touch height.

| Screen | Before | After |
| --- | --- | --- |
| Dashboard, desktop | [Before](../evidence/ux-cleanup-20260928/before-desktop.png) | [After](../evidence/ux-cleanup-20260928/after-desktop.png) |
| Dashboard, narrow | [Before](../evidence/ux-cleanup-20260928/before-narrow.png) | [After](../evidence/ux-cleanup-20260928/after-narrow.png) |
| Game, desktop | [Before](../evidence/ux-cleanup-20260928/before-game-desktop.png) | [After](../evidence/ux-cleanup-20260928/after-game-desktop.png) |
| Game, narrow | [Before](../evidence/ux-cleanup-20260928/before-game-narrow.png) | [After](../evidence/ux-cleanup-20260928/after-game-narrow.png) |

Browser checks: populated and empty-filter states, invalid quantity and recovery
through settings, initial loading/disabled controls, keyboard disclosure activation,
open Details surviving Refresh, game navigation, and ordinary Start/Stop/save with
only synthetic loopback feeds. No page-level horizontal overflow at either width,
including expanded narrow Details. Existing focus-preservation tests passed.
Browser zoom shortcuts had no observable effect in the in-app browser, so increased
text/browser zoom and screen-reader behavior remain unverified; narrow reflow is
not a substitute for those checks. No new owner acceptance is inferred.

Validation: 15 Python tests (`test_dashboard_security`, `test_ssot_policy`), seven
JavaScript suites (`test_price_comparison`, `test_concise_dashboard`,
`test_dashboard_failures`, `test_source_details`, `test_board_security`,
`test_session_controls`, `test_freshness_timing`), changed-script syntax, document
links and `git diff --check` passed. The initial price-renderer assertion was updated
for the intentional wording change while preserving assertions for raw evidence,
saved/current context, zero-valued lines and safe link rendering. A mistakenly named
nonexistent `test_opportunity_cards.cjs` command ran no test; it is not counted.
No full CI, installed-build replacement, provider access, performance profiling,
commit, push or release occurred.

Remaining presentation boundary: moving the first narrow-screen price above the
fold would require changing the arrangement of the still-visible filters. If
further compactness is needed, compare one compact filter arrangement against this
same synthetic state before changing the ordinary workflow. No redesign is implied
by this maintenance.
