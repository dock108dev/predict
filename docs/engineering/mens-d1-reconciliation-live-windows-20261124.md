# Reconcile both dates and verify larger live capture windows

Status: reconciliation and signed-in verification complete on `main`. Both
requested live windows and the next relevant repair window are recorded below.
The repaired 25-member production load and both exhaustive slate denominators
remain unverified.
The assignment was prepared November 24, 2026, at approximately 1:20 PM Eastern.
Preparation changed no application code or collection controls. Refresh receipt:
`.local/cbbd-activation-20261124/next-assignment-refresh.json`.

## Copy-ready assignment

Finish the November 23 and 24 men’s D1 experiment reconciliation using the newly
authenticated CBBD evidence. Verify the larger live T−10 windows and show exactly
what still prevents full coverage. Complete necessary correctness, integration
and verification work, not another broad redesign.

### Baseline and preservation

Work in `/Users/michaelfuscoletti/Desktop/prediction-arb`, on `main`, in the
existing working copy. Read AGENTS.md, the active queue,
`docs/engineering/mens-d1-coverage-completion-20261124.md`, and this assignment.
Preserve existing uncommitted documentation edits, credentials, Stop/pause
choices, account/quota/reservation/hold records, original responses and runs.

Baseline HEAD/deployed app: `3da369b5cdeaf34d50e8c784b3133af99cb69e38`.
Required CI: https://github.com/dock108dev/predict/actions/runs/45451724362
Refresh the actual installed revision, health and evidence before proceeding.

CBBD is authenticated and active. The first real collections succeeded:

- November 23 results at 1:13 PM: 47 rows, 32 eligible, 13 excluded, 2 unresolved.
- November 24 slate at 1:14 PM: 86 rows, 77 eligible, 9 excluded.
- Both original-response hashes verified; two metered calls recorded. The last
  authenticated balance check showed 998 of 1,000 shared CBBD/CFBD monthly calls
  remaining. Refresh allowance through `/info` and preserve the shared quota.

At the read-only 1:19 PM check, Monday had 27 exact source/provider matches,
five schedule conflicts, and 33 provider-known eligible games. Tuesday had 73
exact matches, three schedule conflicts, one source-only row, and 77
provider-known eligible games. Complete expected slates were unknown. Tuesday
had six current eligible frozen captures and 71 upcoming. These are different
populations and overlapping facets, not interchangeable denominators.

### 1. Reconcile game identity, scope, date and results

Build one inspectable game ledger for each Eastern date, covering the union of
the retained CBBD exports/API revisions, original provider population, source-only
games and retained official corroborations. Deduplicate actual occurrences while
preserving every source record. Include games with zero qualifying EV.

For each occurrence show team/source/provider IDs, season D1 membership, scope
disposition, original and normalized clocks, timezone, schedule revisions,
match/conflict reason, first observation, pre-T−10 knowledge, capture disposition,
and sporting-result state with original evidence.

Resolve demonstrated matching and normalization defects. Investigate the two
Monday TBD identities, the Monday schedule conflicts and provider-only eligible
games, Tuesday’s three start-time disagreements and source-only game, and
Stanford–Colorado’s Eastern-midnight disagreement. Check whether prior
school/conference corroborations remain discoverable and applicable after the
new authenticated revision. A disappearing conflict counter alone is not proof
of resolution. Preserve conflicting clocks and the basis for any decision.

Reconcile authenticated finals against provider/official evidence, including
Middle Tennessee–Southern Illinois. Unplayed Tuesday games stay pending.
Do not turn sporting finals into venue settlement or financial P&L in this slice.

A retrospective result/slate can resolve identity or eventual membership; it
cannot establish that the game was known before its historical T−10 window.

### 2. Reconcile opportunities and both paper variants

Preserve Monday’s original and corrected runs and Tuesday’s original snapshot:

- Corrected Monday:
  `db29fca80c85b7f9c7c7ca3a4efcee7eae593513b71a73b88103d31b1186349f`
- Tuesday snapshot:
  `f86e9ad57e5ec5a545a1e4adfcb45e13bba210dbe3fbea7baf2b981f2bd13758`

Monday’s saved eligible population is six frozen, 20 reconstructed and seven
missing. Its 6,236 offers reconcile into 1,774 unavailable, 1,546 reference
exclusions, 2,802 below 4% and 114 All venues tickets. Best venue has 76 tickets
and $4,497.26 turnover; All venues has 114 and $5,985.33. The original ledger’s
eight misses/19 refusals remain distinct from the reconstructed run.

