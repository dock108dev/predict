# Consolidated lead assignment: Workbench beta with Win $10 and Kelly comparison

## Highest-priority owner outcome: reusable Experiments creation

The owner explicitly says the most important goal is being able to create a
similar experiment later directly in Experiments without an engineer. A one-off
November 23 replay or a backend-only sizing feature does not complete this task.
Prioritize this normal product flow before visual polish:

Experiments → Create experiment → choose name, supported scope and dates →
choose Win fixed profit and editable target (default $10) → optionally enable
Kelly comparison with editable existing defaults → choose EV minimum/buckets
and portfolios → review a plain-language summary → Save and run.

Use sensible defaults and show mode-specific/advanced fields only when useful.
The same saved configuration must drive historical replay, future scheduling,
results, comparisons, revisions and exports. No hardcoded date, target, campaign
ID, hidden API payload, manual SQL/job registration or code edit may be required.
No-data/partial/historical-gap states must remain explicit. Reopening and editing
creates a new immutable revision through the same UI. Preserve support for
creating Kelly-only experiments as well as fixed-profit with optional comparison.

Primary release acceptance is a signed-in UI journey from the Experiments list,
not a direct seeded URL: create the requested November 23–29 Win $10 experiment
with Kelly comparison, then independently exercise another name/date range/
target through the same form to establish generic behavior. Use disposable data
for expansive test combinations; a clearly labeled bounded production exploratory
configuration may establish the deployed save flow without extra acquisition.
Verify save, validation, reload, automatic replay/schedule/result state, revision,
daily/weekly inspection and export. Return the exact owner click path in closeout.

Implement, integrate, deploy and verify the approved unbranded Workbench beta
and a **Win $10** paper sizing version for **November 23–29, 2026 inclusive**,
America/New_York. Calculate the Kelly comparison from the same retained evidence.
Every owner action must be available in the signed-in production UI.

This consolidates the Workbench assignment and fixed-profit amendment. Build
on the committed Workbench implementation and verify the combined flow in
production before owner review.

## Baseline and preservation

Use `/Users/michaelfuscoletti/Desktop/prediction-arb`, on `main`, the existing
single working copy. Read AGENTS.md, the active queue, this assignment and
`docs/engineering/predict-first-beta-closeout-20261124.md`.
Preserve existing documentation edits, credentials, user data, original odds
and result evidence, source pauses, Stop choices and account/hold state.

HEAD was `f9b86c465a7c3c8226182bc0368c48b758c8e070` at preparation, containing
the unbranded Workbench. The previous production closeout records application
revision `825cf299ded7eb3be4b8031ada47e7170d9fc20c`, migrations through 123 and
required CI 45542675533. Verify the current deployed revision before release.

## Sizing modes and shared experiment rules

Expose two versioned modes in experiment creation/revision:

1. **Win fixed profit**, target $10, the new primary experiment view.
2. **Kelly**, calculated with 1/40 full Kelly (2.5%) on the $10,000 reference
   for this experiment. The inputs are editable when creating future experiments.

For ordinary zero-fee binary odds with net win multiple b, ideal stake is 10/b.
American odds A>0 gives b=A/100; A<0 gives b=100/abs(A). Examples before rounding:
−110 → $11; +300 → $10/3; +500 → $2; +1000 → $1; +3000 → $1/3.
Winning net profit targets $10, returned cash is stake+$10, and losing profit is
−stake under that model. This does not remove variance or equalize downside risk.

Use exact arithmetic and existing frozen cashflow/fee inputs. Reprice the
actual commitment; do not scale the original fee receipt or change displayed
stakes alone. Honor captured quantity/price increments and fees. For an
unattainable exact target choose the nearest achievable positive net win profit,
breaking ties toward lower commitment. Version this rounding rule; record target,
achieved modeled win profit and difference. Explain material grid limits and
mark unsupported calculations unavailable with a reason. Never silently claim
exact $10 or manufacture executable precision. An ideal fractional-stake replay,
if offered, must be separately named and must not replace the grid-aware mode.

Recheck >=4% net EV after sizing and select the best qualifying venue from the
full candidate pool. Compare modes using stable quote/checkpoint/bet identities,
not mode-specific ticket IDs. Counts can differ after legitimate requalification;
explain the differences rather than forcing the same tickets to remain selected.

Keep shared rules: men’s D1 versus D1, Eastern dates November 23 through Sunday
November 29, final eligible T−10 within the existing capture window, unrounded
minimum EV 4%, unchanged exact-line reference method, Best venue and All venues,
distinct lines kept distinct, EV buckets [4,8),[8,15),[15,25),[25,+infinity) percent,
alternative minimum screens, provenance/freshness analyses, paper assumptions
and known coverage gaps. No new aggregate cap or compounding and no real orders.

## Comparison and automatic operation

Create the Win $10 experiment with Kelly comparison through the UI. Include
sizing mode, target, rounding/solver version and assumptions in definition/run
identity. Changing a sizing control creates a new version. Both modes can be
recomputed from retained quote and sporting evidence.

Both definitions run for November 23–29: replay retained elapsed days and schedule
remaining days. Reuse the same retained odds acquisitions and evidence wherever
possible. Multiple sizing calculations must not duplicate paid odds pulls or
orders. Preserve T−10 priority, storage reservations and account/source guards.

