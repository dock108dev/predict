# Interface design

The working flow is **Odds board → Arbs → Admin**. Keep comparisons prominent and
source operation in the separate Admin page.

## Comparisons and Details

Group exact outcomes by game, market, period and signed line. Align venue columns
on desktop and label prices on narrow screens. The Odds board compares the same
selection; Arbs names both opposing outcomes and venues. Primary percentages
require no stake entry. Preserve supported positive, zero and negative results;
missing information is never displayed as zero.

A price selection opens Details. Details follows current quote revisions and
exposes originals, conversion basis, clocks and material rules. At narrow widths
it becomes a modal and returns focus when closed. Manual dollar What-if is
secondary and uses a temporary immutable server lease for its calculation.

Source state, receipt age and browser connection have distinct meanings. Keep
unavailable, stale, delayed and unknown states near affected results. Expanded
status holds longer source explanations. Never replace unavailable current prices
with saved or synthetic observations.

## Controls and rendering

Use restrained cool surfaces, system typography, blue actions/selection, visible
focus and controls of at least 44px. The shared stylesheet scopes ordinary app
styles with `.current-app`; retained preview selectors keep their separate roles.
There is no dependency on an external template gallery.

Use content-sized fields, readable prices and wrapping long names. Details should
not reserve empty space when closed. Material uncertainty must remain visible,
and color must not be the only state indicator. Keyed updates preserve disclosure
identity, open state and keyboard focus. Respect reduced-motion preferences.

Admin presents refresh, Stop/recovery, source health, quota and current issues.
Explain costs and recovery consequences beside actions; keep encoded state and
extended measurements secondary. Visual edits must preserve accounting, due
times, source clocks and original-input calculation policy.

Use the [synthetic preview](development.md#synthetic-preview) and existing browser
regressions for UI development. Screen appearance alone does not prove price
freshness, live coverage or calculation eligibility.
