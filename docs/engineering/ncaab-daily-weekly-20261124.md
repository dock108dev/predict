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

Pending deployment and signed-in schedule creation. Local checks cover exact
Kelly scale, fractional EV boundaries, best-venue reselection at higher cutoffs,
seven-day registration, idempotent publication and immutable parent definitions.
The browser flow exercises form creation, dates, portfolio switching, the daily
and weekly report, EV comparisons and creating a revised version at 390px.

Future scheduled dates remain unobserved until their actual operating turns.
Historical replay does not imply those prices or EV were successfully displayed
at T−10. Grade completion does not establish full-slate or venue inventory coverage.
