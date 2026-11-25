# November 23 data audit and resolution plan

Planning only: no application code, production evidence, original capture tasks,
saved run or experiment definition changed. Read-only production audit at
November 24, 2026, 10:21 PM Eastern. Current deployment: `3743a873`.

## Outcome and accounting

Close the one-day pilot with every known occurrence and offer accounted for.
Accept explicit historical/source limits rather than requiring a line at every
venue, deleting unknowns, or continually treating resolved history as active work.
Accounted-for coverage and successful capture coverage must stay separate.

The current November 23 occurrence ledger has 46 rows: 33 eligible on-date
men’s D1-versus-D1 games, 12 non-D1 exclusions and one game assigned to
November 24 Eastern. No on-date occurrence has unresolved membership or date.
The 33 are a reconciled observed cohort; an independently exhaustive slate is
not established. Adopt that named cohort as the pilot’s operational denominator
and retain the full-slate limitation without pretending it invalidates the run.

The 33 games reconcile to six frozen captures, 20 reconstructions and seven
historical price gaps. All 33 have retained sporting finals. Of the 26 games
with usable price evidence, 21 produced qualifying tickets and five produced
zero qualifying tickets. No evidence-bearing game had zero returned offers.

Offer accounting: 6,236 = 1,774 unavailable + 1,546 reference-ineligible +
2,802 below 4% + 114 qualifying venue offers. The 2,916 evaluated offers are
the 2,802 below-threshold and 114 qualifiers. The Best portfolio has 76 tickets;
the All portfolio has 114. Missing prices never become zero-EV or zero-P/L rows.

The reviewed saved run is
`5100a1a827c4e76236489281f67f92e411ce2f8b61495cb9f5e823635b881ea3`,
the November 23 member of the November 23–29 campaign with 1/40 full Kelly.
Earlier quarter-Kelly runs remain immutable.

## 1. Correct misleading current status and count projections

- Daily headline and default facets must count on-date eligible occurrences.
  Current facets report 34 eligible and 34 source finals while the result ledger
  correctly counts 33. San José State–UC San Diego belongs to midnight Eastern
  November 24; keep its source disagreement in audit history and link to that
  date. It must not inflate Monday's eligible/final headline.
- Current raw-source match counts still contain two unresolved TBD participants
  even though official occurrence evidence resolves UT Martin–Temple and
  Stephen F. Austin–Utah Valley. Show raw-source counts separately from current
  reconciled decisions. Do not create unresolved membership work for those two.
- Four Monday start disagreements have official/provider corroboration:
  Middle Tennessee–Southern Illinois, Southern Utah–Arkansas State, Yale–Belmont
  and Colorado State–Arizona. Mark their operational schedule decision resolved
  by corroboration, preserving the differing CBBD clocks and the exact original
  capture target. The fifth raw warning is the other-date San José game.
- The 12 non-D1 occurrences remain excluded with membership evidence. Missing
  scores or absent capture tasks on these rows do not block this experiment.

Acceptance: 33 eligible Monday games, 33 finals, zero unresolved on-date
membership/date decisions, four corroborated historical clock disagreements,
12 exclusions and one other-date occurrence available in audit filters.

## 2. Preserve usable reconstructions; close seven historical price gaps

Original capture reliability is six successful, 19 refused for retention and
eight missed. Paper usability is six frozen, 20 reconstructed and seven missing.
Those are different dimensions. All 19 refused games and the Illinois State–
Santa Clara late-persistence case have usable reconstructed evidence; preserve
the original refusal/miss while showing “usable reconstruction” and a closed
historical capture issue. Reconstruction must not become a live-capture success.

Accept these seven as historical T−10 gaps after the already-completed receipt
review; reopen only if original evidence within the original window is found:

