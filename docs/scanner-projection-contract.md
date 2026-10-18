# Global opportunity scanner v1

`GET /api/scanner` reads the ordinary data runtime’s published scanner; it does not redefine readiness v1, board v2, slate v2 or Details v2. [Schema](contracts/predict-opportunity-scanner-1.schema.json), [authored examples](examples/scanner-1/README.md), [qualification table](scanner-qualification-decisions.md).

## Financial ownership and categories

`comparison/scanner_finance.py` uses the existing `estimated_pair.Leg`, fixed allocation consumer, quantity grid, observed fill path, nonlinear fee/pool engine, funded collateral and joint-state economics. It does not use the old pair EV ranking eligibility to gate cashflow qualification. Mandatory readiness execution/contract checks still gate evaluation, including the original 30/900 second execution limits, 30 second cross-leg skew, exact identity/grid/model/collateral and pregame boundaries. Deadline equality withdraws. Optional EV references retain their separate 1,800 second policy and cannot block independently supported cashflows.

A `covered_outcome_arb` has distinct execution venues and a strictly positive minimum after modeled costs and exactly one deployed-capital buffer across every required feasible joint state. A probability of zero never excludes a feasible loss. `conditional_hedge` uses a positive decisive minimum with losing or unknown admitted cases; it ranks on `net_decisive_minimum_return_percent`. `ev` uses a supported probability/reference expectation, labels complete versus decisive conditional and current versus last-known, and ranks on `net_expected_return_percent`. EV never promotes an arb. Exact rational strings and display companions are supplied by the server.

The default basis is `net_complete_minimum_return_percent = 100 * (minimum state profit after required costs - deployed capital * buffer rate) / deployed capital`. Returned capital/refunded holds are part of cashflow reconciliation, not profit. Required unknown costs or settlement cashflows cannot establish complete qualification. Equal explicit completion conditions or supported nested start/reschedule clauses use the existing joint-state owner. Unknown or incomparable clauses retain decisive scenarios with an explicit unknown joint partition and incomplete coverage; speculative asymmetric states are not fabricated as exact contracts.

Discovery requires no Amount. Each row contains a real supported legal allocation, native quantities/units, modeled deployed capital, exact metrics, source prices/common price displays and original clocks. Only observed ladder quantity is consumed. Shared liquidity is refused, legal minimums/increments and the existing $25 decisive exposure / 20% share constraints remain. The default policy ceiling limits search; it does not require full deployment. Requested-budget reconciliation and verified destinations belong to selected-ticket.

Search evaluates at most 16 points per leg / 256 allocations, adds payout-balanced neighborhoods and preserves nonlinear costs. `search` discloses allocation count, whether the legal grid was exhaustive, and that global optimality/maximum size is not proven. A positive allocation proves existence. A nonqualifying sampled search cannot prove evaluated-zero: `bounded_size_search_incomplete` prevents complete coverage. These are selected supported allocations, not advertised maximum capacity or guaranteed fills.

Scanner search privately requests only wired `profit_usd` state fields from the
existing joint-economics owner. Capital, cell parsing, gains, unknown cashflows,
independent charges, shared-pool conflicts and charges, and profit arithmetic
still run for every admitted allocation. Only unused state presentation is
omitted. Ordinary economics callers and selected tickets retain the full state
output by default.

Search and public classification share the same scalar classification logic,
including buffer and complete/conditional probability partitions. Ranking keeps
the original `Fraction(wire(raw_metric))`, capital and native-quantity tuple,
with strict greater-than replacement. At most three category winners retain
their original states, capital, quantities and bounded component records. The
public classifier formats those exact winners after search; display values,
allocation fields and state profits keep their existing meanings and rounding.
For unusually large fractions, a conservative precision check still invokes the
public formatter during each provisional allocation, including losing ones, so
existing display-bound refusals remain. This changes no numerical policy limit.
All allocation points, cancellation checkpoints and completeness rules remain.

## Identity, order and filters

An opportunity identity binds occurrence, sport/league, market/period/overtime, exact native contract/predicate/line/side/units and settlement interpretation. Leg order is canonical. Price/depth/source-clock changes revise dependencies/economics without changing opportunity identity; changed native predicates/terms remain distinct. Category row IDs suffix that identity. summary must use opportunity identity and epoch/gap semantics when defining episodes, not count polling/publication receipts as arrivals.

All current evaluated rows form one flat universe. Filters apply to the entire universe before sorting and pagination. Default category is covered-outcome arb, descending exact complete-minimum percentage; ties use occurrence then stable row ID. Games are context, never a ranking/grouping stage. A venue filter must include both execution legs. Pinnacle is reference-only and rejects as an execution venue.

