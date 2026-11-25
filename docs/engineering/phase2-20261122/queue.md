# Phase 2 completion and deferred backlog

## Delivered: Win $10 and Kelly in the Workbench beta

Signed-in create, review, save, replay, revise and results verification passed
on production revision `8073f25`. The saved November 23–29 experiment is
running with independent Win $10 and Kelly views. November 23 is graded,
November 24 is partially graded, November 25 is collecting and November
26–29 are scheduled. Both historical sizing modes reconcile across trades,
daily and weekly totals, and exports. This release completes the Workbench
and fixed-profit implementation entries below.
[Closeout and production links](../workbench-win10-beta-closeout-20261125.md) ·
[Required release CI](https://github.com/dock108dev/predict/actions/runs/45552224802)

## Active assignment: Workbench + Win $10 + Kelly comparison

**Owner's highest priority:** reusable creation directly in Experiments. The
normal Create → configure dates/sizing/optional comparison/EV → Save and run
flow must drive replay, scheduling and results without engineering intervention.
A one-off backfill or backend-only feature is insufficient; prove a second
independent configuration through the same UI before calling this complete.

The [consolidated owner assignment](../workbench-win10-beta-20261124.md) governs
the ongoing beta work: unbranded flat-trade Workbench, UI-configurable Win $10
with a November 23–29 replay and 1/40 Kelly comparison on shared evidence,
automatic daily/weekly operation/results, explicit target rounding and complete
information/evidence. Build on committed Workbench revision `f9b86c4` and verify
both modes through the signed-in production UI. Validate their newly calculated
results against the retained inputs. Historical result preservation is outside
release acceptance.

## Owner amendment: Win $10 sizing for a new experiment version

Add [fixed-profit sizing](../fixed-profit-sizing-amendment-20261124.md) to the
Workbench beta assignment. The owner wants each winning paper bet to target
$10 profit, with stake based on the odds and losses equal to committed stake.
Publish a November 23–29 definition with UI configuration, explicit fee/grid
rounding and automatic replays/results. Calculate the Kelly comparison using
the same retained evidence.
Implementation is pending; the lead's ongoing Workbench source edits remain intact.

## Delivered: unbranded Workbench presentation

Revision `b404e97` installs the unbranded Research, Data and Settings shell,
flat daily trade ledger, selected-trade inspector and retained game coverage.
The November 23–29 Kelly campaign continues on its existing definition.
The closeout records signed-in checks, pinned exports, immutable populations and
the final deployment. [Workbench closeout](../predict-first-beta-closeout-20261124.md#workbench-release) ·
[Required release CI](https://github.com/dock108dev/predict/actions/runs/45548444638)

## Delivered: first research beta with the experiment running

The [beta closeout](../predict-first-beta-closeout-20261124.md) records application
revision `825cf29`, migrations 122/123, passing required CI, signed-in production
verification and the restarted campaign's automatic grade. Local HEAD `348675f`
is a documentation follow-up. The original assignment below is retained as
history; the Workbench presentation is the next selected implementation.

The owner requested the [first-beta lead assignment](../predict-first-beta-20261124.md):
implement the audited November 23 fixes, reusable issue resolution in the UI,
derived census summaries and provenance/freshness comparisons; deploy and
verify the private beta with the existing November 23–29 paper campaign running.
Finish engineering before owner review. Future dates remain in progress;
Sunday's finals must continue through the November 30 collection and corrections.
Accept supported historical/source limitations without altering frozen runs or
claiming complete captures. This entry assigns work; implementation is pending.

## Planned: November 23 data resolution and issue closure

The owner requested an audit and resolution plan, including accepted gaps,
exclusions and legitimately unavailable lines. The
[November 23 plan](../nov23-data-resolution-plan-20261124.md) records the
10:21 PM Eastern read-only production audit and all 46 proposed occurrence
dispositions. No application or production data changed for this audit.
Next implementation: fix on-date scope counters and stale market summaries,
separate original capture failure from usable reconstructed evidence, and add
versioned issue closure through the UI. Preserve seven historical T−10 gaps,
method-ineligible reference offers and bounded venue-inventory limitations.
Follow with separately versioned quote-freshness analysis and prospective
capture verification; no-line conclusions require affirmative scoped evidence.

## Deployed: November 23–29 daily and weekly paper experiment

The [daily/weekly implementation and operating record](../ncaab-daily-weekly-20261124.md)
is deployed on `3743a873012ed5676b5cb35d1e59a385935207ba` with required CI
passing. The owner-facing UI created the actual men’s D1 schedule for November
23–29, using 1/40 full Kelly, 4% minimum EV, both paper portfolios and continuous
4/8/15/25% EV boundaries. Date range, sizing and EV analysis are configurable
without CLI; changes create a new immutable version. November 23/24 published
automatically, and November 25–29 are scheduled. Daily → game → trade → weekly
navigation and the exact weekly export passed on production. All 12 original
saved run hashes remain intact. November 23 selected tickets are fully graded;
November 24 results remain partial. Future operating turns and historical
full-slate/market coverage remain unproven; scheduling does not close those gaps.

## Deployed: automatic experiment results

The owner requires [automatic prior-day results and game/trade reports](../automatic-experiment-results-plan-20261124.md)
for all paper-trading experiments, rather than a one-off November 23 grading
screen. Retained score revisions should enqueue deterministic grading for every
dependent saved run; new runs should grade against already-retained results.
Version grades separately from frozen opportunity selections, and show the
day → game → trade result flow by default without a manual replay.

The shared worker and signed-in day/game/trade flow are deployed on
`3e85b6a6e9dd4a4335b8c539717ab51804a9107d`.
[Required CI](https://github.com/dock108dev/predict/actions/runs/45532782516/attempts/2)
passed after guarded backup and migration. The production worker published all
12 saved runs and the original hashes matched. The November 23 review graded
76 Best and 114 All tickets across 33 retained finals, with seven historical
missing captures visible. Back, reload, versioned exports, and the frozen trade
calculation and original receipts passed on production. The next operating
observation is the November 25 5:30 AM Eastern prior-day collection.

## Men’s D1 reconciliation and live-window verification

The [lead assignment](../mens-d1-reconciliation-live-windows-20261124.md)
uses the newly authenticated CBBD results and slate to reconcile November 23/24,
save separate current analyses, verify the 2:50 PM four-task and 6:50 PM
25-task capture outcomes, and expose the exact remaining full-coverage gaps.
Preparation made read-only production checks and documentation updates only.

The reconciliation, original downloads and follow-up repairs are installed on
`590a028` after [required CI](https://github.com/dock108dev/predict/actions/runs/45515797394).
Production has separate current-evidence and saved-version navigation, dated
game and offer exports, and a missing-item ledger. The first two signed-in
saves are versioned and the earlier hashes still match. The occurrence ledger
counts 33 eligible Monday and 77 eligible Tuesday games, with both complete
denominators unknown. The Tuesday source-only Stanford–Colorado game remains
date-disputed. See the lead assignment for the current live-check state.

The 2:50 PM Eastern observer verified all four planned men’s D1 members in
one physical request. All four returned and were visible in SQL before the
existing deadline, with four confirmed object credits and no retry. The
last persistence check was at +25.243 seconds. The independent 6:50 PM
cross-sport batch returned all 25 in one request and published 14 before
deadline. It published 12 of 22 eligible D1 checkpoints. The 11 misses remain
in the original ledger while an exact-receipt recovery appends separate paper
evidence for ten D1 games. The repaired runtime published four of four at
7:20 PM and 14 of 14 at 7:50 PM, including 11 of 11 eligible D1 at 7:50.
Independent SQL saw each before deadline. Repaired 25-member production
capacity remains unmeasured. The final signed-in Tuesday run `e54dd0c2`
contains 56 frozen, ten reconstructed and 11 pending of 77 eligible games.
Its dated game export and 16,018-offer download verified. The remaining work
is tied to future capture and finals observations, source coverage and the
next naturally comparable 25-member production load. See the lead assignment
for the evidence ledger, exports and exact limits.

At 1:19 PM Eastern, CBBD remained active. Monday had 32 source-eligible rows,
27 exact provider matches and five schedule conflicts, versus 33 provider-known
eligible games. Tuesday had 77 source-eligible rows, 73 matches, three schedule
conflicts and one source-only row, versus 77 provider-known eligible games.
Both complete expected populations remained unknown. Current Tuesday had six
eligible frozen captures and 71 upcoming; its original saved snapshot still
had three. Both larger batch sizes remained unmeasured in production.

The existing capture observers were confirmed armed for 2:51:10 and 6:51:10 PM
Eastern. Their actual evidence, rather than another controlled replay, is the
required next live check. Tomorrow's finals observation is pending rather than
an additional overnight completion gate for this milestone.

## CBBD source activated, November 24 at 1:14 PM Eastern

The owner supplied an authorized shared CBBD/CFBD credential. It is installed
in the collector's protected secret mount; the temporary local copy was removed.
The live `/info` check verified the shared monthly allowance. The source is now
active, with no application code change or service restart.

The scheduled November 23 `results_corrections` job succeeded at 1:13 PM.
A one-time November 24 `schedule_activation` job succeeded at 1:14 PM through
the normal guarded scheduler, leaving recurring jobs unchanged. Retained
responses contain 47 Monday rows (32 eligible, 13 excluded, 2 unresolved) and
86 Tuesday rows (77 eligible, 9 excluded). Both original hashes verified.
The source ledger records two metered calls, no held/unknown dispatches and no
retries. Complete expected-slate coverage and larger live capture capacity
remain unverified; neither is implied by credential activation.

## Men’s D1 operating loop deployed

Web, collector and archive run
`3da369b5cdeaf34d50e8c784b3133af99cb69e38` after
[required CI and deployment](https://github.com/dock108dev/predict/actions/runs/45451724362).
The signed-in Data, Research and Settings walkthrough passed. The delivered
coverage slice remains reviewable.

- The controlled four- and 25-task clusters both completed within the existing
  60-second window using one physical request each. In the pinned serial
  baseline, 22 of 25 completed. Independent claims, original receipts and
  account and storage guards remain in effect.
- The 12:50 PM Eastern live batch persisted both games by +8.920 seconds
  with one request and two object credits. The 2:50 and 6:50 PM windows
  still need their own measured outcomes. Persistent, read-only observers cover the capture
  windows and the next slate and prior-day finals turns.
- Recurring CollegeBasketballData collection is wired into the existing
  scheduler. Production is disabled until an authorized existing key is
  available and its allowance check passes. The complete expected slate
  remains unknown. Sports Reference remains disabled.

The [assignment and operating record](../mens-d1-coverage-completion-20261124.md#operating-loop-continuation)
has stage timings, account evidence and result boundaries.

## Next continuation: capture throughput and recurring slate ingestion

This section preserves the state at the start of the operating-loop assignment.

The deployed coverage slice is available for owner review. A November 24
12:28 PM Eastern read-only server check still forecasts 4 tasks at 2:50 PM
(74.804 seconds of serial p95 service against the existing 60-second window),
and 25 tasks at 6:50 PM (22 NCAAB, 467.523 seconds). These are conservative
success-history estimates, not observed future misses. One and two tasks,
respectively, lack dedicated storage reservations; fresh admission may still
be possible under existing headroom and guards.

Next engineering should address the full serial claim/acquisition/calculation/
persistence path and establish recurring permitted slate/results ingestion.
Public CBBD receipts currently supply retrospective evidence; the scheduled
Sports Reference path remains disabled. No further accounting/UI expansion is
required to review the delivered slice. See the continuation scope and stopping
conditions at the end of the [assignment](../mens-d1-coverage-completion-20261124.md).

## Men’s D1 coverage slice deployed

The [coverage assignment and operating record](../mens-d1-coverage-completion-20261124.md)
contains the source, capture, market, reference and trade-evidence reconciliation.
The source and capture views separate current evidence from the immutable
November 23 corrected run and November 24 saved snapshot. Production runs
`b25586946517674a49d1ee631d3a282e02f50abb` on the three application roles after
the [passing release retry](https://github.com/dock108dev/predict/actions/runs/45445919672/attempts/2).

CollegeBasketballData supplies dated source evidence for 32 and 77 eligible
rows, with one official Eastern date discrepancy on each date. Both complete
expected-slate denominators remain unknown. Sports Reference remains disabled
pending source permission and configured Firecrawl access. Recurring ingestion
requires an active, authorized source. Venue-wide market inventory and actual
executable size remain unverified. The collector exposes its remaining
serial-capacity risk for the 6:50 PM Eastern cluster in Settings.

The November 24 12:20 PM window froze both games on the first attempt with
two scheduled SportsGameOdds requests, two confirmed object credits, and no
competing dispatches. At 12:21 PM the current Tuesday view had five frozen
and 72 upcoming provider-known eligible games. The saved snapshot still
has three frozen and 74 pending. The dated exports, immutable replay
witnesses and raw receipt hashes are recorded in the assignment.

- [November 23 coverage and output](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-23)
- [November 24 coverage and output](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-24)
- [Collector status and deadline forecast](https://predict.dock108.dev/settings#mens-d1-jobs)

### Historical 11:41 AM handoff baseline

The [five-priority implementation assignment](../mens-d1-coverage-completion-20261124.md)
was ready for engineering at this checkpoint. A read-only production refresh on November 24 at
11:41 AM Eastern confirms 33 eligible provider-known Monday games: 6 frozen,
20 reconstructed and 7 missing. Tuesday remains 77 eligible, 3 frozen and 74
pending. Neither date has an independently verified expected slate.

Corrected Monday scope has **26 evidence-bearing games** and **1,546 offers
lacking required reference evidence** (672 exact-pair gaps and 874 two-book
gaps), replacing the older 27 / 1,547 counts. Market completeness is unproven
for all 26; the existing false flag is conservative, rather than proof of
missing markets. Next work covers expected population, capture reliability,
returned markets, references and usable quote/fee/size evidence together.
Source activation must not hold up independent capture and accounting fixes.

This refresh changed planning documents only. Local main is `1431897`, with
[passing CI](https://github.com/dock108dev/predict/actions/runs/45435387664);
installed app roles remain healthy on `c75ffcd`. Sports Reference remains
disabled with zero Firecrawl requests, charges or holds. Current research
unreserved headroom is 364,754,617 bytes (347.9 MiB). The prior implementation
and its 11:09 AM observation below remain historical evidence.

## Active follow-on: men’s D1 daily coverage

The November 24, 2026 [implementation assignment](../mens-d1-daily-coverage-20261124.md)
starts from main `4cc9f745c193b3ef03a2fac1a589f510f1a4a566` and the deployed
Research workspace. The collector schedules daily imports and the Data view
accounts for retained games, captures, and results by date. The feature shipped
in `0e26f88bac69f0e7984a2dbeba46712a0ce3e9db` through
[main CI](https://github.com/dock108dev/predict/actions/runs/45432360098/attempts/2).
The installed follow-up is `c75ffcd52707699a7615decea903feadf799f376`
([release CI](https://github.com/dock108dev/predict/actions/runs/45434711197)).
The signed-in walkthrough verified the stored evidence, date selection,
variant selection, exports, reload, and the next scheduled job in Settings.

At 11:09 AM Eastern on November 24, retained evidence showed 33 eligible games
on November 23 (6 frozen, 20 reconstructed and 7 missing) and 77 on November 24
(3 frozen and 74 pending). November 23's corrected run contains 76 Best and
114 All venues tickets. November 24's retained snapshot contains 8 and 12.
Middle Tennessee–Southern Illinois is the eligible November 23 game with no
retained provider final, though Southern Illinois independently reported the
result. The assignment records dates, excluded and missed games, setup, and
verification. Local evidence includes a 115-row game reconciliation and signed-in
screenshots under `.local/mens-d1-20261124`.

- [November 23 in Data](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-23)
- [November 24 in Data](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-24)

Sports Reference ingestion is disabled pending permission for private hosted
use and verified Firecrawl account/access. Both dates' source-declared
denominators and cross-source matches remain open. Firecrawl recorded zero
requests, credits and incremental cost.

The phase 2 completion entries below are historical. Their former landing-page
and 128 MiB allocation observations do not override the current Research landing
page or the current 512 MiB research allocation. The broader model-comparison
backlog remains deferred beyond the inventory/result work explicitly assigned.

## Historical phase 2 completion

Phase 2 engineering, integration and engineer-led verification are complete.
The historical phase 2 deployed baseline was `6ed321157bb44dd98833deeaf246a371940477b8`.
All six foundation phases and the subsequent checkpoint experiment,
credit-saving acquisition policy and private-beta CI/CD are installed.

## Personal data workspace assignment

The [implementation handoff](../personal-data-workspace-handoff.md) is implemented
and installed from `b449e79` in this checkout. Final routes are `/data` (home),
`/experiments` and `/settings`; the [operating guide](../../personal-data-workspace.md)
describes game/capture/exact-bet navigation and legacy-link compatibility.
Trading results cover prediction markets against sportsbook references and
other prediction markets. Sportsbooks remain received reference-price evidence;
book-to-market and sportsbook-to-sportsbook result views are excluded.
Local verification, required CI/deployment and installed owner evidence are
recorded separately below. Phase 2 remains complete.

### Workspace completion and fresh start

Application commit [b4ef1f6](https://github.com/dock108dev/predict/commit/b4ef1f6f8f4b2b716e6002c9ca09cb9177637b83)
is installed. The required [CI/deploy run 45104792325](https://github.com/dock108dev/predict/actions/runs/45104792325)
succeeded on [e9bbf92](https://github.com/dock108dev/predict/commit/e9bbf9224b42eef6fcd4da07ad36fe64b0d3c928)
in 103 seconds, including replacement of all three application roles and health
of all four configured services. The first run passed its required checks but
refused SSH handoff when its remaining rollout allowance was 0.3 seconds short;
the retained failure is [45104365121](https://github.com/dock108dev/predict/actions/runs/45104365121).
Portable and PostgreSQL validation now run concurrently after baseline checks;
every required result is still joined and gated. The complete local change
selection passes in 16.1 seconds under that implementation (portable 7.6 seconds
and PostgreSQL 12.5 seconds overlap).

Before the owner-authorized reset, the actual installed UAB–Rhode Island journey
covered main/alternate lines, the Kalshi home −2.5 source price of −107, explicit
current-calculation unavailability, both frozen negative checkpoints, complete
export, Back/reload context and incomplete future capture. Its complete export
reproduced 6,157 immutable records and 34 numeric screening results at each of two
checkpoints offline. Native Chrome at retained 150% confirmed exact inspection
and download with remembered login; an isolated browser through the existing
private SSH access completed Back/reload, Settings and functional legacy-link
checks without interfering with the owner's Chrome activity. API reads reported
zero provider requests; scheduled acquisition remained independently owned.
Four browser journey fixtures, 23 existing control tests plus two subtests,
affected data/math/collection/SQL checks and focused CI failure/join tests pass.

The owner's later direction authorized a fresh observed-data population.
After verified matching server/Mac database and protected-state backups, the
active/public, retained and cohort market/research tables were cleared in one
explicit transaction without CASCADE. Source-only files were quarantined
recoverably. Seven protected SQL table signatures and 1,178 protected file
signatures were unchanged across the reset. Journal, account/quota/reservation/
hold/exposure state, settings, source Stop/pauses, scheduled-slot history,
provider credentials, migration hashes and both owner-login files were preserved.
The same reset transaction had first passed a rollback rehearsal on the private
snapshot. The restarted services are healthy; archive capture, mount and identity
were verified under the existing archive environment.

Fresh installed observation: November 22, 2026, about 10:33 PM Eastern. Data and
Experiments each show zero games; the new immutable policy requests ten selected
sportsbook references plus four supported trading markets, solely through SGO.
The unchanged 128 MiB research cap has 134,208,348 unreserved bytes after initial
metadata. Next discovery is 10:50 PM Eastern under the preserved :20/:50 schedule.
There is no fabricated fresh T−10 pair or outcome; new evidence follows its
ordinary schedule. Old screenshots/exports prove the pre-reset journey and are
not current-population claims. Detailed private evidence and backup manifests
are under `.local/personal-workspace-20261122/`.

The [NCAAB model and game-log backlog](../ncaab-model-research-backlog.md) is
deferred planning, not an active implementation or unfinished phase 2 requirement.
It does not enable new feeds, backfills, subscriptions or runtime changes.

## Completed operating state

- Discovery runs :20/:50 each hour, 24/7 Eastern, only when its durable slot is due.
- One full initial snapshot within 24 hours of start is followed by scheduled
  T−10 capture; first observation is not necessarily T−24h. No separate saved-game
  alternate refreshes or repeated Live polling remain. Discovery still bills
  returned known games. Bounded postgame checks remain enabled.
- Research/details/plots/export and historical Live inspection work; default
  EV/Arbitrage reads use Monitor. Browser reads are passive.
- All four services are healthy; the final installed observation confirms 115
  migration hashes, matching role fingerprints, preserved Stop/pauses and
  86 interrupted ledger rows representing 94 account objects. Five valid
  distinct checkpoint pairs were retained at that observation.

[Required CI/deployment run 45093123941](https://github.com/dock108dev/predict/actions/runs/45093123941)
succeeded on `6ed3211` in **102 seconds** for the complete job, including actual
web/collector/archive replacement. It supersedes the earlier 73-second reused-image
run as changed-role timing evidence. Setup plus focused validation fell from 36
to 17 seconds using the same hash-locked dependencies through uv.

Normal CI is one main-only job with a two-minute timeout, focused data/math/
collection/deployment checks, source-identified role images, private proxy
validation, pinned manifests, current-main and installed-health checks. Broad
regression/public-user journeys and disposable Compose rehearsal are manual-only;
removal-only tests are not routine requirements. Old tests/workflows are preserved
in Git and a verified private 803-file archive. Pending schema changes require
the explicit backup/migration maintenance path before normal fast deployment.
See [CI](../../CI.md) and [server operations](../../hetzner.md).

The installed evidence is dated November 22, 2026, 8:13:50 PM Eastern and retained
privately at `.local/ev-experiment-20261122/final-discovery-installed-6ed-check.json`.
Its 10,225,788 unreserved research bytes (about 10.2 MB) are under the unchanged
128 MiB logical cap, separate from roughly 21.2 GB physical free disk. Counters
are dated observations, not a guarantee of continuous future coverage. No cap
increase or automatic eviction follows from compression or server cleanup.

Model accuracy/calibration, comprehensive NCAAB game logs, executable liquidity
and profit remain unproven research topics. Pending sporting outcomes, refused
or missed captures and finite retention stay visible; they do not reopen the
completed engineering milestone. Pacers–Knicks remains explicitly missed.

## Historical implementation sequence

The checkpoint descriptions below preserve the earlier integration sequence.
Their pending deployment/CI wording is historical; the completion above governs.

The assignment was the first-observation versus T−10 EV experiment.
The latest owner steering keeps 24/7 :20/:50 discovery while removing separate
saved-game refreshes until T−10. The owner explicitly accepts that league
discovery still bills returned known games; it cannot exclude arbitrary saved
IDs. First full snapshots and bounded sporting-result follow-up remain.
The phase 2 foundation below is completed historical implementation evidence.
Current policy and operating details are in `docs/ev-checkpoint-experiment.md`.

| Historical checkpoint | State at that stage | Evidence tracked |
| --- | --- | --- |
| Versioned policy and scheduling transition | Integrated and installed, migration 115 | Immutable activation, old history preserved, primary scheduler replaced |
| Guarded early/late acquisition and coverage | Deployed; Magic–Wizards and UAB completed both scheduled checkpoints | Actual nine-book full-alternate request/receipt/persistence clocks, explicit timing/completeness caveats |
| Exact identity, sign selection and cross-reference math | Integrated; real exports reproduce offline | Independent branches, unavailable and chronology cases; final focused checks include 37 PostgreSQL tests and 32 portable tests plus 10 subtests |
| Comparison, source context, observed plots and exports | Installed native 150% and mobile checks passed | Complete native-click export and offline reproduction of both real snapshots |
| Scheduled operation, outcomes, storage and deployment | Corrective product revision `a8a482f` deployed; required hosted CI tracked on final integration revision | Both live pairs retained; append-only Pittsburgh baseline correction verified; lossless encoding reduces measured pair by 84.7%; no cap raise or historical rewrite |

Deployment run `45088113403` installed `a8a482f` through the existing workflow.
All 115 migration hashes match. The stale asset-delivery assertion from initial
CI `45084819231` was reproduced and corrected: each Research script must call
its own endpoint; all existing delivery checks remain. Its focused suite passes
eight tests and four subtests. The coordinated personal-server CI/CD change
follows the owner's newer two-minute normal-release direction: focused required
checks and deployment, with full regression assurance reported separately. The
combined final-main GitHub check is the source for hosted completion, separate
from installed proof. The final summary query counts only valid distinct
checkpoint pairs; aliases, missed tasks and superseded schedules cannot inflate
completion or measured runway.

The research allocation remains finite. Legacy evidence and existing late
reservations nearly fill 128 MiB; the compact format reduces future writes but
does not reclaim prior rows. Capacity refusals are reported and are not retried
with later observations. Export preserves every retained game revision and its
dependencies. There is no new cap, eviction, service or profitability gate.

The live stopping condition comes from the owner's explicit two-checkpoint
verification request. No positive cases, minimum early lead time, completed game
outcome, or extra observation duration is added. The late tolerance and postgame
attempt limits are versioned engineering policies, not review gates.

Owner direction: November 22, 2026 pasted assignment. This is the completion
record for that implementation. The audit and implementation proposal are dated starting
evidence, not proof of present runtime. Work stays on `main` in this checkout.

| Phase | Work | State | Completion evidence |
| --- | --- | --- | --- |
| 1 | Reconcile plans, recover maintenance, measure acquisition/archive gaps | Complete; deployed scheduled receipt and export verified | Bounded low-headroom regression; actual candidate disposition; deployed scheduled receipt through admission and export |
| 2 | Received-data catalog, exact inspection and export | Complete; local and installed passive flows verified | Normal operator flow includes nonpositive, missing fee/reference, unmatched and unavailable rows; passive reads |
| 3 | Bounded original responses and explicit capabilities | Complete; normal scheduled capture and exact reparse verified | Reparse retained bytes, caps/retries/gaps, requested vs unsupported fields; no weakened normalized ingress |
| 4 | Frozen calculations and coherent evaluation probabilities | Complete; exact, SQL, authentic v6 and offline export reproduction verified | Independent exact examples and policy reproduction; existing conservative screen preserved |
| 5 | Prospective population, causal replay, outcomes and scoring | Complete; installed automatic retention recovery and offline population reproduction verified | 1,159 declared cases / 259 events; 507 due / 652 pending at 22:12 UTC; prior gaps retained; 428 new observations / zero refusals after measured allocation repair |
| 6 | One additional book and bounded game/player case; detached historical consumers | Complete; real BetOnline/game-result chains and E5 detachment verified | Full source/identity/retention/inspection/evaluation trace; fixture vs live labeled; no broken imports/assets/migrations |

## Historical review blockers and stopping conditions

The owner cannot review the requested outcome while collection fails before
dispatch, received SGO data is absent from raw inspection, or research cannot
freeze and reproduce its inputs. These are agreed engineering needs. They do
not depend on positive EV, actual trading, calibration claims, or public launch.

Before a costly run, name the changed behavior and unresolved question. For
recovery, the earliest sufficient deployed observation crosses the actual
maintenance and scheduled collection transitions and establishes a new receipt,
admission and export. No unrelated multi-hour window or fixed sample count is
added. Repository CI remains its own check; fixtures do not establish live
coverage or predictive quality.

## Scope decisions

- Reuse existing PostgreSQL, exact math, current rows, raw/details/Admin and journal
  timing rules. Freeze decorative expansion. Preserve useful existing routes.
- Preserve all private evidence, credentials, controls, account/quota/reservations
  and unresolved holds. No archive, database or journal purge.
- $50/week is the working dollar envelope; SGO consumes $30/week. Existing
  hosting/services must be accounted before additional spend. No new paid
  service is selected; use actual existing data first. Credit guards remain
  separate from dollars.
- Historical plans retain bugs and evidence but no longer set milestone gates.
  See [archive decisions](archive.md) and [historical next steps](historical-next-steps-20261122.md).

## Evidence and continuation

Phase changes and verification were recorded here and in the technical handoff.
Local tests, commit/push, hosted CI, installed behavior, research validity and
actual fills are separate claims. No owner review is requested while known
agreed engineering remains.

Phase evidence is recorded in [progress](progress.md) and the [research operating guide](research.md). Final installed/CI evidence will remain distinct from local implementation.

All six engineering phases are integrated on `main`. Earlier installed `2a3e218` was
healthy with migration 113 and a completed automatic research pass. Its complete
daily evidence export contains 2,575 immutable records and reproduces 1,728
distinct snapshots offline. A narrow CSS fix addressed the cohort export
button at the owner's 150% browser zoom; its installed check and the required
hosted CI closeout were tracked separately and are now superseded by the final
installed `6ed3211` and successful 102-second required run above.
Historical observation gaps, finite storage and missing native price history
remain explicit operating limitations, not fabricated successful coverage.


## Owner follow-up: Open game and fee assumption

The original installed single-navigation journey did not catch overlapping reads.
The owner reported a 429 on Open game: each navigation reread the list and the
browser retried any token-bearing error, including admission rejection. The new
controller serializes navigation, reuses its captured list and refreshes only an
expired snapshot. Regression cases for duplicate reads and 429 retry fail on the
previous controller and pass on the repair. The unchanged four-slot server limit
now waits within the existing read deadline rather than rejecting normal bursts.

Default Data now shows trading markets, sportsbook reference coverage and best
stored EV. A status filter qualifies games before full game context is rendered;
opening one no longer discards reference or nonpositive observations.

Include fees defaults off, per the owner's later instruction. The durable setting
retains existing fee code and schedules; zero-fee cashflows and mode revisions are
captured explicitly. Turning fees on uses the prior fee model. Current working
calculations are invalidated and queued without acquisition; immutable historical
checkpoints and their exports are preserved. Missing non-fee inputs remain
unavailable. NCAAB models and game logs remain deferred.

Focused evidence includes real retained-data Open game, exact inspection and Back
using one list read; busy/expired/overlapping navigation; four-slot admission;
zero/nonzero fees, native contract grids, on/off invalidation and offline export
reproduction. The genuine 6,157-record historical bundle still reproduces both
checkpoints unchanged. Hosted deployment and final installed follow-up evidence
are reported with the follow-up commit/run, separately from these local checks.

### Installed follow-up evidence

Application commit `6044281b5c61eee84f741928e599f5e5a590b396` is installed.
Normal [CI/deploy run 45109399267](https://github.com/dock108dev/predict/actions/runs/45109399267)
succeeded in **92 seconds** (04:02:11–04:03:43 UTC). The unchanged four service
roles are healthy; the release actually replaced the application images. Local
normal checks passed in 17.064 seconds: 264 portable tests plus 41 subtests and
32 PostgreSQL tests plus three subtests, with lint/workflow/secrets passing.

Installed follow-up verified 49 freshly collected games, the owner's expired
bookmark recovering, the useful default summary, Open game without another
list read, full calculation-status context, exact export, reload and Back, and
the off/usable Settings switch. The isolated browser used an 800 CSS-pixel
viewport at 1.5 device scale for the 1200-pixel 150% layout; this is separate from
the earlier native owner's retained-150% journey. All observed read/export APIs
reported zero provider requests, with no browser errors. Public unauthenticated
access remains 401 and both proxy authentication file hashes are unchanged.

The installed current calculation queue was empty with **860 numeric zero-fee
calculations and zero numeric fee-enabled/legacy calculations**. One genuine
Prophet Exchange example at +285 committed $100 and returned $385 in the win
state, using recorded probability 85/319: exact EV 3/116 (+2.59%), with every fee
zero. Mode, source clocks and exact revision are in the matching downloaded
export. The dedicated disposable tests prove enabling fees restores nonzero
fees and that disabling them rebuilds the same source prices without acquisition.

Fresh T−10 comparisons await their actual scheduled captures. Early checkpoints
captured before this later fee instruction retain their original assumption;
new checkpoints record the actual selected mode. NCAAB model/game-log work
remains deferred. Private screenshots, exports, normal-CI artifacts and installed
journey receipts are in `.local/personal-workspace-20261122/`.


## Private research beta

The November 23–29 NCAAB paper campaign is running on the deployed private beta.
November 23 is reconciled and graded, November 24 is partially graded, and
November 25–29 remain scheduled. Future protected captures, finals and score
corrections remain operating observations. See the [first-beta closeout](../predict-first-beta-closeout-20261124.md).
