# SportsGameOdds paid observation and market-data cleanup

On November 11, 2026 at approximately 11:56 a.m. Eastern, a guarded,
first-page sample requested at most two events per league, with a start-time
filter including the preceding 12 hours. It is not a complete slate census.
The five nonempty leagues had further pages. The six requests returned ten
events and one empty page, charging 11 objects; an earlier two-event NBA
request charged two. Provider usage moved from 11 to 24, matching 13 locally
accounted objects; the SGO ledger held zero and reserved 10,000 for headroom.
The reported Rookie limit was 100,000 objects and 50 requests per minute.

| League | Events | Phases | Parsed quotes | Available quotes |
| --- | ---: | --- | ---: | ---: |
| NFL | 2 | pregame | 546 | 528 |
| NCAAF | 2 | pregame | 472 | 456 |
| NBA | 2 | pregame | 560 | 536 |
| NCAAB | 2 | 1 live, 1 pregame | 408 | 344 |
| MLB | 0 | none | 0 | 0 |
| NHL | 2 | pregame | 472 | 464 |

Each nonempty sample included moneyline, spread and total quote entries.
Novig, `prophetexchange`, `kalshi`, `polymarket`, `matchbook` and
`betfairexchange` IDs appeared in at least one sample. These are source-local
IDs, not proof of native identity, executable liquidity, settlement, fees,
jurisdiction or equivalence to a direct contract. The vendor lists
`prophetexchange` as Prophet Exchange, but this does not independently bind
it to the existing ProphetX integration. More pages and active slates are
needed. Sanitized detailed counts are in `.local/sgo-paid-sample-20261111.json`.

The worker now reads the ignored root `.env` credential and uses the owner's
first-of-month UTC date as a labeled pacing assumption when the provider gives
no reset. Fresh usage is still required; increased external use is recorded,
lower or contradictory usage fails closed, and unresolved reservations remain
blocking across windows. The calendar boundary does not itself replenish the
allowance. Recent local exposure is counted across pacing windows. Discovery
now fixes a recent start-time filter across each cursor traversal. These changes
do not establish a sustainable schedule or complete the production cutover.

At the owner's direction, the stopped processes' database cleanup removed 96
Odds API current events, six aggregate payloads, 30 alternate payloads and six
event censuses. Associated raw display rows were removed by the existing
deletion triggers. Direct event counts were unchanged by the transaction:
715 Kalshi and 585 Polymarket US. Account and hold records were not deleted.
The processes were restarted with the previous aggregate selection. Receipt:
`.local/odds-api-market-cleanup-20261111.json`.

The live aggregate still selects The Odds API and has no configured Odds API
key. The SGO worker is not yet the running aggregate process; source matching,
Prophet identity, reference qualification, venue economics, actual publication,
recovery and desktop/mobile journeys remain open. The sample and passing
unit tests do not demonstrate those outcomes.

## Follow-up observation and recovery fixes

