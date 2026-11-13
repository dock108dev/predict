# Storage ownership

The ordinary data process owns collection and comparison publication. The app
reads committed revisions. The Database tab defaults to `public`, which holds
the working schema. Select `retained` for historical research and retired
board records. Historical tools opt in with `open_retained()`. Migration 082
moved those relations and their foreign keys in place.

| Facts | Authoritative storage and owner | Readers |
| --- | --- | --- |
| Source receipts | `acquisition_receipt` holds native queries, pages, rejected frames, and The Odds API featured, alternate, and census responses. `current_acquisition_image_parts` holds native stream images with their own synchronization and disposition. | Restart, acquisition diagnostics, alternate scheduling, and Raw Odds. |
| Native metadata | `current_native_market_body` holds each exact market body once. `current_acquisition_market`, `current_native_market_recovery`, and `current_native_catalog_recovery` carry census and recovery membership, clocks, and scope. | Native restart, census, and raw inspection. |
| SportsGameOdds evidence | `sgo_quote_revision` owns exact source quotes. `sgo_event_evidence` holds frame membership, separately timed venue catalog facts, and history counters. `current_sgo_history` retains bounded superseded observations. | Ordinary calculation, Quote Quality, and sportsbook display. |
| Normalized market data | `current_event`, `current_contract_storage`, and `current_offer_storage` own admitted identities and offer authority. Native offers point to `native_book_revision`, whose exact ladders live in `native_ladder_revision`. Independent depth belongs to its contract. | The ordinary comparison worker, Scanner readiness, and source diagnostics. |
| Calculation settings, inputs, and results | `comparison_policy_revision` has one active settings revision. `comparison_snapshot` and `comparison_snapshot_result` preserve original inputs and exact result bytes. New results also bind the settings revision with a foreign key. Ordinary results hold EV values and the default $100 modeled arbitrage payoff, with its fee evidence identity. | Live and manual comparisons, replay, and pinned Details. |
| Display and inspection | `comparison_publication` holds live and manual heads, current components, Coverage, and Scanner. `comparison_result_reference` holds ordered members, review pins, and leases. The compact read projection is on the exact result row. | Opportunities, Browse Odds, game pages, Coverage, Raw Odds, and Scanner. |
| Operations and policy evidence | `data_runtime` and `data_runtime_command` own Stop, pauses, heartbeat, and control acknowledgments. `current_row_state` holds reset epoch, committed source status, and refresh ordering. `delivery_clock` holds delivery telemetry. `public_fee_schedule` holds reviewed fee evidence and `schema_migration` records the upgrade history. | Admin, runtime authority, delivery diagnostics, and calculation. |

## Remaining working relations

The working schema has 25 top-level tables, including the migration ledger.
`retained` has 45 top-level historical tables. The Database tab can include
SQL read views, partitions, and sequences on demand. The views expose the
existing query shapes without additional stored copies.

Provider accounting lives separately in the existing guarded ledger and quota
files. Historical comparison review pins and leases protect their exact inputs.
The working database uses compact calculation packets and versioned display
fragments. Filters sort eligible values from the publication. A custom arbitrage
stake uses the same payoff function at the requested amount. Native and
aggregate landing keep distinct receipt formats. Scanner retains its own
observed-depth sizing and ticket policy.

An admitted native offer links to the book revision whose source and receipt
clocks, confirmation, units, and exact same-outcome ask match the observation.
For a complemented price the link also identifies the original bid ladder.
Migration 091 binds any uniquely matching retained revision to its exact offer.
Later updates to the current book head do not change the price or evidence of
an older offer. An observation without a unique match keeps its own price and
source clocks and supplies no book depth to readers.

The ordinary app answers the superseded board endpoints with HTTP 410 and
points to `/api/comparison-current`. `/api/boards/readiness`, `/api/coverage` and
`/api/scanner` are still served. The historical `latest_board` tables are
available in Admin under `retained`.

For an installed upgrade, quiesce the app and data processes and make a private
database restore point. Verify the previous schema, saved review hashes, and
durable Stop and pause state. Apply forward migrations in order and verify
the same records before restarting normal collection. A database restore
requires the matching application version. Keep any later provider accounting
records and the upgraded data available if investigating a rollback.

Native metadata conversion proceeds in bounded maintenance turns. Legacy inline
rows remain readable while they convert. Existing capacity limits still apply.
The number of inline rows remaining can be checked with `metadata_id IS NULL`
in `current_acquisition_market` and `current_native_market_recovery`.
