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

Acquisition route and represented venue are separate fields. The configured scope
is NFL, NCAAF, NBA, NCAAB, MLB and NHL full-game winners, spreads and totals.
For the current owner-selected test, `direct_kalshi_enabled=false` and
`direct_polymarket_us_enabled=false` route both venues through SportsGameOdds.
Both direct adapters remain available to re-enable. SGO's `polymarket` bookmaker
is temporarily treated as Polymarket US under that explicit test assumption;
`source.provider=sportsgameodds` and the original bookmaker ID remain recorded.
This mapping is not evidence that SGO's product identity has been independently
established. Changing routes does not rename an observation's source history.

Existing Stop, source pauses, account limits, reservations and holds remain owned
by acquisition. No dashboard request starts a provider request or calculation.

## Storage and ownership

`app/collection/current_database.py` admits observations through the existing
ordered current event/contract/offer owners. SQL triggers coalesce material changes
into `current_pregame_work`. The same ingestion call invokes
`app/storage/current_pregame.py:process` after source admission commits. The data
runtime's `PregameOwner` recovers unfinished accepted work without replaying a
provider call. Work is per affected occurrence; references and fee schedules are
loaded once per processing batch. A game failure retains its diagnostic and
accepted observations while other games proceed.

The existing current-row advisory transaction lock orders observation writes and
complete calculation replacement. Delayed work cannot publish over a newer
admission. Complete rows replace atomically per game. Reference pairs are indexed once per
occurrence. Posted sizing searches only the exact fee-rounding envelope, and
changed rows are written in one SQL pipeline; unchanged excluded rows do not
repeat no-op writes. The public SQL projection
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
calculation prerequisite chain. Their archive/practice and Arbitrage consumers
retain their own evidence models. Research children wait during source admission
and yield at safe checkpoints when an accepted page needs processing. They never
pause while holding SQL transaction locks.
Housekeeping commits reference, frame, history and native-evidence cleanup
independently. It yields between cleanups and rewrites when source admission is
active, releasing the shared writer lock for the waiting update. Physical storage
limits and the normal maintenance retry remain enforced.

## HTTP reads

`GET /api/pregame` returns complete current rows. Supported query fields are
`league`, `family` (`moneyline`, `spread`, `total`), `venue`, `search`, `game_key`,
`bet_id`, `id`, `lines=all`, `browse=1`, `limit` (1–100), and `offset`.

The default list selects the highest unrounded Net EV venue per exact bet, keeps
positive opportunities, then orders by Opportunity Score, Net EV and stable bet
identity before pagination. Browse includes nonpositive complete comparisons.
`bet_id` reads all quoted complete venue comparisons in Net EV order; `id` reads
one exact current calculation, including an alternate excluded from the default.

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
Unchanged revisions avoid reading the list. Kickoff timers also refresh the list
without waiting for another provider response. Failed refreshes preserve rendered
rows. Inspection keeps a compact selected-row copy, with source clocks in details.

Ordinary pregame requests to `/api/comparison-current` forward to this read path.
Retired amount/mode parameters return HTTP 410 explicitly. Live research,
Arbitrage and saved replay retain their separate contracts.

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
