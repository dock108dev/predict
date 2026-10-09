# Latest-only update repair — October 8, 2026

Owner requested changed-only updates with bounded memory rather than storing every price observation. Current state now retains only the latest admitted quotes and calculation graphs. No quote history database or patch queue was introduced. Existing restart receipts and quota/accounting records remain preserved.

## Update flow

Every changed exact market group uses the existing strict serializer and exact original-input calculations. Unchanged groups reuse immutable calculation graphs. A change to price, depth, binding evidence, source state, reference or freshness eligibility invalidates the relevant group; explicit cross-group engine legs retain full projection. Revisions, global instrument consistency and aggregate source-clock rules remain enforced. Atomic admission swaps only after validation succeeds.

Current and Arbs clients initially fetch a full snapshot, then fetch only events changed since their runtime/revision cursor. Latest event revisions plus bounded removal tombstones support coalescing; old/foreign cursors receive a fresh snapshot. Browser rendering updates affected event nodes while preserving filters, focus and open price details. Server clock metadata rebases unchanged source ages; elapsed time does not refresh a price or baseline.

Native price batches detach only book/health maps rather than cloning the full inventory. Aggregate/native event association reuses the latest sport association when identity inputs are unchanged. Pure sporting event identity checks share the validated default read-only entity registry, invalidated by file identity/timestamps; explicit authoring loads remain detached. Canonical JSON now streams chunks into one byte buffer rather than building a giant temporary string. Exact canonical UTF-8 bytes and hashes are preserved.

## Resource finding and accounting recovery

An initial incremental-only live attempt still hit the unchanged 768 MiB ceiling. A controlled repeated encoding of a fixed approximately 13 MB board grew from 160 MB highwater to over 930 MB after 21 full encodes with the previous encoder. The streaming encoder preserved exact bytes; the traced 40-encode test plateaued at approximately 225 MB. Temporary tracing was removed before the final runtime. This is bounded local evidence, not a guarantee for indefinite operation.

The earlier memory stop had cancelled one NCAAB request, leaving its three-credit reservation uncertain. A later free sports endpoint returned 120 used / 99,880 remaining and last charge zero, identical to the sole uncertain attempt baseline more than an hour after dispatch. The narrow recovery method accepts only one expired uncertain request, current exclusive ownership, the same reset window, a recent successful free usage observation and exactly unchanged counters. Any spend or extra uncertainty preserves the reservation. The original attempt and consumed authority retain an explicit recovery evidence hash; due times and prior spend are unchanged. The following ordinary six-sport cycle completed and reconciled 15 credits to 135 used / 99,865 remaining. No quota reset or assumed lost-response header was supplied.

## Validation

200 affected controlled Python checks passed, plus the additional exact UTF-8/numeric-rejection check and dependency-free current client and board security checks. Controlled tests cover one-group recomputation, reuse of unchanged calculation graphs, equality with full canonical projection, atomic rejection, coalesced deltas, removal, ageing/EV expiry, runtime recovery, Arbs cursors, registry invalidation and zero-charge recovery refusal when counters show spend. An exploratory historical normalization suite encountered four missing phase-0 manifest errors; maintained registry and affected sporting suites passed in the final run.

Final live measurements and screenshot are recorded separately below. Long-duration owner operation remains unqualified. The memory ceiling and bounded transport queues remain enforced.
