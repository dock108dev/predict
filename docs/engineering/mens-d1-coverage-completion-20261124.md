# Men’s D1 experiment coverage: next implementation assignment

Status: deployed and signed-in engineer walkthrough verified. The complete expected
slate, venue-wide inventory, and larger deadline cluster remain unverified. The
11:41 AM baseline below is preserved as a dated observation.

## Verified baseline

Read-only production refresh: **November 24, 2026, 11:41 AM Eastern**.
Local main: `1431897931a57aa60ec6172b288baabdf8768f24`;
[its CI passed](https://github.com/dock108dev/predict/actions/runs/45435387664).
Installed web, collector and archive image labels remain
`c75ffcd52707699a7615decea903feadf799f376`; all three and PostgreSQL are healthy.
The newer local commit records documentation, rather than different app behavior.

| Evidence | November 23 | November 24 |
| --- | ---: | ---: |
| Provider-known eligible D1 versus D1 games | 33 | 77 |
| Frozen captures | 6 | 3 |
| Reconstructed captures from original responses | 20 | 0 in saved run |
| Missing / pending | 7 missing | 74 pending |
| Retained provider finals for eligible games | 32 | 1 |
| Best venue paper tickets / turnover | 76 / $4,497.26 | 8 / $569.73 |
| All venues paper tickets / turnover | 114 / $5,985.33 | 12 / $775.88 |
| Independently verified expected slate | Unknown | Unknown |

Monday has **26**, rather than 27, eligible evidence-bearing games. The corrected
run observed 6,236 offers and evaluated 2,916. It excludes 672 offers for
`reference_exact_pair_unavailable` and 874 for
`reference_two_trusted_books_required`: **1,546**, rather than 1,547, lack the
required reference evidence. These are offer dispositions, not unique games.
None of the 26 games has proven market completeness. `complete_market=False`
is currently a conservative constant in `ev_movement.py`; it does not prove
every game actually lost a page or an available market.

The seven Monday games still lacking usable price evidence are:

- Late discovery: St. Bonaventure–Appalachian State; Northern Iowa–Davidson.
- Missed window: Georgia Southern–Northern Kentucky; Central Arkansas–North
  Florida; Texas A&M-Corpus Christi–Wichita State; Denver–Kansas;
  Stephen F. Austin–Utah Valley.

Illinois State–Santa Clara has an original persistence-after-deadline miss, but
its original response supports reconstruction. Thus the original ledger's eight
misses and 19 refusals coexist with seven missing games in the corrected run.
All 19 refused eligible games were reconstructed; reconstruction does not turn
the original task into a successful live capture.

Sports Reference remains disabled for unverified private-hosted-use permission
and Firecrawl account/access. Requests, charged credits and held credits remain
zero. Scheduled job rows do not establish that a collection occurred. Research
has 364,754,617 bytes (347.9 MiB) unreserved headroom within 512 MiB. The existing
forecast lists 90 upcoming late tasks across sports, including 84 NCAAB tasks;
these are task counts, not the eligible November 24 denominator. Its 11 planned
basic scrape credits exclude retries and future detail requests.

Private refresh receipt: `.local/mens-d1-20261124/coverage-priority-refresh.json`.
This refresh read saved runs and current coverage in a repeatable-read,
read-only transaction; it created no new run, provider request or order.

## Copy-ready lead-engineer prompt

Implement and deploy the next coverage slice for Predict’s men’s D1 paper
experiment. Complete the engineering, integration and engineer-led verification
in this assignment. The outcome is an honest answer to: **Which games should
have been covered on November 23 and 24, what did we actually capture, which
offers could be evaluated, and what do the paper totals assume?**

### Baseline and rules

Work in `/Users/michaelfuscoletti/Desktop/prediction-arb`, on `main`, using the
existing working copy. Start by checking this assignment, the active queue,
`docs/engineering/mens-d1-daily-coverage-20261124.md`, current HEAD and production.
The verified baseline above is time-stamped, not a promise that later counts
stay fixed. Preserve uncommitted work, original runs, response receipts,
credentials, Stop/source-pause choices, account windows, quotas, reservations
and exposure records. Follow the repository's existing deployment workflow.

Keep the existing paper definition: both teams men’s NCAA D1 for the relevant
season; Eastern game date; final eligible T−10 capture under its existing
window; unrounded EV >=4%; existing reference-probability method; quarter Kelly
with fixed $10,000 reference bankroll and no portfolio budget cap or compounding.
At exactly 4% EV, the -110 baseline is $110, +300 is about $33.33 and +3000 is
about $3.33. Keep Best venue only and All qualifying venues. Best deduplicates
the same exact bet across venues; different lines remain distinct. Preserve
the original zero-fee, quoted-size model. Any different method, freshness screen,
fee-adjusted qualification or sizing policy needs a separately versioned
experiment; do not rewrite old tickets. No real orders.

### 1. Establish the expected game population

Finish the existing daily source path rather than building a parallel slate
system. Retain dated source receipts and immutable slate revisions with source
observation/recording times, season membership, game identity, start time,
timezone, additions, cancellations and reschedules. Count zero-positive-EV
games, source-only games and games without provider markets.

Verify the source's actual permitted use and the existing account/key/budget
configuration without exposing secrets. The current Sports Reference policy
restriction is an external source condition, not a new owner approval gate.
Use Firecrawl only when that source use and account allowance are verified;
ordinary API/acquisition authorization already exists in AGENTS.md. If the
source remains unavailable, evaluate a permitted existing source or practical
alternative and state exactly what it can establish. Do not bypass access
controls, silently substitute sources or call provider-known counts the full
slate. Continue priorities 2–5 while resolving this dependency.

Reconcile both dates game by game. Preserve original names/IDs and evidence for
cross-source bindings; surface ambiguous identities, schedule disagreements and
unresolved membership. Publish revised populations rather than mutating older
saved populations. A retrospective schedule may verify eventual membership;
it cannot establish what we knew before a game's T−10 deadline.

### 2. Diagnose and improve T−10 capture reliability

Reconstruct the two late-discovery and five missed-window timelines from source
receipts, discovery slots, schedule revisions, task claims, dispatch/receipt
times, processing/persistence times, retries, refusals and worker state. Include
the reconstructed persistence miss separately. Identify demonstrated causes and
unknowns; simultaneous deadlines alone do not establish queue saturation.

Fix the demonstrated scheduling, acquisition, persistence or reservation causes.
Protect deadline work from ordinary discovery, scraping and result imports
within existing budgets and explicit Stop choices. Make schedule changes,
duplicate claims, restarts and retries safe. Retain enough instrumentation to
explain the next miss without guessing. Do not manufacture retrospective quotes
or relabel reconstructed data as live success.

Forecast the next actual deadline clusters: tasks and pages/requests, permitted
concurrency, observed latency, queue delay, retention bytes and reservations,
retry allowance, provider/account limits and exhaustion behavior. The current
347.9 MiB headroom and 90-task count are inputs, not a completed capacity proof.
Verify busy simultaneous deadlines with realistic controlled checks and observe
the next available live cluster. If it falls outside the working session, leave
durable scheduled instrumentation and label live qualification pending; do not
claim fixture success establishes live operation.

### 3. Account for returned market coverage

Build an inspectable census for each selected game, configured venue, market
family, outcome and exact line. Preserve requested scope, received pages,
cursors, response hashes, normalized rows and rejected/unsupported/conflicting
rows. Verify what provider pagination actually means and finish applicable pages
within budget and deadline constraints. Do not assume an event cursor proves
missing lines within a particular event.

Distinguish requested-but-unreturned, explicitly unavailable/withdrawn,
unsupported, partial retrieval and unknown completeness. An absent venue or
line is not proof it had no market. Report request/response completeness
separately from knowledge of all markets existing at the venue. Replace the
blanket completeness flag with evidence-backed statuses. Reconcile all 26
Monday evidence-bearing games and all available Tuesday captures. Historical
claims must use historical responses; a new live pull cannot repair old T−10
coverage. Keep valid prices visible when matching or reference calculation fails.

### 4. Explain the reference gaps

Trace the 1,546 Monday offer exclusions: 672 missing exact reference pairs and
874 lacking two trusted books. Export per-game/venue/market/line counts and
original evidence. Separate genuine exact-line gaps, absent sides/books,
withdrawals, scope omissions, normalization/matching defects and unresolved
causes. Reconcile the observed-offer census, evaluated offers, exclusions and
qualifying tickets under the implementation's actual counting rules.

Fix data-handling defects while preserving source truth. Keep legitimate gaps
explicit. Do not interpolate alternate lines, loosen trusted-book requirements,
invent fair probabilities or change the method to improve coverage. A corrected
calculation gets new reproducible evidence/run identity; older results remain
available with the reason for the correction.

### 5. Make the trade evidence usable

For each paper opportunity expose the source quote timestamp, request/receipt
and capture clocks, quote age, venue and provider identifiers, native contract
identity where available, exact bet terms, quoted odds, fair probability, gross
EV, Kelly inputs/stake, fee assumption and size evidence. Missing timestamps,
native IDs, fees or depth must have explicit unknown/unavailable states.

Show that current turnover is modeled at zero fees and assumes availability at
the modeled stake. Distinguish quoted-price paper sizing from verified executable
size. If the existing source cannot supply depth or verified fees, expose that
limitation; do not treat unknown as zero or open-ended liquidity. Add useful
cost/size sensitivity only as clearly separate analysis with recorded inputs.
Version any resulting change to qualification or portfolio selection.

### UI, evidence and completion

Use the existing Research → experiment → saved run → game/ticket → original
evidence path, with Data for slate, capture and market reconciliation. Provide
a compact coverage summary with separate population, capture, market, reference
and trade-evidence states, denominators, as-of times and drilldowns. Include
zero-qualifier games. Distinguish current coverage from a saved run's frozen
population and distinguish original task failure from successful reconstruction.
Keep latest-pull and saved T−10 evidence clearly identifiable.

Retain sporting finals independently, including the missing retained Middle
Tennessee–Southern Illinois final if a permitted verifiable source supplies it.
Do not expand this slice into venue settlement, financial results or annual
profitability claims. The priority is recording and accounting for opportunities.

Acceptance checks must cover both dates, excluded non-D1 opponents, zero-EV and
source-only games, reschedules, late discovery, clustered deadlines, storage
pressure, actual pagination semantics, exact-line reference gaps, unknown fees
and depth, immutable replay and variant deduplication. Use proportionate tests,
then the signed-in production UI for date/variant selection, drilldowns,
downloads, Back and reload. Confirm reads/replays cause no hidden provider
collection and submit no orders. Preserve the original corrected Monday run
`db29fca80c85b7f9c7c7ca3a4efcee7eae593513b71a73b88103d31b1186349f` and Tuesday
snapshot `f86e9ad57e5ec5a545a1e4adfcb45e13bba210dbe3fbea7baf2b981f2bd13758`.

Use the relevant existing modules: `app/research/{mens_d1,paper,experiment,
ev_movement,workspace}.py`, `app/storage/mens_d1_coverage.py`,
`app/collection/{mens_d1_jobs,mens_d1_source,experiment_acquisition,
sportsgameodds_worker}.py`, the coverage API and existing Research/Data UI.

Deploy through existing CI and verify server behavior. Stop a collection path
on a real access restriction, exhausted account allowance, explicit source
pause or unsafe storage condition; retain its reason and continue independent
engineering. Do not invent additional review gates or purchase a new plan.
Historical missing quotes may be irrecoverable and venue-wide completeness may
remain unknowable; those facts must remain visible rather than blocking every
other improvement or being labeled complete.

Close out with the exact deployed revision, CI, production walkthrough links,
dated reconciliation exports for both days, before/after counts, demonstrated
causes and fixes, resource measurements, actual API credits/cost, zero orders,
and any still-unverified operating or external dependency. Update the active
queue and assignment with evidence. Finish all authorized engineering before
requesting owner review.

## Implementation and verification record

The coverage view now reports five separate denominators. Research uses the
immutable saved run for offer decisions and paper sizing. Data joins the
current provider ledger and retained independent schedule to that run and
allows selection of a current or saved market census. Game rows retain
excluded participants, missing provider matches, zero qualifiers and schedule
conflicts. Sporting finals are independent evidence.

### Source and game population

Sports Reference access remains disabled. The publisher requires permission
for the intended private tool and the examined environments had neither a
verified grant nor a configured Firecrawl key and allowance for this source.
Firecrawl requests, charges, holds and cost were all zero.
[Sports Reference data use](https://www.sports-reference.com/data_use.html) ·
[Sports Reference automated access](https://www.sports-reference.com/bot-traffic.html)

The permitted alternative was the official CollegeBasketballData public games
exporter. The two displayed pages were retained at 11:49:21.978 AM Eastern on
November 24 with source identity, season and exact Eastern-date filter bounds,
source and upstream game IDs, raw page evidence hash, and observation and
recording clocks. The import attached four immutable receipt records for the
two schedule and two sporting-result revisions from the same browser artifact.
Its SHA-256 is
`2c93ab9fe294d51ee7854702b6f49be140b2733dafbd80cac9047dacb7646f42`.
The app exposes derived facts and original receipt metadata while retaining
the publisher's raw export privately. No account was created, no plan was
purchased, and the offline import made zero API requests. Recurring ingestion
still depends on a configured permitted source. The exporter is unofficial
and both complete expected-slate denominators remain unknown.
[CollegeBasketballData exporter](https://www.collegebasketballdata.com/exporter/games) ·
[CollegeBasketballData terms](https://www.collegebasketballdata.com/terms)

| Dated schedule evidence | November 23 | November 24 |
| --- | ---: | ---: |
| CollegeBasketballData rows | 47 | 86 |
| Season-verified D1 versus D1 source rows | 32 | 77 |
| Excluded source rows | 13 | 9 |
| Source rows with unresolved participant identity | 2 | 0 |
| Exact provider matches among eligible source rows | 27 | 73 |
| Schedule conflicts among eligible source rows | 5 | 3 |
| Eligible source-only listings | 0 | 1 |
| Source rows durably known before their T−10 target | 0 | 72 |
| Expected complete slate | Unknown | Unknown |

The Monday 13 exclusions include a duplicate Seattle–Loyola Chicago time-TBD
placeholder alongside the confirmed occurrence. Separate school evidence
identifies UT Martin–Temple and Stephen F. Austin–Utah Valley for the two
unresolved source rows. Both original placeholders remain visible. Middle
Tennessee–Southern Illinois has a retained CBBD final of 77–76 and a
20-minute start disagreement with the odds provider. Other Monday conflicts
include Southern Utah–Arkansas State (15 minutes), Yale–Belmont (15 minutes),
Colorado State–Arizona (25 minutes), and San José State–UC San Diego
(11:59 PM in CBBD, midnight Eastern in the school and odds-provider evidence).
The source total therefore cannot be turned into a confirmed Monday total by
adding the two corroborated games.

Tuesday's unresolved source times are Evansville–Missouri, Idaho State–Boise
State and Sam Houston–Washington State. Official 9 PM Eastern schedule
evidence is attached separately. Stanford–Colorado is a source-only listing
in the retained November 24 source revision. CBBD lists 11:59 PM Eastern and
the ACC lists 11 PM. Both schools' published local times translate to midnight
Eastern on November 25. The game remains inspectable with all clocks and the
original match disposition. These retrospective observations establish which
evidence exists on each date. They do not backdate Monday source knowledge.

### Capture reliability

The November 23 original eligible ledger contains six frozen captures,
eight misses and 19 refusals. The corrected paper run independently counts
six frozen, 20 reconstructed and seven missing. All 19 paid storage
refusals and the Illinois State–Santa Clara persistence miss have original
responses that support the already-retained reconstruction. Their original
capture outcomes are preserved. Ecclesia–Grambling remains excluded.

The two late discoveries occurred together at 10:51:26 AM Eastern, after
the 10:51 AM deadline. The first NCAAB page of the 10:50 ordinary cycle
arrived at 10:51:25.921 after ordinary pages from other leagues occupied the
shared lane. Earlier provider visibility remains unknown. Five previously
discovered games had a frozen early baseline and zero late claims or
requests. The ordinary ledger shows four, two and three competing ordinary
dispatches in the 6:50, 7:20 and 7:50 PM windows. Earlier accepted claims,
storage refusals, and collector SQL writer-lock timeouts explain observed
pressure on the lane. There is no per-job trace that attributes every
unclaimed interval to one cause. The logged provider responses were HTTP 200.

Illinois State–Santa Clara was claimed at 6:50:47.754 PM, dispatched at
6:50:53.463, received at 6:50:53.899, and finished calculation at
6:50:55.083. Persistence crossed the 6:51 deadline and rolled back. The 19
original paid refusals record `research_retention_capacity` at the former
128 MiB limit. The earlier storage ledger showed about 0.1 MiB unreserved
after protected space. The prior increase to 512 MiB also included
market-publication bytes in future reservations. Per-attempt historical
allocation totals are unavailable.

The collector now protects the serial provider lane from the existing
one-minute request-reservation lead through T−10. Ordinary discovery and
the competing current-pregame owner defer inside that interval. Idle claims
avoid the writer lock. Snapshot calculation and compression happen before
the final locked persistence transaction, which rechecks the task token,
schedule, capacity and deadline. Stage clocks are retained in the acquisition
and refusal evidence. Existing Stop, pause, account, retry and storage guards
still govern requests.

### Returned markets, reference coverage and sizing

| Saved paper evidence | November 23 | November 24 |
| --- | ---: | ---: |
| Evidence-bearing games with retained original bodies | 26 | 3 |
| Returned bookmaker / outcome combinations | 2,035 / 2,184 | 240 / 252 |
| Normalized provider rows | 20,954 | 2,429 |
| Observed paper offers | 6,236 | 683 |
| Evaluated offers | 2,916 | 357 |
| Explicit price unavailable | 1,774 | 210 |
| No qualifying trusted exact pair | 672 | 65 |
| Fewer than two trusted exact pairs | 874 | 51 |
| Evaluated below 4% EV | 2,802 | 345 |
| Best venue tickets and turnover | 76 / $4,497.26 | 8 / $569.73 |
| All venues tickets and turnover | 114 / $5,985.33 | 12 / $775.88 |

All 29 original response hashes match their immutable bytes. Every response
contains the pinned event. The provider paginates events and embeds alternate
lines in the returned event. The event cursor cannot establish unseen venue
lines. Data exposes the request, source hash, returned cells, exact offers,
unavailable or conflicting rows and the reference decision for each book.
Venue-wide market completeness remains unknown.
[SportsGameOdds events](https://sportsgameodds.com/docs/endpoints/getEvents) ·
[SportsGameOdds pagination](https://sportsgameodds.com/docs/guides/data-batches)

All 1,546 Monday saved reference exclusions reproduced. Across different
trusted books, 1,095 show exact lines unreturned alone, 86 show explicit
withdrawals or unavailability alone, and 365 show both. No reference exclusion
required a normalization, matching, or request-scope correction. For
Indiana State–East Carolina, Kalshi's total over 133.5 at −719 remains
inspectable with one qualifying trusted book out of two. EV remains
unavailable for that price. The same reconciliation reproduced all 116
reference exclusions in the saved Tuesday snapshot.

The two saved reports reopened with the same identities and SHA-256 values.
Unrounded 4% EV, exact-line equivalence, reference method, fixed $10,000
bankroll and quarter Kelly remain frozen. Every saved ticket has a recorded
quote age, and all tickets in both saved runs assume $0 modeled fees and
availability at the quoted price for the modeled stake. Actual fees,
executable size and fills remain unverified. Data and Research reads and
saved-run replays recorded zero acquisition requests and zero orders.

### Deployment and signed-in verification

Web, collector and archive are healthy on
`b25586946517674a49d1ee631d3a282e02f50abb`, installed in the
[passing main CI retry](https://github.com/dock108dev/predict/actions/runs/45445919672/attempts/2).
The first attempt passed checks, proxy smoke and build, then stopped at a
GHCR `unknown blob` error before server handoff. The
[failed attempt](https://github.com/dock108dev/predict/actions/runs/45445919672/attempts/1)
remains available. The [initial release](https://github.com/dock108dev/predict/actions/runs/45443809144)
and [first corroboration release](https://github.com/dock108dev/predict/actions/runs/45444804722)
also passed. Additive schema migration 119 was verified against all packaged
migration hashes and applied after a 240,569,648-byte PostgreSQL backup
whose contents list was verified.

The implementation fast check passed 259 portable tests plus 26 subtests and
21 disposable PostgreSQL checks. The additional integrated storage and
experiment run passed 31 PostgreSQL checks. Ten Chromium regressions passed.
The capture fixture verifies simultaneous windows, storage pressure, delayed
persistence and original clock retention. Dated slate fixtures cover excluded
participants, source-only matches, adjacent-date discrepancies, reschedules
and idempotent receipt attachment. The manual test registry audit still flags
the same 18 pre-existing unregistered modules as the starting revision. The
required personal beta checks passed.

A signed-in Chrome walkthrough verified both dates, both portfolio variants,
five games with zero qualifiers, Stanford–Colorado without an odds-provider
match, the official schedule notes, a reference-gap drilldown, source quote
age, modeled fee and size assumptions, and the original evidence route. It
verified downloads, Back, and reload. The Indiana State–East Carolina original
download matched SHA-256
`3e22a2287292f607bcd6fd7d4b6e6b4a36435a8c28c0b4b808196ca847a7baf9`.
Both frozen report identities and contents reopened in read-only PostgreSQL.
No new saved run was created by verification.

- [November 23 in Data](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-23&run=db29fca80c85b7f9c7c7ca3a4efcee7eae593513b71a73b88103d31b1186349f)
- [November 24 in Data](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-24&run=f86e9ad57e5ec5a545a1e4adfcb45e13bba210dbe3fbea7baf2b981f2bd13758)
- [November 23 saved paper run](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-23&run=db29fca80c85b7f9c7c7ca3a4efcee7eae593513b71a73b88103d31b1186349f)
- [November 24 saved paper snapshot](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-24&run=f86e9ad57e5ec5a545a1e4adfcb45e13bba210dbe3fbea7baf2b981f2bd13758)
- [Deadline forecast in Settings](https://predict.dock108.dev/settings#mens-d1-jobs)

### Installed T−10 operating observation

The first available simultaneous window after the final release was
November 24 from 12:20 to 12:21 PM Eastern. Both scheduled games captured on
their first attempt while the installed revision stayed healthy.

| Game | Dispatch | Provider receipt | Checkpoint persisted |
| --- | --- | --- | --- |
| Southeastern Louisiana–Northern Colorado | 12:20:04.306 | 12:20:04.658 | 12:20:07.540 |
| Belmont–Akron | 12:20:11.661 | 12:20:12.636 | 12:20:16.364 |

The observer verified the original response hashes and 91,676 / 97,166 byte
sizes. The full protected lead and window recorded two scheduled
SportsGameOdds event requests, two confirmed object credits, zero ordinary
event dispatches, and zero retries. The engineering reads triggered zero
provider requests and zero orders. The existing metered account supplied the
two credits. An incremental dollar charge per request was unavailable.

At the 12:21 reconciliation, Tuesday's current ledger had five original
captures and 72 upcoming in 77 provider-known eligible games. The saved
snapshot still has three captures and 74 pending. The five current captures
yield 400 of 420 bookmaker / outcome combinations, 1,169 observed offers,
627 evaluated offers and 200 reference exclusions. The two new captures
have 486 observed and 270 evaluated offers. Their offers appear in the
current census with their own checkpoints and receipts.

At 12:21:17 PM Eastern, research had 359,763,004 unreserved bytes of
536,870,912. SQL used 932,985,879 bytes of 4,294,967,296. Host disk free space
was 20,077,854,720 bytes. The earlier forecast observed a 50 requests/minute
provider limit, 50,881 usable objects and no current hold. Interrupted
historical exposure remained accounted for.

The 6:50 PM Eastern deadline cluster forecast showed 25 tasks across sports,
22 NCAAB, 25 maximum single-event requests, and one permitted in-flight
request. It reported 2,946,040 bytes reserved and two tasks without a dedicated
reservation. The pre-release success-only history over 11 captures measured
18.701 seconds per task at p95 and 36.652 seconds queue delay at p95. The
467.523-second serial planning estimate exceeds the 60-second window. The
12:20 observation qualifies two simultaneous tasks only. Evening throughput
remains unverified, and the two late-discovered Monday games still lack
an earlier provider observation.

Private evidence is under `.local/mens-d1-coverage-slice-20261124` and
`.local/mens-d1-20261124`. The dated game reconciliations include both the
current evidence and the saved snapshot. The Tuesday market census includes
current captures acquired after the saved snapshot. Monday's task timing
CSV, both original-response market censuses, replay verification and the
12:20 request/receipt timeline remain separate inspectable artifacts.

- November 23 export contains 54 source and provider audit rows.
- November 24 export contains 94 source and provider audit rows.
- [November 23 coverage download](https://predict.dock108.dev/api/workspace/mens-d1?date=2026-11-23&run=db29fca80c85b7f9c7c7ca3a4efcee7eae593513b71a73b88103d31b1186349f&export=1)
- [November 24 coverage download](https://predict.dock108.dev/api/workspace/mens-d1?date=2026-11-24&run=f86e9ad57e5ec5a545a1e4adfcb45e13bba210dbe3fbea7baf2b981f2bd13758&export=1)
