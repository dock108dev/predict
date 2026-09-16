# E2 — offline reference adapter, immutable enrichment and durable replay

Completed September 15, 2026 for the **authorized local synthetic implementation only**. One explicit invented NFL ATL/PIT pregame event, `synthetic-atl-pit-e2`, one `h2h` market and one `pinnacle` bookmaker through a The Odds API-shaped injected transport. **Neither provider is qualified for live fair-price inputs. E3 is not started.**

## Exact candidate and preservation

- Base HEAD remains `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`. No commit or push.
- Uncommitted E2 implementation digest: `b498cede9eb5f8762fbe4ecae5b2594ef3fca6d7cc2828b9af3317343a3fd94c`. This is SHA-256 of the sorted compact JSON mapping of the 12 implementation/test paths to their file SHA-256 values. [Exact file manifest](../evidence/e2/implementation/candidate-implementation.json).
- [Entry manifest](../evidence/e2/implementation/entry-manifest.json) retains the preexisting application, guidance and evidence identities. E1 is preserved except the narrow new reference-eligibility guard in `app/edge_contracts.py`. README, roadmap, prior qualification, E1 examples/tests/evidence and archived source copies are preserved.
- Archived SDA remains clean at `b63ad4d985ab9e8d007767e2b97c78b4783d7c65`; Scroll Down remains clean at `087411753d6f4a2665820f84bf6270b08d05ea91`. Neither was run or modified.
- [Final verification](../evidence/e2/implementation/verification.json) records preservation and artifact hashes. The Desktop tracker is outside this Git repository.

## Implemented path

**Injected response → ingress receipt → PostgreSQL raw artifact/receipt → immutable matching revision → failure/recovery observations → versioned export → fresh PostgreSQL restore → exact as-of replay.**

| Files | Concrete behavior |
|---|---|
| `app/reference/adapter.py` | Reference-only async protocol, injected transport/clock, unique ingress IDs, sanitized fixed request metadata, repeated usage headers, finite requests/retries/time, pregame cutoff, cancellable request/backoff, quota/entitlement stops, fresh-snapshot recovery and close semantics. No HTTP implementation or credential loader. |
| `app/reference/records.py` | Frozen source, receipt, enrichment and gap records; exact raw bytes/base64 and hashes; source effective/known-at times; strict dependency bindings; `reference-bundle-1` export/import and receipt-plus-knowledge as-of selection. |
| `app/reference/enrichment.py` | Exact JSON Decimal parsing, identity-based orientation, explicit missing slots, optional SID kinds, provider last-read semantics, null side times, full saved normalization registry, exact-schedule event comparison, existing moneyline rule binding and settlement comparison. Replay recomputes the revision using its saved knowledge. |
| `app/reference/storage.py` | Existing `Store` migration/artifact/session foundation, atomic immutable inserts, raw-artifact verification, receipt/source/gap foreign keys, fresh-store reference restore and as-of replay. Caller must provide an explicit connection. |
| `app/storage/migrations/004_reference_history.sql` | Four new reference tables, time indexes and SQL mutation-rejection triggers. No fair-price tables or calculations. |
| `app/edge_contracts.py` | The Odds API-shaped references cannot pass E1 eligibility without the explicit synthetic pairing assumption; an assessment not effective at the observation is excluded. No executable venue/book types changed. |
| `app/storage/store.py` | Existing capture readers accept an exact original migration set when only the additive E2 migration is absent. Capture format and existing table meanings are unchanged. |
| `app/reference/fixtures.py`, `tests/test_reference.py` | Invented provider-shaped fixtures and 29 focused E2 tests. Positive pairing, family/copy lineage, alias mapping and rules are labeled synthetic assumptions. |
| `app/reference/verify_storage.py`, `integration_tests/test_storage.py` | Reproducible new-cluster verification and existing storage regression suite; migration count updated from three to four. No owner connection helper is called by the verification runner. |
| `docs/e2-implementation-report.md`, `docs/e3-handoff.md`, Desktop tracker | This report, one concrete proposed E3 package and current status. |

## Evidence and results

| Check | Result |
|---|---|
| Focused adapter/contracts/models/arbitrage/depth/fees/event matching/moneyline/normalization suite | **242 tests passed**, 29.559 seconds. [Full output](../evidence/e2/implementation/focused-tests-complete.txt). |
| Existing PostgreSQL storage suite, connection entry point explicitly rebound to the identity-checked disposable cluster | **26 tests passed**. [Output](../evidence/e2/implementation/foundation-storage-tests.txt). Covers existing precise receipts, immutable storage, rollback, detector/depth replay and indexes. |
| New PostgreSQL integration pipeline | Passed four migrations plus idempotent reapply; stored **9 receipts, 11 enrichment revisions and 6 gap/stop/interruption records**, plus two source revisions. [Identity and check ledger](../evidence/e2/implementation/storage-verification.json). |
| Reference export / fresh-store restore | Full export byte-identical. SHA-256 `d2db196f7d3801468866ab5e8f4bf3d375e31367b2bf66ebfd2466158df4abe6`. [Bundle](../evidence/e2/implementation/reference-bundle.json), [restored bundle](../evidence/e2/implementation/reference-bundle-restored.json). |
| As-of reconstruction | Six cutoff reconstructions byte-identical after restore; each hash appears in the ledger. Every enrichment is recomputed from its saved registry, source and assessment before accepted replay. |
| Existing capture compatibility | A real `capture-bundle-1` created on migrations 001–003 restores on 001–004, and its existing detector audit replays successfully. [Legacy bundle](../evidence/e2/implementation/legacy-capture-bundle.json). |
| Storage/interruption failures | An actually closed disposable PostgreSQL connection produces an explicit failure journal retaining the unsaved raw response; cancellation writes a PostgreSQL interruption gap. Queue and disk-failure injections are also covered by unit tests. [Disconnected-store journal](../evidence/e2/implementation/disconnected-db-journal.jsonl). |
| Identity and cleanup | Every connection verifies database, user, data directory, socket, port and empty TCP listen address before use. The newly created cluster was stopped and its directory removed. Owner database and services were not accessed. |
| Whitespace/preservation | `git diff --check` and entry-file preservation verification passed; exact records are in final verification. |

