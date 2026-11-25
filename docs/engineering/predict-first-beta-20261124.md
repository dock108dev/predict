# Lead assignment: first Predict research beta and running NCAAB experiment

## Outcome

Implement, integrate, deploy and verify the first usable private Predict research
beta at https://predict.dock108.dev. Close the November 23 data audit with honest,
versioned dispositions, and leave the actual November 23–29, 2026 men’s D1 paper
experiment running automatically. Complete the engineering before owner review.
Future game dates do not need to finish before beta release; the experiment
remains in progress until their capture and result evidence arrives.

## Workspace and baseline

Work on `main` in `/Users/michaelfuscoletti/Desktop/prediction-arb`, the existing
single working copy. Read AGENTS.md, this assignment, the active queue,
`docs/engineering/nov23-data-resolution-plan-20261124.md`,
`docs/engineering/ncaab-daily-weekly-20261124.md` and
`docs/engineering/automatic-experiment-results-plan-20261124.md`.
Preserve all existing edits, untracked plans, user data, credentials and history.

At the November 24 late-evening check, HEAD/web was
`3743a873012ed5676b5cb35d1e59a385935207ba`; required CI 45537766319 passed.
Collector/archive reused the healthy `c6cc085` role images, PostgreSQL was
healthy, and migrations through 121 were deployed. Verify current role input
digests rather than demanding all role revision labels match a web-only commit.
Refresh current production state before applying this timestamped baseline.

Existing campaign:
`93b8937a41703ce083609c50e52135019fe36bf082a1f32ecf5a00d54daffeda`.
November 23 run:
`5100a1a827c4e76236489281f67f92e411ce2f8b61495cb9f5e823635b881ea3`.
Use the existing campaign; do not create a duplicate schedule.

## Frozen experiment rules

- November 23–29 inclusive, America/New_York game dates; men’s D1 versus D1.
- Final eligible T−10 capture within the existing 60-second capture window.
  Keep reconstructed original in-window evidence explicitly retrospective.
- Unrounded EV >=4%, unchanged exact-line probability/reference method.
- 1/40 full Kelly (2.5%), one tenth of former quarter Kelly, $10,000 reference,
  no aggregate bankroll cap or compounding. Recalculate at the new size; do not
  divide previously rounded stakes. At 4% EV: −110 $11, +300 $3.33, +3000 $0.33.
- Best venue deduplicates the exact equivalent bet across venues; All retains
  each qualifying venue offer. Different lines remain separate bets.
- Continuous EV buckets [4,8), [8,15), [15,25), [25,+infinity) percent and
  alternative >=4/8/15/25% screens, with best venue reselected at each threshold.
  Alternative analyses are never additional portfolio stakes.
- Preserve modeled zero-fee/quoted-size assumptions and all original runs.
  No real orders, fills, payment or settlement claims.

## Implement the November 23 corrections

Follow the complete audit plan and `.local/nov23-gap-audit-20261124/` evidence.

1. Fix date/scope counters and raw-versus-reconciled status projections. The
   46 current occurrences are 33 eligible Monday games, 12 non-D1 exclusions
   and San José State–UC San Diego assigned to November 24 Eastern. Monday
   has 33 finals, no unresolved current membership/date decisions, and four
   officially corroborated start-clock disagreements. Resolve operational
   warnings while retaining original clocks, TBD placeholders and capture targets.

2. Show separate original capture status, usable evidence and issue disposition.
   Original reliability is 6 successful, 19 refused, 8 missed. Paper usability
   is 6 frozen, 20 reconstructed, 7 historical gaps. Keep usable reconstructions;
   close their historical issues without rewriting failed tasks. Accept the seven
   audited gaps with evidence/reason; retain their finals and denominator presence,
   withholding unknown opportunities and financial metrics. A final archive check
   may use existing retained originals; later odds cannot fill historical windows.

3. Preserve five evaluated zero-qualifier games. A no-trade outcome is valid.
   Games without lines remain in the schedule population. Distinguish explicitly
   unavailable, no provider odds observed, requested-but-unreturned, not-requested,
   unsupported, failed and missed. Absence of a response never proves no line;
   no-line claims require affirmative evidence scoped to source/venue/market/time.

4. Publish a versioned, derived market-census summary from retained originals,
   and use it consistently in cards, detail and exports. All 26 usable games have
   detailed event-response evidence: 2,184 requested venue/outcome cells, 2,035
   returned, 149 unreturned. Fix old summaries that say every retrieval is unknown
   or imply zero measured cells. Materialize/cache this background calculation;
   do not decode the entire archive during every UI render. Separate returned
   event completeness, event pagination and unknown venue-wide line inventory.
   Accept genuinely unreturned historical cells as bounded source limitations.

5. Close method-ineligible offer exclusions honestly: 6,236 offers reconcile to
   1,774 unavailable + 1,546 reference-ineligible + 2,802 below 4% + 114 qualifying.
   The 1,546 reference exclusions are 672 exact-pair and 874 insufficient-book
   cases; the raw audit found no normalization loss. Keep missing exact books,
   sides and lines visible. Do not replace probabilities or drop whole games.

6. Add frozen-only versus reconstructed provenance views, quote-age buckets and
   a clearly exploratory <=60-second target-price-age comparison. Eight of 114
   All quotes exceeded 60 seconds at receipt, four exceeded 300 seconds. Define
   clock basis and boundary exactly; distinguish unknown/future clocks. Show
   reference freshness where known, without inventing timestamps. Filter the
   candidate pool before best-venue selection. Preserve the unrestricted campaign;
   adoption of a different qualification policy creates a separate version.
   Keep fees, size and missing native contract IDs visibly unverified for paper.

## Make closure and experiment operation usable in the UI