Saving either mode and receiving finals/corrections must use existing automatic
publication/grading. Verify idempotency, restart recovery, both arrival orders
and late corrections. Per-mode weekly totals count only the latest daily snapshot
once; modes and overlapping alternatives are never summed as one portfolio.
Keep Sunday finals eligible for Monday November 30 and subsequent corrections.
Missing/future/ungraded evidence never becomes zero opportunities or financials.

Preserve actual Stop/source-pause choices. Any required acquisition stays within
existing 300-credit/15-minute and 16,800-credit/day aggregate guards and current
CBBD/CFBD shared allowance. Do not add sources or change account limits for this
work. Passive UI actions/replays over retained evidence make no provider calls.

## Approved Workbench presentation

Use the approved reference:
`/Users/michaelfuscoletti/.codex/visualizations/2026/11/24/01a20b86-adf0-70a2-9a8c-e0378bf8a4fa/research-workbench-trades.html`.
Older carousel choices do not supersede the owner's explicit Workbench decision.
This is a mockup with a pinned snapshot, not production code/data. Do not ship
its embedded tickets, hardcoded results, simplified statuses or preview controls.

Remove visible logos, wordmarks and decorative branding. Retain compact Research,
Data and Settings navigation and existing authentication. Use the already-added
local IBM Plex Sans where suitable, 16–17px main text, strong contrast and weights,
aligned tabular numbers, available desktop width and consistent modest gutters.
Carry the coherent shell/typography into Data and Settings without breaking forms.

Default results to a flat trade list: selection/exact line, venue, odds, EV,
stake, grade and P/L. Game identity is secondary context, never mandatory grouping
or a prerequisite selection step. Keep complete market/period/line identity
visible or immediately accessible; never hide the line behind an ellipsis.
Use a side inspector on desktop and readable detail presentation at narrow widths.

Default sort is unrounded EV descending with stable ties. Filter/sort the whole
population before paging. Preserve valid date, mode, portfolio, filter, selected
trade and report-version context through updates, Back and reload. Clearly label
full-portfolio versus filtered summaries and choose a valid inspector fallback
when the selected trade leaves the current population.

Preserve every existing information path: frozen quotes, reference/probability,
screening/sized EV, appropriate sizing inputs, fee/quantity/cashflow calculation,
expected/realized modeled profit, ROI denominator, timestamps/quote age, provenance,
scores/overtime, grading explanation, original receipts, exports, report history,
source census, issue decisions/reopening, and theories/claims/findings links.
Keep pending/conflicting/unsupported/push/void/no-trade/stale/failure/loading
states correct. Missing-game financials remain unavailable. Secondary game and
coverage views retain zero-qualifier games and accepted gaps.

## Entire owner workflow in the UI

The owner must be able to create/revise an experiment, choose November 23–29,
choose Win $10 or Kelly, edit the target or Kelly inputs, set EV rules/buckets,
save the linked definition, see replay/schedule status and inspect automatic
daily/weekly results without SQL, CLI or manually authored JSON.

Show both sizing versions in one experiment family with an obvious mode switch
and daily/weekly comparison. Preserve the independent Best/All portfolio switch.
Label targets, stakes, modeled win profit/rounding difference and expected profit
distinctly. Kelly-only fields must not imply Kelly is controlling Win $10 stakes.
Include correct sizing assumptions in inspectors, history, comparisons and exports.
Keep issue-resolution and original-evidence workflows usable from this layout.

Create and verify the actual Win $10 version via signed-in production UI after
deployment. Verify the generated Kelly comparison in the same UI. Make repeated
save/replay idempotent.

## Evidence and acceptance

Verify both freshly calculated modes against their retained inputs and the
saved sizing rules. Reconcile exact stakes, returns, P/L and ROI across the
inspector, daily and weekly summaries, and exports. Previously published totals,
report hashes and historical result rows are outside release acceptance. Keep
capture provenance, accepted price gaps and sporting finals visible.

Add proportionate tests for sizing math at both odds signs, repeating decimals,
fees/increments/tie rule/unavailable inputs, EV requalification and best-venue
reselection, immutable identities/backward compatibility, auto-grading/corrections,
restart and idempotency, full-ledger filtering/paging and UI mode/version state.
Use disposable databases and existing required CI. Reconcile API and export
financials from exact values across the full selected population.

Finish integration, commit/push, run required checks and deploy through normal
guarded release with database backup for migrations. Verify services/role inputs
and existing campaign operation. Walk signed-in production at desktop, actual
side-pane and narrow widths: create/revise both modes, switch mode/portfolio/date,
compare days/week, inspect a trade through original receipts, exercise history,
Back/reload, issue actions and exports. Save screenshots of the real owner flow.

Update the beta closeout, consolidated assignment and active queue. Report actual
deployed revision, CI, direct UI links to both sizing modes, production figures,
rounding example, exact invariants, scheduled jobs and remaining operating
observations. Separate local, hosted and live evidence and report actual request/
credit/order usage. Complete routine fixes before owner review. Deliver the
running beta with both sizing versions; future dates remain in progress until
their real evidence arrives, rather than blocking this implementation release.

## Installed outcome

The November 23–29 experiment is live in both sizing modes. The [release
closeout](workbench-win10-beta-closeout-20261125.md) records the signed-in
creation and revision journeys, exact published results, deployed revision,
required CI and upcoming collection.
