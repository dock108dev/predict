# Live pricing and odds history implementation tracker

## Current priority

The owner withdrew the five-year storage target and limited long-term history
to pregame. The historical sizing below records what was measured before that
scope change. Archive capture requires a configured off-host destination.
Split collection, durable current facts, background
publication and web reads along the same boundary used by
[SDA](https://github.com/dock108dev/sda/blob/main/docs/architecture.md).
SDA schedules game and stats refreshes in its scraper and serves normalized
rows from PostgreSQL through a separate API. Predict's streaming feeds have a
different update frequency. The web process still needs only published data.

Start with the three storage groups that accounted for 78% of the measured
1.82 GB database. Native discovery and restart bodies plus order-book images
accounted for 803 MB. SGO quote revisions and superseded quote witnesses
accounted for 392 MB. Calculation input and result packs accounted for
224 MB. The current event, contract, offer, book and ladder tables together
accounted for 145 MB. These are allocated table sizes including indexes and
TOAST.

Measure live tuples and reusable/dead space for each of the large owners.
Retain one durable native book and restart representation per active market
where a disconnect drill proves it can serve both reads. Keep SGO facts once
per exact current quote and reference a separate event definition. New SGO
quote heads and event frames expire at the later of 24 hours after scheduled
start and six hours after receipt. Bounded maintenance applies that window to
existing heads. The seven-day superseded SGO witness store now accepts only
pregame rows. The long-term archive excludes prices, event-specific witnesses
and confirmations at or after kickoff. Keep replaceable publication output and immutable evidence
for saved and pinned inspections. Measure reader parity and prove the
collector can complete a busy slate with web stopped before removing working
copies or reducing diagnostic retention.

## Work completed before the change in priority

Verified the existing checkout is on `main` at `42ab441` at the start of this
work. The storage headroom, orphan cleanup and web changes already in progress
stay in the working tree. Archive measurement used retained evidence and made
zero provider requests. Push, merge and hosting remain with `dock108dev`.

## Ownership and review

| Workstream | Implementation owner | Reviewer | Review checkpoint |
| --- | --- | --- | --- |
| Feed ingress and quote identity | Codex engineering lead | Quant Review and Reliability Review | Exact outcome/side keys, trustworthy clocks, reconnect and accounting invariants |
| PostgreSQL, archive and retention | Codex engineering lead | Storage Review and Reliability Review | Measured sizes, bounded staging, verification after interrupted export |
| Odds, Arb and EV | Codex engineering lead | Quant Review | Identical admitted inputs and existing eligibility, fee and size rules |
| Desk and public API | Codex engineering lead | Quant Review and Reliability Review | Published reads, retained quote labels and responsive filtering |
| Reliability and release handoff | Codex engineering lead | Reliability Review and Storage Review | Idle web, source failures, post-restart recovery and rollback |

Quant Review, Storage Review and Reliability Review are engineering review
agents. No independent human feed, quant, web or SRE reviewers were identified
in the repository. `dock108dev` owns deployment and the hosted verification
handoff.

## Existing path and storage baseline

`CurrentService` owns the native streams and guarded SportsGameOdds cycles.
`current_database` serializes normalized ingress. Events, contracts, offers,
native ladders, exact SGO quotes and co-observed frames supply the data
runtime's `OrdinaryOwner`. Its matched components publish an ordered live
comparison head and immutable members. Exact selected evidence follows
the snapshot and result reference/lease paths. The web reads the live head
through `/api/comparison-current`. It currently projects currentness and some
SportsGameOdds display against working SQL, so publication reads and
read-time authority must be checked independently during shadow validation.
The deploy configuration already separates the collector and web services.

Hosted read-only SQL at 3:54 PM ET November 13 measured 1,817,803,799 allocated
database bytes, of which 1,513,308,160 belonged to the monitored writer subset.
The per-relation measurement covers heap, attached TOAST, indexes and free-page
maps. Logical owner totals below sum partitions without double-counting
parent views. TOAST includes its own index. Total also includes the relation
forks omitted from the main heap column.

| Working table | Heap | Indexes | TOAST | Total bytes |
| --- | ---: | ---: | ---: | ---: |
| `current_native_market_body` | 229,785,600 | 10,797,056 | 95,485,952 | 336,068,608 |
| `sgo_quote_revision` | 253,304,832 | 60,809,216 | 8,192 | 314,204,160 |
| `current_acquisition_image_parts` | 142,680,064 | 17,129,472 | 147,537,920 | 307,871,744 |
| `current_native_market_recovery` | 33,136,640 | 3,080,192 | 122,814,464 | 159,031,296 |
| `comparison_snapshot` | 131,072 | 262,144 | 126,574,592 | 127,492,096 |
| `comparison_snapshot_result` | 786,432 | 262,144 | 95,305,728 | 96,878,592 |
| `current_contract_storage` | 28,860,416 | 3,825,664 | 46,612,480 | 79,822,848 |
| `current_sgo_history` | 57,229,312 | 13,418,496 | 6,774,784 | 77,463,552 |
| `current_acquisition_market` | 44,269,568 | 14,934,016 | 131,072 | 59,858,944 |
| `acquisition_receipt` | 655,360 | 524,288 | 50,937,856 | 52,150,272 |
| `current_offer_storage` | 36,765,696 | 6,012,928 | 4,898,816 | 48,201,728 |
| `sgo_event_evidence` | 1,048,576 | 114,688 | 15,179,776 | 16,343,040 |
| `current_native_catalog_recovery` | 8,192 | 16,384 | 14,417,920 | 14,442,496 |
| `comparison_publication` | 1,122,304 | 114,688 | 13,115,392 | 14,385,152 |
| `current_row_state` | 4,513,792 | 4,112,384 | 8,192 | 8,667,136 |
| `native_book_revision` | 5,357,568 | 2,383,872 | 8,192 | 7,782,400 |
| `data_runtime` | 180,224 | 16,384 | 7,127,040 | 7,348,224 |
| `native_ladder_revision` | 5,283,840 | 606,208 | 8,192 | 5,931,008 |
| `current_event` | 2,621,440 | 286,720 | 155,648 | 3,096,576 |
| `comparison_result_reference` | 253,952 | 991,232 | 8,192 | 1,286,144 |
| `delivery_clock` | 319,488 | 180,224 | 8,192 | 540,672 |
| `data_runtime_command` | 16,384 | 24,576 | 32,768 | 73,728 |
| `comparison_policy_revision` | 8,192 | 32,768 | 8,192 | 49,152 |
| `public_fee_schedule` | 8,192 | 16,384 | 24,576 | 49,152 |
| `schema_migration` | 16,384 | 16,384 | 8,192 | 40,960 |
| Public subtotal | 848,363,520 | 139,968,512 | 747,192,320 | 1,739,079,680 |
| Retained schema subtotal | 7,806,976 | 3,022,848 | 45,596,672 | 56,524,800 |

The detailed measurements, including the 175 relations, 313 indexes and every
retained table, are in
`.local/hetzner-cutover-20261113/storage-baseline-20261113.json`.
The rehearsal dump counted 182,707 native metadata bodies, with 111,925
distinct IDs referenced by either acquisition or recovery, leaving 70,782
unreferenced in that retained snapshot.

The separate 6:45–9:30 PM ET busy-slate sample scheduled 65 games across four
leagues and observed 43 working games. Of 166 samples, 162 supplied SQL
measurements. The database peaked at 2,214,149,143 bytes and the collector
reported 17 distinct runtime IDs. Minimum host free disk was 17,172,287,488
bytes. PostgreSQL's cumulative WAL generation counter moved from
25,862,359,203 to 58,908,913,139 bytes, a delta of 33,046,553,936 bytes.
The sample did not measure on-disk WAL occupancy. Median-of-five-minute
SGO receipt-to-publication medians were 147.9 s for NCAAB, 170.2 s for NBA,
161.9 s for NHL and 222.5 s for NCAAF. Those clocks describe the old path.
The 11 sampled live public views showed zero current outcomes during the
restarts, so they establish a failure window without yielding a parity test.
Sources are `evening-through-2130.jsonl` and
`evening-through-2130-summary.json` alongside the SQL baseline.

## Retained history sizing and replay

The PostgreSQL 16 custom dump ends at 12:14 PM ET November 13, before the
evening window above. `pg_restore --data-only` extracted existing COPY rows
without a running database or provider calls. SGO comparison included all
bookmaker originals and used the exact event, bookmaker, odd identity
and line. Native comparison used top ask and bid by outcome and exact
market from stored immutable ladders. The first surviving observation and
every subsequent change in price, size or availability counted toward the
encoded rows. Sequence, source time, receipt time, revision and evidence
identities accompanied those rows. UTC receipt day selects the group.

| Feed | UTC date | First surviving sides | Subsequent material changes | Unchanged repeats | Quote Parquet bytes | Quote gzip JSON bytes | Definition Parquet bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Kalshi | Nov 13 | 1,604 | 0 observed | 0 observed | 137,877 | 167,318 | 317,413 |
| Polymarket US | Nov 13 | 1,737 | 0 observed | 0 observed | 173,199 | 207,331 | 440,497 |
| SportsGameOdds | Nov 11 | 21,201 | 0 observed | 0 observed | 1,880,463 | 2,516,476 | 261,425 |
| SportsGameOdds | Nov 12 | 52,595 | 0 observed | 0 observed | 4,427,844 | 6,440,301 | 364,838 |
| SportsGameOdds | Nov 13 | 78,393 | 7,269 | 20,360 | 7,491,230 | 10,250,789 | 1,036,832 |

November 13 totals 9,597,048 bytes for Parquet quotes and latest surviving
definitions, versus 13,141,906 bytes for gzip JSON. A separate compact
confirmation encoding measured 42,467 gzip bytes across 659 surviving native
confirmation records. Those sizes omit the missing receipts and historical
definition versions. Native sides came from 1,116 current books and just
30 retained older books whose exact sides did not overlap another surviving
revision. SGO history had already evicted 174,628 of 201,916 written witnesses.
The dump and evening telemetry cannot establish material updates per day
for a full busy slate, the five-year rate, or a production storage limit.
Measure a continuous 24-hour busy slate and a full week of exports before
committing to the 20–30 GB target.

PyArrow 21 with Parquet/Zstandard used 4,096-row groups ordered by event and
quote identity. The replay filters were `event = :event_id` and
`received_at <= :cutoff`. It kept the last surviving row per exact side
for the as-of view. The gzip JSON reader decompressed each entire file
before applying the same filters. Both returned the same exact change IDs
in every sample.

| Feed | Event ID | Cutoff UTC | Rows | Parquet | Gzip JSON |
| --- | --- | --- | ---: | ---: | ---: |
| Kalshi | `KXNBASPREAD-26NOV13NYKIND` | 2026-11-13 17:14:01.342651 | 12 | 22.2 ms | 6.2 ms |
| Polymarket US | `209094` | 2026-11-13 17:01:51.042934 | 18 | 1.3 ms | 6.3 ms |
| SportsGameOdds | `naU7rmIsNSaJ10dYfqfd` | 2026-11-13 04:30:41.539962 | 1,032 | 10.8 ms | 317.8 ms |

These timings exclude network fetch, dimension joins, cross-day replay and
application math. Parquet quote files
were 16–31% smaller. In the Nov 13 SGO sample, limiting scope to winners
would reduce 8.53 MB of Parquet quotes and definitions to 2.08 MB. Limiting
bookmakers to Kalshi, Polymarket, Novig, ProphetX, Pinnacle and Circa would
reduce it to 2.13 MB. Both would remove observed coverage and remain
sizing scenarios. The full configured acquisition and archive scope stays
the comparison basis.

Reproduce the measurement with Python 3.13, PyArrow 21 and PostgreSQL 16
client tooling. The script reads the dump offline, keeps extracted data in a
private temporary directory and emits only aggregate findings and replay
checksums to the requested report file. A second run against the extracted
COPY directory matched every byte count and change-ID checksum.

```sh
/opt/homebrew/bin/python3.13 scripts/measure_odds_history.py \
  .local/hetzner-cutover-20261113/rehearsal.dump \
  --pg-restore /opt/homebrew/opt/postgresql@16/bin/pg_restore \
  --output /tmp/predict-odds-history-measurement.json
```

### V1 exporter volume and storage target

A second offline simulation used the production v1 SGO quote, definition,
event and quote-clock builders on the retained current SGO references and
rotated reference history. It ordered receipts by original clock, tracked
the prior recorded material per identity, reconstructed up to 12,000 rows
and 6 MiB of staged content per shard, and compressed each file with gzip
level 6. This simulation excludes native, separate offer witnesses,
page receipts and source status. It also simulates a day-at-once flush, so
the deployed 15-minute flush can yield different sizes.

| SGO UTC receipt day | Original v1 compressed bytes | Optimized v1 compressed bytes | Optimized logical staging bytes |
| --- | ---: | ---: | ---: |
| Nov 11 | 12,502,779 | 4,413,473 | 21,130,874 |
| Nov 12 | 30,054,317 | 10,816,034 | 56,081,151 |
| Nov 13 | 58,118,987 | 19,141,474 | 102,523,022 |

Grouping records by event and exact scope puts repeating hashes, witnesses
and times near one another. Grouping alone reduced the Nov 13 witness
to 23,942,041 bytes in the event, scope, kind and receipt trial. Removing
redundant same-receipt clocks alone while retaining hash ordering reduced
it to 40,317,688 bytes. The optimized implementation combines the
event/scope/receipt/id sort with clock witnesses only when the prior
admitted SGO top material is unchanged. Its Nov 13 witness retained 95,274
top, 90,641 definition, 695 event and 9,851 quote-clock records. The 64 MiB
logical stage allowance therefore depends on regular drain under this load.

| Optimized v1 SGO sample coverage, Nov 13 UTC | Compressed bytes |
| --- | ---: |
| All retained market families, lines and books | 19,141,474 |
| Main lines only | 14,343,636 |
| Moneyline only | 5,033,394 |
| Kalshi, Polymarket, Novig, ProphetX, Pinnacle and Circa | 3,419,410 |

The optimized SGO witness alone exceeds the approximate 16.4 MB/day upper
budget of 30 GB over five years. Repeating that value every day for five
years would use 34.95 GB for SGO alone. The partial retained day included
first-observed quotes and lost intermediate changes, so it cannot establish
the sustained archive rate. The normalized Parquet measurement above uses
a smaller analytical schema. It favors testing production sections encoded
as typed columns and clustered dictionaries, with unchanged scope and exact
replay parity, before choosing any archive coverage reduction.

## Historical coverage and gaps

- SGO source quote evidence spans November 11–13 UTC. There are 983 complete
  nonempty event frames of 1,644 surviving heads and old frames. Their exact
  completeness was tested by joining every member's quote ID and revision
  to surviving quote evidence. For example, event `kNKsNKgZnURoL7mYhH6a`
  at `2026-11-12T07:05:02.547926Z` reconciles all 995 members across
  157 market/period/line triples. Missing members make the remaining frames
  partial. Settlement stays unverified where the source witness says so.
- The dump holds 29,150 Kalshi and 34,970 Polymarket US persisted images
  marked admitted, one per latest scoped event/market key. Their receipt
  ranges are October 27–November 13 UTC. They can supply point observations
  where exact clocks, identity and catalog evidence survive. Pending raw
  images alone supply no admitted history. No continuous native interval
  can be inferred from those heads.
- The exact snapshot store separately preserves 486 automatic input packets
  for part of November 13 UTC and 15 manually captured input packets dated
  November 2–4 UTC. Replays from those packets can anchor selected historical
  calculations, including their original quote, rule and fee evidence.
  Coverage between those packets is unknown.

## Retention and cutover decisions

- Capture native synchronization and positive confirmations plus SGO poll
  confirmation and source-state boundaries as independently timed evidence.
  Distinguish discovery absence from explicit close, provider unavailability
  and transport failure. Quant review must validate how replay interprets
  the intervals and their expiry.
- Keep full calculation depth, restart metadata, raw inspection data and
  saved evidence while validating shadow reads. Native raw diagnostics
  currently have an existing two-day inactive/withdrawn window and latest
  images for the active census. SGO's working frames and quotes currently
  expire at the later of 14 days after start and one day after receipt.
  SGO diagnostic history also has a seven-day and 32 MiB logical cap.
  These are baseline retention settings. Shorter live windows need recovery,
  inspection and storage measurements before removing the old copies.
- Track staged bytes, oldest unverified receipt, confirmed off-host bytes,
  capacity gaps and clock ranges independently from feed health. Protect
  the live writer budget during a long archive outage and surface the
  unexported interval for recovery from surviving evidence.
- Sandbox permissions blocked PostgreSQL 16 `initdb` at `shmget` and
  access to the Docker socket. Dump extraction and Parquet replay succeeded.
  Database-backed and hosted restart claims require a runnable disposable
  PostgreSQL cluster and the owner's deployment window.

## Implemented locally

| Change | Verification and remaining work |
| --- | --- |
| Source admission stages material native top-of-book changes and SGO reference changes in the existing ingress transaction. Definitions, matching facts, native confirmations, SGO page receipts and selected execution references have their own record kinds. | Local replay verifies exact source and receipt evidence and quote-time definitions. A versioned gap is an observation, with separate timestamps for recorded staging failures. Confirm the full source-to-export reconciliation under representative load. |
| The archive service verifies a durable shard before releasing staging. Claim membership remains stable across restarts. Receipt-day paths accept late shards. A 64 MiB logical staging limit and SQL runway limit protect live admission. | Local file retry, mount identity, corrupt payload and exact replay tested. PostgreSQL-backed crash and late-arrival drills are registered in the normal SQL qualification lane. Brokered mount setup and backlog measurements remain hosted. |
| Arb ranking reads the existing published payoff at $100. Custom sizing uses one exact pinned pair. Per-component capture and finance savepoints let healthy siblings publish and retain original price credit and inspection evidence. | Unit parity checks and failed-component projection passed. SQL failure injection, public browser behavior and the busy-slate web-off drill remain open. |
| Planned storage maintenance lets an owned SGO page finish accounting and admit before restart, then blocks the next request. | Provider-free regression covers the paid-page boundary and confirms controls and the discovery cursor survive. |
| Operational recovery | [Host setup, verified export, acceptance drill and rollback](odds-archive-operations.md). Migration 092 adds the archive tables. The capture flag starts off. Existing recovery bodies, full working depth and saved evidence stay in place while measuring. |

Source evidence currently keeps authentic native snapshot confirmations, an
early depth-clock witness per native 15-second bucket, and an early unchanged
SGO quote-clock witness per five-minute bucket. Page receipts and source,
runtime and discovery transitions provide separate boundary evidence. Quant
Review approved the conservative interpretation for shadow use. This cannot
prove every intermediate live freshness decision. Scope and freshness need
further measurement before using the archive for exact as-of EV or Arb replay.
Historical fee witnesses and required depths remain available through the
existing exact saved inspection path.

The local sandbox blocked PostgreSQL 16 initialization via `shmget`, Docker
daemon access, IPv4 loopback binds, and Chromium startup. These are execution
blockers for the SQL/browser and hosted service drills. The code and package
remain on the local `main` checkout. Hosted publication lag, the stable live
database footprint after the slate closes, the busy-slate idle-web test,
and the 20–30 GB target require measurement after the off-host mount is
configured and the owner deploys. No provider request was made by this work.