### Required-case coverage

- Complete and reversed-order pairs produce the same canonical ordering and exact `1.90000000000000000001` / `2.1000` values. Missing sides remain null; no previous-side cache exists. Duplicate, third/draw, unknown, malformed and invalid-price outcomes retain rejected raw receipts.
- Missing optional bookmaker/market/outcome SIDs do not alter the scoped market locator. Native labels are explicitly labels, optional SIDs separately retained. Missing market time stays unknown; bookmaker time is not substituted. Side timestamps stay null; market time is provider last-read, not bookmaker price-change.
- Unknown pairing, source lineage and rules remain ineligible. Source copies use null for unassessed lineage, and an empty tuple requires explicit invented external-only evidence. Pair assumptions do not qualify live input.
- Unknown/ambiguous participant mappings, changed or absent schedules, unsupported periods/terms and unresolved phase are rejected or explicitly unresolved. Schedule/phase uncertainty stops observation. A later alias registry creates a new immutable revision; earlier reconstruction still returns the unresolved revision.
- Identical and non-opportunity payloads remain separate arrivals. HTTP 429, exhausted/contradictory quota headers, entitlement failures, bounded timeout/retries, request/backoff cancellation, consumer close and fresh complete recovery are covered.
- Polling intervals are sampled coverage, not outage claims. Failure detection and last successful observation remain distinct from unknown actual outage onset. Recovery links a new receipt; it does not fill unseen history.
- Later source/rule/mapping knowledge and later receipts are excluded from earlier reconstruction. Archived snapshot timestamp and previous/next pointers are separate from market read time and actual synthetic download receipt time.
- Exact bytes, Decimal spelling/scale, request metadata, usage headers, evidence hashes, source/mapping/rule revisions and rejected responses survive export and durable restore.

The first storage run reached the new reference pipeline but failed in the **legacy test harness** because it passed `as_of` instead of the existing detector's `evaluation_time` argument. That harness was corrected; the failure log and cleanup record remain at [initial run](../evidence/e2/implementation/storage-run-initial.txt) and [initial ledger](../evidence/e2/implementation/storage-verification-initial.json). Intermediate successful artifacts are retained in `second-run/` and `third-run/`; the linked top-level bundle and final logs describe the current candidate.

## Operational limits and remaining work

- This package deliberately has **no production network transport** and enforces synthetic event/source/session scope. Account entitlement, live event delivery, real source lineage, upstream pair synchronization and actual target settlement compatibility remain unverified. Qualification documentation is preserved separately.
- Bounds default to 12 requests, two consecutive retries, 120 seconds overall, five seconds per request, one-second fixture polling/backoff, ten-second maximum retry delay, 1 MiB per response and 12 MiB cumulative response thresholds. These are offline test/work limits, not recommended live cadence or cost limits. The first over-limit delivered response is retained and stops further work; a future network transport needs bounded streaming ingress. No unbounded ingestion queue is introduced.
- A failed primary sink stops immediately. Its fallback journal explicitly says primary persistence failed; it is not counted as PostgreSQL completion. If both primary storage and the journal fail, an exception states durability is unknown. No automatic journal reimport or hard-process-kill recovery is claimed.
- Reference export preserves reference/session IDs and complete reference records. Restoring creates explicitly synthetic capture-session provenance; it does not recreate an owner collector's runtime state. Full existing prediction capture remains the separate `capture-bundle-1` format.
- Raw timestamp strings retain provider precision; E1 datetime projections use Python datetime precision. E3 must use retained exact-time evidence when submicrosecond distinctions matter. No upstream latency or subsecond lead/lag claim is made.
- E1 checks structural input assumptions. E3 must consume receipt-bound revisions with knowledge cutoffs and define latest-snapshot, pairing, freshness, de-vig and target-specific policy. No production fair-price calculation or persistence was added.
- No provider requests, credentials, signup/subscription, outreach, owner database access/migration, owner-service changes, UI expansion, trading, commit, push or publishing. The deferred **250 ms gate remains deferred**.

**Stop reached: E2 offline implementation complete.** Next proposed action: the [bounded E3 offline baseline handoff](e3-handoff.md), requiring separate authorization. Live qualification and owner acceptance remain separate outcomes.
