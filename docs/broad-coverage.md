# Retained coverage

Ordinary Odds links to `/current/coverage`. Its `/api/coverage` reader consumes a
compact latest PostgreSQL publication produced by the independent data runtime.
Page loading, local filters, sorting, cell inspection and links back to Odds never
start collection. The prior saved-session `/coverage` page remains a separate
historical reader.

## Reading coverage correctly

Coverage separates discovered offerings, received raw values, synchronized books,
matching and financial publication. A retained-row ratio is not an independently
measured provider-wide coverage percentage. The software does not currently
establish a universal 99% acquisition, display or financial-completeness result.

An offered unit is provider, venue, native event, native market, outcome/side,
native line and period. Repeated receipts are deduplicated; distinct sides and
lines are not collapsed. A complete denominator requires all relevant pages or
an authoritative inventory boundary, including failures and continuation state.
Unknown and truncated inventories remain unknown. Zero offerings requires a
complete successful query, not an empty result after a failed request.

Source change time, receipt, admission, publication and display measure different
things. An unchanged native book can remain synchronized if its initial image,
subscription and ordered feed continuity remain valid. Connectivity alone is
insufficient; loss of continuity, missing initial images and backlog remain
visible. Synchronization does not remove financial identity, settlement, depth
or model requirements.

See [acquisition](acquisition.md) for source ownership and backpressure, and
[raw prices](raw-prices.md) for access to retained observations independently of
matching and financial availability.

## Scope and capability

The matrix comes from shared configuration, source selectors and representation
registries, plus encountered retained catalog types. NFL, NCAAF, NBA, NCAAB, MLB
and NHL share the same pipeline. Kalshi and Polymarket US are native acquisition
sources. Novig and ProphetX are venues supplied by `the_odds_api`; Pinnacle remains
reference data supplied by that same upstream provider. The aggregate source has
one shared budget and existing holds, independent of the native scope.

Configuration, acquisition enabled state, implemented discovery/normalization,
comparison capability and observed support describe different facts. A supported
class still needs the individual source's participant, sporting occurrence,
period, predicate, signed line, equality and scoring facts. Unsupported family or
period cells stay visible. Registry support never proves a provider lists a market.

## Measurements and denominators

A retained observation is one distinct source-native event, market, outcome and
side with a retained price. Matching original source and receipt clocks bind it
to the corresponding ordinary publication. An outcome is a canonical predicate
with occurrence, subject, period, line, equality and scoring meaning. An underlying
pair is an undirected pair of distinct observations from different comparison
venues. Its two signed directions are a different unit. Pinnacle contributes
reference observations separately and cannot become a comparison peer.

Ratios name the numerator, denominator and captured retained scope. Supported-peer
observations, current-peer observations and current observations use the same
captured retained cohort. A zero denominator produces N/A. Unknown measurements
remain null. Original source clocks and separately validated complete-book confirmations
determine age; a metric capture, heartbeat, receipt or metadata update cannot renew
a quote. Current comparisons require both original inputs to be current under
their own rules.

Exact discovery diagnostics describe their own query time, request identity and
complete, partial or unmeasured listing scope. Unique games, markets and native
outcomes are measured before admission where possible. Reported rows and measured
unique identities are distinct fields. Failed queries have unknown offered counts.
An exact empty query does not establish provider-wide absence. Discovery and
retained-price windows are never presented as a single conversion funnel.

Global totals remain visible beside filtered totals. Native observations can be
summed across cells; canonical outcomes, occurrences and underlying pairs use
compact shared membership groups to avoid counting the same unit twice.

## Gap explanations

Structured causes distinguish configuration, source omissions, implementation,
identity/meaning, operational limits, freshness, publication and display filters.
Counts can overlap. Each affected observation also receives a deterministic primary
cause so primary counts reconcile. Bounded representative observations retain the
original price, source identifiers, source/receipt clocks, missing fields and
captured selection identity; technical codes remain available inside disclosures.

