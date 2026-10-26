# Retained coverage

Ordinary Odds links to `/current/coverage`. Its `/api/coverage` reader consumes a
compact latest PostgreSQL publication produced by the independent data runtime.
Page loading, local filters, sorting, cell inspection and links back to Odds never
start collection. The prior saved-session `/coverage` page remains a separate
historical reader.

## Next-version target — bulk live data and 99% coverage

Owner direction on October 26, 2026 changes the completion target. This section
specifies required behavior; the retained-cohort implementation described below
has **not** achieved it. Coverage must expose offered scope independently of the
subset already stored. Bulk acquisition and raw visibility precede semantic
qualification and maths. No per-game installation, approval or qualification
sequence is required. Small regression cases may support engineering, but cannot
qualify broad live coverage.

### Scope and denominator

The target is the full available pregame offering for NFL, NCAAF, NBA, NCAAB, MLB
and NHL, moneyline/winner, spread and total, full game, across Kalshi, Polymarket
US, Novig and ProphetX; Pinnacle is measured separately as reference-only. Include
all available in-scope lines and native sides, not just a selected main line or a
handpicked near-term cohort. Other periods, futures and extra providers remain
outside this version. No new narrower time horizon may be introduced to improve
the percentage. Started/ended/postponed/unknown states need explicit evidence and
separate current eligibility; preserve inspectable raw observations.

Define one offered unit as provider + venue + native event + native market +
outcome/side + native line + period. Deduplicate reconnects and repeated pages;
do not deduplicate distinct native sides into a synthetic outcome. Measure the
available authorized source route, not an unobservable entire provider business.
Reconcile listing identities and price-bearing responses at documented capture
boundaries, including additions, withdrawals and pagination races. Listing-only
markets with no offered price are counted separately with evidence.

A denominator is complete only when all relevant listing/response pages or an
authoritative inventory/delta boundary are accounted for. Report route, scope,
start/end, exhaustion/continuation, failures and completeness. An unmeasured,
failed or truncated inventory cannot pass as 99%; retained-row ratios cannot
stand in for offered coverage. Zero offered units is N/A with fresh complete-query
evidence. Provider absence must not be inferred from a failed request or a cap.

### Acceptance measures

| Measure | Required result and denominator |
| --- | --- |
| Raw acquisition coverage | At least 99% of independently enumerated offered price units have faithful raw values, native units/IDs and original available clocks locally inspectable. |
| Raw display coverage | At least 99% of those offered units are reachable in ordinary paginated Odds/Original views, including unmatched, stale and rejected-for-calculation values with explicit labels. Raw visibility never grants calculation authority. |
| Fresh coverage | At least 99% of offered units have valid, independently supported currentness at the sampled time under the declared source-specific policy. Recent receipt, ingestion or model time cannot make an old source quote fresh. |
| Validation accounting | 100% of received units have an explicit valid, invalid, missing-fact, stale, unsupported or pending disposition, with reason and provenance. This accounting percentage is not the raw/fresh coverage percentage. |
| Comparison processing | At least 99% of reference-enumerated eligible cross-venue comparisons are evaluated and published; count deterministic output selections separately from all evaluated candidates. Missing peers and unresolved meaning remain measured gaps. |
| Financial processing | At least 99% of valid input sets eligible for each implemented metric are computed/published. Separately show eligible/total offered and blocked counts by missing fee, payout, probability, size or reference input. An empty eligible set cannot establish financial completion. |

Raw acquisition, display and freshness targets apply both globally and to each
nonempty venue/league/family cell, with reference cells reported separately. A
large NFL cell cannot hide a missing NHL or ProphetX cell. Report numerators,
denominators and residual gaps, not only rounded percentages. Use the smallest
integer numerator meeting 0.99 times the denominator. Rejected or unsupported
received rows remain in raw coverage denominators; only evidenced source absence
or genuine out-of-scope units leave the offered cohort.

Missing contract/financial evidence cannot be removed from the overall gap
report by shrinking an eligibility denominator. The core type-driven contracts
and maths must work across the full selected scope. Missing evidence is explicit
remaining work or a named owner-accepted limitation; neither is called 99%
financial coverage. This target does not promise 99% profitable opportunities,
identical venue offerings, actual fills or execution-qualified returns.