Extend existing Research/Data/Settings flows rather than building another site
or a Monday-only pipeline. Provide reusable append-only dispositions: open,
resolved by evidence, accepted historical gap, accepted source limitation,
excluded by scope and assigned another date. Each records item identity, evidence
revision, reason, actor/time and history. New relevant evidence should surface
for review; a decision must not silently carry over to a different issue.

Expose resolve/accept/exclude/reopen through the signed-in UI. Exclusion requires
scope evidence; closing an issue never silently deletes a losing ticket, changes
saved P/L or overrides financial assumptions. Cohort/selection changes produce
new experiment/run versions. Apply the audited November 23 dispositions through
this workflow, with bulk actions allowed only for explicit selected identities
and shared reasons. Preserve all 46 occurrence audit rows.

Default to actionable open issues; make accepted/resolved history easy to open.
Show the funnel: 33 reviewed games → 26 usable (6 frozen/20 reconstructed) →
21 with trades and 5 without qualifiers; 7 accepted historical gaps; 33 finals.
Use the reconciled 33-game cohort as the named operational denominator while
retaining the unverified independently exhaustive slate limitation. Do not call
accepted gaps successful captures or claim full global sportsbook coverage.

The owner must be able to create a similar experiment, choose dates/sizing/EV
buckets, revise it, inspect daily/weekly results, resolve issues and export from
the UI. Verify week → day → game → trade/calculation/evidence → week, portfolio
switching, date/version state, Back/reload and narrow/desktop layouts. Keep paper
results, missing data, pending results and actual venue execution distinct.
Fix known usability or route errors on this path before declaring the beta ready.

## Leave the actual experiment running

Verify the existing production campaign covers November 23–29 exactly once per
date, resumes after restarts, publishes changed retained evidence idempotently,
and grades automatically when finals/corrections arrive in either order. Weekly
totals count the latest run once per date; old snapshots remain accessible.
Missing/future/ungraded days never masquerade as zero-return days.

Check current independent slate/finals jobs, provider discovery, protected T−10
dispatch, reservations/storage forecast and results-worker health. Fix engineering
defects exposed by those checks. Discovery must account for all requested event
pages/IDs, include games without odds, and retain failure/missing-member receipts.
Do not silently widen provider scope or bypass capture/account guards.

Ensure the Sunday November 29 experiment remains eligible for prior-day finals
on Monday November 30 and subsequent corrections. Persist job status and any
failure visibly; no manual SQL, browser session or Codex chat may be required to
keep it running. Preserve explicit owner Stop/source pauses. If those prevent
operation, identify the exact setting and affected work without overriding them.

Existing acquisition authorization applies: aggregate 300 credits per 15-minute
cycle and 16,800 per operating day across the existing six-league/three-family
scope, with current account/quota/reservation/hold guards taking precedence.
CBBD/CFBD share the existing monthly allowance; inspect current balance without
exposing credentials. Do not add Firecrawl or another source to finish this beta.
Research views/replays/exports must not trigger paid collection.

## Verification, deployment and completion

Use disposable test databases. Add focused tests for the actual failures and
state boundaries: scoped counters, corroborated disagreements, raw/reconciled
counts, no-line versus unknown, census consistency, immutable issue decisions,
reopening/new evidence, exact offer accounting, threshold/freshness best-venue
reselection, duplicate/reordered results and worker restart. Test the UI where
the owner must perform the action. Existing related tests cover men's D1,
market census, paper campaigns and paper-result queues; extend them proportionately.

Snapshot original definition/run/report hashes before writes. For the pinned
1/40-Kelly November 23 run, verify Best 76 tickets/$448.68/−$45.44 P/L and All
114/$596.34/−$135.28, with all selected tickets graded. Preserve original versions
if legitimate newly retained result corrections require a later report version.
Verify exact arithmetic across trades/games/venues/provenance/days/buckets, not
only displayed rounding. Disposition labels alone must not change these totals.

Run required repository CI, commit/push, use normal guarded deployment with DB
backup for migrations, verify role inputs/health, then exercise the signed-in
production workflow including the actual saved dispositions and running campaign.
Repair engineering failures without another owner permission cycle. External
historical/source limits receive explicit accepted dispositions; they do not
justify leaving fixable beta defects unfinished. A future natural 25-game live
cluster is operating evidence still to obtain, not proof supplied by a fixture
or a reason to wait until Sunday to release a usable beta.

Publish a first-beta closeout in docs/engineering, update this assignment, the
audit plan and active queue without erasing earlier evidence. Report deployed
revision, CI, usable UI links, one concrete repaired case, verification scope,
all accepted gaps, actual campaign daily status and next automatic jobs. Separate
local tests, production UI evidence and actual scheduled collection. Report
requests/credits/holds/bytes/orders as observed, not guessed.

Deliver the deployed beta with the experiment running. Do not declare the week
finished before final evidence arrives, claim guaranteed profitability, require
real orders to finish a paper beta, or stop after writing another plan. If truly
blocked by external access/evidence, explain the affected behavior, finish all
independent work and leave its exact visible disposition and next action.


## November 24 delivery

The private beta is deployed with the original campaign still running. The
November 23 reconciliation, exact totals, production verification and upcoming
job evidence are recorded in the [first-beta closeout](predict-first-beta-closeout-20261124.md).

## Approved Workbench presentation follow-up

The owner selected an unbranded Workbench with a flat trade list and all existing
information/calculations preserved. The
[Workbench beta assignment](workbench-beta-design-20261124.md) governs that
implementation. It supersedes game-first browsing as the mandatory results
entry path while retaining game context, evidence, historical deep links and
secondary game-level views. The delivered beta and original experiment rules
remain the baseline, rather than work to rebuild.