| Game | Evidence and proposed disposition |
| --- | --- |
| St. Bonaventure–Appalachian State | Late discovery; first retained observation 10:51:25.921 AM, after 10:51 deadline. Historical gap; earlier upstream availability unknown. |
| Northern Iowa–Davidson | Same late-discovery timing and historical-gap disposition. |
| Georgia Southern–Northern Kentucky | Early baseline, no retained late claim/request at 6:50 PM. Accept historical gap. |
| Central Arkansas–North Florida | Same absent late dispatch at 6:50 PM. Accept historical gap. |
| Texas A&M–Corpus Christi–Wichita State | Early baseline, no retained late claim/request at 7:20 PM. Accept historical gap. |
| Denver–Kansas | Early baseline, no retained late claim/request at 7:50 PM. Accept historical gap. |
| Stephen F. Austin–Utah Valley | Same absent late dispatch at 7:50 PM. Accept historical gap. |

Retain their finals and presence in the 33-game denominator. Exclude them from
EV calculations, trade counts and P/L; do not assign fictional zero trades or
use opening/closing/today’s odds as T−10. Keep a frozen-only result comparison
alongside the frozen-plus-reconstructed retrospective report. This is a
provenance comparison, not evidence that either subset is more profitable.

Prevention work is operational: earlier independent slate discovery, retained
provider visibility observations, protected T−10 dispatch and reserved storage.
The repaired 25-member live capacity remains an operating observation to obtain
when a comparable natural cluster occurs; it cannot repair Monday.

## 3. Distinguish absent lines from absent observations

Do not expect every game, market, exact line or venue to have odds. Define the
paper universe as the declared provider, venues, families, period and T−10 window.
The daily schedule population must include games without odds; schedule discovery
must not depend on a positive-EV or currently-available-odds filter.

Use these separate terminal outcomes, scoped to venue/market/time:

- Observed and evaluated; zero qualifiers is valid completion, not missing data.
- Explicitly unavailable/withdrawn: no usable price at the observation time.
- No odds present in the declared provider response: no provider line observed,
  supported by a successful event response and the applicable odds-presence flag.
  This does not establish that every sportsbook lacked a line.
- Requested but unreturned: unknown offering; accept a bounded source-coverage
  limitation when no authentic historical witness exists. Never relabel as no line.
- Not requested, unsupported, failed or missed: distinct scope/collection states.

The five valid zero-qualifier games are Middle Tennessee–Southern Illinois,
Illinois State–Santa Clara, Fairleigh Dickinson–Iona, Winthrop–Illinois and
Seattle–Loyola Chicago. Retain all five as evaluated games, including their
available prices, exclusions and finals.

## 4. Repair the market summary; accept bounded inventory limits

The daily summary reports unknown retrieval on all 26 games and zero countable
requested/returned cells. The detailed raw census establishes 26 retained event
responses with 2,184 requested cells and 2,035 returned cells: 149 unreturned.
All 26 current checkpoint identities are present in the archived census; the
only extra archived game is the excluded Ecclesia–Grambling occurrence.
A fresh production census for Indiana State–East Carolina reproduced every
prior summary measure and now explicitly says all requested events returned.

The defect is the old compact checkpoint coverage summary not carrying the
later verified census, not evidence that all games lost markets. Publish a
derived, versioned census summary from retained bytes in background work;
reuse it in daily cards, game detail and exports. Avoid re-parsing all archived
responses on every browser render or changing the original checkpoint payload.

Event pagination and venue inventory are separate. The census shows unfollowed
event cursors; all target event objects were returned. Cursors do not establish
missing pages of alternate lines inside an already-returned event object.
Future discovery must traverse event pages/deduplicate IDs and explicitly account
for omitted requested IDs; exact-ID batches should validate every requested
event. An advertised cursor can survive even when no additional events remain.

Close the 149 cells as “unreturned; historical venue offering unknown” unless
existing same-time evidence resolves them. Keep full venue inventory as an
accepted provider-scope limitation, not 26 active engineering failures. Retain
the 1,774 explicitly unavailable offer rows as legitimate excluded observations.

