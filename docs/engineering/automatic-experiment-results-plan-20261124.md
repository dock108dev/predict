# Automatic experiment results and game/trade review

Status: deployed and verified on November 24. Automatic grading and game/trade
review apply to every saved paper experiment. November 23 supplies the first
retained-data validation. The next scheduled prior-day arrival is pending.

The pre-backfill production baseline was healthy on `590a0284cc309fb6a48ca479de66735293c3989b`
and matched local/remote `main`. The baseline SQL snapshot froze original
payload, report and summary hashes for 12 runs across 10 definition versions.
The acceptance evidence is publication by the production background worker,
preservation of those hashes, and a signed-in review through the normal
experiment UI. The repository's additive-schema release requires the guarded
maintenance backup and the checked image digests from CI. The next actual
scheduled arrival supplies additional operating evidence if it falls later.

## Intended product outcome

Opening a paper experiment shows its latest results first, with date and Best
venue / All venues controls. The owner can open any game, see its final score
and paper trades, then inspect the calculation, modeled payout/P&L and original
evidence. No manual score entry, grading button or experiment replay is needed
to receive results. The same flow applies to every saved paper run; November 23
is the first end-to-end validation dataset, not a hard-coded feature branch.

Initial support covers the existing full-game moneyline/spread/total paper
markets and configured result sources. The common workflow applies across
experiment definitions and dates. Other sports/periods/contract rules use
explicit grading adapters, with unsupported cases visible rather than guessed.
No new feeds, subscriptions, real orders or economic-policy changes are implied.

## What exists and what is missing

`app/research/workspace.py` retains immutable definitions/runs and frozen sizing
witnesses. `app/research/paper.py` has decisive sporting grading and portfolio
arithmetic. Its scoped runs deliberately use `defer_results=True` and mark each
ticket `results_integration_deferred`. `app/collection/mens_d1_jobs.py` already
collects prior-day CBBD results at 5:30 AM Eastern with correction/follow-up
turns. `app/storage/mens_d1_occurrences.py` reconciles identities, dates, scores
and conflicts. The Research run UI and Data result ledger currently display
these as separate records.

The missing component is a shared, durable dependency from a retained result
revision to grades for every affected saved run, and a report showing those
grades alongside the games and trades. Do not solve this by rerunning screening
against newer odds or mutating the opportunity snapshots.

## 1. Define immutable grading inputs and result revisions

Retain a normalized result record containing occurrence ID, canonical
participants, source IDs, final/status, period and overtime information, scores,
source observation/recording times, original receipt hash and result revision.
Keep conflicting revisions; never match only on display names or calendar date.

For each frozen paper ticket retain a dependency on the exact occurrence,
contract outcome/side, line, period and scoring terms. Preserve its original
odds, fair probability, EV, stake, fee/cashflow witness and frozen/reconstructed
origin. Verify home/away orientation against canonical participant evidence;
source display order is not authoritative.

Store append-only trade grades and run-result snapshots separately from saved
selection runs. A stable result identity combines the frozen run identity,
result-evidence revision and grader version. Record supersession and original
evidence so a corrected score creates a new result version, not a rewritten
historical finding. Old graded versions must remain inspectable/exportable.

Add the required schema through the existing additive migration workflow.
Include derived result storage in retention accounting and admission controls.

## 2. Wire automatic scheduling and a durable grading queue

Use the existing prior-day collector and its configured correction/follow-up
schedule. The 5:30 AM Eastern CBBD turn is already implemented, not a new
completion threshold. Sources already collecting finals during the day should
also trigger grading immediately after a valid revision is retained; they
should not wait for the following morning's sweep.

After committing a new result, atomically enqueue the affected run dependencies
or use a durable transactional outbox. Creating a new saved run likewise queues
grading against existing results. Coalesce duplicate work with a unique key
over run/result/grader revision. Claim work with a lease and make restart,
retry and partial completion safe. A periodic repair sweep catches retained
results/runs without a derived report; it must not fetch new odds.

