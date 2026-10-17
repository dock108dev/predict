# Scanner readiness v1 — SC01 consumer contract

Implemented in the ordinary main app. Current source/model qualification remains separate from local implementation and authored verification. The bounded process-local preparation owner is documented in the [preparation contract](scanner-preparation-contract.md).

## Read and ownership

`GET /api/boards/readiness` returns `predict-scanner-readiness-1` in the ordinary app. Optional comma-separated `venues`, `sports`, `leagues`, `markets` and `periods` select an exact universe. Defaults are four execution venues, `football`, `NFL`, `winner`, `full_game`. Pinnacle is reference-only and cannot be an execution venue. Unimplemented sports/markets return explicit unsupported scopes; changing a filter cannot authorize collection.

The existing board/slate/Details versions keep their meanings. The readiness route shares their one-reader/four-waiter limit, cancellation and failure handling. It reads the existing service configuration/authority and current rows; it does not initialize a collection owner, inspect credentials, read/write settings or call recovery. No HTTP endpoint accepts client-authored evaluation receipts.

The internal entry point is `app.storage.scanner_readiness.read(db, config=..., authority=..., at=..., selection=...)`. Use a dedicated autocommit connection; it establishes one repeatable-read, read-only transaction. It captures current offers, exact discovered contract counts, native book headers/depth and source status, and builds bounded model inputs. It does no sizing, profitability calculation, financial classification, projection persistence or acquisition. Invalid instrument inputs fail their affected scope; unrelated healthy inputs survive. A catalog-level failure remains explicit.

The pure `app.comparison.scanner_readiness.assemble` seam accepts typed adapter output and optional **trusted SC02** receipts. `Selection` and `Check` are typed records; [wire schema](contracts/predict-scanner-readiness-1.schema.json) defines the exact output, counts, checks and clocks. [Receipt schema](contracts/predict-scanner-evaluation-receipt-1.schema.json), [authored examples](examples/scanner-readiness-1/README.md).

## Coverage and dependencies

`universe_basis=selected_current_admitted` means the selected upcoming admitted working set, with source discovery limits still disclosed. It is not a count of every market that exists at a venue. `scopes` includes empty, unsupported and unauthorized selected scopes. Each scope separates configuration, authority, supported adapter, discovery, offered contracts, exact identity, retained synchronized depth and current cashflow-input readiness.

Every count carries `{value, denominator, unit, scope}`. Observed-occurrence denominators describe the observed set, not an unknown provider population. Offered contracts divide by discovered contracts; instrument checks divide by selected observed instruments; ready pair inputs divide by exact structurally opposing pair inputs. Evaluated pairs divide by ready pairs. A denominator of zero is an explicit empty set, not a percentage or a checked-empty market. Never sum different units or overlapping causes. `causes` is a stable sorted union with purpose-specific instrument counts and `causes_overlap=true`.

Each instrument preserves occurrence, native event/market/outcome/side, the actual native predicate, units, native contract ID and contract-terms digest. An input pair requires distinct execution venues, the same occurrence/market/period/overtime and opposing decisive directions. This is **structural input compatibility**, not equivalent contracts, supported exceptional joint cashflows or an arb. Native NO is not rewritten as opponent YES; Short remains Short and unresolved collateral blocks its contract readiness.

Three independent `checks` have stable reason codes:

- `execution`: source availability, original clocks, age, synchronized book, correct units/price and positive observed legal-minimum depth. Connected transport cannot repair stale or unsynchronized prices. Aggregate odds have no observed synchronized native size; their execution-depth gap remains explicit.
- `contract`: exact identity/occurrence, applicable fee/payout/quantity/settlement content, actual known grid, pregame stage/overtime, selected model intervals and collateral. Named hypothetical quantities cannot establish a legal execution grid. No required fee/rule/profile expiry is bypassed.
- `ev`: reference/probability dependencies and their original clocks/applicability. It is a fact-dependency check, not a claim of complete numeric EV. Reference absence/expiry never enters cashflow pair input checks. SC02 must still prove the relevant probability partition or label conditional EV.

States include `waiting`, `stale_only`, `partial`, `unsupported`, `failed`, `blocked`, `not_evaluated` and `ready`. Purpose checks and reasons remain inspectable even when a scope summary has another dominant state. No compatible input pairs, no ready pairs and not-yet-evaluated pairs are distinct. `reference_sources` counts Pinnacle originals separately; shared `references` retains original book/market/receipt clocks once per profile identity.

## Clocks, fixed policy and invalidation

