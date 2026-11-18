# Current pregame dashboard

## Data flow

```text
SportsGameOdds / Kalshi direct / Polymarket US direct
    → existing normalization and ordered current observation admission
    → durable coalesced source-event work
    → affected occurrence: current offers + exact references + fee registry
    → exact posted-price cashflows at the internal $100 comparison basis
    → atomic current_pregame_calculation rows
    → SQL read → browser tickets and comparison
```

Acquisition route and represented venue are separate fields. Supported scope
covers NFL, NCAAF, NBA, NCAAB, MLB and NHL full-game winners, spreads and totals;
the configuration selects the enabled subset. The sample configuration sets
`direct_kalshi_enabled=false` and `direct_polymarket_us_enabled=false`, routing
those venue observations through SportsGameOdds when aggregate collection is
enabled. Both direct adapters remain available.

The current SGO mapping displays its `polymarket` bookmaker as Polymarket US.
That product identity has not been independently established; the original
bookmaker ID and `source.provider=sportsgameodds` remain recorded. Changing
routes does not rename an observation's source history.

Existing Stop, source pauses, account limits, reservations and holds remain owned
by acquisition. No dashboard request starts a provider request or durable calculation job.
Arb reads evaluate their bounded allocation from stored fee-qualified prices.
Ordinary pregame collection does not start the separate OddsLink ProphetX
fallback: SGO already supplies that configured price route. The fallback remains
available only with explicit live collection, and its saved observations remain
available to historical and research consumers.

## Storage and ownership

`app/collection/current_database.py` admits observations through the existing
ordered current event/contract/offer owners. SQL triggers coalesce material changes
into `current_pregame_work`. Only the first material change to a game in a serialized source transaction
updates its durable job and browser revision; a later transaction or retryable
failure still advances it. Processing cannot interleave with that admission
because both own the same current-writer lock.
The same ingestion call invokes
`app/storage/current_pregame.py:process` after source admission commits. The data
runtime's `PregameOwner` recovers unfinished accepted work without replaying a
provider call. Recovery yields between games while source admission is active;
inline ingestion keeps ownership of its newly admitted batch. Work is per
affected occurrence; references and fee schedules are
loaded once per processing batch. A game failure retains its diagnostic and
accepted observations while other games proceed.

The existing current-row advisory transaction lock orders observation writes and
complete calculation replacement. Delayed work cannot publish over a newer
admission. Complete rows replace atomically per game. Reference pairs are indexed once per
occurrence. Posted sizing searches only the exact fee-rounding envelope, and
changed rows are written in one SQL pipeline; unchanged excluded rows do not
repeat no-op writes. Small affected-game processing and SGO admission
use transaction-local serial plans,
admission, avoiding parallel worker startup. Reference replacement checks the
global row cap only when new identities can increase membership; the writer lock
keeps that decision stable and every growing batch still checks the full cap.
The public SQL projection
includes only complete calculations, with diagnostic exclusions kept internally.
A collection interruption retains the last accepted complete row.

`current_pregame_calculation` links directly to each exact contract and stores
price, source route/native identity, original clocks, fair reference inputs,
account/schedule evidence, modeled fee cashflows, exact ratios, display values,
input identity, calculation version, and calculation time. Indexed ranking columns
serve small list reads. It is neither a full-slate snapshot nor a selected-amount
board. Generated `pregame_unit_board` and `pregame_unit_member` are removed by a
forward migration. Applied migration history and source evidence remain intact.

Research publication, Scanner and Coverage stay outside the ordinary read and
calculation prerequisite chain. Their archive/practice consumers
retain their own evidence models. Research children wait during source admission
and yield at safe checkpoints when an accepted page needs processing. They never
pause while holding SQL transaction locks.
Housekeeping commits reference, frame, history and native-evidence cleanup
independently. It yields between cleanups and rewrites when source admission is
active, releasing the shared writer lock for the waiting update. Physical storage
limits and the normal maintenance retry remain enforced.
Bounded audit rotation reads only the next oldest prefix through the existing
archive-time index. Multiple batches preserve the exact victim order and byte
cap while avoiding a whole-history window calculation in source admission.

## HTTP reads

`app/storage/current_pregame_read.py` owns the committed-row queries. Callers keep
using `current_pregame.read`; that facade supplies its existing clock and route
resolver. Cheap update-cursor reads still return before resolving routes, and
transaction ownership remains with the caller. Calculation/recovery writes stay
in `current_pregame.py`.

`GET /api/pregame` returns complete current rows. Supported query fields are
`league`, `family` (`moneyline`, `spread`, `total`), `venue`, `search`, `game_key`,
`bet_id`, `id`, `lines=all`, `browse=1`, `view=games`, `view=game`,
`limit` (1–100), `offset`, and `sort` (`growth`, `ev`, `score`, `balanced`, `edge`).
The default sort is `growth`; unknown sorts return HTTP 400.

