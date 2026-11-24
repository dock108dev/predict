# Men’s D1 daily coverage and November 23–24 verification

Status: active follow-on implementation assignment, prepared November 24, 2026. See the implementation and verification record below for the result at this milestone.

## Outcome

Implement, integrate, deploy and verify a daily men’s Division I college-basketball schedule/result import and a usable coverage view in Predict. We need to inspect November 23 and November 24, 2026 and account for every source-declared eligible game: matched, unmatched, scheduled, captured, missing, excluded, final or unresolved. Finish the engineering and production walkthrough before requesting owner review.

This assignment covers game inventory, sporting results, scope correction and coverage. Preserve the existing EV calculation and sizing policy. New models, a year-long backfill, probability blending, execution/depth qualification and real betting are outside scope.

## Baseline and preservation

- Work in `/Users/michaelfuscoletti/Desktop/prediction-arb`, on `main`, in this one working copy. Starting revision: `4cc9f745c193b3ef03a2fac1a589f510f1a4a566`; verify HEAD and preserve any later work. Existing CI: https://github.com/dock108dev/predict/actions/runs/45422813178/attempts/2.
- Production: https://predict.dock108.dev. Research is the landing page; use the existing Research, Data and Settings structure.
- Read `AGENTS.md`, `docs/CI.md`, `docs/paper-experiments.md`, `docs/ev-checkpoint-experiment.md` and `docs/monitor-live.md`. The older model backlog remains deferred except for the game inventory/result work explicitly assigned here. Historical 128 MiB figures are not current configuration: the code currently allocates 512 MiB under existing SQL/disk guards. Recheck actual headroom.
- Preserve evidence, saved runs, credentials, owner authentication, Stop/source pauses, settings, quota/account windows, reservations and unresolved holds. No reset, destructive migration, worktree or new subscription/tier.
- Preserve the existing four trading venues, reference books, other sports and acquisition guards. The new men’s D1 restriction applies to this CBB research scope; do not disable unrelated collection.

Existing November 23 recovery run:
https://predict.dock108.dev/research?section=experiments&run=85dd517e0f454701f281c0ada636607d738f6ed5538a2801dc8ad00f69ed40bb

It records the old scope: 34 tracked games, seven frozen T−10 captures, 20 retrospective raw-response reconstructions and seven missing games. Best venue has 76 tickets/$4,497.26; All venues has 114/$5,985.33. Of the 114, 22 came from original frozen calculations and 92 from later reconstruction. These are preservation baselines, not expected counts for the corrected scope.

Starting code: `app/collection/sportsgameodds_worker.py`, `experiment_acquisition.py`, `current_schedule.py` and `sgo_game_results.py`; `app/research/experiment.py`, `records.py`, `paper.py`, `workspace.py` and `recovery.py`; `app/normalization/college_registry.py`; `app/storage/sgo_schedule_review.py`; `app/dashboard/research_workspace_api.py` and `workspace_routes.py`; and the current `data*.js`, `research-workspace.js`, `research-run.js` and `settings.js` under `app/dashboard/opportunity_static/current/`. Trace actual ownership and reuse these seams rather than building a parallel application.

## 1. Declare the population correctly

Include men’s Division I versus Division I games, including neutral-site and tournament games. Exclude women’s games and D1 versus non-D1 games. Use season-specific membership with retained provenance; rankings, presence at a bookmaker or a name match do not establish D1 status. Keep unknown membership unresolved.

Record membership and exclusion reasons for both participants. Ecclesia–Grambling in the old Monday run is an explicit exclusion case. Publish a new versioned men’s D1 definition/run; keep the old run and all original evidence accessible. Independently derive the new counts—do not hardcode 33 games or unchanged ticket totals.

Keep unrounded EV ≥4%, quarter Kelly against the fixed $10,000 sizing reference, no aggregate cap and no intraday compounding. Reprice at the modeled size under the frozen fee assumption. Best venue selects the highest qualifying sized EV for each exact bet across venues; All venues retains each qualifying venue once. Different lines and material settlement terms stay distinct. The scope/membership version and source population revision must participate in saved-run identity and reuse checks.

Use America/New_York game dates and retain original source date/time/timezone. Handle midnight, DST, postponements, cancellations and schedule revisions. Match source team IDs through reviewed aliases, participant pairs and date/time/site evidence. Neutral-site or reversed display order must not swap scores, contract sides or frozen probabilities. Ambiguous matches stay visible and cannot grade tickets.

