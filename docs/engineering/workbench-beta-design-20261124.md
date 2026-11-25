# Lead assignment: implement the approved unbranded Workbench in the beta

## Owner sizing amendment

The owner subsequently requested a new **Win $10** fixed-profit sizing version
of the November 23–29 experiment. Implement the
[fixed-profit amendment](fixed-profit-sizing-amendment-20261124.md) alongside
this Workbench change using the
[consolidated assignment](workbench-win10-beta-20261124.md). Both sizing modes
use the same retained evidence for comparison.

## Outcome and baseline

Implement, deploy and verify the approved Workbench presentation in the existing
private beta at https://predict.dock108.dev. The owner explicitly chose
**Workbench, no branding, flat trade list, all existing information/calculations**.
This replaces game-first browsing as the default results interaction.

Work on `main` in `/Users/michaelfuscoletti/Desktop/prediction-arb`, the single
existing working copy. Preserve all edits, user data, credentials, account/hold
records, Stop choices and original source evidence.

Read AGENTS.md, the active queue, this assignment and
`docs/engineering/predict-first-beta-closeout-20261124.md` before editing.
The previous beta work has been delivered; do not repeat the November 23 audit
or rewrite its calculations as part of a visual redesign. Read its audit and
daily/weekly documents as needed to preserve behavior.

Current local HEAD is `348675f497b64d8a8df125c831c4be0aac302cd1`; it and
`53223bd` are documentation follow-ups to application revision
`825cf299ded7eb3be4b8031ada47e7170d9fc20c`. Required CI 45542675533 passed;
the closeout records migration 123 and healthy deployed role input digests.
Refresh live state before release; these are dated observations.

## Approved design reference

Use the revised, unbranded, trade-first mockup:
`/Users/michaelfuscoletti/.codex/visualizations/2026/11/24/01a20b86-adf0-70a2-9a8c-e0378bf8a4fa/research-workbench-trades.html`

The earlier three-direction carousel is historical exploration. The owner's
explicit Workbench selection and subsequent unbranded flat-ledger correction
govern even if an older carousel emits a different selected variant.

The mockup is a visual/interaction reference, not production code or a data
source. It contains a pinned November 23 snapshot and simplified prototype
states. Use actual production APIs, formatters and semantics for all dates,
portfolios, result states and evidence; do not ship its embedded dataset,
hardcoded totals, preview labels, rounding calculations or host-only controls.

## Design requirements

- Remove visible logos, PREDICT wordmarks and decorative branding from the
  owner-facing Research/Data/Settings shell. Retain compact functional navigation,
  descriptive document titles, accessibility landmarks and the signed-in gate.
- Use the available desktop width, about 1200–1440px maximum with consistent
  modest gutters, avoiding centered narrow columns and gray walls of text.
- Use IBM Plex Sans as the preferred body face, with a suitable local/system
  fallback; keep font loading reliable. Main text 16–17px, readable table text,
  strong dark foregrounds, medium/semibold labels and tabular numeric figures.
  Maintain readable contrast and clear focus in supported appearances.
- Keep a compact date/experiment header, Daily/Weekly controls, portfolio switch,
  clear financial summary and a compact coverage line. Retain pending/error/stale
  notices with appropriate prominence. Avoid large empty headers and repeated
  explanatory paragraphs; put supporting detail in labeled expandable sections.
- On desktop put the flat trade ledger beside a selected-trade inspector. Selecting
  a row updates that inspector without requiring entry into a game group first.
  On narrow layouts use a usable full-width detail view or stacking arrangement.
  Do not crush seven columns into tiny text or create narrow paragraphs.

## Flat trade ledger

Default experiment/day results to one row per paper ticket across the selected
portfolio and date scope. No mandatory game grouping or game-selection step.

Primary columns: selection including exact line, venue, odds, EV, stake, grade
and modeled P/L. Game identity is secondary context in the row and full context
in the inspector. Never clip the spread/total, sign, market or period needed to
distinguish bets. Keep full names accessible when visually shortened.

Default to descending unrounded EV with deterministic tie-breaking. Filters,
sorts, counts and pagination apply to the full selected population before paging.
Preserve selection and valid filters across inspector changes, passive updates,
portfolio/date navigation, Back and reload. A selected ticket unavailable under
new filters must have a sensible visible fallback, never stale mismatched details.
Summaries must distinguish portfolio totals from a filtered subset.

Keep Best venue and All venues semantics unchanged. A visual flat list does not
alter equivalent-bet identity, venue deduplication or distinct-line selection.
Preserve all existing EV buckets, alternative minimum screens, freshness and
frozen/reconstructed analyses. Keep alternative analyses separate from committed
portfolio totals and make active scope clear.