Provider references:
[events parameters](https://sportsgameodds.com/docs/endpoints/getEvents) and
[event pagination](https://sportsgameodds.com/docs/guides/data-batches).

## 5. Accept reference exclusions under the frozen probability method

The 1,546 exclusions comprise 672 without an exact pair and 874 without enough
trusted books. Detailed causes are 1,095 exact-line omissions only, 86 explicit
unavailability only, and 365 both. The prior raw/normalized audit reproduced
the dispositions without normalization/projection loss. These are unavailable
inputs under the selected method, not 1,546 broken calculations.

Close these as method-ineligible offers, preserving the exact missing book,
side and line. Do not drop the whole game or infer probability from a nearby
line. Different reference books, one-book rules or interpolated lines belong
to separate prospective definitions/exploratory replays, not a repair to Monday.

## 6. Expose freshness and paper execution assumptions

All 114 selected All-venue quotes have source timestamps. Quote age at receipt
ranges from 2.14 to 754.73 seconds; eight exceed 60 seconds and four exceed 300
seconds. All four over 300 seconds are ProphetX quotes. An old timestamp does
not prove a quote was untradeable, but the current paper rules have no freshness
screen, and source freshness matters to the EV interpretation.

Add an explicitly exploratory <=60-second price-age comparison and age buckets,
with missing/future clock anomalies distinguished. Keep the original unrestricted
definition. If adopted for new experiments, freeze target and reference quote
age, timestamp basis and comparison clock before selection and rerun best-venue
selection from the qualifying pool. Review reference ages as well as target ages.
Do not remove a venue merely because its realized losses look unattractive.

All tickets retain modeled zero fees and unverified achievable size; no actual
fee or executable-size witness exists. Missing venue-native contract IDs remain
unknown where absent. Accept these as limits for this pipeline/paper experiment.
A fee/depth/contract-qualified experiment needs same-time venue evidence and a
new definition. Sporting finals are complete; venue fills/settlement are separate.

## 7. UI resolution workflow and completion checks

On the November 23 experiment show a compact coverage funnel: 33 reviewed games
→ 26 usable T−10 games (6 frozen, 20 reconstructed) → 21 with trades and five
without qualifiers; seven historical gaps remain visible. Show results 33/33.
Label the cohort/source basis and accepted full-slate limitation next to coverage.

Provide a per-item disposition with evidence, reason, decision time and version:
open, resolved by evidence, accepted historical gap, accepted source limitation,
excluded by scope, and assigned another date. These adjudications belong beside
original facts; they must not overwrite immutable capture states or prior runs.
Offer “accept gap,” “exclude with scope evidence,” and “reopen” through the UI,
with a reason and evidence link. Default the issue list to actionable unresolved
items, with accepted/resolved history one click away. Keep outcome and data-quality
decisions separate so a losing ticket is never an exclusion reason.

Verify: every 46-row occurrence disposition accounts exactly once; eligible
counts are date/scope consistent; offer counts reconcile to 6,236; price gaps
never appear as zero opportunity or zero financial outcome; reconstructed issues
can be closed without rewriting failed tasks; no-line needs positive scoped
evidence; summaries and detail agree; UI decisions survive reload/export; prior
run hashes and financial totals stay unchanged. The original $448.68 Best and
$596.34 All commitments at 1/40 Kelly remain pinned to this run.

Implement in order: corrected scope/status projection and derived census summaries;
versioned dispositions and UI closure; quality comparisons; prospective collection
verification. There is no need to obtain real fills or exhaustive global market
inventory to close the pilot honestly.

## Audit artifacts

`.local/nov23-gap-audit-20261124/production-coverage.json` is the read-only
production Data projection; `ticket-audit.json` holds the frozen paper inputs
and result report; `current-market-example.json` is a fresh detailed raw census.
`proposed-game-dispositions.csv` records all 46 game decisions for implementation.
The archived 26-game market census is under
`.local/mens-d1-20261124/coverage-slice/` and the saved signed-in offer export
under `.local/mens-d1-reconciliation-20261124/signed-in-exports/`.
Audit reads and local analysis submitted no provider acquisitions or orders.


## Applied audit

Production published all 26 retained-original census summaries and recorded all
99 reviewed decisions. The seven accepted gaps retain their finals and original
capture failures. The pinned opportunity and grading hashes and portfolio sums
matched after the decision writes. See the [first-beta closeout](predict-first-beta-closeout-20261124.md).