Do not grade inside the result-ingestion or T−10 request transaction. Keep
grading/comparison work outside protected capture turns and preserve account,
source-pause, Stop, reservation and storage semantics. Existing source collection
checks the actual shared CBBD/CFBD allowance. UI reads, exports and grading
consume retained evidence and cause zero collection requests.

Backfill all existing saved paper runs from retained results, including old
versions, without rewriting their frozen selection. Keep each run independent;
never sum successive snapshots as if they were additional trades.

## 3. Grade through a shared deterministic service

Create a pure grading service with versioned sport/market adapters. Reuse the
existing `paper.grade`, `records.resolved_side` and fee/cashflow arithmetic where
their supported conditions hold. Validate identity, occurrence, period, scoring
terms and result authority before calculating a grade.

Supported states are pending, win, loss, unresolved/conflicting and unsupported.
Push/void grades require captured refund/settlement rules and cashflows; the
current binary model's unresolved tie/push behavior must not silently become
a refund assumption. Cancellations, reschedules and unsupported periods need
explicit reasons. Include overtime only according to recorded scoring terms.

Use exact numeric inputs from the frozen witness, not rounded UI values:

- Expected profit = frozen commitment × frozen net EV.
- Modeled return = the recorded net receipt for the graded state.
- Modeled P/L = modeled return − original commitment.
- Portfolio P/L and return sum the identical selected-ticket population.
- Partial-report ROI uses resolved stake and labels that denominator; display
  unresolved stake separately. A fully resolved report uses total stake.

Report wins/losses and any supported pushes/voids without conflating win rate
and ROI. Do not infer a historical cash-release time from a score observed the
next morning, or claim actual venue settlement/fills/fees from sporting grades.

Score corrections invalidate and rebuild only dependent result snapshots. A
grader-rule change also creates a new version. Selection, EV and Kelly sizing
do not change when the result changes.

## 4. Publish consistent day, game and trade reports

Build one shared read model/API for Results, experiment pages and exports:

- Run/day summary: selected variant, tickets, games, total stake, expected
  profit, returned amount, modeled P/L, ROI, grade counts and unresolved stake.
- Game summary: score/status, trades, venues, commitment, return, P/L and capture
  origin. Include zero-trade games and missing captures with distinct states.
- Trade row: game, selection, venue, odds, probability, EV, stake, expected
  profit, final score, grade, modeled return/P&L and calculation/evidence links.
- Breakdowns by game, venue and frozen-versus-reconstructed origin. All numbers
  must reconcile to the selected portfolio; Best and All remain separate.

Separate result completion from selection completeness. A report may truthfully
say "All 76 selected tickets graded" while still showing seven games with no
retained T−10 evidence and an unknown complete slate. No-trade and unavailable
are different states. Analysis-only experiments retain their applicable findings
without receiving fictitious financial metrics.

Persist result snapshots for fast reads; expose current job/freshness/error
states separately. Preserve the last valid report with an explicit stale or
correction-pending label if refresh fails. The UI's update time must not be
presented as the original result observation time.

## 5. Put the review flow first in the UI

Each paper experiment should default to a Results view for its selected date:

1. Experiment/date/Best-or-All controls and the portfolio summary.
2. Games & trades table with score, stake and P/L visible without opening evidence.
3. Click a game to see all its selected paper trades alongside its result.
4. Click a trade to see grade reasoning, frozen probability/EV/Kelly math, fee
   cashflows, timestamps and both quote/result provenance.
5. Export the exact graded report, game rows and trade rows with result version
   and evidence hashes.

Provide filters for traded games, zero qualifiers, missing captures, wins,
losses and unresolved trades. Preserve date/variant/game/trade/result-version
context through Back, reload and direct links. Open the latest published result
automatically, while retaining historical versions. Existing findings and
theories remain accessible with labels that distinguish them from trade P/L.
Move lengthy coverage and technical evidence into supporting details; a compact
coverage badge remains visible beside the day result. No manual rerun or grade
button should be necessary for routine operation.

## Implementation order and completion evidence

Deliver as one coherent assignment:

1. Add normalized dependencies/result-version schema, pure grading service and
   durable queue/outbox integration.