At approximately 12:06 p.m. Eastern the provider reported Rookie usage of
26 of 100,000 objects, with a 50-request-per-minute limit and no reset time.
The local ledger recorded 11 initial objects and 15 charged objects, no held
reservations, and 10,000 reserved for headroom. Two guarded one-event NBA
requests accounted for the increase from 24. The first, without a start filter,
returned six quote observations and no current-row projections. The second,
using the runtime's recent-start filter, returned one event with 280 quote
observations, 12 current-row projections (Novig and SGO's Kalshi ID), 280
reference facts and one event frame. The other 268 observations were excluded
from current rows; many remain reference facts. This is not a slate census,
proof of matching or executable liquidity, or a desk publication test.

The live runtime was healthy and active, with global Stop false and no source
pauses, and still selected The Odds API. Kalshi and Polymarket US reported
partial active native coverage. No provider selection was changed or process
restarted in this follow-up; the SGO changes are not loaded by the running data
process. Previous Odds API accounting and holds were not changed.

The SGO worker now waits and retries when its initial account usage request is
blocked by the local request-rate guard. An unstable cursor traversal retains
admitted observations, never declares authoritative absence, and retries
discovery after 15 minutes instead of terminating the worker. Focused SGO
tests passed (44); eight SGO admission, reference and provider-switch checks
passed in a disposable PostgreSQL 14 compatibility cluster. Ruff passed on the
changed worker and its tests. These checks do not establish production cutover.

The provider's [bookmaker index](https://sportsgameodds.com/docs/data-types/bookmakers)
labels `prophetexchange` as Prophet Exchange and classifies it as a sportsbook;
this does not establish that its present quotes are the same contracts as the
current ProphetX prediction market. Keep the identity unbound pending direct
source evidence. The aggregate projection, ProphetX continuity, other P2P
coverage, exact matching, qualified reference and EV, sustainable cadence,
actual publication and desktop/mobile journeys remain unfinished engineering.

## Further reference and close-state checks

At approximately 12:14 p.m. Eastern, a guarded account usage check reported
26 of 100,000 objects used and no reset timestamp. The SGO ledger recorded
11 initial objects plus 15 charged, zero held and 10,000 reserved for
headroom. December 1 at 00:00 UTC is the owner's provisional pacing boundary,
not a provider-confirmed reset. The separate Odds API account status reported
55 uncertain credits across 20 attempts; those records were not changed.
Global Stop was false and no sources were paused. Both direct native workers
were active with partial coverage. The running aggregate still selected The
Odds API and was unavailable due to its recovery credential state.

The vendor fair-odds comparison now requires the fair line to match the
observed offer's line (or both to be line-free), in addition to availability
and same-receipt identity. An event marked completed now makes its observed
quotes unavailable even if a bookmaker flag remains open. These are local
changes; they have not been loaded into the running processes or established
end-to-end publication. Seventy focused SGO and reference tests and Ruff
passed. No event acquisition or source switch was performed in this check.

SGO lists `prophetexchange` as Prophet Exchange, classified as a sportsbook;
ProphetX describes its current product as a prediction exchange. Those source
descriptions alone do not connect an SGO quote to a current ProphetX contract.
The ID remains unbound. The broader cutover and verification work listed above
remains open.

## Running aggregate and desk continuation

The local configuration now selects SportsGameOdds. Guarded discovery admitted
real pages and the ordinary desktop desk displayed six current Novig offers
for Wizards–Pacers across moneyline, spread and total at approximately 12:21
p.m. Eastern. The display distinguishes SportsGameOdds as the price provider.
The pinned details showed SGO fair odds at a different line as context, with
the mismatch explicitly labeled and no offer-specific EV inferred. A mobile
viewport was inspected; when a latest price was unavailable, the drawer kept
its earlier evidence pinned. This is a representative journey, not a complete
mobile or live-market qualification.

The worker now marks the aggregate available after a nonempty successful page,
before admitting its prices. A native Kalshi disconnect no longer overwrites
SGO-origin Kalshi quote state. An unresolved SGO occurrence retains the proper
source-local display scope. The ordinary publication authority no longer
applies The Odds API's pause or accounting hold to SGO as the selected
aggregate. ProphetX is explicitly unavailable pending identity evidence.

The selected SGO ledger's observed balance at 12:37 p.m. Eastern was
11 initial objects plus 453 charged, no held objects and 10,000
reserved. These figures will advance as collection runs. The older Odds API
status showed 55 uncertain credits in 20 attempts; no holds were released.
The calendar boundary remains provisional. The rate guard paused between
request bursts and the worker retried; a complete slate census, a proven
sustainable cost model and moving-traversal production recovery remain open.

The focused suite passed 87 tests and 9 subtests, plus the SGO drawer fixture.
Ten admission, source-status, reference and provider-switch checks passed in
a disposable PostgreSQL cluster; the first disposable run failed its
temporary-directory guard on macOS and passed after the path check was made
portable. Ruff and the whitespace check passed. Existing agreed scope remains:
complete six-league and live coverage measurement, exact native contract and
settlement matching, fee-qualified provisional EV, ProphetX continuity and
other qualified P2P venues, supporting data, recovery and complete journeys.
The observed Wizards–Pacers occurrence association was a unique metadata
match marked estimated, not a verified exact contract.

After the provider-status correction and final restart, both native feeds
reconnected with partial coverage; Polymarket US subsequently reported
resynchronization at 12:37 p.m. SGO resumed after the rate wait, and all six
Wizards–Pacers Novig observations were current again in the desk API at
12:37 p.m. The worker had admitted 48 event observations in that process and
was waiting for its request-rate window; NFL and NCAAF traversals remained
incomplete. Those counts are not a complete slate census.

Review decision: A new multi-book model or calibration study is not required
to display the labeled vendor baseline | owner clarification; not a cutover
or review gate | displayed the baseline separately and retained exact-input
and fee safeguards for offer-specific EV.

## November 11 scheduling and supporting-data continuation

At 1:07 p.m. Eastern the running SGO process had admitted 535 event
observations in that process. NFL, NBA and MLB cursor sequences had completed;
NCAAF, NCAAB and NHL were incomplete. Cursor completion does not authorize
absence. The ledger showed 11 initial plus 940 charged objects, no SGO holds,
and 10,000 reserved; no external-use increase was recorded. The worker makes
a fresh usage check before each paid page. The older Odds API hold was still
55 credits across 20 attempts.

The retained source-local slate then contained 360 events: 28 NFL, 183 NCAAF,
39 NBA, 70 NCAAB and 40 NHL. This was not a provider census. Four were within
three hours, 60 between three and twelve hours, 99 between twelve and 72 hours,
and 197 beyond 72 hours. A later read retained 368 events. The prior three-hour
poll interval for the 3–72-hour tier left the representative NBA prices
expired well before their next scheduled refresh.

The policy now polls events within twelve hours at 45-minute intervals, live
events at 15 minutes, the remaining 72-hour tier at three hours, and more
distant events at twelve hours. A rough static-slate estimate from those
counts is about 2,048 + 792 + 394 = 3,234 event objects per day before discovery,
empty responses, retries, live acceleration and external clients. Two complete
walks over 360 events would add approximately 720 objects. This estimate is
not a sustainable-cadence demonstration: the slate is incomplete, groups move,
and discovery and live costs vary. Fresh provider usage, the existing rolling
daily allowance, reserve and holds remain controlling.

Incomplete bounded cursor walks now resume after one minute rather than
waiting 15 minutes, and their cap allows up to 1,000 pages rather than silently
abandoning a walk at 100. Each page still passes the request and object guards.
The schedule can be seeded on restart from bounded retained event receipts,
without refreshing source clocks or treating absence as closure. An omitted
event-ID response records a local polling attempt only and does not withdraw
the source event. Event frames now retain bounded team scores, full-game team
points, event status and team identities when supplied; they are receipt-time
audit observations, not venue settlement evidence. Existing older frames remain
readable. Focused tests passed 70; 11 disposable PostgreSQL checks passed.

New direct evidence narrows the Prophet identity question: a [New Jersey
regulator order](https://www.nj.gov/oag/ge/docs/Rulings/2025/aug1_15/B8staketrade.pdf)
identifies the historical business as ProphetX, formerly Prophet Exchange.
The [SGO bookmaker list](https://sportsgameodds.com/docs/data-types/bookmakers)
still labels its ID Prophet Exchange and classifies it as a sportsbook. The
historical name relationship does not establish that SGO's current prices are
the present prediction-market contracts, their sides, fee terms or liquidity;
the ID remains unbound. The direct next evidence needed is a current SGO-to-
ProphetX market/contract mapping or another source-specific linkage.

At approximately 1:15 p.m. Eastern the retained SGO reference table held
42,653 current source facts, about 83.4 MB including indexes; event frames
occupied about 8.5 MB for 573 frames, and the whole database about 1.40 GB.
These are instantaneous database sizes, not incremental cost per event or a
retention forecast. The ledger had 1,134 resolved objects plus 11 initial,
zero held and zero recorded other-client increases. The retained fact inventory
contained available source-local Novig, `prophetexchange`, Kalshi and Polymarket
observations in NFL, NCAAF, NBA, NCAAB and NHL, as well as Matchbook and Betfair
Exchange in several of those leagues. No Sporttrade facts were present in that
read. This is provider observation coverage, not verified present jurisdiction,
direct contract identity, execution depth or a complete slate census.

Betfair's [general terms](https://support.betfair.com/app/answers/detail/a_id/10559/)
list the United States and its territories among prohibited territories for
those services; the aggregate ID alone does not establish a usable U.S.
execution venue. Novig's [fee help page](https://support.novig.com/en/articles/16195057-fees-on-novig)
and [fee comparison](https://landing.novig.com/blog/prediction-market-fees-compared)
describe different live straight-trade coefficients for some app/web markets.
The exact applicable product and current terms therefore still need evidence;
the conflict is not resolved by choosing the more favorable rate.

At 1:17 p.m., after restart, the worker reported 368 seeded schedules without
truncation, then admitted 48 event observations in 24 pages. Total payload was
1,823,722 bytes and the largest page 114,484 bytes. The ledger showed 11
initial plus 1,182 charged objects, zero held and 10,000 reserved; these
figures continue to change. Both native sources reported partial active
coverage. The desk again displayed six current SGO-attributed Novig offers for
Wizards–Pacers; an inspection at 1:18 p.m. showed an offer of Pacers -3.5 at
+106 and vendor fair odds -104 at -2.5, explicitly as different-line context.
Fee and EV remained unavailable. During “Use latest prices” the first attempt
detected a change and kept the old inspection; a retry adopted a newer capture
with the same displayed price. A 390-pixel mobile details viewport was checked.
New event-context frames were observed for pregame NFL, NCAAF and NBA; none of
those frames contained scores or results. Two NCAAB live events were present in
older reference facts, but the new score capture and in-game journey have not
yet been validated against a fresh live observation.

At 1:20 p.m. the provider usage check reported 1,245 of 100,000 objects
before a two-object page; the ledger then recorded 1,247 total, with no SGO
hold. This is a point-in-time reconciliation, not a reset confirmation.
The signed Novig worker reported `novig_v3_read_key_unavailable` and zero
qualified live markets, so that path could not provide direct book sequence
or contract evidence. The Novig public inventory does not substitute for a
signed post-reset book. In the retained SGO reference set, three of 573 event
IDs had aliases; the observed aliases were SGO-shaped IDs and did not supply
an established native-provider namespace or exact-contract linkage.

At 1:21 p.m. the latest provider usage observation and ledger both reported
1,291 objects used, zero held, with 10,000 reserved and no provider reset
timestamp. The current data process was healthy with SGO waiting between rate
bursts after 24 pages and 48 event observations; both NFL and NCAAF traversals
remained incomplete. Its 368 retained schedules were not truncated. The last
24 pages totaled 1,823,256 bytes, with a maximum of 114,494 bytes. Kalshi had
256 active subscriptions and 10,733 deferred; Polymarket US had 256 selected
and 13,062 deferred, and was resynchronizing after 24 invalid or missing
initial images. These are observed rotating partial coverage, not a verified
full feed or proof of the cause of every resynchronization.
## Request-category accounting continuation

At approximately 2:07 p.m. Eastern the running worker reported that all six
league cursor sequences had reached their ends during that process. This does
not establish a stable complete snapshot or authoritative absence. The SGO
ledger contained 2,231 resolved objects plus 11 initial, zero held and 10,000
reserved. The resolved requests spanned approximately 12:53–1:55 p.m.; these
historical records do not distinguish discovery from refresh, so their category
breakdown cannot be recovered from this ledger. This concentrated burn is not
evidence of a sustainable daily cadence. The separate Odds API status still
reported 55 reserved credits and its recovery-credential pause; those records
were left intact.

New SGO reservations atomically retain whether a request is league discovery
or an event-ID refresh, and the league for discovery. This includes uncertain
reservations and empty responses; older reservations remain unclassified.
It enables future object-burn measurement by category and time, but does not
yet distinguish live from pregame or establish sustainable pacing. Thirty-four
focused collector, ledger, worker and schedule tests passed, as did Ruff.

The data process was gracefully restarted with the existing configuration. At
2:09 p.m. it was healthy, global Stop was false and no source was paused. A
fresh SGO usage observation reported 2,289 of 100,000 objects, matching the
ledger's 11 initial plus 2,278 resolved, with no SGO hold and 10,000 reserved.
The reset timestamp remained unavailable; December 1 is only the provisional
pacing boundary. The restarted worker had seeded 513 retained schedules and
was waiting for the request-rate window after 24 pages. Kalshi reported 256
active markets and 10,735 deferred; Polymarket US was reconnecting. The app
process remained running. Follow-on observation is required to assess recovery,
categorized usage and publication after this restart.
The dedicated Novig market-data Keychain reference was checked through the
existing loader without printing its contents; it returned
`novig_v3_read_key_unavailable`. This prevents that worker from supplying a
fresh signed sequence and direct contract evidence; it does not establish that
aggregate Novig observations or other venues are unavailable.


## Budgeted schedule and source evidence continuation

At about 2:11 p.m. Eastern the retained scheduling population was 512 events:
28 NFL, 213 NCAAF, 39 NBA, 181 NCAAB and 51 NHL. No MLB event was retained;
this is not proof that the provider had no MLB event. The static population had
63 within 12 hours, 182 from 12 to 72 hours and 267 later. At the former
intervals these imply 4,006 event refreshes per day, plus roughly 1,024 objects
for two full rediscovery walks, before live acceleration, empty responses,
retries or external usage. This is a scenario, not measured daily consumption.

The worker now chooses among bounded interval policies using the current daily
allowance and retained slate, with 35% of that allowance outside the projected
refresh allocation for discovery, live-slate movement, retries and other
headroom. It slows distant and near events first; live remains 15 minutes. If
no candidate fits, it exposes the excess projection and the existing durable
pacing guard remains authoritative. The calculation assumes the present slate
and treats each currently live event as live all day. Neither this headroom nor
the assumed December 1 boundary proves affordability or actual reset. After
integration, the worker reported an estimated 3,011 refresh objects/day against
4,687 available per day, with 45-minute imminent, six-hour near, and 24-hour
distant intervals. Two 512-event discovery walks would add about 1,024 objects;
actual live, retry and external costs must still be measured. Longer polling
intervals can leave source prices stale, and the display must continue to honor
source-clock expiry.

Completed discovery times now persist for restart scheduling only. They do not
assert a complete snapshot or withdraw absent events. Event-ID refreshes follow
an explicitly returned SGO alias in the local poll schedule without claiming a
native cross-provider match or deleting stored observations. An unavailable or
incomplete SGO fair baseline now remains visibly labeled unavailable, retaining
its reported odds and line as context when supplied; it never supplies EV.

At approximately 2:15 p.m. the desktop desk showed six retained Wizards–Pacers
Novig observations with expired price status. Its Pacers -3.5 +108 drawer
showed SGO fair odds -104 at -2.5 as different-line context and withheld
settlement binding, fee qualification and EV. During the inspection a newer
source capture arrived, and “Use latest prices” adopted it. A 390-pixel drawer
view was readable. This is one pregame journey, not a full mobile, concurrent
update, in-game or fee-validation pass.

ProphetX's [market-data documentation](https://docs.prophetx.co/docs/getting-started)
identifies a distinct market-data API, and its [ISV guide](https://isv-docs.prophetx.co/docs/getting-started)
says requests require authentication. The configured dedicated production
credential reference was unavailable through the existing loader. The current
[trading fee documentation](https://docs.prophetx.co/docs/fees) says account
fee models and rates are set by ProphetX; it does not establish the terms for a
particular SGO observation. No current SGO-to-ProphetX contract mapping was
established. Separately, Novig's help page and comparison article still present
different live straight-trade coefficients for some products; the precise
applicability remains unqualified.

A subsequent recovery check found that restart seeding had depended on a
projected desk event. Two NCAAB live event frames with score observations had
no such event row, so the scheduler omitted them after restart even though the
frames retained their own league, start and receipt. Restart seeding now reads
the frame first and uses an event row only for older incomplete frame context.
The unchanged retained source frames restored both live IDs without inventing
clocks or settlement evidence. A disposable PostgreSQL test exercised a live
frame without a projected event. In the read-only retained slate this expanded
the population from 512 desk-backed events to 991 frame-backed events, including
two last observed live; their last source receipts were at 1:47 p.m. Eastern,
so they are not evidence of a fresh score at the time of this check.

For that 991-event static slate the scheduler selected 15-minute live,
60-minute imminent, 12-hour near and 24-hour distant polling, estimating
2,953 refresh objects per day. Two daily rediscovery walks alone would consume
roughly 1,982 objects, beyond the space left by the earlier estimate. The
scheduler therefore lengthens the normal discovery interval to 24 hours when
two static walks exceed one quarter of the available daily pace. An estimated
one 991-object walk plus 2,953 refresh objects is 3,944 per day before empty
pages, retries, changed slate and other usage. This is still a projection and
not a demonstrated sustainable or fresh service; 60-minute imminent polling
cannot keep a three-minute-old source price continuously current. Unstable
walks continue their shorter retry and remain subject to the durable budget.

After the corrected restart at approximately 2:22 p.m. Eastern, the healthy
data process reported 991 seeded events and a 24-hour discovery interval. Its
current projection was 2,953 refresh plus 991 discovery objects per day against
4,688 available per day, before the variable overhead above. The provider's
fresh usage observation was 2,579 of 100,000; the ledger matched at 11 initial
plus 2,568 resolved, zero held and 10,000 reserved. The provider still supplied
no reset timestamp. The two recovered NCAAB frames were refreshed at 2:22:10:
SGO reported Dartmouth 58–Albany 43 live, and Fairleigh Dickinson 80–East Texas
A&M 76 completed. Both scores and full-game points were retained with the same
receipt and source event identities. These are provider audit observations,
not independent confirmation of the score or authority for venue settlement.
The prior process needed more than the launcher's 15-second graceful shutdown
window but exited without a force kill before its successor started.

A cursor walk that reaches its page cap without ending now takes the incomplete
retry path instead of waiting for the completed-walk interval. A focused
fixture exercises that distinction. The final focused Python run passed 84
tests; the SGO saved-drawer fixture, Ruff, JavaScript syntax checks and the
disposable PostgreSQL frame-only restart test also passed. These are separate
from the live observations above and do not establish complete cutover.

The final integration restart loaded the alias, baseline-display, budget and
frame-seeding changes. At 2:24 p.m. the worker was healthy with 990 retained
schedules and reported a 2,857-object refresh estimate plus a 990-object
one-walk estimate against a 4,688-object daily pace. A 2:24 provider read and
ledger both showed 2,657 objects used, zero held and 10,000 reserved. Kalshi
was active with 256 subscriptions and 10,736 deferred; Polymarket US was
still connecting after restart. These figures are snapshots, and any currently
in-flight reservation may appear temporarily as a hold.

## Discovery fairness follow-up

At about 2:32 p.m. Eastern, the running process had locally delayed SGO for its
request rate. The categorized ledger contained 586 discovery objects for NFL,
NCAAF and NBA combined and 29 event-refresh objects, in addition to 2,231
earlier uncategorized objects and 11 initial objects. These counts describe
the observed startup and repeated incomplete traversals, not a daily burn rate.
No completed league walk had been recorded at that point. A rate interruption
could repeatedly restart a cycle at the first league, delaying later leagues;
the worker now rotates the first discovery league after an attempted turn,
including when a local rate or budget exception interrupts it. In-memory
per-league cursors remain intact. A focused interruption fixture, 42 scheduling,
worker, ledger and collector tests, and Ruff passed. Rotation is not proof of a
complete walk, and an actual process restart still loses in-progress cursors.

At 2:32 p.m. a read of retained reference rows counted source timestamps within
15 minutes for 2,760 NBA pregame, 140 NCAAB live, 1,590 NCAAB pregame, 14,104
NCAAF pregame, 5,112 NFL pregame and zero NHL pregame rows. This is a descriptive
15-minute age threshold, not the product's complete freshness qualification,
unique-event coverage, or proof of any venue's executable liquidity. Retained
frames covered five leagues; no MLB frame was retained. The current-reference
and frame tables replace earlier revisions, so these counts cannot reconstruct
the full history. The database occupied approximately 1.72 GB against its 2 GiB
guard, a material constraint on prospective history retention.

The data process was restarted with the existing configuration after the test.
Its graceful shutdown exceeded the launcher's 15-second wait but exited without
a force kill. At 2:34 p.m. the new runtime was healthy, Stop was off, no sources
were paused and SGO had admitted a new page. The latest provider read showed
2,912 of 100,000 objects, with no provider reset timestamp; at the adjacent
runtime snapshot the ledger had 11 initial plus 2,903 resolved, zero held and
10,000 reserved. The two readings straddled additional collection, so they are
not a same-instant reconciliation. The assumed December 1 boundary is still
only a pacing assumption. Both native feeds were reconnecting at that snapshot;
before restart both had become available with partial subscription coverage.
This pass does not complete history, cross-provider binding, economics, live
qualification or the broader cutover; further independent engineering remains.

## Restart-safe discovery follow-up

At 2:39 p.m. Eastern on November 11, the data runtime was healthy, global Stop
was off and no sources were paused. The launcher reported no running app; the
app was started at `http://127.0.0.1:8784`. A read-only storage census measured
1,563,173,667 database bytes and 1,222,664,192 bytes in the guarded writer
subset. `current_sgo_reference` occupied 102,629,376 physical bytes, including
indexes and TOAST; physical allocation is not a reclamation estimate. This is
not a bounded revision-history implementation: the current reference and frame
rows still replace old revisions. Protected data and the storage guard were not
cleared or changed.

The discovery ledger now checkpoints each admitted incomplete page: its exact
query parameters, opaque next cursor, seen event and cursor identities, and
page count. Completion atomically removes the checkpoint and records the
scheduling time. Changed query scope, malformed checkpoints, clock regression,
and checkpoints more than 24 hours old are not restored. A repeated event or
cursor still invalidates the walk; no cursor traversal establishes authoritative
absence. An unsuccessful provider request still holds its uncertain object
reservation: automatic recovery from a provider-rejected expired cursor is not
implemented and must not release that hold without evidence.

After the first integration restart, an NFL walk reached six checkpointed
pages. Following another graceful data-process restart, SGO initially waited on
its existing request-rate guard; at 2:41 p.m. it reported one restored walk and
advanced that NFL checkpoint to 15 pages. MLB had reached the end of a cursor
sequence at 2:36:59 p.m.; a moving walk can still miss or duplicate events.
The worker and app were running, with Stop off and no source pauses. SGO had
received pages, Kalshi was available with 256 subscribed and 10,737 deferred
markets, and Polymarket US was still restoring its saved catalog. These are
point-in-time observations, not complete coverage or sustained performance.

At 2:41:49 p.m. the most recent provider observation showed 3,076 of 100,000
objects used; the adjacent ledger snapshot showed 11 initial plus 3,065
resolved, zero held, and 10,000 reserved. The worker's static-slate projection
was 2,931 refresh plus 990 discovery objects per day against a 4,691-object
daily pace, excluding variable retries and other use. The December 1 UTC
boundary remains an owner-directed pacing assumption, not provider reset proof.
A 15-minute source-clock census of retained reference rows found 1,176 NBA
pregame, 344 NCAAB live, 8,287 NCAAB pregame, 13,483 NCAAF pregame, 5,465 NFL
pregame and 1,390 NHL pregame rows. These are rows, not unique events or the
product's full current-price qualification; no MLB frame is implied by the
completed empty walk.

Forty-five focused worker, ledger, collector and scheduling tests passed using
disposable fixtures, along with Ruff. The fixtures cover restart, unchanged
query scope, repeated-event rejection, completion, stale checkpoint and changed
scope; the real restart observation above is separate. Bounded revision history,
provider-rejected cursor handling, full freshness/consumption study, exact
native contract and settlement matching, fees and EV, venue continuity, and
representative full desktop/mobile and live journeys remain open. The broader
cutover is not complete.

## Cursor rejection follow-up, 2:47 p.m. Eastern

The transport now inspects a bounded 400 response only when a cursor was sent,
recognizing a JSON error explicitly describing an invalid, expired or malformed
cursor without retaining or logging the provider text. The worker discards that
league's incomplete checkpoint and keeps already admitted observations; it does
not claim completeness or withdraw absent events. The failed request's full
reservation remains held. Consequently a fresh walk cannot dispatch until the
uncertain charge is reconciled; automatic end-to-end recovery remains incomplete.
The vendor documents a human-readable error but not a specific cursor error
string, so this conservative classifier has fixture coverage, not a verified
live rejection. Unknown 400s continue to fail closed. Fifty-one focused transport,
collector, worker, ledger and scheduling tests and Ruff passed. The data process
was gracefully restarted to load the change, and its new runtime became healthy.

At 2:46:48 p.m., before restart, the provider usage reading showed 3,212 of
100,000 objects; the adjacent ledger showed 11 initial plus 3,201 charged,
zero SGO held and 10,000 reserved. The schedule still projected 2,931 refresh
and 990 discovery objects per day before variable overhead. The assumed
December 1 UTC boundary is pacing only, not provider-confirmed reset. A current
storage census found 1,681,802,019 database bytes and 1,332,985,856 guarded
writer bytes, versus 1,563,173,667 and 1,222,664,192 in the previous census.
Those are physical allocation snapshots, not a sustained growth rate or a
reclamation forecast. No revision history was implemented or protected data
removed. The separate Odds API ledger still showed 55 uncertain credits over
20 attempts. At 2:47:34 p.m. the restarted data runtime was healthy, Stop was
off, no sources were paused, and native feeds were reconnecting. The app remained
running. Exact matching, fees and EV, bounded revision history, full cursor
reconciliation/retry, consumption/freshness analysis and requested journeys
remain open. Earlier fixture and failed macOS temporary-path evidence above is
unchanged.

At 2:48 p.m. the existing credential loaders were checked again without
printing secret material: the Novig v3 read key and ProphetX production
credentials remained unavailable. These prevent fresh signed Novig sequence
and direct ProphetX contract evidence respectively. The new runtime was healthy
with Kalshi connected; Polymarket US was still connecting and SGO was waiting
for the local request-rate window. No live rejected cursor or recovery was
observed in this pass.

## Bounded history and freshness follow-up, November 11

Migration 073 adds best-effort SGO revision witnesses. On replacement or expiry,
prior reference facts and event frames are archived with their original receipt,
source and revision provenance and a separate archive time. History is limited
to 32 MiB of encoded facts, expires seven days after archival, and stops adding
witnesses if that limit or 64 MiB of database runway would be exceeded. A
persistent counter records additions and capacity/runway skips. These limits do
not change the existing whole-database guard; physical indexes and PostgreSQL
allocation add overhead beyond the logical cap. Current facts, account records,
pinned evidence and other data are not pruned by this history policy. Because
capture is prospective and may skip witnesses at capacity or pressure, and
because frame members can outlive available individual revisions, it is not a
complete seven-day replay guarantee or historical backfill. `read_history`
provides bounded event-level audit reads; a frame and every referenced fact are
not guaranteed to remain together.

At 3:31 p.m., after the initial integration restart, live collection had saved
46 reference witnesses and one frame (75,534 encoded fact bytes), with no
capacity or runway skips then recorded. The disposable PostgreSQL 14 compatibility
suite passed five ingress/history tests including replacement, capacity refusal,
read after reconnect, expiry, and preservation of current rows; 76 focused
Python tests and Ruff also passed. The first history fixture run failed because
it passed a datetime where the storage helper expects a string. A subsequent
run exposed shared disposable-test fixture state; both were corrected before the
passing run. These are not live retention-duration or full replay proofs.

At 3:30 p.m. the database measured 1,560,773,411 physical bytes and the guarded
writer subset 1,232,379,904 bytes; earlier measurements were 1,681,802,019 and
1,332,985,856 at 2:46 p.m. Allocations can fall as maintenance reuses or reclaims
space, so neither difference is a sustained growth rate. The prior temporary-path
failure and successful correction remain recorded above.

The categorized ledger from 2:08 through 3:16 p.m. showed 1,734 resolved
discovery objects (MLB 1, NBA 223, NCAAB 325, NCAAF 527, NFL 449, NHL 209)
and 75 event-refresh objects; 2,231 earlier objects remain uncategorized.
These include interrupted startup traversals and are not a daily burn rate.
At 3:30 p.m. all retained SGO reference rows in the five represented leagues
had source clocks older than 15 minutes; this row census is not a count of
unique games or the product's full current-price test. The desk at 3:31 p.m.
showed 11,414 offers, 54 current and no qualified EV, across all sources.
A 3:30 adjacent provider read was 4,051 of 100,000; the ledger was 11 initial
plus 4,041 charged, zero held and 10,000 reserved, with the one-object
difference reflecting adjacent observations. Its static slate projection was
2,863 refresh plus 989 discovery objects daily before retries, empty pages,
changes and other use. Through the assumed December 1 boundary that is roughly
73,750 additional objects on a fixed slate, leaving roughly 12,200 beneath the
10,000-object reserve after the observed 4,051, before variable overhead. The
boundary remains an owner-directed pacing assumption, not a verified provider
reset, and this projection is not measured continuous affordability or freshness.

A desktop drawer for North Carolina A&T +11.5 showed an expired Novig-via-SGO
price, unverified settlement and unavailable EV, alongside SGO fair odds at
+11 as explicitly different-line context. 'Use latest prices' reported no
current price and kept the inspected evidence pinned. The same drawer was
readable at 390 pixels; no newer qualifying price was available to test adoption
in this pass. Both native feeds had connected before the integration restart;
reconnection remains partial-coverage rather than proof of full continuity.

The provider's current bookmaker list calls `prophetexchange` Prophet Exchange
and categorizes it as a sportsbook; this does not establish a present
contract-level mapping to ProphetX. ProphetX says fee models and rates are
account-specific, so this does not supply a fee for an SGO observation. The
Novig and ProphetX credential paths remained unavailable on the prior loader
check. No current native/SGO exact contract or settlement binding or qualifying
EV was established. Provider usage is account-wide and does not by itself
attribute an uncertain charge or prove its absence in the presence of reporting
lag and other clients; the existing held-charge guard is retained. Automatic
cursor charge reconciliation and retry, complete matching and economics,
sustained consumption/freshness tuning and in-game qualification remain open.
Sources: https://sportsgameodds.com/docs/data-types/bookmakers and
https://docs.prophetx.co/docs/fees.

After the final restart at 3:33 p.m., the data runtime was healthy and active,
Stop was off, no sources were paused, Kalshi was connected and Polymarket US
was reconnecting. SGO was waiting for its next cycle; its fresh usage read was
4,052 objects with the adjacent ledger at 11 initial plus 4,041 resolved,
zero held and 10,000 reserved. The app was running on port 8784. The history
survived that restart with the same 47 witnesses and zero skips. The final
physical census was 1,548,329,763 database bytes and 1,211,916,288 guarded
writer bytes. These snapshots do not establish sustained behavior.

## Freshness prioritization and held-charge continuation, November 11

At approximately 4:00 p.m. Eastern, the retained reference census showed
2,498 of 5,381 NBA pregame, 4,094 of 11,938 NCAAB pregame, 435 of 2,146
NCAAB live, 598 of 17,580 NCAAF pregame, 0 of 8,261 NFL pregame and 1,282
of 4,210 NHL pregame rows with source clocks within 15 minutes. These are
reference rows, not uniquely current offers; source availability and the
publication's other checks still apply. NCAAB started-phase rows
included no available offers. Selected P2P row samples included 16 of 56 Kalshi
live and 16 of 73 Novig live within 15 minutes, and 237 of 1,899 Kalshi and
237 of 1,370 Novig pregame. An SGO `polymarket` row is not proof of a US
contract, and `prophetexchange` identity remains unverified.

The acquisition adapter preserves SGO's `lastUpdatedAt` as the bookmaker source
clock; receipt time schedules the next fetch and does not renew price authority.
Repeated observations with unchanged source revisions do not refresh the
source clock. Publication independently expires the source price and withholds
EV when exact reference, settlement or fee qualification fails. Consequently
frequent polling can improve coverage but cannot force a vendor to provide a
newer source clock or establish a native contract match. At 4:04 p.m., during
native-feed restart, the desktop showed 9,731 offers, zero current and zero EV;
that restart snapshot is not a steady-state measurement.

The scheduler now gives pregame events within two hours a 30-minute target,
keeps live at 15 minutes, and wakes at the next due time or tier boundary rather
than always waiting a full 15-minute cycle. On the 989-event static slate the
budget policy selected a two-hour cadence for the remainder of the 12-hour
window, 12 hours for the next 60 hours and 24 hours beyond that. Its projected
refresh cost is 2,409 objects/day plus an estimated 989 discovery objects/day,
versus the earlier 2,863 plus 989. This deliberately trades slower coverage
for games two to twelve hours away for faster immediate pregame refresh; actual
source-clock freshness and costs over changing slates remain unproven. In the
hour ending approximately 4:00 p.m., the ledger recorded 417 discovery and 49
refresh objects, including startup traversal, not a sustainable hourly rate.

A rejected cursor still keeps its reservation held; account-wide use alone is
not treated as request-specific charge evidence. The running worker now waits
without paid event dispatch while an unresolved charge blocks it and resumes
automatically after an independently evidenced ledger resolution, rather than
requiring a process restart. A disposable fixture exercised the wait, preserved
hold and resumption; it did not establish automatic charge attribution, and no
live cursor rejection or attributable receipt was observed. Unknown errors and
cross-window exposure retain existing safeguards. Fifty-four focused tests and
Ruff passed. No new user review was requested.

At 4:05 p.m. the restarted data process and app were healthy, Stop was off,
no sources were paused, Kalshi was connected and Polymarket US was reconnecting.
The latest provider reading was 4,100 objects; the adjacent ledger showed 11
initial plus 4,090 resolved, zero held and 10,000 reserved. These adjacent
values differ by one object. The first-of-month boundary remains a provisional
pacing assumption, not a confirmed reset. The separate Odds API ledger retained
55 uncertain credits across 20 attempts. The database occupied 1,516,208,931
physical bytes, with 1,185,914,880 in the guarded writer subset. History held
9,051 reference and 50 frame witnesses, approximately 10.5 MB encoded facts,
with no skips. The credential loaders again reported the Novig read key and
ProphetX production credentials unavailable.

A desktop Polymarket US Saint Joseph's spread drawer preserved its expired
long-side price, withheld EV and displayed the fee as historical/outside its
review window. 'Use latest prices' found no current replacement and retained the
pinned evidence. The drawer was readable at 390 pixels; adoption of a newer
qualifying price and a fresh in-game EV remain unverified. Exact native/SGO
occurrence and settlement bindings, applicable fees, automatic request-specific
charge evidence, sustained freshness and full P2P integration remain open.

History rotation follow-up: because the live history reached 10.5 MB of encoded
facts soon after integration, migration 074 changes the capacity behavior. When
new witnesses fit the existing database runway, the oldest SGO audit witnesses
are evicted as needed to keep the 32 MiB logical cap. This supersedes the prior
description that capacity alone stops all new history. Expiry after seven days
still applies, but capacity can shorten retention; current facts and separate
pinned originals are not touched. Runway exhaustion still skips new witnesses
without evicting existing history. A persistent eviction counter supplements
the skip counters. Six disposable PostgreSQL 14 compatibility tests passed,
including rotation and runway refusal. A fixed 3,398 objects/day refresh plus
discovery scenario through December 1 from 4:05 p.m. would consume about
64,975 more objects and leave roughly 20,925 before the 10,000-object reserve,
before retries, empty pages, other use or changing slate. This is a static
scenario, not a measured or provider-confirmed account window.

After the final rotation-code restart, at 4:09 p.m. the data process was healthy
and active, Stop remained off and no sources were paused. Both native feeds were
reconnecting at that instant; SGO was waiting for its next cycle. Provider usage
and the adjacent ledger both showed 4,101 objects, zero held and 10,000 reserved.
History survived the restart with 9,101 witnesses, no skips and no capacity
evictions yet. Physical database and guarded-writer sizes were 1,506,108,195 and
1,177,354,240 bytes. The graceful shutdown exceeded the launcher's 15-second
window but finished without a force kill before the new process was started.

## Admission scheduling recovery follow-up, November 11

A paid response previously modified the in-memory poll schedule before the
page's source-revocable ingress transaction succeeded. An ingress failure could
therefore postpone the next attempt or remove the old scheduling alias despite
no successful admission. The worker now stages the schedule, admits the page,
and only then commits the in-memory changes. An isolated failure fixture checks
that a rejected admission leaves the old event and alias untouched. This does
not establish request-specific charge attribution or live cursor recovery.
Fifty-five focused worker, scheduling, collector, ledger and transport tests
passed, as did Ruff. The existing working tree and account records were retained.

The first post-change data restart inadvertently omitted the previous explicit
configuration argument; it was stopped and restarted with
`.local/predict-current-config.json`. At 4:16 p.m. Eastern the restored process
was healthy and active, with Stop off and no source pauses; direct feeds were
still reconnecting and SGO was waiting on the local request-rate window. The app
responded before restart. This startup snapshot does not prove feed continuity.

A 4:15 p.m. retained reference-row census using the original source clock found
431 of 2,395 NCAAB live rows within 15 minutes and none within 15 minutes in
NBA pregame (5,381), NCAAB pregame (11,930), NCAAB started (367), NCAAF
pregame (17,580), NFL pregame (8,261), or NHL pregame (4,210). These are
reference rows, not qualified offers. An initial query used the wrong timestamp
units and was corrected before these figures; its zero counts were invalid.
The ledger recorded 17 discovery and 50 refresh objects in the preceding hour,
including startup effects; that is not a sustained rate. Before restart the
latest worker reading was 4,101 of 100,000 objects, with zero SGO held and
10,000 reserved. The earlier static projection remains 2,409 refresh plus 989
discovery objects per day on a fixed slate, excluding variable overhead. The
December boundary remains an assumption, not a provider-confirmed reset. The
separate Odds API held 55 uncertain credits across 20 attempts.

At the census, history contained 9,051 reference and 50 frame witnesses totaling
10,494,239 encoded bytes; recorded was 9,101, with zero capacity evictions or
skips. The database measured 1,632,543,523 bytes. Retention remains at most seven
days and can be shorter at capacity; this snapshot does not prove duration or
replay completeness. Exact native binding, applicable fees and EV, automatic
charge attribution, current full journeys and sustained freshness remain open.

At 4:17 p.m. the restored runtime remained healthy and active. Kalshi had
connected with 256 active and 10,863 deferred markets; Polymarket US was still
connecting and SGO was still waiting on its request-rate window. These are
startup observations, not a completed continuity check.

## Feed continuity and started-game scheduling, November 11

At 4:19 p.m. Eastern, before this pass's restart, the prior corrected runtime
was healthy and active with Stop off and no source pauses. The explicit running
configuration selected SGO for all six aggregate leagues, with the same six
native leagues and all three families. Kalshi and Polymarket US were both
connected with partial rotating subscription coverage. SGO had fetched and
admitted four pages/eight events since the corrected restart. This establishes
post-restart continuity at that time, not continuous complete coverage.

The scheduler treated a provider phase of `started` as pregame even when a game
had begun and had not ended. It now gives `started` the same 15-minute polling
priority as `live`, while retaining the original provider phase and availability
for publication. The fixed-slate budget projection counts these events at the
active rate. A disposable worker fixture verifies the due time and preserves the
phase; it does not prove live source prices or constant freshness. Fifty-six
focused collection, scheduling and recovery tests, 43 reference/adapter/desk
tests, the saved-details JavaScript fixture and Ruff passed.

At about 4:20 p.m. the reference-row census showed 472 of 2,693 NCAAB live
and 604 of 11,798 NCAAB pregame rows with source clocks under 15 minutes; 439
and 604 respectively were also provider-available. There were 116 of 487 started
rows with recent source clocks, none available. Other retained league/phase rows
had none within 15 minutes at that snapshot. Event-frame receipts showed three
live and four pregame NCAAB events received in the preceding 15 minutes; no
NBA, NCAAF, NFL or NHL frames were received in that interval. Current reference
rows retain the earlier receipt when an unchanged revision is reobserved, so
row receipt counts are not an exhaustive fetch census. In recently recorded
NCAAB rows, some provider timestamps remained older than 15 minutes. Both the
budgeted polling intervals and provider source clocks affect useful freshness;
a new receipt cannot renew the source clock.

At 4:23 p.m. the desk publication contained 12,032 offers across sources, 58
current, and zero qualified before-fee or fee-adjusted EV. The desktop drawer
showed an expired Kalshi offer and missing settlement/reference/fee evidence;
'Use latest prices' reported no current replacement and retained the pinned
original. A qualifying newer capture and a mobile journey were not tested in
this pass. Novig's read-key loader and ProphetX's production credential loader
both again returned unavailable without exposing secrets. They block direct
Novig stream evidence and direct ProphetX contract evidence respectively; no
current SGO Prophet Exchange-to-ProphetX binding or account-specific fee was
established.

The ledger recorded 58 event-refresh objects in the preceding hour; its existing
refresh accounting does not attribute those objects to league or phase. The
latest adjacent provider reading was 4,109 of 100,000; the ledger held zero SGO
objects, recorded 4,098 resolved in addition to 11 initial, and retained a
10,000 reserve. The separate Odds API retained 55 uncertain credits across 20
attempts. No current discovery walk was checkpointed; the last completed walks
ranged from 2:36 to 3:16 p.m., and do not establish a stable snapshot. On the
new 988-event retained slate the static projection was 2,363 refresh plus 988
discovery objects/day, excluding retries, empty pages, other clients and slate
changes. It is not a sustained burn measurement; the December 1 boundary remains
an assumption.

The latest history census contained 10,105 witnesses and 11,695,056 encoded
bytes, oldest at 3:30 p.m.; no capacity evictions or skips had been recorded.
The guarded database subset occupied 1,571,193,635 bytes against a 2 GiB cap.
Seven days is an upper bound and the 32 MiB logical cap can shorten retention;
physical space is not represented by that logical cap. Exact native matching,
fee-qualified EV, automatic request-specific charge evidence, a live rejected
cursor, complete desktop/mobile and in-game journeys and sustained usage remain
open. After the scheduling restart, at 4:23 p.m., the data runtime was healthy
and active with controls unchanged; Kalshi was connected, Polymarket US was
still reconnecting, and SGO was waiting for scheduled work. Earlier continuity
is distinct from this new startup snapshot.
At 4:24 p.m. both native feeds had connected after the scheduling restart:
Kalshi had 256 active and 10,865 deferred markets, and Polymarket US had 256
active and 13,216 deferred. SGO had not yet reached its next scheduled fetch.

A representative retained live observation was North Carolina A&T at East
Carolina, SGO event `QykPUTtCYGym1GjDDWGv`, scheduled 4:00 p.m. Eastern. The
Novig-via-SGO over 151.5 was +106, with a 4:18:22 p.m. source clock and 4:18:42
receipt; the vendor fair context was +102 at over 150.5. Those lines differ,
so this fair value is not the offer-specific reference. The same event's
Kalshi-via-SGO home moneyline was -719, with vendor fair -549 on the moneyline;
its quote clock was 4:18:06. SGO did not supply a fair source clock in these
records, and neither observation establishes an exact native contract,
settlement equivalence, executable size or applicable account fee. These are
source observations from one point in time, not qualified after-fee EV.

## Object attribution continuation

Resolved SGO responses now retain an atomic breakdown by returned event league
and provider phase. An empty discovery page is charged to its requested league
with unknown phase; an empty event refresh has unknown league and phase. Older
records without this evidence are reported as unknown rather than inferred.
The breakdown covers resolved request charges only, excluding held reservations
and externally observed account increases. It does not change pacing or release
holds. The vendor describes event objects as the top-level items returned by
the events endpoint; this accounting retains the existing minimum-charge rule.

Fifty-four focused ledger, collector, worker and scheduling tests and Ruff
passed, including mixed-league/phase response attribution, empty response,
legacy unknown and atomic failure fixtures. After the data restart with the
existing explicit configuration, the runtime became healthy. At 4:28 p.m.
Eastern, the fresh provider usage read was 4,109 of 100,000, matching 11 initial
plus 4,098 resolved ledger objects; zero were held, 10,000 remained reserved,
and no external increase was recorded. The new breakdown had no live entries
yet because the worker had not fetched another event page after restart. The
separate Odds API reserve remained 55 credits. The estimated fixed-slate cost
was 2,363 refresh plus 988 discovery objects per day, before variable overhead;
the December 1 boundary is provisional. The process was running, Kalshi had
reconnected with partial coverage, Polymarket US was still connecting and SGO
was waiting for its next cycle. These startup readings do not prove sustained
cost, current SGO prices, or post-restart continuity of all feeds.

Exact native identity and settlement, qualified fees and EV, current desktop
and mobile journeys, fresh live cursor recovery, and sustained league/phase
consumption and freshness remain unverified. This attribution change is a
partial continuation, not completion of the requested cutover.

## Source-rule channel and live attribution follow-up

At 4:32 p.m. Eastern, the ordinary desk reported 11,769 offers, 134 current,
and no qualified before-fee or fee-adjusted EV. At 4:35 p.m., following the
restart below, it reported 11,793 offers, 55 current and no qualified EV; the
publication was partial even though finance was ready. These are point-in-time
counts, not sustained coverage. A desktop inspection of an expired Kalshi
spread showed missing cross-site settlement and reference evidence. “Use latest
prices” reported no replacement and kept the inspected evidence pinned. A newer
qualifying replacement and a mobile journey were not verified in this pass.

The source-input rule lookup classified every provider other than The Odds API
as native. Consequently an SGO venue label could look up a native venue rule
without evidence that the aggregate quote was that native contract. SGO now has
a distinct aggregate channel; neither a native rule nor the older aggregate
channel applies by name alone. This is a qualification safeguard, not proof
that any particular previously displayed result used such a rule. A focused
fixture covers both refusals. The data and app processes were restarted using
the existing explicit data configuration and app port 8784.

The new attribution was observed in actual resolved requests: two NCAAB
pregame refresh objects at 4:30:59 and one NCAAB live refresh object at
4:34:20. In the hour through approximately 4:35, the ledger showed 60 refresh
objects: those three categorized and 57 older objects unknown. No discovery or
empty response with new attribution was observed in this short period; empty
responses remain fixture-tested, not live-verified. The three categorized
objects reconcile with their resolved request charges. The live event was
North Carolina A&T at East Carolina: Novig-via-SGO away moneyline +809, source
clock 4:33:49 and receipt 4:34:20, with same-line SGO fair odds +643. The fair
clock was not provided; the SGO label does not prove a native Novig contract,
settlement, fee applicability, executable depth or a fill. The matching path
requires an explicit non-estimated occurrence and retained native scoring
proof; the observed SGO association and direct book evidence do not satisfy
those requirements. The vendor baseline is not an offer-specific EV input.

A 4:35 source-clock census found 158 of 2,753 NCAAB live reference rows and
394 of 11,794 pregame rows within 15 minutes, of which 154 and 394 respectively
were available. All retained NBA, NCAAF, NFL and NHL pregame reference rows and
NCAAB started rows were older than 15 minutes. These are source facts, not
qualified offers; receipt of a page does not renew an unchanged source clock.
The fixed-slate scheduler projected 2,436 refresh plus 988 discovery objects per
day before variable overhead. The observed one-hour 60-object count is not a
sustained consumption rate. December 1 remains a provisional pacing boundary.

At 4:35:21 the latest provider usage read was 4,112; the ensuing two-object
response brought the ledger to 11 initial plus 4,103 resolved, with zero held,
10,000 reserved and no recorded external increase. The provider reading
preceded that response; it is not a fresh post-response reconciliation. The
separate Odds API retained 55 uncertain credits. Stop remained off and no source
was paused. At 4:35:37 the data process was healthy, Kalshi was connected with
partial coverage, and Polymarket US was connecting after restart. SGO had
admitted two pages and three events since restart.

The Novig read-key and ProphetX production credential loaders again returned
unavailable without exposing credentials. The first prevents signed direct
book and contract evidence; the second prevents authenticated ProphetX mapping
and market evidence. ProphetX's current published mapping endpoint lists
OpticOdds as its supported provider, not SGO; the SGO bookmaker index calls
`prophetexchange` a sportsbook. Neither establishes a current SGO-to-ProphetX
contract mapping. Novig's published fee page contains inconsistent live-rate
statements, so it does not independently settle the applicable rate for this
aggregate observation. Source references: https://docs.prophetx.co/docs/opticodds-id-mapping,
https://sportsgameodds.com/docs/data-types/bookmakers and
https://support.novig.com/en/articles/16195057-fees-on-novig.

History contained 10,509 witnesses and 12,150,495 logical bytes, oldest 3:30
p.m., with no recorded capacity evictions or skips at the measurement. The
physical database was 1,660,216,099 bytes at that measurement; a later guarded
subset reading was 1,547,993,891 of 2,147,483,648 bytes. Retention has a seven-day
upper limit and 32 MiB logical capacity; neither guarantees a complete replay.
Current facts and pinned originals have separate authority from the rotating
history. The focused Python suite passed 102 tests and three subtests; Ruff,
`git diff --check` and the SGO saved-details JavaScript fixture passed. Live
rejected-cursor recovery, request-specific charge attribution, complete
matching and fee-qualified EV, sustained usage, fresh direct-feed continuity
after this restart, and the remaining requested journeys are still open.

At 4:36 p.m. both native feeds had reconnected after the integration restart,
each with 256 active subscriptions and 10,867 Kalshi / 13,216 Polymarket US
markets deferred. This establishes partial post-restart continuity, not full
coverage or sustained freshness.

## Subsequent read-only verification at 4:43–4:44 p.m.

The cutover remains open. The ordinary desk API at 4:43:40 p.m. Eastern
reported 12,697 offers, 24 current and zero qualified before-fee, reviewed-fee
or conservative EV. A separate desktop view at 4:44:42 reported 13,035 offers,
79 current and zero in all three EV categories. These independently timed and
changing publications are snapshots, not a sustained coverage measurement.
The desktop showed retained prices with explicit expired/unavailable labels.
This pass did not test a mobile journey or a latest-price replacement.

The retained North Carolina A&T–East Carolina away moneyline observation was
Novig-via-SGO +809, with an available, line-free SGO fair baseline +643,
source clock 4:33:49.796 p.m. and receipt 4:34:20.174 p.m. The fair value has
no source clock. The SGO side, period and line are identifiable within this
receipt; the occurrence association is estimated, and a verified native
contract, settlement and applicable fee are not established. The vendor
baseline is display context, not a qualified offer-specific reference. Neither
before- nor after-fee EV is established by these facts.

At 4:43:20, of the retained SGO reference facts, 468 of 2,911 NCAAB live and
370 of 11,792 NCAAB pregame facts had source clocks within 15 minutes; 455
and 370 respectively were marked available. No retained NBA, NCAAF, NFL or
NHL pregame fact, or NCAAB started fact, had a source clock within 15 minutes.
These facts are not desk offer counts. The worker's next scheduled cycle was
4:48:41; a new receipt cannot renew an unchanged bookmaker source clock.

At 4:43 the SGO ledger had 11 initial plus 4,103 resolved objects, no held
objects, 10,000 reserved and no recorded external increase. The last provider
usage observation was still 4,112 at 4:35:21, before a two-object response;
it is not a post-response reconciliation. In the preceding hour, 62 resolved
refresh objects comprised three categorized NCAAB live, two NCAAB pregame and
57 older unknown objects. No discovery charge appeared in that hour. The
fixed-slate schedule still projected 2,436 refresh and 988 discovery objects
per day, with a 4,711-object daily allowance, before variable overhead. This
is a projection rather than measured sustained use; the December 1 boundary
remains provisional. The separate Odds API reserve remained 55 credits.

Both processes were running, global Stop was false and no source was paused.
Both native feeds had reported partial active coverage; Polymarket US was
resynchronizing in the desk snapshot. The Novig signed worker reported its read
key unavailable. The current [Novig fee page](https://support.novig.com/en/articles/16195057-fees-on-novig)
still gives 0.06 for live takers in its main schedule and example but 0.03
in its multi-price FAQ. Its [market rules](https://support.novig.com/en/articles/9612523-market-rules)
say the individual contract governs settlement. Neither establishes the
actual SGO-labeled contract or resolves the live-rate conflict. ProphetX's
[published mapping](https://docs.prophetx.co/docs/opticodds-id-mapping)
continues to name OpticOdds rather than SGO.

History held 10,796 witnesses and 12,525,366 logical bytes, with no recorded
capacity skips, runway skips or capacity evictions; the physical database was
1,663,427,363 bytes. The logical cap and seven-day maximum do not guarantee a
complete replay. The focused SGO, matching-input and reference suite passed
119 tests and three subtests, and the saved-details JavaScript fixture passed.
These are disposable fixture results, not live rejected-cursor or
request-specific charge reconciliation evidence. No implementation change,
paid dispatch, process restart or account modification was made in this pass.
Remaining engineering includes exact current matching and economics, measured
freshness and scheduling improvements, live recovery and the requested mobile,
replacement and in-game journeys; those are not represented as complete.

## Adaptive live polling continuation, November 11

The live scheduler now uses a five- or ten-minute target when the retained
slate's projected refresh cost fits the existing 65% refresh allocation; it
otherwise retains the fifteen-minute target. It chooses the existing pregame
policy first, and projects each observed live or started event as active for
an entire day when testing the faster target. The daily pacing, request,
reservation, Stop and source-pause controls still apply. A polling target is
not a source-clock freshness guarantee.

At approximately 4:55 p.m. Eastern, the retained schedule had 988 events,
including three live events, and the current allowance was 4,714 objects per
day. The new calculation selected five minutes and projected 3,012 refresh
objects per day; the existing discovery estimate for a fixed 988-event slate
is 988 more, before empty responses, retries and changes in the slate. This is
a static projection, not evidence of sustained affordability. The assumed
December 1 boundary remains unconfirmed by the provider.

Before restart, the 4:54 p.m. census had 437 available NCAAB live reference
facts out of 3,142 with source clocks within 15 minutes. At about 4:57 p.m.,
after the data restart, the corresponding count was 690 of 3,372. These are
different, changing populations and a short observation: they do not prove a
causal or sustained improvement. Three live event-refresh objects were
resolved after restart; one refreshed North Carolina A&T–East Carolina at
4:55:43, with 158 available facts within five minutes at 4:55:54. These are
provider facts, not qualified executable desk offers. The SGO ledger had 11
initial plus 4,136 resolved objects, no SGO hold and 10,000 reserved at the
later snapshot. The separate Odds API reserve of 55 was not changed.

The data and app processes restarted with the existing configuration and port.
The data process became healthy; Kalshi and Polymarket US both connected with
partial rotating coverage. The desktop desk showed 12,722 offers, 197 current
and zero qualified EV in a 4:56 p.m. snapshot, with source attribution and
expired-price labels. The attempted browser view initially encountered the
older app process's 403 response; after the app restart the in-app browser
loaded the desk. A complete mobile, replacement and fresh in-game drawer
journey was not established in this pass.

At a 390-pixel mobile viewport, an SGO-attributed Kalshi spread inspection
showed its original price and the separate SGO fair baseline at a different
line. Its settlement and fee were unqualified. The latest-price action kept
the same pinned capture; this did not establish adoption of a changed quote.
That inspection revealed a presentation issue: the generic venue heading and
starting fee formula could suggest the SGO observation was bound to native
venue terms. The ordinary drawer now labels its outcomes illustrative and
withholds the generic starting fee formula for SGO observations. The actual
offer, fair baseline, missing-rule explanation and EV safeguards remain. The
corrected drawer was verified in the running app and the focused DOM fixture.

Fifty-five focused worker, ledger, collector and scheduler tests, 69 adapter,
reference, source-input and desk tests (plus three subtests), the saved-details
JavaScript fixture, Ruff and the whitespace check passed. The controlled tests
cover cursor checkpoint restart, rejected-cursor hold and resumption following
evidenced resolution; no live request-specific rejection resolution was
observed. Exact native contract and settlement evidence, applicable fees,
qualified EV, complete P2P coverage and sustained freshness measurement remain
open. Novig's signed read key and ProphetX credentials were still reported
unavailable by the runtime; they are dependencies for those direct evidence
paths, not a reason to treat aggregate prices as native contracts.

Further code inspection found an independent in-game engineering gap: the
ordinary source-input phase resolver called the pregame-only event eligibility
check before accepting explicit live phase metadata. It now accepts live only
when explicit source lifecycle, live metadata, and a post-start price within
the existing 15-second freshness limit agree. A controlled fixture covers
fresh, stale, contradictory and completed states; 24 source-input tests and
three subtests passed after correcting the clock type in an initial failing
run. The data process was restarted to load the change. The legacy decisive
benchmark aging path still marks post-start values last-known. It must be
reconciled with live evidence before claiming in-game calculation support.
This remaining engineering is independent of missing venue credentials.
At 5:00 p.m. the new data process reported healthy; native reconnection was
still in progress. Between the first restart at 4:54:27 and the second at
5:00:16, the ledger recorded three live and two pregame refresh objects.
The SGO ledger then held zero and recorded 4,138 resolved plus 11 initial
objects. This short interval cannot establish a daily consumption rate.

## Live benchmark aging continuation

The legacy decisive-benchmark aging bridge now accepts a live input only when
the comparison phase is live and the existing price-lifecycle owner verifies
an explicit live event and a fresh post-start source price. Each reference
original must also have a post-start source clock no more than 15 seconds old;
missing, future, pre-start and stale clocks remain non-current. Pregame and
unverified post-start inputs continue to be non-current. This change affects
aging of an already established benchmark; it does not itself bind an SGO
fair line, a native contract, settlement or a fee, and does not demonstrate an
end-to-end live EV calculation. Existing retained last-known behavior is not
converted into a new current result.

The focused Python checks passed 139 tests and three subtests, including live
aging, source qualification, reference, scheduler, worker, ledger and collector
fixtures. The first run exposed that the worker rate-limit fixture attempted
to access the local database despite mocking initialization; its retained
schedule is now mocked. Ruff and whitespace checks passed before this report
update. These are local fixture results.

The current execution environment denied access to the existing PostgreSQL
Unix socket (operation not permitted) and process inspection. Consequently this
continuation could not inspect current account usage, safely restart or verify
the running collector and app, measure fresh object use and source clocks,
perform live desk journeys, or establish adoption of latest prices. No account,
source controls, holds, credentials or running processes were changed. The
4:55–5:00 p.m. measurements above are historical, not a current balance or
freshness census. Runtime integration and the independent engineering and
verification in the active plan remain open.

## Ordinary desk and P2P continuation, November 11, 5:11–5:35 p.m. Eastern

The ordinary publication path now carries an exact SGO reference through
before-fee math, read-time withdrawal, ranking and the pinned drawer. Live
contributors must both be post-start and at most 15 seconds old. The reference
keeps the original side, signed line, source and receipt clocks. The named
Pinnacle path verifies the reference's source lifecycle as well as the offer's.
The native Kalshi path separately uses the reviewed series and event fee terms,
with account precision required for reviewed EV. The signed Novig and native
Polymarket US paths continue to require their existing product-specific fee and
settlement evidence. The labeled SGO fair and book consensus baselines retain
their own lines and availability. The baseline fields carry no supplied source
clock, and neither enters offer-specific math.

The first-delivery scheduler now recognizes admitted SGO frames and keeps
aggregate Kalshi observations out of the native Kalshi priority slot. The
collector schedules a guarded poll at kickoff when the last attempt predates
kickoff, and accounts for that extra object in its projection. The budgeted
fallback can extend refreshes beyond 72 hours to 48 hours while discovery still
follows its existing cadence. New worker diagnostics count admitted P2P
observations by league, phase, family and bookmaker, including 15-minute
source-clock coverage and receipt-time live clock triples against exact
Pinnacle sides. A clock triple is a timing observation only. Native occurrence,
settlement and applicable fee remain separate requirements.

### Running observations

| Observation | Result |
| --- | --- |
| Process access | The shell denied `/bin/ps`, the PostgreSQL socket and the app's loopback port. The in-app browser reached the running desk on port 8784 and read Admin status. The app served the updated SGO account display. The ordinary calculation child loaded the new code during its normal loop. Its first query used an invalid SQL alias and interrupted publication. After correction, new captures resumed, the desk reported 157 current of 12,601 offers at 5:31:41, and Admin showed a healthy data runtime with no board error at 5:34:55. No controlled restart of either long-lived process was possible, so the collector's updated scheduling and counters remain unverified in its running process. |
| Native continuity | At 5:23:11, Kalshi and Polymarket US both reported completed restoration and available prices, with 256 active each and 10,874 and 13,482 deferred respectively. Their latest native source clocks were about 2.6 and 3.4 seconds old. Polymarket US was resynchronizing at 5:33:12 and available again at 5:34:55. Stop was off and no sources were paused. These are partial, rotating subscriptions. |
| SGO accounting | At 5:34:55, 4,212 locally accounted objects (11 initial and 4,201 charged), zero held, 10,000 reserved and 85,788 available above reserve. Provider usage was 4,211 immediately before the last one-object response, so post-response provider reconciliation remains pending. The local ledger recorded zero external increases. The separate 55 uncertain Odds API credits remain held. |
| SGO spend, hour ending 5:33:12 | 101 resolved event-refresh objects: NCAAB 73 pregame, 14 live and 2 started, NBA 6 pregame, NCAAF 3 pregame and NHL 3 pregame. No discovery charge fell in this hour. The ledger had completion markers for all six league cursor walks and no in-progress checkpoints at the read. These markers record traversal, without establishing complete coverage or withdrawal. |
| Pacing | At 5:23:11 the running collector projected 3,351 refresh and 988 discovery objects/day on 988 retained events against a 4,719 allowance. The 15-minute live target was selected and the refresh projection exceeded its 65% allocation. The 380-object difference between allowance and combined static projection precedes variable overhead. The December 1 reset remains a pacing assumption. Rookie advertises three-minute updates and its tier has no streaming entitlement. [Pricing](https://sportsgameodds.com/pricing) · [Streaming](https://sportsgameodds.com/docs/guides/realtime-streaming-api) |
| Available freshness evidence | A materialization-cache sample read at 5:26 had 113 unique SGO offer identities across 14 events, 85 Kalshi-labeled and 28 Novig-labeled. Among 89 available originals, 29 source clocks were within 15 minutes of the 5:23 observation and 10 were within 15 seconds at their own receipt. Zero were both post-start and within 15 seconds of their receipt. The cache omits the reference pair and is a bounded subset, so it cannot establish a real-feed triple rate or a current SQL history census. At 5:12:46 the live-observed desk filter showed 50 offers and zero current. The later unfiltered desk snapshot still had zero qualified EV. |

### Representative offers and controls

- North Carolina A&T at East Carolina, the earlier Novig-via-SGO away full-game
  moneyline, retained +809 and the line-free vendor fair baseline +643. They
  imply 11.00% and 13.46% respectively. The match remains estimated, the
  baseline has no supplied source time, and the native contract and fee are
  unverified, so neither before-fee nor after-fee EV qualifies for this offer.
- The running desktop and mobile drawers showed East Carolina versus Charlotte,
  Novig-via-SGO East Carolina -11.5 at -106, expired, with the independent fair
  baseline +100 at -12 and no original baseline clock. The 390-pixel viewport
  check showed the loaded baseline and latest-price control without horizontal
  overflow. The desktop latest-price action kept the capture pinned and reported
  no current price. A live-observed Kalshi spread on Saint Joseph's was expired
  and correctly withheld both EV results.
- A current Novig-via-SGO North Carolina Central -7.5 at -102 could be pinned.
  Its latest-price action returned the same capture. A current native Kalshi
  Indiana Pacers -9.5 at +233.33 subsequently showed a change in available
  calculation evidence. The replacement ceased to be current before adoption,
  and the original stayed pinned. The controlled DOM check adopted a newer
  qualifying capture and verified the updated fee and reference together.
- Controlled live NBA spread: 40¢ Kalshi acquisition cost, two exact Pinnacle
  sides at -110, and a 50% decisive probability. The $1-claim profit before
  fees is $0.10 and the return is 25.00%. The reviewed direct-account fixture
  produces a $0.0168 fee and a 19.96% return. The public conservative scenario
  risks $0.42 and returns 19.05%. Expiring the reviewed fee withdraws its
  result while leaving before-fee EV current. Expiring the reference withdraws
  the remaining EV. The contract, account and clocks in this case are fixtures.

### Remaining evidence and verification

- The signed Novig key remains unavailable, which blocks the signed quote,
  contract and depth journey. The public help page gives 0.06 in the live
  schedule and 0.03 in the multi-price FAQ. The applicable signed market terms
  and exact contract settlement are required before live fees can qualify.
  [Fee page](https://support.novig.com/en/articles/16195057-fees-on-novig) · [Market rules](https://support.novig.com/en/articles/9612523-market-rules)
- `prophetexchange` remains an SGO identifier. The public ProphetX mapping
  supports OpticOdds IDs. A current SGO-to-ProphetX contract mapping and
  applicable account terms are still needed for native settlement and EV.
  The preceding run reported the production credential unavailable.
  [Mapping](https://docs.prophetx.co/docs/opticodds-id-mapping)
- The retained free sample's `polymarket` link points to `polymarket.com`,
  while direct Polymarket US stays independent. Matchbook and Betfair Exchange
  observations remain available for audit. Their bookmaker labels supply no
  verified applicable U.S. product, contract, depth or account fee for the
  desk. Matchbook's published commission varies by location and account.
  [Matchbook terms](https://www.matchbook.com/page/getting_started/placing-bets-on-matchbook/)
- A current reviewed occurrence link or typed shared identifier plus exact
  native scoring evidence is still required for live SGO-pair publication.
  The current account's rate of co-fresh exact observations, SQL history
  runway, request-specific rejected-cursor reconciliation, two-process
  restart and adoption of a newer qualifying running capture remain open.
  An uncertain charge requires authoritative request-level evidence. The
  controls, credentials, holds and quotas were left as observed.

The focused Python suites passed 249 tests and 13 subtests. The retained
Kalshi replay suite initially failed because its historical packet is absent
from the active evidence directory. All three replay tests passed when pointed
at the archived packet in place. Both drawer fixtures, JavaScript syntax,
Ruff and whitespace checks passed. The PostgreSQL 16 disposable harness was
attempted and `initdb` failed at `shmget` with `Operation not permitted`, so the
SQL integration suites could not run. The collector's controlled rate-limit,
rejected-cursor, interruption and evidenced-hold-resolution fixtures passed.
No request-specific live rejection or charge resolution was observed.

## Evening runtime and qualification follow-up

At 5:52:01 p.m. Eastern the ordinary desk showed 138 current of 12,658
offers and zero EV in all three calculation bases. At 5:54:09 the live-observed
filter showed 63 retained offers, zero current and zero EV. At 6:01:11 the
ordinary fee census (generation 48,441) showed 218 current of 12,286 published
offers, zero numeric fees and zero before-fee or after-fee EV. The current fee
gaps were 84 awaiting calculation under the current policy, 72 SGO observations
without a verified native contract, 42 requiring public schedule review, and
20 outside the reviewed fee window. These are separately timed views, with
different populations and filters. The 99% fee-coverage goal remains open.

### Representative journeys

- The independent Kalshi Pacers -9.5 Yes contract
  `KXNBASPREAD-26NOV11WASIND-IND10` was pinned at +233.33 (30¢). The
  retained native binding was verified and the `KXNBASPREAD` scoring evidence
  includes overtime. Its exact normal outcome is home margin greater than
  9.5. The three-source occurrence was a unique metadata association marked
  estimated. A retained update at 6:02:27 carried the same price. The latest
  action first left the same capture pinned and a later attempt found no
  current price. No newer qualified result was available to adopt.
- The desktop live-observed Polymarket US South Florida -21.5 Short against
  Saint Joseph's showed its original 1¢ acquisition price (+9900), an
  expired offer, missing cross-site settlement and reference evidence, and
  an expired account review. The drawer kept the earlier evidence when the
  latest-price action found no current replacement.
- At 390 pixels, the North Carolina Central +7.5 Novig-via-SGO drawer showed
  -104 and the independent SGO fair baseline of +100 at +7.5. The fair
  baseline's receipt was 5:52:55.897 p.m. Eastern and its original source time
  was unavailable. The aggregate observation has no verified Novig contract
  binding. The drawer fit without horizontal overflow, and the latest-price
  action preserved its evidence when a current replacement was unavailable.
- The controlled live Kalshi regression still gives 25.00% before fees,
  19.96% with reviewed fees and 19.05% with conservative fees. Reviewed-fee
  expiry withdraws the reviewed EV while the original reference still supports
  before-fee EV. Reference expiry withdraws that result too. Controlled drawer
  tests adopted a qualifying replacement and kept an earlier capture when
  authority was withdrawn during adoption.

### Receipt clocks, usage and evidence gaps

- The materialization cache at approximately 5:59:19 retained 450 unique SGO
  offer identities across 49 events (252 Kalshi-labeled and 198 Novig-labeled).
  Of 272 available originals, 76 had a source clock within 15 seconds at their
  receipt. None had a post-start source clock. The occurrence associations
  were estimated for 200 offers and source-local for 250. The cache omits the
  reference pair and is bounded. The live fee census and cache cannot establish
  the receipt-time triple rate across actual paid pages.
- At 5:58:37 the collector projected 3,376 refresh and 986 discovery objects
  per day against a 4,725-object allowance. The refresh target stayed at 15
  minutes for active events. At 6:02:24 Admin showed provider usage and
  the ledger in agreement at 4,242 used (11 initial and 4,231 charged), zero
  SGO holds, 10,000 reserved and 85,758 available above reserve. The earlier
  read-only ledger sample for the hour ending 5:52:58 recorded 88 refresh
  objects, including 11 live and two started NCAAB objects. The separate 55
  uncertain Odds API credits were still held. The December 1 pacing boundary
  remains an assumption. Rookie advertises a three-minute update frequency,
  so another local poll cannot make an unchanged provider clock fresh.
  [SGO plan](https://sportsgameodds.com/pricing)
- The existing runtime reported both native feeds restored and available,
  each with 256 active subscriptions. At 6:01:11, Kalshi's status source
  clock was 1.82 seconds old and Polymarket US's was 2.14 seconds old. The
  deferred counts were 10,878 and 13,484. Global Stop was off and there were
  no paused sources. At 6:02:24 Admin showed no board error and about 1.88 GB
  of physical SQL use. The history census and runway still require direct SQL.
- The retained NBA and NHL source responses each had five Novig event links,
  five Pinnacle links, five Matchbook links and five `polymarket.com` links.
  The Novig event UUID is review material for a future join to the signed
  native catalog. Event links supply no individual market, outcome, fees or
  depth. The public Novig help page still gives 0.06 for straight trades and
  0.03 in its multi-price live FAQ. The signed read key remained unavailable
  in Admin. Those gaps block a signed live quote, its exact applicable fee
  and confirmed Novig contract economics. ProphetX still requires an
  authoritative SGO-to-current-contract map and applicable account terms.
  SGO's `aliases` are prior SGO IDs. The published ProphetX mapping accepts
  OpticOdds IDs. [SGO events](https://sportsgameodds.com/docs/endpoints/getEvents)
  · [Novig fees](https://support.novig.com/en/articles/16195057-fees-on-novig)
  · [ProphetX mapping](https://docs.prophetx.co/docs/opticodds-id-mapping)

### Working-copy changes and remaining verification

- Due kickoff and active refreshes now run between discovery pages using the
  existing request, pacing and object guards. Discovery retains its original
  filter and cursor. Poll telemetry records schedule delay at the guarded
  request attempt. Receipt measurements separately count explicit live state,
  post-start clocks, clocks within 15 seconds, reciprocal exact Pinnacle pairs
  and the remaining clock window after admission. These counters are
  source-local observations. Desk eligibility still requires native
  occurrence, settlement and current authority evidence.
- The ordinary path now identifies a matched pair whose clocks or game phase
  prevent qualification separately from a missing pair. The 15-second ceiling
  still applies. SGO event frames retain bounded, provider-attributed
  bookmaker hosts and paths for review. The link fields carry no automatic
  contract authority and exclude URL query strings and fragments.
- The focused Python run passed 209 tests and 14 subtests. The wheel build,
  both drawer fixtures, Ruff, JavaScript syntax and whitespace checks passed. PostgreSQL
  16.15 `initdb` again failed at `shmget` with `Operation not permitted`, before
  the disposable SGO scope, ingress, ordinary publication and snapshot suites
  could run. The shell also denied `/bin/ps` and the existing socket on port
  55432. The running Admin heartbeat still reported data PID 99805, and the
  collector did not expose either the receipt or poll counters. These
  restrictions blocked the two-process restart, direct SQL freshness/history
  census, post-restart native continuity and running cadence comparison.
  Qualification with real current references and adoption of a newer
  qualified capture remain unobserved. The controlled evidence is retained
  alongside those running limitations.

## Follow-up on main, November 11, 6:10–6:25 p.m. Eastern

The coverage worker now uses the selected aggregate provider's scope,
accounting and query history. Legacy Odds API receipts and holds stay in
their original records. A Kalshi-labeled SGO observation uses SGO source
authority for its coverage clock. Coverage uses the same explicit live state
and 15-second post-start clock as the desk. The collector measures an exact
reciprocal Pinnacle pair independently of clock eligibility. It counts
available observations within 15 seconds at receipt and records how many
active and kickoff polls completed between discovery pages. Admin reports
the counters, the provider and ledger snapshots, and the discovery and
refresh projections. A completed walk still supplies no coverage denominator.

| Check | Observed result |
| --- | --- |
| Loaded runtime | The running app served the updated SGO Admin diagnostics on port 8784. The 6:23:46 p.m. Coverage capture showed the new SGO accounting route and 30 retained NBA Novig moneyline observations. The capture was marked stale at read. The 6:24:12 heartbeat reported the ordinary board and Coverage running with no errors. Data PID 99805 was unchanged and neither collector counter was present. The app process record listed PID 86084. |
| Native feeds and controls | At 6:10 both feeds were restored and available with 256 active each, 10,878 Kalshi and 13,484 Polymarket US deferred. At 6:24 Kalshi was resynchronizing while Polymarket US remained available with a 1.64-second-old source clock. Global Stop was off and no source was paused. |
| Spending | At 6:24 the SGO ledger accounted for 4,282 objects (11 initial and 4,271 charged). Provider usage of 4,281 immediately preceded a one-object resolved response. The last provider reading and subsequent charge account for the observed difference. A post-response provider reading was unavailable at that snapshot. There were zero SGO holds and zero recorded external-use increases, with 10,000 objects reserved and 85,718 available above reserve. The separate Odds API ledger still held 55 uncertain credits in 20 attempts. |
| Last hour ending 6:24:30 | 102 resolved objects from 57 refresh responses and zero discovery charges. NCAAB used 58 pregame, 11 live and 2 started; NBA used 17 pregame, NCAAF 6 and NHL 8. All six leagues had earlier cursor completion markers. No in-progress checkpoints were present at the earlier 6:13 ledger read. |
| Schedule and storage | The running collector projected 3,781 refresh and 986 discovery objects/day against a 4,730-object daily allowance. The projection exceeds allowance by 37 before variable overhead. The running collector still showed 24-hour distant polling and 15-minute active polling. The working copy's 48-hour distant fallback still needs running measurements. Admin reported 1,721,467,683 of 2,147,483,648 physical SQL bytes. The earlier history census remains the latest direct measurement of the seven-day and 32 MiB history bounds. |
| Offer freshness and EV | The 6:18 bounded materialization-cache sample retained 142 distinct SGO offers across nine events. Of 124 available observations, 16 were within 15 seconds at receipt and zero had post-start clocks. All 142 occurrence associations used metadata. At 6:24:54 the fee census reported 111 current of 13,988 published, including four in-game Kalshi-labeled offers. Zero had a numeric fee, an exact Pinnacle reference or qualified EV. Of 111 fee gaps, 72 lacked a verified SGO-to-native contract, 21 were outside their review window, and 18 required public fee schedule review. |

At the 6:18 cache read, the Wizards–Pacers Novig-via-SGO Pacers full-game
moneyline was -141 for SGO event `GjXCvh8mMGBUweiItPMp` and odd ID
`points-home-game-ml-home`. Its original source time was 6:02:13.712 p.m.
and receipt was 6:02:30.218 p.m. The 16.506-second receipt age is a measured
provider-to-receipt interval, and the cache retains a metadata-only
occurrence match. The quote supplies no verified Novig contract, depth or
fee. The independent Kalshi Pacers spread retained its reviewed scoring
scope, with the cross-provider occurrence association still estimated.
The retained SGO NBA and NHL pages include venue event links, with no
individual market deeplinks for the sampled exchanges and no typed shared
event ID. SGO documents both link levels separately.
[SGO bookmaker links](https://sportsgameodds.com/bookmakers)

The live-observed desktop drawer showed Bethune-Cookman -3.5 on Kalshi at
+1150 (8¢), with unavailable reference and fee results. On mobile, the
Polymarket US Bethune-Cookman +6.5 drawer showed +104.08 and preserved the
6:15:53 p.m. capture after a latest-price request. At a 390-pixel viewport
the drawer's client and scroll widths were both 322 pixels. Both running
drawers kept their prior capture when a replacement was unavailable. The
6:24:54 census caught four current in-game offers. A later live-observed
desk read showed 99 offers and zero current. No newer qualifying running
replacement was available in the sampled journeys. The controlled drawer
adopted a newer qualifying capture and retained the original when authority
changed during adoption. The controlled Kalshi calculation still yields
25.00% before fees, 19.96% reviewed and 19.05% conservative. Fee expiry
withdraws reviewed EV first and reference expiry withdraws before-fee EV.

Signed Novig access remained unavailable and public discovery reported
HTTP 429. The fee help page still lists 0.06 for live straights and 0.03 in
its multi-price explanation. Novig's October 12 article describes a
league-dependent app/web schedule. Applicable terms for the exact signed
market and fill route are still needed for live after-fee EV. The market
rules require the terms of the specific contract for settlement. ProphetX
still needs a current SGO-to-ProphetX event, market and strike mapping and
applicable account terms. Its public mapping API lists OpticOdds.
[Novig fees](https://support.novig.com/en/articles/16195057-fees-on-novig) ·
[Novig fee comparison](https://landing.novig.com/blog/prediction-market-fees-compared) ·
[Novig market rules](https://support.novig.com/en/articles/9612523-market-rules) ·
[ProphetX ID mapping](https://docs.prophetx.co/docs/opticodds-id-mapping)

The existing launcher could not inspect process ownership because the
session denied `/bin/ps`. Direct access to the existing PostgreSQL Unix
socket on port 55432 and binding an HTTP fixture socket were also denied.
The primary PostgreSQL 16.15 rerun reached `initdb`, which failed creating
its shared-memory segment with `shmget` and `Operation not permitted`.
The SGO current-row, ingress, ordinary publication and snapshot SQL tests
did not execute. A separate legacy Admin recovery selection stopped in
fixture setup with `clock_continuity_unknown`. The controlled SGO tests
cover kickoff and active interleaving, cursor recovery, durable uncertain
charges, Stop and budget guards. The running restart, new collector
telemetry, fresh SQL history census and measured schedule comparison need
local process and socket access. This pass made no source, credential or
account-control changes. Owner review remains pending integrated verification.

The final focused run passed 225 tests and 31 subtests. One HTTP occurrence
test was excluded after its fixture could not bind loopback. The separate
asset-delivery HTTP fixture hit the same restriction. Both drawer fixtures,
Ruff, JavaScript syntax and whitespace checks passed. The final wheel built
with SHA-256 `e195fd76d3d25edc4380ff09dff228954410c085688f1a0d02356d068ca30ed8`.
The earlier build and its 209 tests and 14 subtests remain part of the record.

## Pacing and access follow-up on main, November 11, 6:35–6:40 p.m. Eastern

- The running collector still reported PID 99805 and neither new counter.
  Between the two heartbeat reads it advanced from 92 to 96 requests and
  from 167 to 174 returned event observations. Both native feeds reported
  available at both reads. Board and Coverage reported running. Coverage
  published a 6:39:44 capture across all six configured leagues with SGO
  accounting, 17,469 retained observations and 739 current. The capture was
  marked stale by the time it was read.
- The provider and ledger agreed at 4,314 objects at 6:35. At 6:38 the
  local ledger recorded 4,319 (11 initial and 4,308 resolved), zero holds,
  no external-use increases and 10,000 reserved. The preceding hour used
  106 refresh objects across 59 responses, with zero discovery charges.
  The later heartbeat showed 4,323 accounted and a preceding provider
  reading of 4,321. The 55 uncertain Odds API credits were preserved.
- The 6:35 collector projected 3,830 refresh plus 985 discovery objects
  per day against 4,731. The working copy now uses the refresh projection
  when selecting 12-, 24- or 48-hour repeat discovery. It aims to keep the
  combined estimate below 90% of allowance, with at most 25% allocated to
  discovery. If none of the supported intervals meets the target it uses
  the slowest interval and leaves the existing hard accounting guards in
  force. Applying the new repeat interval to the observed projection alone
  would reduce discovery from 985 to approximately 493 objects/day.
  That is a calculation using the earlier refresh estimate. Actual cadence,
  spend and discovery latency still need measurement after restart.
- At 6:38 the ordinary fee census counted 433 current offers out of 10,297
  published and no current in-game offers. Zero had numeric fees, an exact
  Pinnacle reference or qualified EV. Of the current offers, 384 lacked
  verified SGO-to-native contracts, 31 lacked applicable fee review, and
  18 required public schedule review. The 6:38:52 cache sample had 253
  distinct SGO offers across 17 events. Of 222 available, 68 were within
  15 seconds at receipt, 56 were within 15 minutes at read, and zero had
  post-start source clocks. Occurrence methods were metadata for 210 and
  source-local for 43. The earlier Pacers, running drawer and controlled
  adoption results remain separate evidence.
- The pacing wheel built with SHA-256
  `e83f4b354cef984e6b9cc36322d9565ed3a9ddb16a2fcc023966cc920b3ad5be`.
  The focused run passed 225 tests and 31 subtests with the existing
  loopback-bound test deselected. Both drawer fixtures and Ruff passed.
  The primary PostgreSQL 16.15 and compatibility PostgreSQL 14.20 harnesses
  both failed at `initdb` shared-memory creation with `shmget` and
  `Operation not permitted`, before running SQL tests. The existing PG14
  socket and launcher process inspection were still denied. The deployed
  collector and PostgreSQL census need execution from a session with
  access to the local socket and process controls.

The [read-only census](../scripts/sgo_runtime_census.sql) is ready to run
against the project socket. It uses a single read-only snapshot for source
clock ages at receipt and at read, the seven-day age limit, retained logical
bytes, and capacity/runway counters. It reports retained SGO reference facts
separately from the ordinary desk's verified outcomes.

## Restart follow-up on main, November 11, 6:54–7:02 p.m. Eastern

- The local launcher records show data PID 32598 at 6:54:57 and app PID
  32605 at 6:54:58, replacing PIDs 99805 and 86084. The owner confirmed
  HTTP 200 from the desk and a healthy, active data process. The initial
  owner status check showed a request-rate wait and zero admitted pages.
- At 7:01:51, the SQLite ledger showed 14 resolved event-refresh requests
  created after the restart, charging 28 objects. Of those, 19 were
  NCAAB live, five NCAAB pregame, three NBA pregame and one NHL pregame.
  The ledger then accounted for 4,371 objects, with zero SGO holds. The
  prior 55 uncertain Odds API credits were not changed.
- The 7:01:48 calculation materialization cache contained 139 distinct
  SGO offer observations with receipts after the data restart, alongside
  438 from Kalshi and 470 from Polymarket US. Of 69 available SGO
  observations, all 69 had post-start source clocks and 34 were within
  15 seconds at receipt. This is a bounded calculation input sample.
  It does not establish desk publication, verified contracts, eligible
  fees or the full collector timing distribution.
- The restarted processes were accessible from the owner's Full Access
  shell. The assistant shell still denied local process inspection,
  the PostgreSQL socket and the HTTP loopback port. The live collector
  counters, complete Coverage and fee results, and the direct SQL
  freshness/history census remain pending an export or access from this
  session. The previous PostgreSQL 16.15 and 14.20 fixture failures are
  unchanged.

## Post-restart export and running desk, November 11, 7:04–7:07 p.m. Eastern

The Full Access shell exported Admin status and ran the read-only PostgreSQL
census. The prior process and socket restrictions no longer blocked these
checks. The earlier disposable PostgreSQL harness failures remain part of
the test record.

- At 7:04:30, data PID 32598 was healthy with Stop off and no sources paused.
  Both native feeds reported 256 active subscriptions and partial coverage.
  SGO had admitted 22 pages with 43 event observations. Poll counters showed
  four active, 24 kickoff and 15 scheduled events. At 7:07:22 it had admitted
  23 pages and the active poll count reached six. No active or kickoff poll
  was counted between discovery pages in either read.
- At 7:04, the selected live target was 15 minutes, repeat discovery 48 hours
  and distant refresh 48 hours. The static projection was 4,698 refresh
  plus 492.5 discovery objects/day against a 4,736 allowance, about 455 over
  before variable overhead. Provider usage was 4,384 before a resolved
  two-object response, with 4,386 accounted in the adjacent ledger, zero
  SGO holds and 10,000 reserved. The 55 uncertain Odds API credits remain
  separate. The pacing boundary remains provisional.
- In the collector sample, 95 of 223 available live offers met the source
  clock check at receipt and 93 at admission. Zero had an exact live
  Pinnacle pair. The 7:04:32 SQL census found 56,455 retained reference facts
  and 46,545 available, of which 695 had post-start clocks within 15 seconds
  at receipt. Zero still met the post-start 15-second clock test at read.
  The collector and SQL counts describe different populations.
- SQL history retained 29,117 witnesses and 33,554,379 logical bytes against
  a 32 MiB cap. It recorded 26,496 capacity evictions, zero capacity or
  runway skips, and zero rows older than seven days. The oldest witness
  was about 75 minutes old. The history relation occupied 69,754,880
  physical bytes, and the database measured 1,758,585,635 bytes.
- The 7:07:44 fee census counted 242 current offers of 11,513 with zero
  qualified fees. The gaps were 178 unverified SGO-to-native contracts,
  34 expired or ineffective fee reviews, and 30 requiring public fee
  schedule review. The 7:07:57 ordinary desk read counted 238 current
  of 11,513 with zero before-fee, reviewed-fee or conservative EV.

Runtime reload and direct SQL verification are complete. The integrated
cutover remains open on budget and freshness, contract and settlement
evidence, fee and reference qualification, supported P2P paths and running
in-game and newer-price adoption verification. Continue the known engineering
in one assignment. Keep the missing Novig and ProphetX evidence scoped to the
venue outcomes it affects.

## Cutover work on main, November 11, 7:04–7:52 p.m. Eastern

The working copy plans refresh and discovery against the same allowance.
Discovery uses the greater of retained events or the last completed walk's
charge per league, including empty-page minimums. The plan leaves 10% for
variable cost and stretches pregame refresh before slowing live polling.
Repeat discovery has 12-, 24-, 48-, 72- and 96-hour choices. The hard ledger
checks still own dispatch. A synthetic 985-event fixture using the 4,736
allowance projected 3,738 refresh plus 492.5 discovery objects/day and
retained the 15-minute live target. The running collector still uses its
prior policy.

Kickoff and active work can preempt discovery across scheduler turns.
Routine backlogs have bounded work between discovery pages. A lagging
balance retries the usage read while paid dispatch stays blocked. Rejected
cursors drop the checkpoint and retain the unresolved reservation. Controlled
tests covered those paths, including active and kickoff interleaving.
Normal running interleaving was not observed.

### Matched spend and source-clock windows

The 7:04:30–7:31:51 p.m. window used 44 resolved objects, all event refresh.
The quote counts are differences between the two admitted collector exports
from the same PID. They include repeated observations in the P2P and Pinnacle
clock sample.

| League and phase | Objects | Available observations | Live fresh at receipt | Live fresh at admission | Exact live Pinnacle pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| NBA pregame | 5 | 160 | — | — | — |
| NCAAB pregame | 7 | 129 | — | — | — |
| NCAAB started | 1 | 0 | — | — | — |
| NCAAB live | 26 | 463 | 130 | 118 | 0 |
| NCAAF pregame | 3 | 75 | — | — | — |
| NHL pregame | 2 | 64 | — | — | — |

NFL and MLB had no charged event refresh in the interval. At 7:44:42 the
ledger accounted for 4,468 objects after a provider reading of 4,467.
SGO had zero holds and a 10,000-object reserve. The separate 55 legacy Odds
API uncertain credits were left in place. The running policy was still
15 minutes live and 48 hours for discovery. Its active and kickoff
interleaving counters remained zero. The pacing boundary remains provisional.

The current Santa Clara Novig-via-SGO winner showed -108, SGO fair odds of
-110, and consensus of -121. Its book clock was 7:33:48.125, receipt was
7:33:59.347, and desk capture was 7:38:37.542 p.m. Eastern. That is 11.222
seconds source-to-receipt and 278.195 seconds receipt-to-capture. First
publication timing is unavailable for that capture. The working copy adds
bounded admission, capture, and first publication-write clocks, and a
league/phase SQL census. Fresh explicit SGO live receipts get a publication
slot ahead of routine work while preserving oldest and native-feed slots.
These changes preserve the 15-second in-game clock limit. The provider lists
a three-minute Rookie update frequency. [SGO plan terms](https://sportsgameodds.com/pricing)

### Qualification and journeys

- Verified venue event permalinks can associate a Novig UUID or a Kalshi
  ticker with an independently observed source event of the same league,
  roles and start. The tests reject wrong hosts, conflicting schedules and
  duplicate aggregate events. Market, outcome, settlement and fee evidence
  remain independent. The current SGO Novig and Kalshi-labeled observations
  lacked an exact contract witness. Historical provider start values are
  retained for audit.
- The Polymarket US review matched the full normalized official page against
  the collector's independent document hash. The November 11 and 14 changes
  apply to combos. The standard tier ceiling, order insertion, acquisition
  price and rounding checks remain in force. A prospective worker check
  after reload is still needed. Kalshi's installed review was expired and
  its official PDF renderer route was unconfigured.
  [Polymarket US schedule](https://docs.polymarket.us/fees) ·
  [Kalshi PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf)
- Both native feeds reported 256 active images and partial coverage at 7:29
  and 7:44. At 7:44 there were 9,979 Kalshi and 12,550 Polymarket US
  deferred. At 7:46:42 the census found six current in-game Polymarket US
  NBA offers, two each in winner, spread and total. A subsequent live-only
  read had zero current of 579. The earlier unfiltered census counted zero
  qualified fees or EV out of 136 current offers, including 77 awaiting
  calculation under the current policy, 31 public schedule review gaps,
  20 unverified SGO contracts, and eight expired or ineffective reviews.
  At 7:52:27, the 119-current-offer census had no remaining policy-replaced
  gaps. It counted 24 current in-game offers and zero qualified fees or EV.
  The fee gaps were 59 public schedule reviews, 36 unverified SGO contracts
  and 24 expired or ineffective reviews.
- The desktop Pacers -5.5 drawer kept +138.10 after an unavailable latest
  price. The mobile Bethune-Cookman Novig-via-SGO drawer fit at 390 pixels
  with a 352-pixel client and scroll width, and kept the original pinned.
  Santa Clara showed the current source price and both vendor baselines.
  Newer qualifying adoption passed in the controlled drawer and remains
  unobserved on the running desk. The live Celtics–Raptors Polymarket US
  Celtics -6.5 drawer showed +488.24 and retained its 7:52:42 capture.
  It subsequently signaled changed calculation evidence. The controlled ordinary Kalshi case
  reconciled 25.00% before fees, 19.96% reviewed and 19.05% conservative.
- Novig's signed API documents per-market terms and a 0.06 live-game taker
  coefficient. The signed path preserves a post-reset top price when the
  one-order size or fee terms are incomplete. The production read key was
  unavailable, so signed live prices, applicable terms and depth remain
  unobserved. The ProphetX production credential was inaccessible. Its
  public mapping accepts OpticOdds and its fees depend on account terms.
  SGO Prophet Exchange observations remain source-local pending an
  authoritative event, market and strike map and applicable fees.
  Matchbook and Betfair Exchange provide observations without established
  US execution and fee applicability. [Novig API fees](https://docs.novig.com/api/concepts/fees) ·
  [ProphetX mapping](https://docs.prophetx.co/docs/opticodds-id-mapping) ·
  [ProphetX fees](https://docs.prophetx.co/docs/fees)

### Runtime and test disposition

The browser reached the installed desk and data PID 32598 remained healthy,
with global Stop off and no pauses. A diagnostic schema edit briefly caused
the respawned calculation child to encounter an undefined column. The
diagnostic now uses a separate optional relation and publication resumed.
Admin reported Board and Coverage running without errors. Calculation
members from the earlier policy still age out through normal publication.
The 7:52 census had no current policy-replaced cohort. The collector and
fee owner still need a verified reload. At 7:52 the running plan projected
5,655 objects/day against 4,745 and the ledger had accounted for 4,496
objects, zero held, and 10,000 reserved.

The latest direct history census remains 7:04:32 p.m. with 29,117 witnesses,
26,496 capacity evictions, zero skips, about 75 minutes of retained history,
and no rows older than seven days. At 7:44:42 Admin reported 1,777,443,619
physical SQL bytes, followed by 1,599,963,939 at 7:52. Direct socket access
was denied, so the later readings measure database runway. The session's automatic approval policy
rejected escalated process and socket preflight. Disposable PostgreSQL
16.15 and 14.20 each failed at `shmget` with `Operation not permitted`.
The Docker socket was also denied. An earlier broad run hit the project
socket from an old reference fixture and failed before opening a database.
That fixture now requires the disposable harness.

The final focused run passed 243 tests and 14 subtests, with 15
disposable SQL cases skipped. Ruff, whitespace, both desk DOM suites
and the wheel build passed. The wheel SHA-256 is
`a9083e533f76724b4e4cad59c7ccd84fb10af3205f8f28da639d183d9d1e837c`.
A compatible local session must reload both owners, rerun SQL and verify
the updated schedule, clock census and fee renewal. The assignment remains
open through that verification and the unresolved venue outcomes above.

## Running verification follow-up, November 11

The installed data owner was still PID 32598. Its heartbeat was healthy,
Stop was off and there were no source pauses. Board and Coverage reported
running with no errors. Desk reads continued to advance after the earlier
diagnostic schema correction. Kalshi showed 256 active and 9,406 deferred
subscriptions. Polymarket US briefly reported resynchronizing and returned
to available with 256 active and 12,856 deferred. Both native feeds reported
available independently at 9:01 p.m. Eastern.

### Spend, freshness and history

Read-only ledger accounting for 7:52–8:52 p.m. counted 183 resolved objects,
all refresh. NBA used 17 live and 14 pregame, NCAAB 100 live, 22 pregame and
five started, NCAAF 12 live, and NHL seven live and six pregame. NFL and MLB
had no charges. All six discovery sequences last completed between 2:36 and
3:16 p.m. Eastern and no checkpoint was open. No running traversal or
active/kickoff interleaving occurred in the observed window. The controlled
worker checks exercised active and kickoff refreshes between pages, cursor
and filter continuity, restart recovery, rate interruption, budget waits,
and an uncertain rejected-cursor charge that remains held.

The following deltas use the same running owner at 9:01:24 and 9:05:19 p.m.
Eastern. Available and fresh counts are repeated observations in the
collector's P2P and Pinnacle clock sample. The later export had no Pinnacle
clock cohort, so the sample cannot establish Pinnacle entitlement. Object
counts come from the matching SQLite reservation interval.

| League and phase | Objects | Available observations | Within 15s at receipt | Live fresh at admission | Exact live Pinnacle pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| NBA live | 7 | 207 | 54 | 48 | 0 |
| NBA pregame | 1 | 32 | 6 | — | — |
| NCAAB live | 6 | 70 | 17 | 16 | 0 |
| NCAAB pregame | 4 | 88 | 28 | — | — |
| NCAAB started | 2 | 0 | 0 | — | — |
| NHL live | 1 | 32 | 6 | 6 | 0 |
| NHL pregame | 1 | 32 | 16 | — | — |
| Total live | 14 | 309 | 77 | 70 | 0 |

The earlier NCAAB window had 130 of 463 fresh at receipt (28.1%) and 118
at admission (25.5%). The later NCAAB cohort had 17 of 70 (24.3%) and 16
(22.9%). The later window used 22 objects overall and zero discovery objects.
Its different slate and shorter duration limit rate comparisons. Seven live
observations aged out between receipt and admission. All 309 had an original
clock within 15 minutes at receipt. The existing 15-second live limit and
Rookie's published three-minute provider update frequency are distinct.
[Provider pricing and updates](https://sportsgameodds.com/pricing)

At 9:05 the installed owner still targeted 15 minutes live and 48 hours
for discovery, with 5,943 + 489.5 = 6,432.5 projected objects/day against a
4,757 allowance before variable overhead. The earlier crowded-slate fixture
for the updated policy returned 4,230.5 against 4,736 with a 15-minute live
target. The charged observations above are from the earlier loaded policy.
The ledger accounted for 4,718 after a provider reading of 4,716 and a
two-object refresh. The 10,000-object reserve and 55 uncertain legacy Odds
API credits remained in place. SGO had zero held objects. The provider
still supplied no reset timestamp.

The working copy now records a common admission clock for all leagues in a
mixed-league receipt and verifies original receipt clocks against the page.
Within each polling tier, due events are ordered by their actual deadline.
Fresh SGO live components use the earliest source deadline for the aggregate
publication slot and preserve the oldest work and native slots. Admin
reports individual live freshness separately from paired freshness. The
read-only SQL census includes page capture, admission and publication timing,
and still returns the retained-history section when the optional clock
relation is absent. The 9:01 Admin export measured 1,709,400,867 physical SQL
bytes. The latest direct history counts remain the 7:04 census above.

### Ordinary desk, fees and venue dependencies

- At 9:03:22, 96 of 13,178 published offers were current. Fees, exact
  Pinnacle references and all EV bases were zero. The gaps were 56 unverified
  SGO contracts, 36 awaiting the current policy, two expired reviews and
  two public-schedule reviews. At 9:08:46, the fee census had 75 current
  offers including seven in-game. Fees and EV were still zero, with 68
  unverified SGO contracts, five public-schedule reviews and two expired
  reviews.
- The running Polymarket US Warriors winner was a full-game Long at $0.3200
  (+212.50) with saved overtime-included rules. The ordinary selection
  reported public-schedule review required and had no qualified reference.
  At 9:05 the desktop drawer adopted a newer current capture at the same
  price, advancing from 9:04:00.771 to 9:05:16.091 p.m. Eastern. An earlier
  attempt during expiry preserved the pinned capture. A changed qualifying
  price was exercised in the controlled fixture and was unobserved on the
  running offer.
- The live-observed Pacers–Wizards desktop drawer showed the original Novig
  via SGO Pacers -5.5 price of +100 separately from the SGO fair -109 and
  consensus -118. The fair value was labeled different-line context. An
  unavailable replacement kept the original pinned. At a 390-pixel mobile
  viewport the native Polymarket US Pacers winner drawer fit at 352 pixels
  client and scroll width. Its expired -4900 price retained the 9:01:30
  capture after checking the latest price. The earlier running current
  Celtics–Raptors in-game drawer remains a separate witness.
- In controlled ordinary publication, the prospective Polymarket US review
  restored a $0.02 conservative one-fill fee for an applicable $0.30 Short.
  The older capture stayed unqualified. The exact paired SGO fixture for
  that acquisition price used reciprocal -110 Pinnacle prices and a verified
  occurrence and decisive settlement. It yielded 66.6667% before fees
  ($0.50 expected normal payout on $0.30 cost) and 56.25% after the modeled
  fee ($0.50 expected payout on $0.32 risk) in both pregame and live. With
  occurrence evidence removed, the fee could still publish and EV was
  withheld. With the reference source paused, current fee evidence remained
  available and the EV result was withdrawn. The installed Polymarket US
  owner still showed explicit review required. The fee and EV numbers here
  are controlled evidence. [Official fee schedule](https://docs.polymarket.us/fees)

| Dependency | Running outcome affected |
| --- | --- |
| Authorized local process and PostgreSQL access | Reload of the collector and fee owner, confirmation of prospective Polymarket US renewal on current offers, the fresh history and publication-clock census, and measurement of a normal discovery traversal under the shared policy. |
| Fresh exact reference and verified occurrence and settlement | A live ordinary before-fee EV result and, with an applicable fee, live after-fee EV. The source and the two vendor baselines remain individually visible. |
| Kalshi request-bound official PDF rendering over trusted HTTPS | Automatic renewal after the expired review, and current-offer fee and after-fee EV under applicable exact-market evidence. |
| Novig production signed read access and exact-market terms | Signed post-reset native top of book, one-order depth, exact-market fee and a qualified in-game fee journey. Public discovery and SGO prices remain observable. |
| Authoritative SGO-to-ProphetX event, market and strike mapping and applicable account terms | Current ProphetX contract attribution, its account fee and downstream economics. SGO Prophet Exchange stays source-local. |

### Verification limits

The launcher status preflight failed on `/bin/ps` and the existing project
socket returned `Operation not permitted`. The previous automatic approval
rejection is retained above. Fresh disposable PostgreSQL 16.15 and 14.20
attempts each failed on `shmget` during `initdb`, before running SQL cases.
The broad fixture attempt also hit two Kalshi renderer tests that need a
loopback listener and failed on `bind`. Direct handler checks with an HTTP
fixture then passed for an origin 429 receipt and complete two-page Poppler
extraction. No production renderer route was installed.

The focused run passed 257 tests and eight subtests, with 14 disposable
SQL cases skipped. Both desk DOM suites, Ruff, whitespace and the wheel
build passed. Wheel SHA-256
`292d8fc262c0e1446ef18ec84eeaf55592a4adde9fe398db57afc57fdf79d348`.
The installed owners and their configuration were left in place. Owner review
is pending the remaining engineer-led runtime verification.

## Runtime follow-up and SGO admission latency, November 11

From 9:20 to 9:28 p.m. Eastern, Admin continued to report the earlier data
owner, PID 32598. Stop was off and there were no source pauses. The 9:20 read
briefly reported the owner unhealthy, and the next read reported it healthy.
Kalshi and Polymarket US each showed independent book admissions in the 9:20
diagnostics. Kalshi was available while Polymarket US was resynchronizing at
9:21, and the inverse was observed at 9:24. Polymarket US recorded 17 book
batches in the recent window at 9:28 while Kalshi was resynchronizing. The
ordinary publication generation advanced from 50511 to 50565.

The read-only ledger counted 178 objects from 8:20 to 9:20, all refresh,
versus 183 in the earlier one-hour sample. The later hour included 25 live
and six pregame NBA, 89 live, 23 pregame and 12 started NCAAB, nine live
NCAAF, and six live and eight pregame NHL objects. No discovery charges or
open checkpoints were observed. The subsequent 9:20:21–9:24:49 sample
charged 18 refresh objects. Both live and kickoff interleaving counters
remained zero in the running sample. The 9:28 export accounted for 4,771
objects with zero held, a 10,000-object reserve and the 55 separate legacy
uncertain credits. The earlier loaded policy projected 4,985 objects/day
against 4,761, including 482 for discovery. The updated fixture projected
4,230.5 against 4,736. Running measurement of the updated policy still
depends on the owner reload.

| 9:20:21–9:24:49 Eastern | Charged live objects | Available live observations | Fresh at receipt | Fresh at admission | Exact Pinnacle pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| NBA | 3 | 66 | 25 | 2 | 0 |
| NCAAB | 5 | 40 | 4 | 4 | 0 |
| NHL | 1 | 25 | 6 | 6 | 0 |
| Total | 9 | 131 | 35 | 12 | 0 |

Three completed SGO preparations in the 9:20 diagnostic sample spent
4.8, 13.1 and 7.8 seconds in the combined SQL phase. The PostgreSQL log also
showed maintenance and advisory-lock timeouts in this period. Those timings
do not identify the share attributable to any single statement. The working
copy now upserts reference facts per page in one SQL statement and archives
the accepted prior witnesses in a batch. The source-clock conflict rules,
current and history capacity checks, old-revision evidence and atomic page
transaction still apply. New ingress timings distinguish reference writes and
event-frame writes from the rest of SQL admission.

The 9:22, 9:24, 9:27 and 9:28 desk censuses had zero current offers. The
9:28 read retained 14,372 offers, with source expiry reported for 14,364.
The installed fee route still reported Polymarket US review required and
Kalshi review expired. The prior running same-price adoption and desktop,
mobile and in-game pinned-evidence checks remain the running witnesses. The
later sample had no qualifying changed-price replacement or real fee and EV
result. The exact paired EV and prospective fee fixtures remain passing.

This session's `/bin/ps` preflight and the direct PostgreSQL socket read
again returned `Operation not permitted`. The fresh PostgreSQL 16.15
disposable run failed at `shmget` during `initdb` before any database tests.
The previous automatic rejection and PostgreSQL 14.20 failure remain in the
record above. The focused run passed 258 tests and eight subtests, with 14
disposable SQL cases skipped. Both desk DOM fixtures, Ruff, whitespace and
the wheel passed. Wheel SHA-256
`6a32b34c6ac3a00ac1ded14be787b4adffb3e1ccc82d23fbc29a4c46486fe774`.

An authorized local session still needs to run the existing beta launcher
with port 8784 and `.local/predict-current-config.json`, then verify the
new owner, the prospective fee renewal and the SQL census. The existing
runtime and controls were preserved during this follow-up. The Kalshi,
Novig and ProphetX dependencies remain as recorded above. Owner review
follows the engineer-led runtime verification.

## Batch SQL qualification and changed-price adoption, November 11

The actual reference and history batch statements executed in a disposable
in-process PostgreSQL 18.6 database using PGlite 0.5.16. The check loaded the
repository's reference, frame, history and delivery-clock migrations and
called the application write functions against that database. The scratch
driver adapted the PostgreSQL parameter and result interfaces. The installed
cluster and its native driver were outside this test.

- A mixed batch admitted a new Pinnacle reference and a changed FanDuel
  reference. The unchanged Novig fact retained its original source and receipt
  timestamps. The new price retained its microsecond source timestamp. An
  older observation and a conflicting usable price at an identical source
  timestamp left the current facts intact. Explicit withdrawal was accepted.
- The archive retained the replaced reference and prior event frame. An
  expiry-only write preserved both original clocks. An injected failure after
  the reference, frame, history and admission-clock writes rolled back the
  entire transaction, including history counters. The repository's SQL
  regression now exercises the mixed batch, archived facts and rollback.
- In the same engine, a reduced logical history cap verified oldest-first
  rotation, duplicate suppression, capacity and runway counters, and
  seven-day pruning. A mixed NBA/NHL receipt recorded one admission time in
  both leagues. The fixture also exercised capture and publication clocks and
  the read-only census SQL. The installed census still needs a socket read.

The refreshed regression run passed 258 tests and eight subtests. Its 14
socket-based cases were skipped. The separate embedded run executed the
expanded mixed-batch SQL case. Both desk DOM fixtures, Ruff and whitespace
passed. The production wheel remains the 9:27 build recorded above.

The 9:51 p.m. running read showed healthy PID 32598, both native feeds
available, and 13 recent Kalshi and 14 recent Polymarket US book admissions.
The desk census showed 39 current offers, including 27 in-game, in
generation 50805. The 21 Kalshi offers had no effective fee review and the
18 Polymarket US offers required public fee schedule review. There were no
qualified fees or before- or after-fee EV values. The controlled Polymarket
US fee and exact-reference EV regressions still pass.

On the running in-game desk, the Polymarket US Orlando winner inspection
advanced from **−122.22** at 9:51:32.505 to **−108.33** at 9:52:00.150 using
**Use latest prices**. The replacement showed a full-game Long at **$0.5200**
per contract. The drawer identified the outstanding fee review and absence
of a qualified live model and reference. At a 390-pixel mobile viewport,
the drawer's 352-pixel content fit without horizontal overflow. After the
replacement expired, checking latest again kept the adopted evidence pinned.
This supplements the earlier running same-price adoption and pinned-evidence
checks.

The 8:48–9:48 p.m. ledger window contained **132 refresh objects and zero
discovery objects**. The last resolved request was reserved at 9:24:46 and
the last admitted clock sample was at 9:24:58. The 9:51–9:52 status reads
showed zero new quote observations. The earlier collector was waiting for
its daily object budget. Its account showed 4,771 used, zero held and a
10,000-object reserve. The separate 55 legacy uncertain credits remained
protected. Its projection was 4,985 against a 4,761 daily allowance. The
new policy's 4,230.5-object result is still a fixture projection. The
running split SQL timings and a like-for-like freshness comparison require
the owner reload and a budget-eligible collection cycle.

The managed shell again denied `/bin/ps` and the project PostgreSQL socket.
Automatic approval rejected the elevated read-only preflight because this
session disables sandbox escalation. The earlier native PostgreSQL
shared-memory failures remain above. The installed collector and fee owner
kept their existing configuration and controls. The launcher reload, native
socket census, loaded fee renewal and post-reload collection measurements
still require an authorized local session. Kalshi's PDF renderer, Novig's
signed production access and exact-market terms, and ProphetX's mapping and
account terms remain the venue-specific dependencies recorded above.

## Local reload and live fee qualification, November 11, 10:07–10:13 p.m. Eastern

The local launcher recorded data PID 1781 at 10:07:42 and beta app PID 1788
at 10:07:43 on port 8784. The project SQL census from the authorized local
session is `.local/sgo-post-batch-reload-census.txt`. The managed shell still
denied `/bin/ps` and the project socket, and its automatic approval policy
rejected the read-only escalated preflight before execution. The earlier
shared-memory failures remain part of the record. The authorized disposable
lanes subsequently passed 15 SQL cases each on PostgreSQL 14.20 and 16.15.
The embedded PostgreSQL 18.6 regression also passed again, including retained
source and receipt timestamps, history rotation and pruning, and rollback.
The current focused run passed 193 tests and skipped 15 socket-only cases.
Both desk DOM fixtures, Ruff, JavaScript syntax and whitespace checks passed.
The updated wheel built with SHA-256
`313ee30e109f35639190ec4e5c89ab189eb3613ecc4c84d1b386b6d4e26bf195`.

At 10:13:30 the data heartbeat was healthy, Stop was off, and no sources
were paused. Board and Coverage were running. Both native feeds independently
reported available with recent receipts. The new owner had admitted 384
Kalshi and 268 Polymarket US book batches. The ordinary desk advanced from
generation 51023 at 10:09 to 51062 by 10:12.

The first guarded collection cycle resolved four requests from 10:07:56 to
10:08:00. The ledger records **eight refresh objects and zero discovery
objects**. Three NCAAB objects were started, and the live objects were one
NCAAB, three NCAAF and one NHL. The collector then returned to daily pacing
wait, with its next retry scheduled for 11:08 p.m. The provider and ledger
agreed on 4,779 accounted objects. The ledger held zero, kept the 10,000
reserve, and preserved the separate 55 uncertain legacy credits. The loaded
plan projected 3,679 refresh plus 480.5 discovery objects/day, 4,159.5
combined against a 4,769 allowance. The plan retained a 15-minute live target
and 48-hour discovery and moved distant polling to 96 hours. This burst
had no discovery traversal or discovery interleaving witness.

| Live exchange-labeled observations | Available | Fresh at receipt | Fresh at admission | Exact Pinnacle pairs |
| --- | ---: | ---: | ---: | ---: |
| NCAAB | 18 | 13 | 13 | 0 |
| NCAAF | 56 | 14 | 14 | 0 |
| NHL | 32 | 6 | 6 | 0 |
| Total | 106 | 33 | 33 | 0 |

The earlier 9:20:21–9:24:49 sample had 35 fresh at receipt and 12 at
admission across 131 available observations. NBA accounted for all 23 lost
observations in that sample and had no counterpart in the new burst. In
the overlapping league samples, NCAAB retained all 4 earlier and all 13
new fresh observations, and NHL retained all 6 in both samples. The new
sample had 73 observations already outside the live freshness requirement
at receipt. Native admissions displaced the four SGO pages from the shared
32-entry SQL timing history before the first retrieved status. The project
census provides delivery clocks, with separate reference and frame SQL
duration measurements still open. The working copy now retains the last 16
committed SGO preparations separately with receipt time, leagues, row counts
and phase timings. This diagnostic change was made after the 10:07 reload.

The 10:08:08 project census counted 75,790 retained reference facts, 58,730
available, and 74 available post-start facts within 15 seconds at read. In
the retained last-hour SQL cohort, median source-to-receipt age ranged from
39.638 to 61.063 seconds across the live leagues. Median receipt-to-admission
was 0.744 seconds for the NCAAB and NCAAF rows with admission clocks and
1.058 seconds for NHL. Median admission-to-first-page-publication was 5.688
seconds for NCAAF and 6.456 for NHL. The SQL cohort includes pre-reload rows
and incomplete page clocks. History retained 25,172 witnesses and 33,535,829
logical bytes. There were 76,634 capacity evictions, zero skips and zero
rows past seven days. The oldest retained history was about 110 minutes old.
The history relation used 73,949,184 physical bytes and the database used
1,564,910,371 bytes.

Before reload the Admin hourly spend sample stayed frozen during pacing wait.
Read-only ledger queries reproduced 132 refresh objects in the 8:48–9:48
p.m. window and found 51 in the hour ending at 10:06:28, with zero discovery
and no newly reserved paid event requests after 9:24:46 until the restart.
The reloaded Admin now dates the sample. The hour ending at the 10:07:56
cycle start showed 28 refresh objects and preceded the eight new charges.

Polymarket US renewed at **10:07:53.433 p.m.** through 10:07:53 p.m. the
following day. The loaded Admin digest matched the reviewed official source.
At 10:09:48 generation 51033 had 51 current offers, all in-game. All 39
Polymarket US offers had numeric conservative fees. The 12 Kalshi offers
had expired reviews. There were zero exact Pinnacle references and zero
before-fee, reviewed-fee or conservative EV results.

| Current Polymarket US offer | Event / market / outcome | Price and side | Unrounded → published fee | Settlement and reference |
| --- | --- | --- | --- | --- |
| Utah +4.5 vs. Orlando | `200746 / 2421654 / 4842695` | $0.40 Short | $0.0228 → $0.02 | Exact full-game half-point predicate, overtime included. SGO occurrence association remains estimated and zero reference inputs qualified. |
| Orlando–Utah over 217.5 | `200746 / 2421687 / 4842760` | $0.86 Long | $0.011438 → $0.01 | Exact full-game half-point predicate, overtime included. SGO occurrence association remains estimated and zero reference inputs qualified. |
| Philadelphia winner vs. Edmonton | `240511 / 2261442 / 4522320` | $0.41 Long | $0.0229805 → $0.02 | Market wording includes overtime and shootout. The exact comparison equality term remains unresolved and zero reference inputs qualified. |

Each fee used one acquired $1-payout contract at the highest standard taker
coefficient of 0.095, with round-half-even cents. The prospective renewal
fixture preserves the earlier capture's fee qualification state. The controlled
$0.30 Short with an exact pair still yields $0.02 in modeled fees, 66.6667%
before fees and 56.25% with conservative fees. The real offers above had
no qualified fair probability and published no EV. The earlier Orlando
−122.22 to −108.33 adoption and 390-pixel pin check remain the changed-price
witnesses. A further pre-reload desktop inspection of Chicago +15.5 kept the
$0.71 Short pinned after the offer expired and the latest lookup returned no
available replacement. [Polymarket US fees](https://docs.polymarket.us/fees)

| External dependency | Outcome still gated |
| --- | --- |
| Kalshi request-bound official PDF rendering through a trusted HTTPS route | Prospective automatic review renewal and current-offer fee qualification. The loaded owner reported `kalshi_renderer_unconfigured`. Native prices and book ingestion continue. |
| Novig signed production read access and exact-market terms | Post-reset native price, executable one-order depth, applicable in-game fee, and live fee-qualified inspection. Public pregame review was verified. SGO Novig remained separately attributed and pacing-delayed. [Novig contract rules](https://support.novig.com/en/articles/9612523-market-rules) |
| ProphetX exact event, market and strike mapping and applicable account terms | Authoritative SGO-to-ProphetX contract attribution, account-specific economics and a current ProphetX journey. Its published mapping endpoint supports OpticOdds. SGO Prophet Exchange prices retain their source-local identity. [ProphetX mapping](https://docs.prophetx.co/docs/opticodds-id-mapping) |

The reloaded SGO collector and Polymarket US fee qualification were
verified for this cohort. The follow-up below records the timing recorder
reload and remaining dependencies for live EV and P2P.

### Collector timings and reference entitlement, November 11, 10:18–10:21 p.m. Eastern

The data owner reloaded as PID 43556 at 10:17:58 p.m. with the existing
configuration. The app stayed on PID 1788 and port 8784. A paid refresh
admitted two events, 21 price records, 384 reference rows and two event
frames. The SGO-only diagnostic ring recorded 178 ms for reference SQL,
71 ms for frame SQL and 424 ms for total preparation. This is a single
page under the loaded owner. In the first reload's delivery-clock
sample, receipt to admission ranged from 0.340 to 1.058 seconds, and
admission to first page publication ranged from 5.688 to 15.582 seconds.

The 10:18 p.m. provider and ledger both recorded 4,781 objects, zero
holds and a 10,000-object reserve. The separate 55 uncertain Odds API
credits remain held. The loaded slate projected 3,847 refresh and 319.33
discovery objects per day against a 4,770 allowance, with a 15-minute
live target and 72-hour repeat discovery. The rolling budget guard
deferred further paid event dispatch and scheduled a check for 11:18
p.m. No discovery interleaving occurred in this window. At 10:20 p.m.
both native feeds had been available after restart, and Polymarket US
subsequently resynchronized. Stop was off and no source was paused.

Native disposable PostgreSQL 14.20 and 16.15 each passed 15 checks,
including batch admission, rollback, history rotation and scope recovery.
The 100 focused application tests, both drawer fixtures and two browser
regressions passed. A running desktop and 390px mobile check opened
current Polymarket US in-game fee-bearing details without overflow.
The 10:16 p.m. census independently found 17 current Polymarket US
offers with qualified fees, 24 current Kalshi offers with expired fee
review and zero qualified EV.

The retained reference table contained zero Pinnacle rows. The SGO
account is Rookie, and SGO lists Pinnacle as Pro and higher. Named
Pinnacle EV needs an entitled reference source as well as fresh, exact
paired prices and matching settlement. The existing alternative needs
reviewed exact-occurrence and bookmaker-market evidence, which was
unavailable. The labeled vendor baseline remains visible.
[SGO Pinnacle coverage](https://sportsgameodds.com/bookmakers/pinnacle-odds-api)

Kalshi's official PDF again returned HTTP 429 from this Mac. The trusted
renderer route remains unconfigured. Native Kalshi price collection
continues independently. Novig and ProphetX dependencies remain as
listed above. [Kalshi fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)

The retained source-local P2P census also found 2,066 Prophet Exchange
rows across 190 event IDs, 612 Matchbook rows across 75 and 208 Betfair
Exchange rows across 104. These counts measure retained SGO observations.
They establish neither a native contract binding nor current executable
liquidity. Matchbook and Betfair Exchange remain outside the ordinary
offer venue registry.

### Best sportsbook payout and de-vig, November 11, 10:40 p.m. Eastern

The owner selected the highest payout for the same outcome among FanDuel,
DraftKings, BetMGM and Caesars via SGO. The desk compares current two-sided
pairs and applies proportional de-vig to the selected book's own prices.
Sportsbook EV before fees is a separate estimate for the same SGO event,
side and exact line. The drawer retains the selected book, both original
prices and clocks. Replaced frames and expired prices withdraw the estimate.
The separately labeled SGO fair odds remain context. Additional P2P venues
are backlog work. Rookie excludes both Circa and Pinnacle.
[SGO Circa coverage](https://sportsgameodds.com/bookmakers/circa-odds-api)
· [SGO Pinnacle coverage](https://sportsgameodds.com/bookmakers/pinnacle-odds-api)

The controlled +140 case selected FanDuel +120/−150, giving 25/58 no-vig
probability and 3.45% before-fee EV. A read-only replay of 20 real retained
event frames produced 10 estimates at their receipt times. The controlled
SQL case passed through ordinary capture, projection and desk publication,
then withdrew the estimate at expiry. The first full SQL run reused an
earlier fixture's event ID and frame. A separate fixture ID corrected the
test isolation. The final run passed 10 disposable PostgreSQL checks, and
80 focused tests and both drawer fixtures passed.

Both installed processes reloaded. Desktop and 390px mobile loaded the
new desk basis without overflow or browser errors. The first two SGO
pages admitted four event frames. One NCAAB frame contained four fresh
DraftKings prices, while its available Novig and Kalshi aggregate prices
missed the live age limit. The running desk showed zero current sportsbook
estimates in this window. Cross-source native matching and fee-qualified
EV remain separate work for offers with the required evidence.

Polymarket US's standard sports fee review was verified and renewed until
November 12 at 10:07 p.m. Eastern. Novig's eligible pregame review was
verified through November 12 at 5:25 p.m. Eastern. Kalshi's review expired.
The 10:28 p.m. fee census had 12 covered of 29 current offers, with the
other 17 carrying the expired or ineffective review reason.

### Fee verification deadline and live page coverage, November 11, 10:43–10:44 p.m. Eastern

The Kalshi deadline is Predict's review window. The official PDF still
describes the schedule effective July 7, 2026. The installed review
expired November 10 at 11:24 p.m. Eastern, and the runtime PDF fetch
again returned HTTP 429. The fee model is present. Polymarket US's
standard sports review and Novig's eligible pregame review were verified.
[Kalshi schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)

| Desk read | Current offers | Numeric fees | Sportsbook EV | Qualified EV | Current before-fee arb pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10:43:47 p.m., generation 51419 | 44 of 13,689 | 20 of 44 (45.45%) | 0 | 0 | 0 |
| 10:44:28 p.m., generation 51427 | 2 of 13,802 | 2 of 2 (100%) | 0 | 0 | 0 |

At 10:43:47, the 20 current Polymarket US offers had numeric fees and all
24 current Kalshi offers lacked an effective review. The 10:44:28 read
published 13,023 of 13,055 in-scope working price keys (99.75%), including
stale prices. Current financial coverage was much lower. With zero
eligible current before-fee arb pairs, a two-leg fee percentage is
undefined. These short reads do not measure 99% of the available provider
market universe or sustained performance.

### Cleanup harness and coverage planning, November 11, 11:02 p.m. Eastern

The Desktop harness was applied to the working diff and affected callers on
main. The pass registered 11 SGO offline modules, three PostgreSQL modules
and the SGO client fixture. It separated publication writes from read-time
authority, made the SGO sample and private key setup explicit, and verified
the regular, owner-only, untracked credential boundary. The provider-switch
SQL case now freezes both publication and capture clocks. The shared SQL
fixture uses authored config in place of the installed owner's local file.
Those fixture fixes address the initial failed SQL runs.

The EV desk shows current offers ahead of retained offers within the unranked
population and shortens expired cards. Arbitrage distinguishes no current
opposing pair from return filters excluding an evaluated pair. Both pages
were rendered on desktop and 390px mobile after the restart, with no overflow
or JavaScript errors. Keyboard filter open and close passed. The controlled
fee browser tests still cover pinned and changed-price details.

Local checks passed for 177 affected Python cases and six subtests, 43
disposable PostgreSQL 16 cases and four subtests, and a separate 19-case
ranking and browser pass. Both client fixtures, the fresh package/install
smoke, suite and generated-asset checks, redacted source scan, actionlint,
Ruff and documentation links passed. Hosted CI and a separate user's real
credentialed setup were outside this verification.

At 11:01:50 p.m., generation 51627 showed 24 current offers out of 15,242,
20 numeric fees, zero sportsbook and qualified EV, and zero eligible current
arb pairs. Four fees lacked an effective Kalshi review. This read supplies a
current desk sample. It does not establish the independently offered universe
or sustained data coverage. The updated [execution queue](../NEXT_STEPS.md)
owns the remaining measurement, freshness, exact comparison, fee, usability
and installed-verification work.