Reconcile newly matched games and current captures against the original evidence.
Save separately versioned current analyses for both dates where new population
or checkpoint evidence changes the run. Show their relationship and differences
from the old snapshots: games, captures, offers, exclusions, tickets and turnover.
If a run cannot be saved accurately through the existing UI, fix that path.
Do not overwrite a prior run or manufacture historical prices for newly found
games. Same inputs must reopen the same saved result without acquisition.

Keep both teams men’s NCAA D1, Eastern date, existing final T−10 window,
unrounded EV >=4%, existing exact-line reference method, quarter Kelly against
fixed $10,000 reference bankroll, no aggregate cap/compounding, and Best/All
variants. Best deduplicates the same exact bet across venues; different lines
remain distinct. Preserve the zero-fee quoted-size assumptions. Changes to
economic policy require a separate experiment version. No real orders.

### 3. Verify the actual larger live windows

At 1:19 PM, today’s actual ledger planned:

- 2:50–2:51 PM Eastern: four NCAAB tasks, one four-member request.
- 6:50–6:51 PM Eastern: 25 tasks across sports, including 22 NCAAB, one request.

Verify the full batch for capacity, then classify men’s D1 coverage separately.
Refresh exact membership before each target; preserve legitimate reschedules,
Stop and scope changes. Do not pad task counts to recreate the forecast.

Existing observer files/scripts:
`/srv/predict/operating-evidence/d1-20261124/`.
Verified timer names:
`predict-d1-observe@capture-1450-20261124.timer` and
`predict-d1-observe@capture-1850-20261124.timer`.
They are scheduled for 2:51:10 PM and 6:51:10 PM. The slate and next-day final
observers are also armed. Verify their execution and inspect the artifacts;
armed timers are not completed evidence. If starting later, inspect retained
results first rather than repeating collection.

For each window reconcile planned, claimed, requested, returned, persisted,
omitted, refused, rescheduled and missed members. Retain stage clocks, independent
claims, shared receipt hashes, logical pulls versus physical requests, object
charges, competition, retries, holds and actual storage admission. Confirm each
valid member persisted before its existing deadline. Verify raw integrity and
that forecast measurements describe the observed batch size. A 25-event
request returning fewer events is partial evidence, even if every returned
member succeeds.

If a defect occurs, preserve the failure, identify the stage, implement the
needed repair, run proportionate regression checks and deploy through required
CI. Verify the repair on the next relevant available live load without inventing
an endless sequence of successful windows. Do not widen the window, clear
uncertain exposure or issue paid retries to make the evidence look successful.

### 4. Make the remaining coverage gaps explicit in the site

Use the existing Data and Research routes. For each date provide denominators,
as-of times and drilldowns for:

1. Expected population: source-observed eligible games, independently established
   expected population or explicit unknown, source/provider-only games, unresolved
   membership and date/schedule conflicts.
2. Captures: known in time, frozen, reconstructed, zero-offer/zero-EV, missed,
   refused, pending and absent task, with precise original reasons.
3. Markets: requested/returned event and venue/outcome/line coverage, provider
   unavailability, missing observations, pagination and unknown venue inventory.
4. References: evaluated versus excluded offers and exact causes. Reconcile the
   existing 672 exact-pair plus 874 insufficient-book Monday exclusions and report
   any evidence-backed changes separately.
5. Trade evidence: quote age, exact identity, fee and size evidence or explicit
   unknowns; quoted-size turnover remains modeled.
6. Sporting results: final, pending, conflicting or missing, separate from trade
   settlement.

Make counts reconcile within a clearly defined cohort. Do not sum overlapping
facets or call equal source/provider counts proof of equal game membership.
Source-observed eligible counts must not masquerade as a verified whole-slate
denominator. State the actual source-completeness limit and the additional
evidence needed to resolve it. Report both shares of known populations and any
unknown absolute denominator honestly.

Provide an actionable missing-item ledger: game/market/line affected, missing
evidence, consequence, cause, recoverable engineering versus external fact versus
irrecoverable historical loss versus future event, and the next concrete remedy.
Fix authorized defects instead of merely adding them to a backlog. Keep valid
prices visible when other evidence is unavailable.

### Completion and evidence boundaries

The requested live-window verification comes from this owner assignment. The
60-second rule comes from the experiment definition; four/25 tasks come from the
dated ledger. No extra numeric gate or arbitrary soak period is imposed.

Complete independent reconciliation/UI work while the existing observers wait.
The earliest complete live-verification result for both planned windows is after
the 6:50 window closes and its evidence is inspected. Do not claim that requested
part complete from fixtures or armed timers. If actual task counts change,
report the actual load qualified and the larger load still unverified.