2. Backfill existing runs and implement reconciled run/game/trade summary APIs.
3. Integrate the shared results-first UI and exact result exports.
4. Verify, deploy through required CI and exercise signed-in production.

Use meaningful tests for result-before-run and run-before-result ordering,
duplicate arrivals, restart, score correction, source conflict, canonical-team
orientation, overtime/period rules, push/void unknowns, zero trades, missing
captures, two experiment definitions using one game, multiple saved versions,
Best/All deduplication and exact arithmetic. A fixture must prove automatic
queueing from result retention, not merely call the grade function directly.

Use November 23 as the real retained-data validation: 33 known eligible games
have finals, and the 76 Best / 114 All tickets must retain their original stake
and selection. Verify every supported grade and reconcile game/venue/portfolio
totals. East Carolina −14.5 at Novig +669, stake $75.32 and expected profit
$15.18 must show a modeled loss of $75.32 against Indiana State's 77–76 win.
Missing seven-game quote evidence remains visible and creates no invented trade.

Verify the same automatic path on another authored experiment definition using
the same game; no date-specific or definition-specific implementation. Freeze
and compare original run hashes before/after backfill. Demonstrate idempotent
processing and a correction that changes only derived grading versions.

Earliest sufficient engineering completion is the shared pipeline integrated,
required checks/deployment passed, and existing real November 23 inputs processed
by the production background queue into the signed-in day → game → trade flow.
The next actual prior-day scheduled arrival supplies additional operating
evidence; if still in the future, state that observation pending rather than
invent an overnight soak gate. Full-slate collection, repaired 25-game capacity,
probability calibration and actual settlement are not prerequisites for grading
already recorded trades. They retain their own open claims and evidence.

Closeout includes deployed revision/CI, original and graded-result identities,
exact graded trade totals, production walkthrough/export links, automatic
queue/restart/correction evidence, actual acquisition usage and remaining
unsupported cases. Complete authorized fixes before owner review. No real bets.

## Implementation and retained-data rehearsal

Migration `120_paper_results.sql` registers paper-run dependencies and writes
outbox signals in the transactions that retain result evidence. The supervised
web image runs a separate lower-priority grader process. The worker consumes
PostgreSQL through a lease, waits outside the existing protected T−10 window,
uses the existing storage admission guards, and publishes immutable report
versions. Reads check for both dispatched work and newly committed outbox
entries. When either is pending, the current view hides superseded grades and
keeps published versions available from history.

