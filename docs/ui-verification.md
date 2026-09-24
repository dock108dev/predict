# Predict UI verification

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

The original report referenced screenshots and browser results in the optional
`UI Templates/review.html` gallery on the owner's Desktop. That gallery is
unavailable in the current workspace, so its artifacts were not reverified during
the September 23 documentation pass. The following remains the September 21
report, not current-checkout visual evidence. Browser specimens were local
fixtures or isolated startup states. Web review checked representative
1440px/390px layouts, page exceptions, and page-level horizontal overflow; it was
not an exhaustive audit of every state, contrast pair, screen reader, browser,
installed build, or physical phone.

Template gallery search, form submit feedback, dialog opening, and Escape dismissal were exercised. Shared styles include keyboard focus, reduced-motion, and reduced-transparency handling. Native Godot is a basic translucent fallback, not a true blur material. Native games retain their desktop layout and illustrated artwork.

See [design and future template use](ui-design.md). No owner acceptance or release qualification is inferred. Rebuild/relaunch the appropriate source application to see the change; installed or frozen copies remain their original versions.