Tomorrow’s 5:30 AM finals job has a 5:33 AM observer. Inspect it if it has run;
otherwise leave it explicitly pending. It is not a new overnight gate for the
two-date current reconciliation and today’s capture verification. The delivered
coverage UI remains reviewable throughout. Genuine source limitations and lost
historical quotes limit claims; they do not justify inventing completeness or
deferring all independent work.

Verify both dates in the signed-in production UI: current versus saved evidence,
both variants, reconciled/excluded/conflicting games, zero-EV games, a missing
capture, original receipt downloads, exports, Back and reload. Confirm saved
replays and passive reads make no hidden acquisition and submit no orders.
Run tests appropriate to changed behavior; required CI/deployment applies to
code changes. Do not rerun unchanged costly tests just to enlarge evidence.

Close out with deployed revision/CI, production links, per-date game and offer
exports, old/new run IDs and population/ticket/turnover deltas, both measured
live-window outcomes, shared quota usage, costs where known, zero orders, and
the remaining missing-item ledger. Update this assignment, the active queue
and operating record. Separate completed work, genuine external limitations,
irrecoverable history and future observations. No new source purchase, broad
redesign, probability model, annual-profitability claim or financial settlement.

## Reconciliation evidence

The read-only production comparison after the 1:30 PM slate refresh found 46
Monday occurrence rows and 87 Tuesday rows. These counts include excluded,
other-date and disputed occurrences. Both complete expected slates remain
unknown. The counted paper populations are 33 and 77 observed on-date men’s D1
games respectively. On Monday, all 33 had retained sporting finals. The Tuesday
early-afternoon observation found two finals and 75 pending in the 77-game cohort.

| Dated occurrence | Reconciliation |
| --- | --- |
| UT Martin–Temple and Stephen F. Austin–Utah Valley | Official records identify both Monday TBD slots. Their provider games were already in the counted cohort. The placeholders and their later observation times remain visible. |
| Four same-date Monday clock conflicts | Southern Utah–Arkansas State, Yale–Belmont, Colorado State–Arizona and Middle Tennessee–Southern Illinois have scheduled starts corroborated by the odds provider and official schools. The original CBBD clocks still differ by 15–25 minutes. |
| San José State–UC San Diego | Official and provider clocks agree on midnight Eastern November 24. CBBD’s Monday 11:59 PM listing survives, with one shared occurrence ID across both dates. |
| Three Tuesday clock disagreements | The school and provider schedules agree at 9 PM Eastern for Evansville–Missouri, Idaho State–Boise State and Sam Houston–Washington State. Their CBBD time-TBD evidence and official citations remain attached across revisions. |
| Stanford–Colorado | Source-only, with 11:59 PM Eastern from CBBD, 11 PM from the ACC and midnight November 25 from the schools. It remains outside the counted Tuesday cohort with a disputed Eastern date. |
| Middle Tennessee–Southern Illinois | The official school and CBBD confirm Middle Tennessee 77–76. A provider final was not retained. Sporting results remain separate from settlement. |