The grader binds frozen game, participant, line and period evidence before
applying the recorded win/loss receipts. The modeled full-game score includes
overtime where the adapter supports it. NHL spreads and totals require the
shootout scoring basis. Push/void cashflows require applicable recorded refund
terms. Sources include the existing dated CBBD and public evidence, official
corroboration, and SportsGameOdds retained results. See the
[SportsGameOdds period definitions](https://sportsgameodds.com/docs/data-types/periods)
and [market identity fields](https://sportsgameodds.com/docs/data-types/odds).

The real-data rehearsal restored a bounded retained evidence subset into
disposable PostgreSQL 16, applied the additive migration, and started the
normal supervised web command. The worker published all 12 saved runs.
The November 23 game/trade browser smoke caught a legacy HTML redirect that
classified any `game` query as Data. Research now recognizes a paper game
when a saved run is selected in Experiments. Reload and Back passed on the
normal HTTP route with the real retained East Carolina ticket.

The focused local batch passed 24 portable and browser checks and 19
disposable SQL checks. The SQL cases cover both save/result orderings,
transactional retention, duplicate arrivals, restart after an expired lease,
rollback, an in-flight correction, explicit conflict and recovery, and T−10
priority. An optional broader browser run stopped after five assertions in
the existing activity-mode tests looked for retired controls. That manual
lane is separate from the required deployment CI and signed-in Research check.

## Production delivery and verification

The web, collector and archive roles are healthy on
`3e85b6a6e9dd4a4335b8c539717ab51804a9107d`. The first
[CI attempt](https://github.com/dock108dev/predict/actions/runs/45532782516/attempts/1)
passed its checks and published the images. Its fast release stopped at the
unapplied-schema guard. The guarded maintenance release used those images and
retained the 279,336,086-byte pre-migration backup
`/srv/predict/backups/before-migration.92SqRYDA.dump`.
[Post-migration CI](https://github.com/dock108dev/predict/actions/runs/45532782516/attempts/2)
passed through deployment and health verification.
[CodeQL](https://github.com/dock108dev/predict/actions/runs/45532782740)
also passed for the same revision.

The production worker dispatched 107 retained-input signals and published a
current report for all 12 runs by 9:29:37 PM Eastern. No jobs had errors or
undispatched inputs at that read. The original payload, report and summary
hashes matched for all 12 runs. The primary November 23 frozen run is
`8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796`.
Its frozen payload SHA-256 is
`ff5cf4a6e0ceb39e18e591725cc211fcf23ad5569b153dd1921717b2962756f5`.
The first published result is
`3a0a3bdc97e7f87c61062d61dbdd69a959b0fa1eb7e1ba4c1235376339554751`
under `paper-sporting-grades-1`. The shared scoring evidence was also
verified on the separate authored definition's existing
`47e7bbc6b575de525d15895259fbdddf1a297821a8f438b5aef9cf0d1791fbca` run,
which published `175515ea804b9498cd345789bc98a6aab885fba46da1f937cffdf5d9719b9884`.

| November 23 portfolio | Graded | Wins / losses | Staked | Expected profit | Returned | Modeled P/L | ROI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Best venue | 76 | 18 / 58 | $4,497.26 | $385.36 | $4,038.32 | −$458.94 | −10.20% |
| All qualifying venues | 114 | 21 / 93 | $5,985.33 | $542.40 | $4,620.70 | −$1,364.64 | −22.80% |

The seven historical missing captures and five captured games with zero
qualifiers are visible across 33 finals. Unresolved tickets and stake are
zero in both portfolios. Exact ticket money reconciles to game, venue, capture
origin and portfolio totals. Each displayed amount rounds independently.

The signed-in [day](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-23&run=8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796),
[game](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-23&run=8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796&variant=all_venues&game=d028570b138eb4b53dc05b26f5a0b211d9f13687e54d1f90d179662399c30409)
and [trade](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-23&run=8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796&variant=all_venues&game=d028570b138eb4b53dc05b26f5a0b211d9f13687e54d1f90d179662399c30409&trade=5fc0d3b9cdc19f9bb944084eb069c14a3c1ac5ae2b3c958372f1ecfe36684857)
worked with Back, reload and version pinning. Indiana State's 77–76 overtime
win graded East Carolina −14.5 at Novig +669 as a $75.32 loss against
$15.18 expected profit. The original quote and both the CBBD and
SportsGameOdds result responses matched their retained hashes.

- [Exact graded report](https://predict.dock108.dev/api/research/workspace/runs/8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796/results?version=3a0a3bdc97e7f87c61062d61dbdd69a959b0fa1eb7e1ba4c1235376339554751&variant=all_venues&export=report)
- [33 game rows](https://predict.dock108.dev/api/research/workspace/runs/8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796/results?version=3a0a3bdc97e7f87c61062d61dbdd69a959b0fa1eb7e1ba4c1235376339554751&variant=all_venues&export=games)
- [114 All venue trade rows](https://predict.dock108.dev/api/research/workspace/runs/8b027e84b7c85e7974a87ca8fca85745ac5b986d3eddb0757536f9877bdb5796/results?version=3a0a3bdc97e7f87c61062d61dbdd69a959b0fa1eb7e1ba4c1235376339554751&variant=all_venues&export=trades)

The browser made 47 passive same-origin requests with zero browser errors.
The worker and verification used zero provider API requests, zero incremental
provider usage, and zero orders. The guarded collector stayed on its saved
configuration after restart. The before/after production views both recorded
four ordinary CBBD metered calls and zero uncertain calls for the day.
Incremental dollar charges for that ordinary source activity are unavailable.
Production evidence is in `.local/automatic-paper-results-20261124/`. The
November 25 5:30 AM Eastern prior-day arrival is the next operating observation.