Optional query fields: `venues,sports,leagues,markets,periods` (comma-separated), `category`, `minimum_edge`, `minimum_size`, `offset` (default 0), `limit` (default 50, maximum 100), `since`, `epoch`, `query_id`, `expected_revision`. Edge is percentage points on the category's named basis. Minimum size tests the supplied legal allocation's deployed capital; it is not a fresh budget request. No amount/settings mutation, receipt, provider request or ticket query is accepted. Unsupported dimensions return explicit unsupported filters and no matching rows. Filter options come only from configured, authorized implemented adapter scopes: currently NFL/football, winner/full_game, not broader configuration vocabulary.

## Coherent incremental protocol

One background projection serves all users and filters, publishing bounded latest state to PostgreSQL. GET hydrates that state and never starts a financial worker. Missing, unhealthy or superseded publications remain unavailable; they never report a checked-empty ready universe. [Ownership and persistence](data-app-runtime-contract.md). The initial `snapshot` supplies policy/readiness bindings, selected filters, server/epoch/publication/query identity, flat ranked page, total matches, coverage and original clocks. `complete=false` discloses unevaluated, unavailable, partial, unknown, failed or capacity-limited evaluation even if rows are already available. Zero compatible pairs is not an authoritative evaluated-zero. Empty selected scope and failed scopes cannot claim no qualifying opportunities. Coverage counts describe compatible input pairs and authoritative evaluations, not games or all provider markets.

For updates, repeat the same filters/page with `since=publication_revision&epoch=...&query_id=...`. `unchanged` retains the prior page; `replace_page` atomically replaces that whole compact ranked page. Any previous row absent from `ranked_ids` leaves this view, including withdrawal, removal, filter or rank movement. This is an authoritative page replacement protocol, not a list of patches to append. Internal bounded withdrawal tombstones preserve removals; no journal is exposed to clients. All responses carry current scoped coverage. On `resync`, discard the prior page and adopt the supplied bounded replacement. Server restart, epoch/query change, future/missed revision or bounded journal loss causes resync. A later pagination request supplies `expected_revision`; mismatch returns 409 `scanner_page_revision_changed`, so partial multi-page collections are discarded.

Expiry is checked on reads and independently by the scanner worker. Consumers must remove current authority at `expires_at` even if transport fails. Stop immediately empties the projection when read and cancels active finance cooperatively; restart/epoch change starts a new generation and cannot resurrect an old result. Pending turns yield through the shared worker. Stop is checked during allocation, after the final calculation and after blocking proof/capture work before ingestion or publication. Old results completing after Stop, generation or dependency changes are discarded.

## Dependency reuse and trusted receipts

readiness v1 receipts keep exactly their original five fields and strict whole-scope revision/membership/clock validation. Public HTTP accepts no receipts. scanner explicitly adds [trusted receipt v2](contracts/predict-scanner-evaluation-receipt-2.schema.json), consumed only internally. It retains original `evaluated_at` / `original_readiness_revision` and separately records actual current `revalidated_at`, exact current ready pair/readiness/dependency/evaluator identity and qualifying result. Duplicate/member/revision/policy/evaluator/clock/expiry checks reject invalid proofs. Original economic source/book clocks cannot postdate calculation; a transport-only newer receipt may postdate calculation only after unchanged dependency proof at revalidation. It is never relabeled as newly calculated or backdated to an expired model.

The proof retains exact native inputs, originals, depth, required/optional profile payloads/evidence, model/check applicability, source status, event/group meaning, engine and policy. It excludes only specified quote IDs/revisions and transport receipt/projection clocks. Unknown changed fields invalidate conservatively. Whole-scope publication churn does not enter pair economic identity. FIFO pending keys survive unrelated captures; changed dependencies coalesce in place. No per-user/filter/settings financial graph or full report per poll is retained.

The private scanner capture may share recursively immutable preparation facts.
Only that private ingest can retain an already calculated dependency string,
and only when pair ID and leg order match, each leg's immutable instrument and
financial-input objects are identical, and the complete policy, evaluator
version and engine context match. Any changed object, unknown nested fact,
receipt/source clock, temporal preparation, policy, version or engine falls back
to the unchanged financial dependency owner. Equal serialized bytes in different
objects also take that fallback. Ordinary mutable captures and public ingest
always calculate the owner proof; public ingest and returned views retain
detached ordinary mutable dictionaries and lists. Selected-ticket capture keeps
its separate fresh SQL proof and mutable default preparation.

