# Combined occurrence input contract

`predict-combined-occurrence-inputs-1` binds immutable SQL envelopes to one
resolved sporting occurrence while preserving original economic contracts. It
supplies the ordinary saved-board pipeline and shared financial evaluators.

## Concrete owners and invocation

`app/comparison/combined_inputs.py` owns `build`, `validate` and `calculate`. `app/comparison/combined_native.py` adapts retained native catalogs/books through `collection/current_sink.normalized_records(..., dated_annotations=False, clock=at)`. `comparison/occurrence_matching.OccurrenceResolver` owns joins and provider-local fallback. `storage/current_games.GameStore` adds `combined_envelopes` and `retain_combined`; its existing `snapshot`, `calculate`, immutable tables and atomic publication retain their ownership. No new database or migration is required.

```python
from app.storage.current_games import GameStore, calculate
from app.comparison.combined_inputs import build
from app.comparison.estimated_policy import DEFAULT_POLICY

store = GameStore(db)  # Existing project connection; use a disposable database in tests.
envelopes = store.combined_envelopes()  # One SQL statement/snapshot, no acquisition.
bundles = build(envelopes, at=aware_iso_clock,
                selected=(provider, native_event_id), benchmark_venue='pinnacle')
for bundle in bundles:
    key = store.retain_combined(bundle)
    snapshot = store.snapshot(key, DEFAULT_POLICY)  # Keeps bundle's evaluation instant.
    result = calculate(snapshot)                   # Outside capture transaction.
    result_id, published = store.publish(snapshot, result)
```

For an explicitly selected Novig/ProphetX benchmark, build with that venue and use `dataclasses.replace(DEFAULT_POLICY, benchmark_venue=venue)`. A crossed policy refuses. Historical replay supplies original envelope rows directly to `build`; reopening never selects a later evaluation clock for an existing bundle. `snapshot(..., at=different_clock)` refuses for combined inputs. A new as-of boundary requires a new bundle and identity, with original source clocks intact.

`selected=(provider,native_event_id)` selects the resolved occurrence containing that original member; omit it for bounded discovery. Output is a list, because unresolved occurrences retain their source-local scope. Pinnacle is reference only. This owner currently selects NFL/full-game moneyline; spread/total original envelopes remain unchanged. The database pipeline owns scheduling and guarded publication; the saved-board API owns compact responses.

## Lossless inputs and identity

Envelope rows are `{id, payload_sha256, record}` from immutable `current_envelope`. The original SQL IDs need not equal the payload hash. Each full record and aggregate decoded-body hash is verified before use. Latest admitted catalogs/books and quote observations are reduced at the supplied instant. Every used quote retains its catalog/book or aggregate-envelope association. Input caps are 256 envelopes / 24 MiB; the persisted projection cap is 8 MiB. Native depth and shared-profile bounds stay unchanged.

The bundle retains original envelopes, normalized source-local records, occurrence match audits, source IDs/roles, native predicates/wording, quantities/prices and every source/receipt clock. `state_inputs` contains reusable recipes and content-addressed profiles, including the selected benchmark and quantity model. `input_version` hashes this complete graph; `game_key` is the canonical event alias. `validate` checks its content seal. Snapshot identity additionally binds policy, as-of and exact engine digest; result identity binds snapshot and complete result bytes. Relevant membership, adapter, reference, quantity/fee/payout recipe or policy changes therefore cannot masquerade as the same result.

The Combined identity profile resolves the legacy producer/fallback alias discrepancy. It retains the complete parent identity profile and occurrence match revision under `combined_occurrence_binding`; original observation/economic-contract bindings are not rewritten. The resolver's three-member metadata join now handles a weak aggregate ID plus a unique native witness without requiring an unknown source to witness its own season/stage. Repeated games, conflicting shared IDs, reviewed-edge restrictions and role reversals still refuse independently.

Engine binding now includes native adapters, occurrence resolution, normalized/source projection seams and the storage owner in addition to policy, financial and content owners and retained catalogs. Historical readers remain available. A snapshot with an earlier engine digest requires its matching original engine implementation for recalculation; it is never rebound to current code. Results cross a canonical JSON boundary before SQL persistence, preserving exact number spellings and preventing tuple/list round-trip differences.

## Selected benchmark originals

`produce_two_way_benchmark` consumes the two original admitted outcomes from exactly the selected sportsbook's shared response/event/h2h frame. It preserves odds, roles, bookmaker/market clocks, receipt and source revision, with proportional no-vig decisive weights. Missing, incoherent, future or expired selected originals withhold EV; no substitute is chosen.

The existing aggregate normalizer creates outcome-local market locators. Typed benchmark outcomes use an explicitly declared h2h grouping key, not a fabricated native market ID. `benchmark_originals.source_originals` retains both complete original records and their original outcome-local market IDs; `grouping_authority` and `grouped_market_id` identify the shared provider frame. Native instruments never supply sportsbook benchmark odds. Decisive benchmark scope does not assert common tie or completion settlement.

## Native model and semantic boundaries

Kalshi phase uses an exact scheduled milestone associated with the catalog event; US phase uses the exact event ID, active/open NS state and scheduled-start fact. Participant roles come from retained source roles. No dated selected-game proof, team-name-only join, bare unnamespaced source ID or permanently selected fixture provides authority.

YES/NO and Long/Short retain their source IDs and predicates. Kalshi NO remains not-win with its own tie receipt. US Short remains its original instrument and complementary bid representation; unsupported collateral remains `estimate_short_collateral_unresolved`. Kalshi's 48-hour start window, US's two-week rescheduling window, fair-mark terminal clauses and sportsbook refunds remain distinct in originals and modeled cashflows.

`predict-combined-quantity-model-1` declares a 0.01 increment/minimum in existing admitted decimal $1 purchase-contract units. It preserves the original quantity profile/status, explicitly leaves actual minimum/increment qualification false, and supplies no fixed-point scale. Kalshi's cent-price/cent-contract path supports the fee owner's required six-decimal notional. Bound or contradictory grids retain precedence. This is a named calculation grid, not execution qualification. Actual fills, additional account charges and grades remain unknown. Observed depth support and hypothetical fills are separate.

Content recipes retain their declared effective intervals, expiry and kickoff
limits in `app/fixtures/estimated-content-v1.json`. Other games/instants must pass
their own applicability checks. A model recipe cannot cure conflicting units or
predicates; content is not extended by a read or a later calculation.

## Financial consumption and publication

Read `financial_metrics`, `funding`, `benchmark`, `classification`, `model_versions` and the original native contract from the shared [financial contract](requested-trade-financial-contract.md). Default is requested $1,000 shared funding and one 0.005 deployed-capital buffer. Complete EV stays null for unbound terminal partitions; conditional EV and decisive/all-state margins remain separately named. No positive expected value, supported depth or scenario margin establishes a guaranteed fill/profit.

Single and pair eligibility are dependency-local. The saved-board read model
ages each result against its actual legs, reference and content. A stale alternative
does not withdraw healthy independent calculations. The current-state compatibility
reader's `age_result` can mark an entire event historical; it has a different contract.
The database pipeline owns bounded scheduling/coalescing and guarded latest
publication. Building or reading a bundle never requests collection.

See the [structural schema](contracts/predict-combined-occurrence-inputs-1.schema.json)
and [saved-board API](comparison-board-api-contract.md).