## 2. Validate Sports Reference through Firecrawl

Preferred candidate for schedule/results: Sports Reference. Use its dated schedule page for upcoming matchups and its dated box-score index for completed games. Inspect actual links and page structure; do not assume the box-score index contains every upcoming game.

- November 23 schedule: https://www.sports-reference.com/cbb/seasons/schedule.cgi?day=23&month=11&year=2026
- November 24 schedule: https://www.sports-reference.com/cbb/seasons/schedule.cgi?day=24&month=11&year=2026
- Box-score index: https://www.sports-reference.com/cbb/boxscores/
- Example overtime detail: https://www.sports-reference.com/cbb/boxscores/2026-11-23-21-providence.html

The schedule mixes men’s and women’s rows. Apply explicit men’s classification and the D1 membership filter. Retain returned-but-excluded rows for the coverage audit.

Inventory the existing Firecrawl account, credentials and recorded limits securely. Test actual retrieval with a small sample of these dated pages and one linked completed box score. Direct web-tool fetches returned 403 during planning; Firecrawl access has not been demonstrated. Review the current source rules: https://www.sports-reference.com/data_use.html and https://www.sports-reference.com/bot-traffic.html. Record whether the intended private hosted use is covered; a rate threshold alone does not establish reuse permission.

Use Firecrawl’s targeted Scrape endpoint, fresh retrieval (`maxAge: 0`), raw HTML and links, and deterministic parsing for teams, dates, scores and status. Avoid a broad site crawl or AI-generated numeric extraction. Use slow sequential requests, bounded retries and actual credit accounting. Preserve the original returned artifact, final URL/status, request/receipt times, hash and parser version. Never retain credentials in artifacts.

Reject block/challenge/login pages, wrong dates and malformed layouts as acquisition failures. An empty or failed extraction is not a verified zero-game slate. If access, credentials or source-use permission remains unresolved, report the exact external dependency, finish independent engineering and keep the unverified source disabled. Do not silently substitute another source or claim live verification from fixtures.

## 3. Implement server-owned daily acquisition

Reuse the existing collector/runtime and persistence owners. The server runs these jobs with the browser closed; do not implement a chat automation or a timer that requires an open page.

- Fetch the current Eastern date’s schedule early enough to precede the first game; retain a versioned source-declared slate.
- Refresh the schedule before the first tipoff and perform bounded reconciliation for later changes. Keep additions/removals and their first-known times.
- Import the prior date’s results each morning. Recheck unresolved recent games under an explicit bounded retry horizon, including games crossing midnight. Preserve corrections as new revisions.
- Start with daily index pages. Fetch individual box scores when final status, overtime, identity or score details require confirmation. Store the reason and cost for each extra request.
- Make jobs durable and idempotent by source/date/purpose, safe after restart, with visible last success, next run, errors and retry state. Coalesce missed daily work without catch-up bursts.

Imported schedule games establish expected membership even if SGO has never listed them. Reconcile both directions with the odds provider. Record missing provider identity, no market observed and identity/schedule conflicts explicitly. A new source does not create historical quotes or repair a missed T−10 capture. Retarget future captures only through the existing verified schedule-revision path.

An unmatched expected game keeps its own source identity. Do not invent an odds-provider ID, frozen quote or capture task to make it appear matched.

Preserve :20/:50 odds discovery and the T−10 to T−9 capture window. Daily parsing/result jobs must not starve price capture. Forecast storage and request demand for upcoming games; keep protected late reservations and existing account limits intact. Browsing, filtering and exporting cause no provider calls.

## 4. Store evidence and results without changing history

Keep immutable source receipts, parsed schedule/result revisions and reviewed canonical bindings. Minimum fields: source/native game and team identifiers, source URL, gender/division evidence, season, date/start/site, status, final scores, overtime/period detail when supplied, source update time when actually published, our observation/recording time, parser version and receipt hash.

Keep scoreless, postponed, cancelled, incomplete and conflicting results explicit. Missing period detail stays missing. Preserve competing result sources and expose disagreements; do not overwrite an existing result silently. Sporting results do not establish venue settlement or actual P/L.