The default list selects the highest unrounded Net EV venue per exact bet, keeps
positive opportunities, then orders by the selected unrounded ranking value,
Net EV and stable bet identity before pagination. Kelly growth evaluates expected
log wealth at the existing model-optimal fraction. The other choices are Net EV,
the original Kelly-fraction score, an experimental softer payout penalty, and
reference probability minus after-fee break-even probability. These read-time
rankings do not change stored quote, fee, reference or valuation records.
Each ranked list/comparison row adds `ranking` metadata with the method, label,
unit, numeric value and rounded display value; the original `raw.opportunity_score`
remains unchanged. Browse includes nonpositive complete comparisons.
`app/storage/pregame_ranking.py` is the method/catalog owner. The existing frontend
builder emits `pregame-ranking.js` for the dropdown, column headings and ranking
explanations. Do not edit a separate browser method list or generated metadata.
A catalog entry without an implemented SQL calculation is rejected explicitly.

Ranking values use a canonical, unrounded decimal wire representation in both
list and exact-detail reads. Equivalent numeric encodings, including zero with
different exponents, cannot produce false list/detail mismatches or comparison redraws.
`bet_id` reads all quoted complete venue comparisons in Net EV order; `id` reads
one exact current calculation, including an alternate excluded from the default.

Pregame-only collection admits explicit early `started`/`live` lifecycle notices
while discarding their post-start prices. The source-ingress transaction updates
sporting state before returning, so list and journal readers withdraw that game
even before affected-game recalculation. Repeated notices are idempotent;
rollback preserves the previous state and original price evidence.

`view=games` includes nonpositive complete rows, keeps main lines even when
`lines=all` is supplied, and groups before pagination. It returns `games`, with
`game_key`, `game`, `league`, `kickoff` and all available best-venue main-line
`rows` per game; `total` counts games. Stable ordering is kickoff then game key.
`view=game` requires `game_key` and returns every complete main/alternate exact
bet for that game in one repeatable read, including games with more than 100 bets.
It does not truncate at the ordinary list limit. Exact-bet reads retain precedence.

Exact `bet_id`/`id` reads also include `sportsbooks`: observed posted prices
matched to the selected reference's native event/outcome, league, scheduled
start, full-game family and exact signed line. These use current SGO evidence;
withdrawn, future-received or conflicting latest quotes and other exchange
venues are excluded. They do not change calculation eligibility, fair-reference
selection, fees, ranking or grouping. Each quote supplies its own source/receipt
clock. The selected calculation's reference prices remain its pinned evidence.

```json
{"schema":"predict-current-pregame-1","state":"ready","rows":[],"total":0,
 "offset":0,"limit":30,"generation":12,"provider_requests":0,
 "scheduled_calculations":0,"notice":"Odds may be delayed."}
```

A row contains `id`, `game_key`, `bet_id`, `game`, `league`, `kickoff`, `family`,
`selection`, `venue`, `posted`, `source`, `times`, `reference`, `fee`, `raw`,
`display`, `version`, and `calculated_at`. Exact arithmetic values are strings.
`raw.net_ev` is a ratio; `display.net_ev` is its rounded percentage.

`GET /api/pregame/updates?after=<cursor>` reads the small committed revision and
eligibility deadline, returning `changed` and a suggested 500 ms poll interval.
The cursor includes expiry boundaries from both complete EV rows and independent
fee-qualified prices. Recovery enqueues expired fee inputs from either table,
including prices without a complete sportsbook reference. Unchanged revisions
avoid reading the list. Kickoff timers also refresh the list
without waiting for another provider response. Failed refreshes preserve rendered
rows. Inspection keeps a compact selected-row copy, with source clocks in details.

Ordinary pregame requests to `/api/comparison-current` forward to this read path.
Retired amount/mode parameters return HTTP 410 explicitly. Live research and
saved replay retain their separate contracts. The current Arbitrage page uses the
reference-free price read below.
Captured Arbitrage game links redirect to the existing saved-game reader with
their exact result, occurrence, line and return context. Their historical game
identities are not current-row identifiers.

## Health and operations

`GET /api/health` checks database availability and the supported current-read
schema with bounded SQL. It performs no arithmetic or acquisition. The collector
probe checks owner heartbeat, deliberate Stop/disabled state, dispatch and specific
failed accepted work. An empty opportunity board is a valid operational state.
Health does not establish that a real received offer reached the browser.

Operational SQL owners expose `current_pregame_work` (including failure reasons),
latest `calculated_at`, current offer counts and original receipt clocks. The
ingress metrics keep a bounded ring of affected-game commit durations and
admission-to-commit measurements, separately from source receipt/preparation
stages and browser delivery. No
amount-specific readiness is a health dependency.