## Preserve all existing information

Reuse the existing financial/evidence model and renderers where practical. The
inspector must retain quote, probability/reference inputs, screening and sized EV,
Kelly bankroll/fraction/budget, commitment/quantity/fee assumptions, expected
profit, returns, P/L, ROI context, exact market/period/line, capture provenance,
source/request/receipt/decision/persistence clocks, quote age, sporting scores,
overtime, grading explanation, evidence IDs and original receipt/export access.
Keep unknown native contract IDs, fees and executable size explicitly unknown.

Preserve report history, pinned result versions, corrections/staleness, exports,
deep links, theories/claims/findings relationships, source and offer censuses,
issue decisions/history/reopening and full experiment creation/revision controls.
Game-level evidence and zero-qualifier/missing-game information remain available
as secondary views; they do not become prerequisite navigation for a trade.

Support all actual states: wins, losses, pushes, voids, pending/conflicting or
unsupported grades, no selected tickets, partial reports, absent captures,
zero qualifiers, accepted gaps, failed/stale/loading updates and future dates.
Missing evidence withholds financials; partial ROI retains its correct resolved
stake denominator. Never substitute zero or “all graded” for unknown states.

Apply the coherent typography, spacing and unbranded shell across Research,
Data and Settings without breaking their existing forms, tables or links. The
owner must still complete experiment setup, revisions, issue resolution and
daily/weekly validation entirely in the UI.

## Implementation starting points

Inspect the current code rather than building a separate demo application:
- `app/dashboard/opportunity_static/current/research-workspace.html`
- `research-workspace.css`, `research-workspace.js`, `research-results.js`
- `research-campaigns.js`, `research-quality.js`, `research-issues.js`
- `workspace-nav.js`, `workspace-ui.js`, `workspace-format.js`
- `mens-d1-coverage.js`, `data.html`, `settings.html` and relevant shared styles
- `app/dashboard/paper_results_view.py`

The result view already returns selected-portfolio report tickets. Prefer using
those immutable records for the flat ledger. Add minimal read projections only
if necessary; do not create a new calculation engine or scrape rendered pages.
Reuse shared display components/tokens, and guard against CSS changes spilling
into unrelated trading screens. Reads, filters, exports and inspector changes
must remain passive and must not trigger acquisition or grading writes.

## Running experiment

Use the [consolidated assignment](workbench-win10-beta-20261124.md) for the
November 23–29 Win $10 campaign, Kelly comparison and automatic results.

## Verification and release

Add proportionate browser/component regressions for the new primary interaction:
all portfolio tickets reachable without game selection; exact line visible;
stable full-population sorting/filtering/paging; inspector/URL/Back/reload state;
portfolio and Daily/Weekly switching; quality comparisons and issue workflows;
missing/partial/stale states; historical deep links; exports; narrow/desktop layout.
Exercise an actual trade through every calculation and original evidence link.
Existing browser tests include `test_paper_results.py`, `test_paper_campaigns.py`,
`test_research_issues.py`, `test_research_workspace.py` and Data workspace checks.
Update assertions that intentionally change; preserve their underlying guarantees.

Reconcile API and export financials from exact values across the full selected
population for each sizing mode.
Use disposable test databases and required repository checks. Do not write
pixel-fragile tests for cosmetic details or weaken meaningful existing checks.

Commit/push, deploy through the normal guarded release, verify CI/service role
inputs and health, then exercise signed-in production. Inspect a wide desktop,
the actual side-pane width and a narrow layout. Save screenshots of the flat
ledger and inspector and confirm forms/exports/Back/reload work. Verify workers
and the same campaign remain active after release. Do not use a scheduled future
game as a gate for completing a presentation change.

Update the beta closeout, this assignment and active queue. Deliver deployed
revision, CI, direct daily/weekly/trade links, screenshots, what changed visually,
what financial/evidence invariants were verified, and any actual remaining issue.
Distinguish local, hosted and live evidence. Complete routine repairs and deployment
before requesting owner review; do not stop at a mockup, CSS patch or plan.

## Workbench presentation release

The approved unbranded shell, daily ledger and inspector shipped November 24,
2026 Eastern. Installed web revision
`b404e9770574e0112dd6e1648454320da6c7a976` uses the existing Kelly campaign and
saved evidence. Follow-up verification compared the complete pinned portfolios
and exercised the owned browser flows. The production closeout records the
installed roles, immutable checks, campaign state and direct reports. The
fixed-profit work is tracked in the subsequent consolidated assignment.
[Workbench closeout](predict-first-beta-closeout-20261124.md#workbench-release) ·
[Required release CI](https://github.com/dock108dev/predict/actions/runs/45548444638)