### Freshness and verification window

Record native source/complete-book confirmation time, aggregate source update,
receipt, admission, publication and display separately. Establish a documented
policy per feed using its actual update semantics. Preserve the existing native
30-second policy until an evidenced policy change is justified; never widen it
solely to pass. Aggregate scheduled completeness and between-cycle source age
must be separate measures. A 15-minute paid cadence cannot be labeled a
continuous fresh feed merely because every scheduled request succeeded.

Verify the entire live scope through cold catch-up and then at least two
consecutive operating hours spanning eight scheduled aggregate cycles. Sample
full-scope metrics at least once per minute, plus each completed aggregate cycle;
report cold catch-up separately and require each steady-state sample to meet the
applicable 99% target. This is a next-version engineering acceptance design, not
a previously measured capability. Include an ordinary listing change if observed;
exercise missing transitions in regression tests rather than force paid events.
Recheck supported behavior after app-only restart without interrupting data work.

If a source's offering, timestamps, cadence or account budget cannot satisfy the
target, retain the measured deficit and concrete alternative. Do not silently
substitute last-known prices, change scope, or spend beyond the authorized plan.
An explicit owner decision is needed only for a real change to budget/scope or
acceptance of a measured limitation, not routine implementation or live validation.

### Capacity policy for this version

Remove arbitrary product cardinality cutoffs that prevent complete acquisition,
retention, processing or access: the current 24-event/20-market selections,
fixed discovery-page windows, metadata projection truncation and any whole-slate
row/capture limits must be replaced or revised wherever they lose in-scope data.
Configuration validation currently rejects values above its defaults; editing
only the installed JSON is insufficient. This is implementation work, not a
claim those restrictions have already been removed.

Use incremental current-state updates, shared metadata, streamed complete pages,
indexed SQL and resumable fair queues so chunk size limits memory in flight,
not total represented games. Paginated/virtualized display is compatible with
all values being reachable. Reassess fixed memory/storage budgets from measured
full-scope demand; the old numeric ceilings are not immutable requirements.
Persist progress and make backpressure visible without dropping tail records or
starving leagues. Text wire size alone does not establish decoded graph, depth,
join or calculation memory cost; measure these separately without turning a
speculative large stress campaign into a prerequisite for real bulk operation.

Actual provider limits, paid credit authority, accounting/hold integrity, explicit
Stop and correct cleanup still apply. They are distinct from arbitrary product
coverage caps. No backup, cloned checkout or per-game rehearsal gate is required.

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
Estimates, Scanner and Coverage share one fair optional work slot with current
resident-memory admission. A separate source-publication runway remains available
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

### Compact capture

The capture omits prior display-age calculations and selection prose, retains only
the event start needed for aging and the occurrence identity needed for counts,
and keeps complete confirmation seals and exact original input frames. PostgreSQL
interns repeated field values across saved prices, older frozen comparison inputs
and raw offers/contracts. Native values and generated references have separate
containers. The adapter restores exact values before the existing observation,
comparison, matching and dependency owners run; it never fills a frozen peer from
new ingress. Same-board references use the ordinary exact-reference validator.

Schedule bindings are projected when event and contract starts differ. For aligned
starts that evidence is unused by schedule projection; full contract dependency
hashes and event revisions still govern revocation. A game refused by the source
publication owner cannot count an older saved board as displayed in Coverage.
Its retained observations remain in the denominator and healthy games continue.
The capture preflight includes book dependency rows and complete runtime/control
rows as well as events, shared publications/offers, board status and prior queries.
All capture, reservation, publication, process and storage limits remain unchanged.


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

Coverage computes its shared SQL capture once per repeatable-read snapshot. An
owned server cursor yields admission bytes first, then the bounded shared header
and offered identities, followed by one complete game at a time. Python admission
counts the header plus the largest encoded game, metadata and auxiliary facts;
the separate expanded-work reservation still covers all retained metric inputs.
Every game is consumed before building/publishing denominators. Cursor and
reservation lifetimes are scoped to the transaction/worker and cancellation.
Neither the 8 MiB capture nor 128 MiB work bound increased. Source-price clocks,
matching authority and scope exclusions remain owned by their existing predicates.