No retained comparison is promoted by optional model returns, fees or estimates.
Missing identity or source meaning can prevent a comparison while leaving its
valid original source-local price inspectable. Valid groups continue publishing
beside an invalid group. Details preserves its original captured inputs and the
existing changed-input and authority checks.

## Current implementation bounds and operation

Coverage stores only the latest compact summary with bounded example records and
canonical membership counts. PostgreSQL projects the required metric fields
before decoding; full wording, depth and repeated peer input bodies are excluded.
The projected capture is capped at 8 MiB and its work reservation at 128 MiB.
Estimates and Scanner share one fair optional work slot with current
resident-memory admission. Small-runtime Coverage uses this slot; bulk Coverage
uses one bounded disposable process as described below. A separate source-publication runway remains available
while optional work runs. Deferred work retries at its ordinary cadence; live
synchronous workers retain their reservation after cancellation of an await.
The bounded admission state is available in Admin's retained runtime status.
Ordinary reads use the existing bounded ordinary lane and read a committed summary;
they do not scan or normalize the full store. Existing selected-input lanes,
deadlines, cancellation ownership, captured-slate frame/page/byte limits, source
limits, storage limits and process memory guards continue to apply.

Authored transport and disposable PostgreSQL results establish local engineering
capability. Installed captures describe only the retained owner cohort at their
capture times. Neither establishes a provider universe, hosted CI, formal load
qualification or current-source financial applicability.

## Shared current-input and publication breakdown

The compact cohort now also measures resolved-identity observations, observations
with supported comparison meaning, retained inputs with supported/current peers,
current eligible undirected pairs, supported pairs with at least one noncurrent
input, eligible signed directions, selected current directions awaiting
publication, published current pairs and reporting disagreements. These are
parallel measures over the same repeatable-read retained cohort. They are not a
funnel across discovery windows. Reference data never enters peer denominators.
Input eligibility is resolved by the shared occurrence and exact-outcome owners
before publication; pending publications cannot turn compatible inputs into an
assertion of absent source offerings. Pair membership groups deduplicate both
source filters and global counts. Published current pairs deduplicate the two
selected signed directions. Selected directions are distinct from all possible
eligible directions when multiple peers exist.

Currentness uses the original source book clock, or an explicit validated,
content-bound complete-book confirmation when that is later. Kalshi confirmations
retain the requested complete snapshot's `sending_ts_ms`, subscription/sequence,
generation, request and payload/content seals. US confirmations retain the exact
complete market-data `transactTime`; last-trade statistics and metadata timestamps
are separate. Receipt alone, heartbeat, publication, price equality and metadata
cannot date a book. Original source/receipt clocks remain visible and unchanged.
Missing original clocks may coexist with a known confirmation age. Invalid,
future, replayed, regressing or mismatched proof is refused. The existing
30-second engineering native-book age limit is unchanged and includes its exact
maximum-age instant. Pregame and effective-mapping boundaries still apply.
Continuity loss withdraws old observation authority until that instrument is
received again. Stop, withdrawal, reset and runtime replacement still revoke
current display authority; saved Original Details remains frozen.

Capture age, publication age and capture-to-publication processing time are
separate clocks. Coverage compares material runtime and source authority;
receipt/status revision increments alone do not make its summary stale. A
runtime replacement, control/configuration change, source-state change, epoch
change, unhealthy owner or delayed capture remains an explicit warning. Numbers
always describe the dated captured cohort, including an authentic measured zero.

