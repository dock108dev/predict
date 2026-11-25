# Scheduled NCAAB paper experiments, daily/weekly review and EV screens

Owner scope: November 23–29, 2026 inclusive, men’s D1 versus D1 NCAAB, paper
only. Historical days replay retained T−10 evidence under a separate definition;
future days publish automatically. Original runs remain immutable.

Sizing is one tenth of the former quarter Kelly: **1/40 of full Kelly**, with
the unchanged $10,000 sizing reference (scale $250). At 4% EV the baselines are
$11 at −110, $3.33 at +300 and $0.33 at +3000. Each quote is repriced using its
original fee inputs at the new amount; old rounded stakes are not divided by ten.

EV buckets are continuous, based on unrounded screening EV: [4%,8%), [8%,15%),
[15%,25%) and [25%,∞). Separate overlapping minimum screens >=4/8/15/25% show
how selection would change. Each threshold filters both the frozen screen and
sized EV and reselects the best qualifying venue from the available all-venue
pool. These are alternative analyses, not additional paper trades to add together.

## Implementation

Migration 121 stores immutable experiment configurations and dated publication
pointers/leases. The existing independent paper-results worker handles one due
day from retained evidence, yielding to protected capture turns. New run
publication automatically uses the existing result-grading queue. Snapshots
coalesce on a retained-population/task fingerprint, refresh at 15-minute checks,
and retain original captures, missing games and reconstruction flags. Future
dates wait for their day; late results continue grading existing runs after Sunday.
The UI and exports read the latest pointer for each day once, avoiding duplicate
counting of historical snapshots.

Research → Daily & weekly experiments exposes creation, dates, EV minimum,
Kelly percentage, bankroll reference and bucket boundaries. Editing creates a
separate immutable version. The experiment page has weekly totals, daily links,
EV buckets and minimum comparisons. Daily links lead to the existing game →
trade → calculation/evidence view, with a return link to weekly results. Passive
refresh and exports never collect provider data. New schedules require no CLI.

Capacity review observed 374,631,839 retained bytes and 70,469,051 reserved
bytes against the former 512 MiB research allocation, leaving about 88 MiB.
Research allocation is expanded to 2 GiB under the existing 4 GiB SQL and disk
guards. Source credit/account limits and Stop choices are unchanged. Scheduled
paper replays and EV comparisons make zero provider requests.

## Verification and production

Deployed on `3743a873012ed5676b5cb35d1e59a385935207ba` after
[required CI](https://github.com/dock108dev/predict/actions/runs/45537766319).
The normal migration guard required a maintenance release: all checks passed,
the existing release procedure backed up PostgreSQL, applied migration 121 and
restarted the application and data roles. The first CI's guarded release then
passed on retry. No source-credit or Stop configuration was changed.

Created the actual schedule using the signed-in production form:
[NCAAB · Nov 23–29 · 1/40 Kelly](https://predict.dock108.dev/research?section=experiments&campaign=93b8937a41703ce083609c50e52135019fe36bf082a1f32ecf5a00d54daffeda&variant=best_venue).
The worker published November 23 and 24 without manual replay; November 23 is
graded and November 24 is partially graded. November 25–29 remain scheduled.
The 12 original saved payload/report/summary hashes matched the pre-change
snapshot. The UI export independently reconciled exact daily, weekly and
non-overlapping bucket totals, with one latest run per date and the baseline
threshold matching its portfolio. Evidence is in `.local/ncaab-week-20261124/`.

| November 23 portfolio | Tickets | Stake | Expected profit | Returned | Modeled P/L | ROI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Best venue | 76 | $448.68 | $38.42 | $403.24 | −$45.44 | −10.13% |
| All qualifying venues | 114 | $596.34 | $54.04 | $461.06 | −$135.28 | −22.69% |

Local fast verification passed the portable and PostgreSQL suites, including
21 PostgreSQL cases. Focused checks covered exact Kelly scale, fractional EV
boundaries, best-venue reselection, seven-day registration, idempotent
publication and immutable parent definitions. Two focused Chromium checks
passed, including form creation at 390px and daily → game → trade navigation.
The production walkthrough found a daily-return-link initialization error;
moving portfolio selection before link construction and adding a regression
fixed it before final verification. The signed-in production flow passed
creation, revised-version configuration, portfolio switching, daily/game/trade
calculations, return to week and the JSON export. East Carolina −14.5 shows
Novig +669, $7.53 stake, $1.52 expected profit and −$7.53 modeled P/L, with the
recorded 2.5% full-Kelly multiplier and original quote/result evidence.

Future scheduled dates remain unobserved until their actual operating turns.
Historical replay does not imply those prices or EV were successfully displayed
at T−10. Grade completion does not establish full-slate or venue inventory coverage.