Ingest and verify results in Data. Keep the existing opportunity-only run unresolved and unchanged. Any results-linked paper evaluation must be a separate saved analysis using the existing grading rules and exact source result revisions. New KenPom probabilities and model-derived spread/total probabilities are outside this assignment.

## 5. Make the UI answer the coverage question

Use existing Data and Research → Experiments rather than creating another top-level app.

- Add a dated men’s D1 coverage view: source-declared expected games → provider matches → scheduled/due captures → original frozen captures → retrospective reconstructions → EV-evaluated/qualifying offers → available results.
- Keep those populations distinct and make every count drill into its cases and reasons. Source-declared completeness is not automatically universal real-world completeness.
- Show a row for each eligible game, including no odds and zero qualifying offers. Offer filters for missing, unmatched, upcoming, missed/refused, reconstructed, excluded, final, unresolved and conflicting cases.
- Show source and observation ages, capture target/receipt/persistence clocks, and original evidence/export links. An old quote inside a new response remains visibly old.
- Preserve date, men’s D1 scope, game and saved run through Research/Data links, Back and reload. Avoid the current confusion between a dated experiment, the rolling multi-sport historical list and a single latest odds pull.
- Make November 23 and 24 directly selectable. Keep old versions reachable and the scope correction explained beside the new version.
- Put acquisition status, next jobs, credits/cost and retention headroom in Settings. No model blend, new sizing interface or unrelated navigation redesign.

## 6. Verify both dates and deploy

Produce a reproducible reconciliation for November 23 and November 24, 2026, with an explicit Eastern as-of time. For each date report source-returned men’s games, D1-eligible games, excluded/unverified membership, provider matches, source disagreements, original captures, raw recoveries, pending/missed/refused captures, qualifying tickets and final/unresolved/conflicting results. Name every unresolved game and reason.

November 23: verify the eligible population and available final results against retained source evidence. Recompute both paper variants under the corrected scope and unchanged 4%/quarter-Kelly policy. Preserve the distinction between original frozen EV and calculations reconstructed later. Do not backdate a schedule first seen today into Monday’s known population.

November 24: verify the slate and all evidence available at execution time. Future games remain pending until their capture/result windows; do not label them missing or invent final scores. Prove future daily/result follow-ups are durably scheduled. This assignment can finish with an honest as-of report; it does not require waiting for every November 24 game to end.

Use focused parser, disposable SQL and integration checks for: mixed men/women; D1/non-D1 and unknown membership; neutral/reversed teams; aliases; midnight/reschedules; final versus predicted scores; OT/missing periods; blocked versus empty pages; corrected/conflicting results; restart/idempotence; protected capture scheduling; unchanged historical runs. Test source-change invalidation of saved-run reuse and responsive reopening of unchanged runs. Keep long imports/evaluations in owned background work when needed instead of leaving a browser request to time out.

Commit/push through normal main CI, deploy to production, and perform the signed-in user flow: select each date, inspect coverage and exclusions, trace an eligible game to source evidence and a final result where available, inspect an unmatched/missing case, reopen the corrected experiment, switch variants, export and reload. Confirm reads caused no acquisition and no real orders. Distinguish local fixtures, real source retrieval, hosted CI, production integration and fresh scheduled operating evidence.

## Closeout

Update this assignment and the active queue with the deployed revision, CI URL, direct November 23/24 links, source/canonical reconciliation counts, source-read cost, screenshots and unresolved named cases. Explain the important discoveries and code decisions. Report any missing future scheduled observation or external source dependency precisely. Do not call coverage complete while the denominator, source access, identity or required evidence remains unverified. Finish all unblocked implementation and verification before asking for owner review.

## Implementation and verification record

The existing production run contained 34 tracked games, seven original frozen
captures, 20 recovered raw responses and seven missing games. Its two variants had
76 tickets and $4,497.26 in modeled commitments, and 114 tickets and $5,985.33,
respectively. The baseline was checked by a read-only production SQL snapshot at
10:44:58 AM Eastern on November 24. Research had 150,411,202 retained bytes
and 14,689,022 reserved bytes of 536,870,912. Database usage was 894,180,375
bytes of 4,294,967,296, with 20,717,051,904 bytes free on the host volume.