[Policy](../app/fixtures/scanner-readiness-policy-v1.json) is content bound by `policy_revision`, engine identity and the complete candidate manifest. It records source-file hashes and the October 16 local engineering rationale. These are fixed admission restrictions, not source update guarantees:

| Source and admitted NFL pregame/full-game winner scope | Original execution-price maximum | Native book maximum | Cross-leg skew maximum | Reference maximum |
| --- | --- | --- | --- | --- |
| Kalshi | 30 seconds | 30 seconds | 30 seconds | 1,800 seconds when an explicit supported sportsbook reference is selected |
| Polymarket US | 30 seconds | 30 seconds | 30 seconds | Same |
| Novig / ProphetX via aggregate | 900 seconds | Unknown / unavailable | 30 seconds | 1,800 seconds |
| Pinnacle | Reference-only | Unavailable | Not an execution leg | 1,800 seconds |

The native cap comes from the existing `current_sink` book-age engineering policy and retained fixtures; 900/1,800 seconds retain the existing net-pregame/reference owners. The new conservative cross-leg restriction is one native admission window. It is a local coherence decision derived from that window, **not an empirically certified source cadence**; SC07 must qualify it without adaptive widening. Equality at a source/model deadline withdraws readiness. Skew above 30 seconds refuses the pair even if each individual original is within its own age bound.

`source_at`, `received_at`, native `book_at`/`book_received_at`, aggregate `provider_book_at`/`provider_market_at` and `ingress_projected_at` keep their actual meanings. The latter is an ingress projection clock, **not SQL commit time**. `sql_committed_at` is explicitly null because current rows do not retain an authenticated commit-completion clock. Do not manufacture it from receipt or read time. SC02's publication boundary and SC06's timing instrumentation must add actual causal stage observations bound to source dependency/revision; SC04 adds delivery/render observations. Existing original/receipt clocks are preserved for that chain.

Future-at-receipt, unknown, conflicting and out-of-order inputs do not age into authority. Receipt/heartbeat/connection/calculation times never renew a source price. The next future `expires_at` is the earliest source/book/model/link/pregame boundary; consumers must recapture at that boundary even without a packet. An already-invalid dependency remains invalid; expiry does not extend any model. `revision` binds selected scopes, source/book/receipt identities, model/policy/engine applicability and readiness state. No durable readiness cache or source-fact archive is introduced.

## SC02 integration

Use the integrated main checkout and its current source/runtime binding. Preserve existing source, retained resources and owner state. Use readiness to gate inputs, then separately establish covered-outcome arb, conditional hedge or EV semantics through the existing cashflow/fee/sizing owners. `cashflow_pairs_ready` is not a count of opportunities. Keep fee/rule/identity/quantity/settlement refusals; exclude only probability/reference-purpose failures from cashflow qualification. SC01 does not repair the existing board pair-aging/classification boundary; that remains SC02's work.

After an authoritative check, pass an internal receipt `{pair_id, readiness_revision, evaluated_at, qualifying, evaluator_revision}` to `assemble`. It must name an exact current ready pair and this readiness revision; stale receipts are dropped, duplicate receipts and future/pre-original evaluation clocks reject. Re-evaluate at actual time; never backdate to an expired profile. A complete set of current nonqualifying receipts can report `evaluated_zero`; readiness inspection alone always reports `not_evaluated`, with `qualifying_pairs=null`. The no-qualifying flag applies only to the selected admitted set and stays false for missing/failed/blocked scopes. SC02 owns the classifier/evaluator evidence behind each trusted receipt.

Connect source/model expiry, source withdrawal/Stop, policy/settings and material price/depth/identity changes to targeted projection invalidation. Bind the same source revision to SQL publication, computation and delivered row clocks. Use 500 active events, existing source limits and current-row upserts; do not create per-filter report history. The current SQL capture has no ingress advisory lock and performs no financial sizing while it is open.

## SC04 integration

Consume SC02's eventual scanner protocol for opportunities and this version for coverage. Show one scanner-level degraded summary with inspectable exact affected scopes/reasons. Label retained sync/depth separately from current evaluability. Use named count units and denominators; never label 27 occurrences as 27 two-venue arb markets. Distinguish waiting, stale-only, unsupported, failed/blocked, no compatible pairs, not evaluated and authoritative evaluated zero. Do not calculate money or infer a zero-opportunity result from readiness counts. Unsupported filter vocabulary must not look like available acquisition.

Readiness remains an input contract, separate from scanner financial classification, ticket authority and browser evidence. Warm ready scanner ≤3s, valid receipt-to-visible result p95≤2s/max3s and ready ticket p95≤1s/max2s require their own measured proof. Current source/model/link and finite genuine-propagation qualification remain SC07 work.
