# Predict private research beta

**Released November 24, 2026 Eastern.** Predict’s private Research, Data and
Settings flows are live. The existing November 23–29 men’s D1 paper experiment
continues automatically on the same campaign. [Weekly research](https://predict.dock108.dev/research?section=experiments&campaign=93b8937a41703ce083609c50e52135019fe36bf082a1f32ecf5a00d54daffeda&variant=best_venue)

## Release and verification

- Application revision `825cf299ded7eb3be4b8031ada47e7170d9fc20c`. The normal
  fast release refused pending migrations before changing services. The
  guarded maintenance release preserved a 306,789,427-byte PostgreSQL backup,
  applied migrations 122 and 123, and verified web, collector, archive and
  database health. The three running image input digests match the checked
  candidate. [Required CI after migration](https://github.com/dock108dev/predict/actions/runs/45542675533/attempts/2)
- Local verification passed 347 portable checks plus 30 subtests, 39 disposable
  PostgreSQL 16 checks, and eight focused Chromium journeys. The final
  missing-capture export follow-up also passed its two API cases and Chromium
  result journey. SQL covered duplicate and reordered result inputs, stale
  leases, correction versions, protected dispatch, and the Monday prior-day
  results and correction jobs for Sunday, November 29.
- Production verification preserved the pre-release hashes for 15 original run
  payloads, saved reports and summaries, 12 definition payloads, and 35 graded
  result versions. The original campaign configuration and collector controls
  matched their pre-release records. The signed-in evidence journeys and
  operational state are recorded below.

## November 23 accounting

| Occurrences and evidence | Count |
| --- | ---: |
| Retained occurrence audit | 46 |
| Eligible games in the named November 23 Eastern cohort | 33 |
| Non-D1 exclusions | 12 |
| Assigned November 24 Eastern | 1 |
| Original T−10 captures / refusals / misses | 6 / 19 / 8 |
| Usable T−10 observations, frozen / reconstructed | 26, 6 / 20 |
| Evaluated games with trades / without qualifiers | 21 / 5 |
| Accepted historical price gaps / retained sporting finals | 7 / 33 |

The named cohort uses the reconciled occurrence ledger. Independent exhaustive
slate coverage remains unverified. Two formerly TBD participants and four
November 23 start clocks have retained corroboration, including the original
source placeholders and clocks. San José State–UC San Diego remains in the
audit as a November 24 Eastern occurrence.

The retained target-event originals support **2,184 requested venue/outcome
cells, 2,035 returned and 149 unreturned** across all 26 usable games. The 149
remain unknown for historical offering. Requested-event retrieval, event
pagination and venue-wide inventory have separate states. Across 6,236 offers,
1,774 were unavailable, 672 lacked trusted exact pairs, 874 had insufficient
trusted books, 2,802 fell below the unrounded 4% screen, and 114 venue offers
qualified. Missing exact books, sides and lines are available in the detailed
census. [November 23 Data and issue history](https://predict.dock108.dev/data?evidence=mens-d1&scope=mens-d1&date=2026-11-23&run=5100a1a827c4e76236489281f67f92e411ce2f8b61495cb9f5e823635b881ea3#mens-d1-issues)

**Concrete repaired case.** Northern Iowa–Davidson first appeared in a retained
provider schedule receipt at 10:51:25.921 AM Eastern. The original window had
closed at 10:51 AM. The signed-in Data form saved an accepted historical gap
against that evidence revision. The final and missed task remain visible after
reload. Its game-row export withholds financials. A genuinely new original
observation in the qualifying window can resurface the issue.

The other six accepted gaps are St. Bonaventure–Appalachian State, Georgia
Southern–Northern Kentucky, Central Arkansas–North Florida, Texas A&M–Corpus
Christi–Wichita State, Denver–Kansas and Stephen F. Austin–Utah Valley. The
first has the same retained late-discovery timing as Northern Iowa–Davidson.
The five later games have early baselines and no retained late claim or request
at their target. All seven retain their finals and cohort membership.

| Pinned November 23 portfolio | Graded tickets | Staked | Modeled P/L |
| --- | ---: | ---: | ---: |
| Best venue | 76 | $448.68 | −$45.44 |
| All qualifying venues | 114 | $596.34 | −$135.28 |

The saved runs retain the original exact-line reference, 4% unrounded minimum,
1/40 full Kelly on $10,000, and recorded zero-fee/quoted-size assumptions.
Freshness uses original receipt time minus the provider book timestamp. The
inclusive 0–60-second exploratory analysis filters all venue candidates before
best-venue reselection. It retains 106 of the 114 All-venue tickets. Four were
older than 60 seconds through 300 seconds, and four were older than 300 seconds.
The Best portfolio changes from 76 to 75 selections after reselection. The
unrestricted portfolios remain pinned. Actual fees, executable size, and
unavailable venue-native contract identities remain unverified.
[November 23 results](https://predict.dock108.dev/research?section=experiments&scope=mens-d1&date=2026-11-23&run=5100a1a827c4e76236489281f67f92e411ce2f8b61495cb9f5e823635b881ea3)

## Operating evidence

The production campaign has one durable row per Eastern game date. As of
10:59 PM Eastern on November 24, November 23 was graded, November 24 was
published and partially graded, and November 25–29 were scheduled. Weekly
totals count each latest daily snapshot once, and earlier snapshots and grade
versions remain linked. The restarted worker claimed its due November 24
check at 10:58:40 PM and completed it at 11:04:14 PM, retaining the same
selection snapshot. At 11:06:07 PM the grader published a new result version
for that run with 66 retained finals and 331 graded All-venue trades. The day
remained partially graded, and the previous grade version remained available.

The next independent slate refresh is November 24 at 11:45 PM Eastern, ahead
of the first known protected T−10 target at 11:50 PM for the November 25 slate.
The scheduled November 24 prior-day finals and correction turns are November 25
at 5:30 AM and 12:30 PM Eastern. The same rule puts November 29 finals at
5:30 AM and corrections at 12:30 PM Eastern on November 30, with the unresolved
follow-up at 5:30 AM on December 1. Those future arrivals remain operating
observations. [Collection and results jobs](https://predict.dock108.dev/settings#mens-d1-jobs)

The post-restart ledger observed 20 more retained SportsGameOdds responses and
37 more confirmed objects than the pre-release read. At 10:54:54 PM Eastern,
from November 23 midnight Eastern across the configured collection scope,
the ledger held 4,265 traced responses and 7,640 confirmed objects, including
5,766 for NCAAB discovery. Two retained responses belonged to interrupted
attempts. The period had four objects of uncertain exposure. The account
snapshot had 48,629 objects available, zero current holds and 99 interrupted
objects carried in the account window. CBBD recorded five requests and five
metered calls with zero held. Its latest observed allowance was 996 of 1,000
calls in the shared CBBD/CFBD window. Stop was off, dispatch was enabled and
no sources were paused. Research had 406,198,890 retained bytes and 80,129,113
reserved, leaving 1,661,155,645 under the 2 GiB research cap. SQL measured
944,405,527 bytes against 4 GiB. These measurements come from the existing
guarded collection, whose caps remain 300 per 15-minute cycle and 16,800 per
operating day.

The production browser exercised week → day → game → trade → frozen receipt
→ week, Back and reload, at 1400px and 390px. It reconciled exact stakes, returns,
expected profit and P/L across tickets, games, venues, provenance, days and EV
buckets. One owner-form disposition and 98 audited applications produced 99
saved decisions. A sampled market detail/export matched the published card.
Both journeys made 102 passive first-party browser requests in total, with no
browser errors. Research reads, exports, audit and census publication used
zero provider requests and zero submitted orders. Public Research and Data
returned HTTP 401 without the owner session.

The next protected capture, later daily finals and subsequent corrections
remain natural operating observations. The optional full-suite inventory
diagnostic separately reports 20 pre-existing test classification omissions.
The local output is retained and the focused beta tests run in required CI.