The [Arizona game center](https://arizonawildcats.com/game-center/31829),
[Arkansas State schedule](https://astateredwolves.com/sports/mens-basketball/schedule/2026-27?grid=true),
[Yale schedule](https://yalebulldogs.com/sports/mens-basketball/schedule/2026-27?grid=true)
and [Southern Illinois recap](https://siusalukis.com/news/2026/11/23/mens-basketball-southern-falls-to-middle-tennessee-in-77-76-heartbreaker)
were attached through the existing importer as four official observations.
The append consumed zero metered requests. Their artifact SHA-256 is
`f5dbeec0ef488dba9c3ef2a1e032b2e57413d6e1c7d79c97bc89e0a544ac7768`.
The November 24 observation time remains on the citations.

The read-only paper replay reproduced Monday’s 6,236 offers, 672 exact-pair
exclusions, 874 insufficient-book exclusions, 2,802 below 4% and 1,774
unavailable prices. The 76 Best and 114 All tickets had the same modeled
turnover. The six frozen, 20 reconstructed and seven missing paper games remain
distinct from the original six frozen, eight missed and 19 refused tasks.

The separate archived raw market census matched all 26 saved checkpoint IDs
and reproduced every offer and reference disposition. Raw and normalized rows
each accounted for 15,833 available and 5,121 explicitly unavailable
observations. The provider returned 2,035 of 2,184 requested venue/outcome cells.
The other 149 include 118 William Hill, 10 BookMaker, four BetOnline and 17
across the remaining venues. All 26 receipt clocks and scopes matched, each
event object was retained, and the returned event cursors were unfollowed.
Venue-wide market inventory remains unknown. Of the 1,546 reference
gaps, 1,095 had an unreturned exact line alone, 86 had explicit unavailability
alone and 365 had both. No gap traced to normalization or projection loss.
The 14,718 sportsbook rows rejected by the separate current-row venue
projection remained available to the frozen reference census.

| Historical coverage gap | Consequence and next remedy |
| --- | --- |
| St. Bonaventure–Appalachian State and Northern Iowa–Davidson | First retained observations arrived at 10:51:25.921 AM Eastern, after the 10:51 deadline. No qualifying price evidence can be reconstructed. Earlier upstream visibility remains unknown. Use prospective discovery evidence to distinguish feed visibility from delayed collection. |
| Georgia Southern–Northern Kentucky and Central Arkansas–North Florida at 6:50 PM, Texas A&M–Corpus Christi–Wichita State at 7:20 PM, Denver–Kansas and Stephen F. Austin–Utah Valley at 7:50 PM | All had an early baseline and no retained late claim or request. The original receipts cannot restore a price for an attempt that did not dispatch. Ordinary dispatch competed in all three windows; the retained evidence cannot assign the cause to each game. Verify the current protected lane at actual busy windows. |
| Middle Tennessee–Southern Illinois, Illinois State–Santa Clara, Fairleigh Dickinson–Iona, Winthrop–Illinois and Seattle–Loyola Chicago | All five had returned offers and zero qualifiers in both variants. Zero evidence-bearing Monday games had zero offers. This finding is bounded by the observed requests and offers. |

The 1:30 PM authenticated slate job returned the same 86 rows and same original
response hash as activation, under its own receipt. No schedule member changed.
The latest authenticated balance before that metered request was 998 of 1,000
shared CBBD/CFBD calls. The source ledger recorded three metered calls and zero
held calls after the refresh.

## Release and reproducibility

Web, collector and archive ran healthy on
`117aee7838904015fdb745b305dad799ec7d44d7` after the required
[CI and deployment](https://github.com/dock108dev/predict/actions/runs/45461235553).
PostgreSQL also reported healthy. Before and after the deploy, all seven
pre-existing dated run payloads, stored reports and route responses had
identical hashes.

The signed-in walkthrough found that the receipt route hid raw bodies from
authenticated CBBD because both acquisition paths share the same source ID.
The follow-up uses the retained HTTPS API origin and request timestamp to
identify authenticated originals. Public-export receipts remain metadata-only
in the signed-in UI. Both branches passed regression checks, including a
future parser-version change. Web, collector and archive now run healthy on
`b9c017a910bf772e5de5b39cc3c7b22979eb8d56` after the
[receipt follow-up CI and deployment](https://github.com/dock108dev/predict/actions/runs/45462944797).

The reconciled save stores each sized calculation with the existing lossless
payload codec. The prior Monday dataset projects to 1,005,590 bytes using the
new representation, down from 3,467,160 bytes. Individual ticket or dated run
downloads decode the same calculation. Detailed rejected projection rows and
line ranges are still read from their owning immutable checkpoint. The change
keeps the existing 4 MiB per-evaluation storage limit and original run exports.

The focused local release lane passed 168 portable and 15 PostgreSQL tests,
plus 30 subtests, lint, workflow validation and the secret scan. The separate
Data/Research browser and client suite passed 18 cases. Live observer results
and the signed-in evidence are tracked separately.

## First signed-in saves

| Date | Previous analysis | New analysis | Evidence and paper deltas |
| --- | --- | --- | --- |
| November 23 | `db29fca80c85b7f9c7c7ca3a4efcee7eae593513b71a73b88103d31b1186349f` | `8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796` as of 1:37:30 PM ET | Same 33, six frozen, 20 reconstructed and seven missing. The occurrence joins, scope evidence and sporting results are reconciled separately. Same 6,236 offers and exclusions, 76 Best tickets / $4,497.26 and 114 All / $5,985.33. |
| November 24 | `f86e9ad57e5ec5a545a1e4adfcb45e13bba210dbe3fbea7baf2b981f2bd13758` | `1304312ad15ed4998f492c6fd288c14a998214864af7cdc1f71000d3adac6857` as of 1:40:00 PM ET | Same 77 tracked games. Eight frozen and 69 pending, up five frozen. Offers rose from 683 to 1,919. Best rose from 8 to 22 / $569.73 to $1,479.12. All rose from 12 to 29 / $775.88 to $1,848.31. |

Both runs were saved with their ordinary signed-in Research action. A live
read-only check found the exact existing identities for both unchanged input
sets without decoding their checkpoint offers. Serialized retained payloads
were 1,045,238 and 457,286 bytes. All evidence-bearing games in both runs recorded
zero-fee mode. Tuesday’s later observations belong to subsequent run versions.

The follow-up signed-in walkthrough navigated current and saved evidence, both
original variants, the change comparison, excluded and disputed games,
zero-qualifier examples and Monday’s missing-capture case. Back and reload
preserved the selected run and the original export bytes. Monday’s and
Tuesday’s authenticated CBBD downloads reproduced the recorded raw hashes.
Public-export receipt metadata stayed accessible and both downloaded odds
responses verified their filename hashes. The walkthrough made 63 browser
API GETs with zero API or browser errors, provider acquisitions or order
submissions. It downloaded 6,236 Monday offers in 91.655 seconds and 1,919
early Tuesday offers in 35.877 seconds. The dated game ledgers contained
46 and 87 rows. Private artifacts are in
`.local/mens-d1-reconciliation-20261124/signed-in-exports/`.

## Limits on a full-coverage claim

| Missing evidence | Classification | Concrete remedy and limit |
| --- | --- | --- |
| Complete expected schedule on either date | External source limitation | Obtain an independently exhaustive dated schedule and reconcile occurrence membership across revisions. The current percentages use stated observed cohorts. |
| Stanford–Colorado’s Eastern date and odds-provider occurrence | External source limitation | Retain a corrected or authoritative dated schedule and any provider event. Until supported, keep all candidate clocks and the source-only row. |
| Seven Monday T−10 captures without a qualifying original | Historical loss | Preserve exact per-game causes above. Future protected captures and earlier observable discovery can prevent recurrence, while later prices cannot fill historical rows. |
| Full venue market inventory or candidate lines never returned | External source limitation | Inspect requested and returned event, venue and outcome cells and exact lines in the census. Obtain an independently enumerated venue inventory for an exhaustive denominator. |
| Actual fees, contract identity where absent, and executable size | External source limitation | Obtain the corresponding venue contract, account fee schedule and same-time depth. Frozen quotes and paper commitments support modeled turnover. |
| Tuesday games awaiting a captured sporting final | Future observation | Inspect the eligible finals observer when it runs. Sporting finals remain independent of venue settlement. |

The Data missing-item ledger links dated occurrences to the issue, effect,
cause, classification and remedy. The per-game market census includes missing
requested cells, exact offer lines, references, and trade-evidence gaps. The
Research view pins saved games, exclusions, tickets and receipts to the selected
version and links to the previous version for the accounting delta.

## November 24, 2:50 PM Eastern live window

At 2:49:43.746 PM the pending batch still contained all four originally planned
season-eligible men’s D1 members. Dispatch was enabled with no global Stop or
source pauses. All four were claimed and requested in one physical request.
The request dispatched at 2:50:04.535 and returned all four IDs at 2:50:05.263.
The 342,963-byte response carried a cursor. All four logical pulls verified
the same original SHA-256
`88f857b1608fd84fb82dd0fefc7adebafe4562d3b31146dcbd80799628f7875a`.

| Member | Independent persistence check after 2:50:00 |
| --- | ---: |
| TCU–Miami | 12.985 seconds |
| Appalachian State–Yale | 18.953 seconds |
| North Dakota–Detroit | 21.764 seconds |
| Maryland–Tennessee | 25.243 seconds |

A separate repeatable-read SQL snapshot at 2:50:58.910 verified all four
committed before the existing 2:51:00 deadline. Maryland–Tennessee had no
dedicated reservation and passed ordinary storage admission. Calculation took
0.631–2.496 seconds per member, projection and compression 1.031–1.665, and
SQL persistence 0.818–3.732. Forecast evidence recorded 23.592 seconds from
batch work entry to the final persistence check for the four-member batch.

The one physical request accounted for four object credits. No target member
was missing, refused, rescheduled, failed or retried. There were no competing
task claims or guarded reservations during the window, no new holds, and 99
previously interrupted objects stayed accounted. Incremental dollar cost was
unavailable. The scheduled host observer ran at 2:51:10 on healthy `b9c017a`
and completed. The raw observer, before-deadline witness and per-member details
are under `.local/mens-d1-reconciliation-live-20261124/windows/1450-*`.

At 2:52:51 PM the passive current Data read recorded 14 frozen and 63 upcoming
eligible games. The first Tuesday saved run still showed eight frozen and 69
pending, and the prior original still held three captures. Three sporting
finals were retained. This intermediate current read is a ledger witness;
the next Tuesday paper version will include the later scheduled observations.

A 4:22 PM Eastern read showed 17 frozen and 60 upcoming eligible games, with
zero misses or refusals and six sporting finals. The evening timer remained
armed and the four production roles were healthy. The independently downloaded
early offer ledgers passed their embedded digests. Their per-offer disposition
counts matched the saved exclusions and selected Best and All tickets. Both
exports reported zero acquisitions and zero orders.

At 6:24 PM Eastern, current Tuesday had 29 frozen and 48 upcoming eligible
games, with no misses or refusals and 14 retained finals. The forecast still
listed 25 tasks at 6:50, including 22 NCAAB, with two members lacking dedicated
reservations. The largest completed same-shape production sample at that
point was six members in 31.549 seconds. This forecast did not qualify the
scheduled 25-member load.

## November 24, 6:50 PM Eastern live window

The 6:49:41.695 pre-window read confirmed the original 25 pending members. All
22 NCAAB members were eligible men’s D1. The other three were two NCAAF and one
NBA. One HTTP 200 request returned all 25 event IDs at 6:50:04.417 PM. The
2,423,794-byte original verified as
`658b33ae9744f80f0550daab380bc3a1322b3ba76ba2f472d975b95029e9fa08`,
with 25 logical pulls and 25 confirmed object credits.

Only 14 independent checkpoints published, including 12 of 22 men’s D1.
The final successful persistence check was +55.922 seconds. Separate SQL
reads at 6:50:57.708 and 6:50:59.092 both saw exactly 14 committed. The
observer confirmed 11 terminal misses. Gardner-Webb–Bowling Green entered
calculation at +55.958, finished projection at +58.903, and hit the in-transaction
deadline check at +60.128. Its failed write rolled back. Ten other members,
including the NBA game, reached the deadline before member processing started.
All eleven failure attempts were retained. Both NCAAF members without a
dedicated reservation passed admission and published. There were zero provider
omissions, storage refusals, repeated requests or new uncertain exposures.
The 99 previously interrupted objects remained accounted. The scheduled
observer ran on healthy `b9c017a`. Per-member disposition, original URL,
physical ledger and two SQL visibility checks are in `windows/1850-*` under
`.local/mens-d1-reconciliation-live-20261124/`.

The 14 successful members spent 9.857 seconds on calculation, 14.154 on
projection/encoding, 22.508 from projection-ready to checkpoint-recorded, and
3.039 from record to full persistence check. This located the bottleneck in
serial per-member work. A settled read-only sample put median storage-accounting
queries at 19.1 ms and median database-size reads at 14.3 ms. All existing
admission and existing deadline checks were retained.

The packing repair reuses shared event/fee inputs, full-offer hashes and
canonical JSON buffers. All 25 retained event inputs reproduced identical
packed roots, blobs, compact board rows, allocation sizes and original
digests. A disposable PostgreSQL replay of the same 25 events with retimed
schedules and identical simulated network timings took 18.265 seconds before
the change and 15.643 after it. The fixtures both completed all 25 and used
zero real provider requests. The original production result remains 14/25.
Post-repair live evidence will establish the actual next load.

### Evening source and paper revision

The authenticated 6:30 PM CBBD revision still returned 86 rows. Three previously
aligned rows changed clocks. FIU and Michigan corroborate the provider’s 3:30
and 5:30 PM scheduled starts for Arkansas State–Long Beach State and
Michigan–Creighton. Duquesne and High Point publish 7:30 and 8:15 PM,
respectively, so their start discrepancy remains explicit. Four official
observations were attached with zero metered calls. The late provider also
added Arkansas Baptist–Little Rock. Arkansas Baptist’s season record supports
NAIA exclusion, leaving the counted D1 cohort at 77.

The [first post-window paper run](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-24&run=da643a482e46a345ff32f1c36c52eda990986f593a41bef86b0dd30560248100)
was saved through signed-in Research as of 6:51:46 PM, following `1304312a`.
It retains 41 frozen, ten missed and 26 pending eligible games, with 10,117
offers, 3,384 withdrawals, 1,043 exact-pair exclusions, 1,043 insufficient-book
exclusions, 4,471 below the screen, 128 Best and 176 All tickets. Its original
live misses remain in this immutable run. The normal dated offer download then
returned proxy HTTP 524 at about 120 seconds. The failure was retained and the
route repair is tracked separately from the capture bottleneck.

All ten missed D1 games had an exactly bound, hash-verified original in-window
response, which allows explicit retrospective reconstruction. The eleven task
failures and live capture pointers remain immutable. At 6:51:50 the shared
CBBD/CFBD `/info` balance was 996 of 1,000. Four metered source calls were
confirmed with zero held or unconfirmed calls. Incremental per-window dollar
charges remain unavailable. Engineering submitted zero orders.

Recovery appended ten scoped checkpoints between 7:04:15 and 7:04:27 PM
through the exact original receipt only. A before/after comparison verified
that all 25 original task states, attempt IDs and live checkpoint pointers
were identical. The replays label the appended evidence reconstructed and
carry its actual write clock, with zero new source calls. The fourth metered
CBBD call was the existing 6:30 PM scheduled refresh.

The checkpoint repair passed
[required CI](https://github.com/dock108dev/predict/actions/runs/45514491690).
The streamed attachment followed on healthy `76dfb12` through
[required CI](https://github.com/dock108dev/predict/actions/runs/45514836072).
The production download for the same frozen `da643a48` run began in 0.792
seconds and finished in 127.698 seconds. All 7,673,766 bytes and 10,117 offer
rows verified against its canonical evidence digest. The previous 524 and
the completed attachment are retained separately. The earliest subsequent
capacity observation that meaningfully stresses the changed path is the
scheduled 7:50 PM batch. The 7:20 PM turn supplies an earlier live smoke check.

The [recovery-only paper run](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-24&run=b67c64041c838369100325c51e9b9da114913fdd6cbf109ca871ceae55ce56f7)
supersedes `da643a48`. It keeps 77 eligible games, 41 original frozen and 26
pending. The ten original misses are shown as ten paper reconstructions, and
offer evidence rises by 2,535 to 12,652. Best moves from 128 tickets and
$8,552.82 to 178 and $11,975.20. All moves from 176 and $10,826.77 to 257
and $15,551.33. The recorded report hash and per-cause differences are in
`.local/mens-d1-reconciliation-20261124/signed-in-recovered-tuesday-comparison.json`.

The installed deduplication follow-up `590a028` passed
[required CI](https://github.com/dock108dev/predict/actions/runs/45515797394).
The 7:11 PM production read found one excluded Arkansas Baptist–Little Rock
occurrence with its provider ID and all four source records. The earlier
ledger temporarily showed the same game twice because the provider’s Little
Rock alias and the source’s non-D1 membership record used different identity
witnesses. The dated union returned to 87, with 77 eligible. All seven
pre-existing stored and route hashes still matched on the installed release.

### November 24, 7:20 PM Eastern repair smoke

All four season-eligible NCAAB tasks were claimed, requested, returned and
published on the installed `590a028` revision. The one paid request returned
299,471 verified original bytes and consumed four object credits. All four
logical pulls shared receipt `752997a2ac0d13f29ff570cfcb9ffa81be4ac3e988aa91268653f525df7b6c1e`.
The last persistence check was +11.442 seconds. An independent SQL read at
7:20:54.576 PM saw all four committed before deadline. The collector recorded
zero omissions, retries, competition, refusals or new holds. Details are in
`windows/1920-*`. The next larger live check remains the scheduled 7:50 turn.

### November 24, 7:50 PM Eastern repair verification

The 7:49:40.390 PM read confirmed 14 actual members, including 11 eligible
men’s D1, one excluded NCAAB and two other sports. All 14 were claimed,
requested, returned and independently published on `590a028`. The one paid
request charged 14 objects and returned 1,181,416 verified bytes shared by
14 logical pulls. The original SHA-256 was
`299334bb1175bf7671d817e432b4b7c8b601b7f8b054808b6dafda3f38ed37e6`.

The last persistence check was +39.308 seconds. A separate SQL read at
7:50:55.654 PM saw all 14 committed before deadline. Five members, including
four eligible D1, passed admission without dedicated reservations. Forecast
recorded a 38.999-second service sample for 14 members. No member was
omitted, refused, rescheduled, retried or missed. There were no competing
requests or claims and no fresh uncertain exposure. The historical 99
interrupted objects remained accounted. Exact stage clocks, activity and
accounting are in `windows/1950-*`.

The two requested windows consumed 29 SGO objects in two physical requests.
The two actual post-repair windows consumed 18 in two physical requests.
All 47 are confirmed. Incremental dollars are unavailable. The 7:50 result
qualifies the repaired 14-member live load. The original 25-member window
remains 14/25, and repaired 25-member production capacity remains unmeasured.
The November 25 finals job and its 5:33 AM Eastern observer remain pending.

## Final Tuesday paper revision and dated exports

The final signed-in save `e54dd0c2f192c3cb7b447b469729e9372a8a751d8447cbb34256c1ce72b291ba`
pins evidence to November 24 at 7:51:35 PM Eastern and supersedes `b67c6404`.
Its report revision is
`3c4d43cb4cf0091db45d9bbacedcd3de9ca34710595e068a5e20ffbe81b4ad35`.
The post-repair windows account for all 15 added original frozen D1 games
since the recovery-only version. Four are from 7:20 and eleven from 7:50.
An unchanged-input production check reopened the exact final run ID.

| Tuesday run | Original frozen | Reconstructed | Missed in paper | Pending | Offers | Best tickets and modeled turnover | All tickets and modeled turnover |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `f86e9ad5` original | 3 | 0 | 0 | 74 | 683 | 8 / $569.73 | 12 / $775.88 |
| `1304312a` early | 8 | 0 | 0 | 69 | 1,919 | 22 / $1,479.12 | 29 / $1,848.31 |
| `da643a48` post-failure | 41 | 0 | 10 | 26 | 10,117 | 128 / $8,552.82 | 176 / $10,826.77 |
| `b67c6404` recovery only | 41 | 10 | 0 | 26 | 12,652 | 178 / $11,975.20 | 257 / $15,551.33 |
| `e54dd0c2` final | 56 | 10 | 0 | 11 | 16,018 | 228 / $15,241.46 | 331 / $19,633.54 |

The 16,018 offer rows comprise 5,531 withdrawals, 1,521 exact-pair exclusions,
1,482 insufficient-book exclusions, 7,153 below 4%, and 331 All venues tickets.
The original live ledger still counts ten missed. The saved analysis represents
their observed prices as reconstructed evidence only. All 66 games with paper
evidence had offers, and six had zero qualifiers. Among the 63 games with
countable request cells, 4,856 of 5,292 cells were returned. Exhaustive venue
inventory and three checkpoint retrieval states remain unknown. All 331 All
venues tickets have known quote ages. Actual fees and executable size remain
unverified. The paper policy is unchanged at unrounded 4% EV, existing exact
lines, quarter Kelly on a fixed $10,000, and no aggregate cap or compounding.

At 7:56:15 PM Eastern the dated Data export still had 87 union occurrences,
77 counted eligible games, 56 live frozen, ten live misses and 11 upcoming.
The independent sporting ledger had 17 finals and 60 pending. The schedule
and results receipt hashes from all four authenticated CBBD revisions verified
on the final installed source route. The 6:30 PM slate revision retained hash
`c40df56b43949e727cf0ba5f16a072f95c6c3cd5bc7b072705522d7764ae178d`.

- [November 23 signed-in Data](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-23&run=8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796) · [Game export](https://predict.dock108.dev/api/workspace/mens-d1?date=2026-11-23&run=8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796&export=1) · [Offer export](https://predict.dock108.dev/api/research/workspace/runs/8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796/offers)
- [November 24 signed-in Data](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-24&run=e54dd0c2f192c3cb7b447b469729e9372a8a751d8447cbb34256c1ce72b291ba) · [Game export](https://predict.dock108.dev/api/workspace/mens-d1?date=2026-11-24&run=e54dd0c2f192c3cb7b447b469729e9372a8a751d8447cbb34256c1ce72b291ba&export=1) · [Offer export](https://predict.dock108.dev/api/research/workspace/runs/e54dd0c2f192c3cb7b447b469729e9372a8a751d8447cbb34256c1ce72b291ba/offers)

The final signed-in attachment started in 0.522 seconds and completed all
12,149,840 bytes in approximately 219 seconds. Its canonical evidence SHA-256 is
`c217a4949b7ee863b5cbefbd1d6c7f55633bde48930936b31a423fa497c13df0`.
The exact report payload hash matched before and after reload. Back restored
the selected variant from its predecessor. The browser verification made one
explicit paper-save POST and 228 API GETs, with zero API or browser errors.
It did not dispatch a provider request or submit an order. A separate offline
audit of the delivered Monday and final Tuesday JSONs reconciled each offer
and ticket count and verified quote-age inputs for all selected tickets.
None of those tickets included a native venue contract ID. Artifacts are in
`.local/mens-d1-reconciliation-20261124/signed-in-exports-final/` and
`.local/mens-d1-reconciliation-live-20261124/final-offer-audit.ndjson`.

Review decision: Actual scheduled-window evidence | Owner required both original windows and the next relevant live load after a repair | Inspected both original windows and verified the repaired 14-member batch; the 25-member capacity and next-day finals remain separate observations.
