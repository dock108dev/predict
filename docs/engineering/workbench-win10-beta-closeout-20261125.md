# Workbench Win $10 private beta

**Running November 25, 2026 Eastern.** The signed-in Experiments form created
and started the November 23–29 Win $10 experiment and its fresh Kelly
comparison. All three application roles run
`8073f2555919d26d0dd50764badb0bb4d0cf4d97`, and all four services are healthy.
The [first guarded release](https://github.com/dock108dev/predict/actions/runs/45550027108)
installed `4f15bad`. The [final required CI and deployment](https://github.com/dock108dev/predict/actions/runs/45552224802)
passed in 102 seconds. Schema migration 123 remains current.

[Win $10 weekly results](https://predict.dock108.dev/research?section=experiments&campaign=521543a8363cd0a945e792726e387a23b2003e743fe7364945cd2ebfb5d65864&mode=fixed_profit&variant=best_venue&view=weekly) · [Kelly comparison](https://predict.dock108.dev/research?section=experiments&campaign=521543a8363cd0a945e792726e387a23b2003e743fe7364945cd2ebfb5d65864&mode=kelly&variant=best_venue&view=weekly)

## Scope and working path

Research → Experiments → Create experiment. Enter the experiment name, select
the supported game scope and Eastern dates, and choose **Win fixed profit** or
**Kelly**. Fixed profit defaults to $10 and can include a Kelly comparison with
its own fraction and reference bankroll. Set minimum EV, EV buckets and
portfolios. **Review → Save and run** saves immutable rules. **Edit as a new
version** opens the same form with those rules filled in.

The signed-in November 23–29 experiment uses men's NCAA Division I versus
Division I, the final eligible T−10 observation in the retained window and the
existing exact-line reference probability. It uses an unrounded 4% minimum and
the 4–<8%, 8–<15%, 15–<25% and 25%+ buckets. The saved Kelly comparison uses
1/40 full Kelly on a $10,000 reference. Best and All remain independent, as do
Daily/Weekly and sizing selection.

## What changed

The exact solver compares each feasible net win profit with the target and
uses the lower commitment when the distance ties. It retains the modeled
win profit, signed difference, quantity and price increment evidence, fee
assumption and exact cashflows. The full candidate pool is repriced at its
actual commitment before unrounded EV and Best selection. Frozen quote and bet
IDs connect the modes even if a different size changes qualification or venue.
Sizing exclusions link to the dated offer export.

The first installed pair published both opportunity snapshots, then the grader
processed Kelly and began the following replay while Win $10 grading remained
queued. The follow-up services two due grades before the next replay, reuses
each verified checkpoint across both sizing modes before advancing to the next
game, and displays the current replay lease as queued/running in Experiments.
A disposable regression confirms one retained checkpoint read for the pair and
complete report equality against separate replays.

## Published paper results

The November 25 snapshot around 12:18 a.m. Eastern includes fully graded
November 23 and partially graded November 24. November 25 is collecting and
November 26–29 are scheduled. The same 505 qualified frozen quotes and 345
Best selections appear in both modes across the two reported dates. November
23 used 6 original and 20 reconstructed T−10 checkpoints, with 7 retained
capture gaps. November 24 used 67 original and 10 reconstructed checkpoints.

| Sizing | Portfolio | Graded / selected | Staked | Returned | Modeled P/L | ROI on graded stake |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Win $10 | Best | 326 / 345 | $1,276.71 | $1,115.31 | −$97.69 | −8.05% |
| Win $10 | All | 478 / 505 | $1,573.64 | $1,340.41 | −$151.40 | −10.15% |
| Kelly | Best | 326 / 345 | $2,242.43 | $1,873.69 | −$257.45 | −12.08% |
| Kelly | All | 478 / 505 | $2,886.71 | $2,315.73 | −$434.15 | −15.79% |

Staked includes ungraded tickets. Returned, P/L and ROI use resolved tickets.
Each mode and portfolio counts each available date once. Exact fractions
reconcile across frozen trade cashflows, graded trade rows, daily and weekly
summaries, and versioned JSON exports. Monetary display rounds after summation.

**Published rounding example.** Pepperdine −22.5 at Kalshi +490 won. Twelve
modeled $1 payout claims required `$120/59` and returned $12. The exact net
profit was `$588/59`, or `$2/59` below target. The committed amount is about
$2.03 and the modeled profit is about $9.97. The one-claim increment belongs
to the frozen paper price model. [Open the trade](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&campaign=521543a8363cd0a945e792726e387a23b2003e743fe7364945cd2ebfb5d65864&mode=fixed_profit&variant=all_venues&date=2026-11-23&run=2b1741b9191f46826f5782739d8bf8faea86ff39404c1c39da2b13f362e7705f&result=9b6c83b2729c341d4afd2354ca154f5b8eb632762c85a08bb8eb1fe1b1b6daf2&trade=3c1a10c6dbf6f97c7299f255f544ca4e8f4a7fa3b9f78266dd7c04fac965776e)

## Controlled qualification

The signed-in production form also created an elapsed one-day $7.50 replay
using retained November 23 inputs. Repeating the same save returned the same
campaign. Revising the target to $7.75 saved a linked version. A separate
production-shaped browser and disposable PostgreSQL fixture used a $7.51
target at +300. It staked $2.50, returned exactly $10 on a win, and earned $7.50
modeled net profit. The fixture verified the explicit missing-fee reason and
automatic grading after a later final. Paired SQL checks cover both grading
arrival orders, late corrections, superseded work, rollback and restart.

[Open the $7.50 case](https://predict.dock108.dev/research?section=experiments&campaign=77acdfc86eac152d8b9f0ca07fc1fc07fa0a323207f7c0ab6147c4f836092bea&mode=fixed_profit&variant=best_venue&view=weekly) · [Open the $7.75 revision](https://predict.dock108.dev/research?section=experiments&campaign=8996c9b7dfa170b783af2d7d7d301f948d804d3457d9faa71ca5609383bf68c6&mode=fixed_profit&variant=best_venue&view=weekly)

Both one-day production configurations graded and exported. Best had 76
graded tickets in each version. The $7.50 version modeled +$10.74 on $198.54
staked, and the $7.75 version modeled +$10.99 on $204.98 staked. Repeating the
signed-in create and revise journeys after the final restart returned the
same three immutable campaign IDs.

## Verification and preserved evidence

- Initial local release checks passed 295 portable cases plus 45 subtests
  and 30 disposable PostgreSQL 16 cases. Follow-up checks passed 197 portable
  cases plus 30 subtests and 26 disposable PostgreSQL 16 cases. Eleven focused
  Chromium journeys and the separate real HTTP/SQL browser fixture passed.
- Production Chromium walked the signed-in workflow at 1400, 390 and 319
  CSS pixels. The ledger applied the selected grade and exact EV order
  before pagination. Daily/Weekly, the sizing switch, both portfolios, the
  selected quote, Back and reload retained their intended context. The
  inspector exposed original quote and result evidence, and the user-facing
  trade download matched its pinned report.
- Before/after production snapshots preserved hashes for the 12 original
  definitions, 15 original replay records, 56 existing result versions and
  99 issue decisions, plus all 123 migration hashes and the existing
  campaign and collector controls. The restarted grader published both
  historical sizing modes and the two verification configurations.
- Production evidence, browser screenshots, exact reconciliation reports
  and release receipts are retained under `.local/win10-beta-20261124/`.

## Operating bounds

Use captured quotes as paper price assumptions. Actual executable depth, venue
fees and settlement remain unverified. Missing T−10 captures and pending or
unresolved grades are visible separately, and realized ROI uses resolved stake.
Paper processing adds zero provider requests, credits and real orders. The
source worker continues its existing guarded schedule and accounting.

From November 23 midnight Eastern through the 12:21 a.m. November 25
observation, ordinary collection across the configured scope retained 4,382
SportsGameOdds responses and recorded 7,835 charged objects, with four objects
of uncertain exposure. CollegeBasketballData used six metered calls with zero
held. Research headroom was 1,614,497,476 bytes and PostgreSQL used 968,334,359
bytes under the existing limits. The collection settings, Stop state and
source pauses matched the baseline.

The first protected T−10 target observed after the final release captured at
12:20 a.m. Eastern on November 25. At 12:21 a.m. the next known T−10 was 9:50
a.m. Existing slate refresh was due at 4:00 a.m. November 25, with November 24
result collection at 5:30 a.m. and corrections at 12:30 p.m. The durable paper
schedule already includes Sunday, November 29. The verified collection rule
puts Sunday's finals at 5:30 a.m. and corrections at 12:30 p.m. November 30,
with an unresolved follow-up at 5:30 a.m. December 1. Those collector rows
enter the live planning horizon on its normal schedule. [Collection and results jobs](https://predict.dock108.dev/settings#mens-d1-jobs)