Dependency-proof metadata admits at most 2,048 entries and 2 MiB of charged
metadata. Each entry charges the encoded object containing `key`, ordered
`legs`, `context` and `dependency`, plus 512 bytes of fixed metadata allowance.
Referenced facts belong to the current bounded frame/input graph; this memo
does not retain replaced facts or another payload copy. Ingest prunes changed
identities, context and membership; expiry removes affected entries, and epoch,
Stop and failure clear them. A metadata-cap miss simply recalculates the owner
proof. These encoded-data and fixed-allowance bounds are distinct from physical
Python heap usage, measured by the separate 768 MiB process guard. The memo
grants no readiness, receipt, SQL, financial or freshness authority, and never
changes original calculation or source clocks.

## Per-capture presentation reuse

A private display memo reuses constructed row presentation only within one owned
capture and only for the exact owned financial-record object. Evaluator results
are detached after the existing result-size check. Every ingest clears the memo,
including receipt-only captures, so original prices, source/receipt clocks and
event context are rebuilt from current inputs even when economics are reused.
Stop, capture failure and expiry also clear it; replacing a financial record
invalidates that pair's previous display entry.

Every materialization still checks pair expiry and validates the current receipt
and original clocks before looking up display rows. Fresh post-drain SQL,
registry, policy and source proof continues to control financial publication.
HTTP expiry remains withdrawal-only. The memo supplies no receipt, readiness or
financial authority and changes no allocation, dependency or calculation clock.

The memo admits at most 2,048 pairs, 4,096 category rows and 4 MiB of charged data.
Each entry charges the encoded object containing its pair key and rows, plus
128 bytes per entry and 512 bytes per row for fixed metadata/container allowances.
Nested financial values remain owned by the separately bounded financial cache.
If any memo cap is reached, the projection recomputes presentation without
dropping results or changing financial work. These are encoded-data and fixed
allowance bounds, not a strict Python heap measurement. The independent 768 MiB
physical per-process guard remains in force. See the
[preparation contract](scanner-preparation-contract.md) for capture ownership and
input-byte accounting.

## SQL, causality and instrumentation

`storage/scanner_readiness.capture` extends the read-only readiness seam with detached minimal quote/profile/event/group inputs and the exact current-row revision. `read(...)` and the public readiness wire still return v1 only. The connection and transaction close before finance. The worker cheaply probes current row/config/source/model/policy identity, recaptures on changes/deadlines, and rechecks the causal boundary before publishing newly calculated work. A changed boundary is reconciled against exact current dependencies; unrelated results can survive.

`storage/scanner_publication.transaction` wraps ordinary ingress transactions. It captures exact row revision inside that transaction, and records an actual observation after successful top-level commit. Rollbacks/nested/foreign/pre-start transactions supply no observation. Instrumentation failure cannot fail already-committed ingress. Readiness's `sql_committed_at` remains null. Scanner `causal.sql_post_commit_observation` is null unless an exact retained causal row-revision observation exists; it says **observed after commit**, not PostgreSQL's unrecorded precise commit instant. Never substitute ingress projection, receipt or read time. A foreign writer or expired-row capture mismatch legitimately leaves it unknown.

Rows retain dependency/economic revisions, original source clocks, calculation start/completion and duration. Scope includes actual SQL capture duration, input/readiness revisions and projection publication time. Client timing observations bind delivery, application and rendering opportunities to exact matching revisions. Reused rows preserve original calculation clocks; a newly received packet does not imply fresh calculation or source freshness.

## Bounds and evidence limits

One active capture/finance worker; a single coalescing wake bit; at most 16 pairs / nominal 500ms scheduling turn (an individual bounded evaluation may finish after that turn deadline). The time cap and per-evaluation cancellation/expiry checks remain unchanged; the larger count cap reduces repeated preparation between otherwise underfilled turns. Limits: 500 active occurrences, 2,048 compatible pairs, 4,096 category rows, 64MiB detached inputs, 16MiB scalar result cache, 128 journal entries / 4MiB, 100 rows/page and 2MiB response. Oversized capture/results/response explicitly withdraw or mark incomplete; none can produce a checked-zero or silently imply complete top-N. Retained inputs are replaced and cache keys are pruned with the current target set. No scanner table/migration, raw-response history or durable report archive is added. Existing 2GiB SQL / 1GiB free-disk / 768MiB process guards are unchanged.

Synthetic timing measurements describe only their fixture workload. Full-finance
initialization, source-to-browser propagation and burst behavior require separate
measurements and are not implied by small protocol tests.