The corrected run inherits the original fee assumptions and sizing policy. Its
input is the original saved run's schedule and capture IDs plus season-specific
membership evidence. The review identified Ecclesia–Grambling as outside the
population. This game had a frozen capture and zero qualifying offers in the
original. The correction retains the original run and makes the exclusion
auditable even while Sports Reference acquisition is off.

### Sports Reference access

Direct automated inspection returned HTTP 403. A normal Chrome view opened the
dated schedule, box-score index, and Providence–VCU detail. The dated schedule
uses mixed-gender rows with a shared Eastern time label. Lower-division opponents
can be unlinked text. The result index publishes upcoming and final cards, can
put the winner first, and can report a final without linking a detail page.
Providence–VCU has separate regulation and overtime values in the detailed line
score. These observations qualify the layout only.

Sports Reference's [data-use policy](https://www.sports-reference.com/data_use.html)
requires permission for tools built from scraped data. Its
[automated access policy](https://www.sports-reference.com/bot-traffic.html)
governs access rates separately. No grant for retaining and serving this data
through the private hosted Predict app was found. The configured repository,
developer environment, and hosted provider-secret mount did not contain a
Firecrawl key or a recorded allowance for this use. Firecrawl had zero requests
and zero credits charged. Sports Reference collection remains disabled until
the private hosted use, existing Firecrawl account and budget, and targeted
retrieval are verified. As a result, the source-declared denominator and
cross-source reconciliation remain unavailable for both dates.

### Direct links

- [November 23 men’s D1 coverage](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-23)
- [November 24 men’s D1 coverage](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-24)
- [Original November 23 opportunity run](https://predict.dock108.dev/research?section=experiments&run=85dd517e0f454701f281c0ada636607d738f6ed5538a2801dc8ad00f69ed40bb)

### Retained November 23 evidence

In the restored production database, the corrected original population
contained 33 season-verified games, one excluded game and zero games with
unverified membership. The corrected variants still produced 76 tickets and
$4,497.26 in Best venue, and 114 tickets and $5,985.33 in All venues. All
venues comprises 22 tickets from six original captures and 92 from 20 raw
reconstructions. Best venue comprises 14 and 62 tickets, respectively. The
retrospective calculations inherited the original explicit fee assumptions. Each
ticket's economic fields and evidence matched the corresponding original ticket.

Seven eligible games in the original population had no eligible retained
T−10 response.

| Game | Reason retained by the capture owner |
| --- | --- |
| St. Bonaventure at Appalachian State | Discovered after the pre-target baseline |
| Northern Iowa at Davidson | Discovered after the pre-target baseline |
| Georgia Southern at Northern Kentucky | Capture window missed |
| Central Arkansas at North Florida | Capture window missed |
| Texas A&M–Corpus Christi at Wichita State | Capture window missed |
| Denver at Kansas | Capture window missed |
| Stephen F. Austin at Utah Valley | Capture window missed |

Retained SGO evidence contained 32 finals for these 33 eligible games. Middle
Tennessee–Southern Illinois is the game without a retained SGO final.
Southern Illinois independently reported the 77–76 Middle Tennessee win, and
VCU independently reported Providence's 72–66 overtime win. These checks did
not enter either result into a new source ledger. San José State's 88–79 result
against UC San Diego was listed as November 24 in the Eastern SGO view, and the
school described the game as Monday night in California.
[Southern Illinois recap](https://siusalukis.com/news/2026/11/23/mens-basketball-southern-falls-to-middle-tennessee-in-77-76-heartbreaker)
· [VCU recap](https://vcuathletics.com/news/2026/11/24/mens-basketball-rams-drop-overtime-heartbreaker-to-providence.aspx)
· [San José State recap](https://sjsuspartans.com/news/2026/11/24/masons-31-points-leads-spartans-past-uc-san-diego-to-close-out-acrisure-series).

### Production reconciliation, November 24 at 11:09 AM Eastern

The private release installed `0e26f88bac69f0e7984a2dbeba46712a0ce3e9db` in
web, collector and archive. The [main CI run](https://github.com/dock108dev/predict/actions/runs/45432360098/attempts/2)
passed after the backed-up additive migration. The first attempt passed the
focused checks and published the images, then stopped before server handoff
under the existing CI timing guard. The guarded maintenance step retained a
234,777,180-byte PostgreSQL backup, verified its contents list, and validated
every packaged migration checksum before appending migration 118.

| Evidence | November 23 | November 24 |
| --- | ---: | ---: |
| Sports Reference returned men’s games, eligible slate, matches, disagreements and finals | Unverified | Unverified |
| Retained odds-provider men’s games | 34 | 81 |
| NCAA D1 versus D1 within the retained provider records | 33 | 77 |
| Excluded within those records | 1 | 4 |
| Unverified membership within those records | 0 | 0 |
| Eligible frozen T−10 captures | 6 | 3 |
| Eligible raw T−10 reconstructions | 20 | 0 in saved snapshot |
| Eligible games without frozen/reconstructed coverage | 7 elapsed | 74 pending |
| Eligible original task refusals | 19, all reconstructed | 0 as of observation |
| Eligible provider-observed finals | 32 | 1 |
| Eligible provider results pending or unresolved | 1 without a final | 76 pending |
| Evaluated offers | 2,916 | 357 |
| Best venue | 76 tickets / $4,497.26 | 8 tickets / $569.73 |
| All venues | 114 tickets / $5,985.33 | 12 tickets / $775.88 |

One Monday reconstruction had an original missed disposition. The other 19
had original refusals. The original capture ledger therefore shows eight misses
and 19 refusals, while the corrected paper run has seven games with missing price
evidence. The November 24 saved snapshot is a paper analysis of retained
provider records at that time. It leaves the schedule denominator unverified.
Vermont State Randolph–Stonehill, Penn State Berks–Navy, Bloomsburg–Wagner
and Emerson–Quinnipiac were excluded from the retained November 24 scope.

The corrected Monday calculation recomputed both variants in 103.5 seconds
on production. Repeating it reopened the same run in 0.37 seconds. Every
economic and witness field matched the original eligible ticket. Original
T−10 response bytes were retrieved for the Long Beach State–FIU reconstruction.
The exact retained SGO final responses for VCU–Providence and UC San Diego–San
José State were retrieved and verified by their original receipt hashes. No
Sports Reference receipt or cross-source conflict assessment is available.

- [Corrected November 23 run](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-23&run=db29fca80c85b7f9c7c7ca3a4efcee7eae593513b71a73b88103d31b1186349f)
- [November 24 retained-provider snapshot](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-24&run=f86e9ad57e5ec5a545a1e4adfcb45e13bba210dbe3fbea7baf2b981f2bd13758)

The collector persisted the November 24 afternoon and evening schedule
reconciliation jobs and the November 25 5:30 AM Eastern result import for the
November 24 slate. These jobs have zero Sports Reference dispatches and stay
subject to the source's disabled state. The operating forecast included 87
protected late tasks across sports, of which 81 were college basketball.
Research had 365,450,530 bytes of unreserved headroom against its 512 MiB
allocation. SQL usage was 972,774,423 bytes against its 4 GiB cap. The host
volume showed 20,294,918,144 free bytes. Scheduled job rows and observed source
requests are separate evidence.

### Final deployment check

Web, collector and archive were healthy on
`c75ffcd52707699a7615decea903feadf799f376` after the
[follow-up main CI release](https://github.com/dock108dev/predict/actions/runs/45434711197).
Settings showed the next scheduled job at 12:30 PM Eastern and three past-due
jobs still inside their windows, with the Sports Reference source disabled.
The collector had already persisted the job rows before the walkthrough.
The stored run identity reopened the same correction under both UTC and
American Eastern database session timezones.

The signed-in flow covered both dates, the Ecclesia exclusion, an original
provider final response, an elapsed capture, both Monday paper variants,
coverage and paper downloads, Back, and reload. Exports reported zero provider
requests and zero orders. A separate server read after the walkthrough
confirmed zero Sports Reference requests, charges and holds. The original
response downloaded through Data matched its retained SHA-256.

Local evidence in `.local/mens-d1-20261124` includes
`production-game-reconciliation.csv` (all 115 retained game rows and reasons),
browser exports, `production-november-23-experiment.jpg`,
`production-november-24-coverage.jpg`, and `production-daily-jobs.jpg`.
The full feature's focused local lane passed 309 portable tests and 16
disposable PostgreSQL checks. The follow-up passed 161 portable and 11
disposable PostgreSQL checks before hosted release. Results from a live
Sports Reference run remain unverified.