Display-only legacy accounting status reuses a verified ledger and its exact
encoded byte count while device, inode, mode, size and nanosecond file clocks
remain unchanged. The cache holds only the two configured status paths; dynamic
clock/window checks still run. Its child has background CPU priority. Every
ledger mutation independently reloads and validates disk state; this status cache
grants no acquisition authority and cannot release a hold or pause.

## Reference-free after-fee arbitrage

Migration 105 adds `current_pregame_price`, owned by the same affected-game
processor. Occurrence, schedule, route, source availability, exact line and fee
checks run before the sportsbook-reference lookup. A missing complete reference
can exclude EV while leaving a usable price/fee record for paired research.
The table stores the source record and fee inputs for repricing; the API does not
expose these internal records. Its price identity avoids no-op replacement on
receipt-only confirmation. Source, fee and event changes enqueue the existing
owner; reads suppress pending work until an atomic rebuild completes.

`GET /api/pregame/arbs` accepts `league`, `family`, `venue`, `book`, `search`,
`category` (`market_market` or `market_book`), `limit` and `offset`. It compares
opposite sides of the same occurrence, period, family and exact normalized line.
Same-venue, book-to-book and conflicting explicit overtime scopes are excluded.
Books use current available SGO quotes for the mapped event and exact line;
withdrawn/future, three-way and conflicting latest prices are excluded.
Only explicitly recognized sportsbook IDs qualify for the zero-placement-fee
assumption; unknown venues, sweepstakes products and other exchanges such as
Betfair Exchange are excluded. Zero
sportsbook placement commission is an explicit model assumption.

The exact fee engine reprices both legs on legal quantity increments inside a
$100 combined basis. A bounded cent-allocation search balances their two net
receipts; it does not claim a global optimum. Fees are not linearly scaled from
standalone odds. A pair qualifies only if both decisive completed-game state
profits are positive after fees. Paired return is the lower profit divided by
actual committed cash; residual cash is shown separately. No fair probability,
Net EV or Opportunity Score is used in the result. Push, void, tie, cancellation
and other exceptional states are excluded explicitly, so these are conditional
price-arb candidates, not verified full-settlement arbitrage.

The response supplies `rows`, `total`, source clocks, leg prices/cashflows,
committed cash, both receipts/profits, minimum profit and paired return.
`execution_qualified=false` and `instant_fill_max_usd=null` are explicit: aggregate
quotes do not establish depth or synchronized fills. No source calls, collection,
account writes or scheduled calculation jobs are initiated by this read. A small
process cache reuses results only for the same database, committed revision,
eligibility cursor and filters; cached rows also respect their explicit deadline.
Pagination slices the already-ranked result. Book-event and side-role attachments
are part of the price input identity, so they can update without a new offer.
The app refreshes on changes and deadline, retaining last-good prices on failure.

`/arbs` shares the selected board style and responsive cards. Opening a row shows
both allocations, after-fee state receipts, source/receipt clocks and the formula.
`/about#arbitrage` covers model and execution assumptions; `/about#sources` credits
SportsGameOdds and links official documentation and relevant research. The SGO
affiliate URL is a source comment placeholder until the owner supplies it; the
visible credit uses the official provider site.

## Scoped missing-line availability

A newer source observation that explicitly moves a book's main line immediately
retires that book's previous main for the same game and outcome. Prices at a
different line are different bets: the old price must not remain an available
main-line opportunity. Other books, the opposite outcome, and explicitly observed
alternates remain independent. A delayed older source observation cannot restore
the superseded main; an explicit later alternate observation can restore that line.
Original quote facts and timestamps remain available for history. Collector
startup applies the same rule to retained heads, repairing already accumulated
main lines without replaying sources or changing account records.

Successful SportsGameOdds refreshes requested with `includeAltLines=true` now
record line presence independently of price/source clocks. When a returned game
continues receiving complete scoped refreshes but a particular book/outcome/line
is omitted, it receives a 15-minute grace period starting at its first observed
omission. A later complete refresh at or beyond that boundary suppresses that
quote and any EV/arb using it. The game and other lines remain. Empty book/market
results inside the returned, explicitly requested scope count; absent games,
failed requests, main-only pages, and out-of-order replays do not prove alternate
absence. Main-line replacement above applies to main-only pages as well.

A later receipt containing the exact line clears omission even if its source
price has not changed. Provider quote facts and their original clocks remain
unchanged. Migration 106 seeds known identities without inventing historical
omissions. A frozen local snapshot therefore cannot demonstrate new disappearance
until it receives scoped absence evidence. This is an admission-driven rule,
not a universal 15-minute price-age expiry.