Primary source descriptions: [Kalshi complete snapshots and deltas](https://docs.kalshi.com/websockets/orderbook-updates)
and [US full market data versus trade messages](https://docs.polymarket.us/api-reference/websocket/markets).
These support the existing book-evidence policy; they do not qualify executions,
fees, sizes or settlement.

If Coverage reports a capture-capacity or memory-capacity failure, its summary is
unavailable rather than a measured zero. Check Admin and the safe operation log;
diagnose the current guard and redesign its work granularity under the next-version
capacity policy rather than silently discard inputs. Source prices and other background publications
can remain useful while the independent Coverage worker is unavailable.

### Projected capture

The capture omits prior display-age calculations and selection prose, retains only
the event start needed for aging and occurrence facts needed for counts, and keeps
complete confirmation seals and original input frames. SQL groups projected
prices once per game. The worker streams complete games in the same repeatable-read
snapshot; global SQL JSON interning is no longer the runtime capture path.
Same-board references use the ordinary exact-reference validator before aging.

Schedule bindings are projected when event and contract starts differ. Full
contract dependency hashes and event revisions still govern revocation. A game
refused by source publication cannot count an older saved board as displayed;
retained observations remain in the denominator. Preflight includes offers,
publications, events, books, runtime/control, source status and prior queries.
The occurrence resolver projects each detached result to metrics facts immediately,
avoiding retention of a second full audit graph without changing membership.

## Outcome-first presentation

Coverage leads with the selected captured scope, original capture/publication
ages and availability. Ratios and exact clocks remain in a disclosure. Local
elapsed-time display never renews a capture; a failed read warning persists
through filtering or pausing. Source/capability, accounting hold, explicit pause,
missing matching facts, pending publication and unmeasured counts remain distinct.
Reference observations never substitute for an unknown purchase-peer denominator.

The read response additively carries `publication_worker_state` and
`publication_error` from the current runtime owner. These describe the worker,
independently of `publication_state` and the retained capture. In particular,
`background_coverage_unavailable` can coexist with an inspectable stale capture
or an unmeasured first publication. Displaying that failure does not repair it.

### Complete streamed capture

Every complete game is consumed before publishing denominators. Cursor and
reservation lifetimes belong to the transaction/worker and cancellation. The
largest streamed record is bounded at 8 MiB. The full encoded input sum is charged
at six times its size plus 24 MiB, capped at 1 GiB. This replaces the former
128 MiB work ceiling, which could not process the complete acquired universe.
Bulk Coverage runs in one owned disposable process with a 1 GiB RSS guard,
180-second deadline and 64 KiB reply bound. Stop, parent loss and critical
acquisition pressure cancel it. The source process retains its 3 GiB guard
and 768 MiB source runway;
no observation is dropped to fit. Source clocks and matching authority remain
owned by the existing validators. See [calculation basis](benchmark-ev.md) for
financial applicability and remaining limitations.

## Offered-scope instrumentation

Exact aggregate responses now report source-native deduplicated game, market and
price-unit counts separately for each family and venue, including Pinnacle as
reference. Query hashes, request/receipt clocks, traversal completion, listing-only
markets, received/admitted/rejected counts and omission reasons are exposed in each
cell's discovery inventory. Complete response replacements reconcile additions and
withdrawals; the first boundary after restart explicitly lacks a previous census.
Admission counts describe the received batch, not a promise that every observation
is current or display-qualified. Original source clocks remain separate.

Native cells report listing traversal start/completion, page/continuation evidence,
unique listing identities, metadata/subscription omissions and latest received
book units. Reconnects replace the same event/market/outcome/ask-or-bid units.
Empty book images withdraw their previous units. Partial listings do not prove
withdrawal or zero offerings; unobserved price denominators remain unknown, and
known received-book counts are labeled as a runtime subset. Native metadata and
subscription gaps remain acquisition limitations; raw display is described in
[raw prices](raw-prices.md).

The bulk aggregate route requests featured `h2h,spreads,totals`; its complete
response is not the complete alternate-line or provider-website universe.
[Provider market documentation](https://the-odds-api.com/sports-odds-data/betting-markets.html)
places alternate spreads/totals on per-event odds routes. Featured and alternate routes have separate scopes. Alternate dispatch requires
a complete budgeted manifest and valid local authority; configured credit limits
must not be inferred from the number of featured queries. Coverage fields expose
measurement boundaries, not a completeness guarantee. See [acquisition](acquisition.md).


## Acquisition and publication

See [calculation basis](benchmark-ev.md) for exact conditional benchmark
arithmetic and its limits. Raw display, valid matching and supported financial
models are separate stages; none establishes a complete offered denominator.
