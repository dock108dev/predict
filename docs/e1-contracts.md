# E1 — reference, fair-price and signal contracts

Version: `edge-contracts-1`. Implementation: [app/edge_contracts.py](../app/edge_contracts.py). This is a small executable schema and input-eligibility boundary. It does not select a provider, calculate production probabilities or implement E4/E7/E9 strategies. One module keeps the initial shared vocabulary compact; future packages may import it without another model hierarchy.

## Existing foundation and ownership

| Existing interface | E1 use and extension |
|---|---|
| `app/models/core.py` | Reuse `Probability`, `Money`, `Quantity`, `Venue`, `MarketType`, timestamp/Decimal validation and native `OrderBook` types. No external bookmakers added to `Venue`. |
| `app/normalization/{registry,observations}.py`, `app/matching.py`, `app/moneyline.py` | Keep canonical league/team/event/market IDs and immutable, versioned matching evidence. Reference mapping is separate enrichment; no fuzzy result becomes an accepted canonical ID automatically. |
| `app/settlement.py` | `MarketTerms.rules_profile_json` retains the existing versioned assessed rule profile with source text/hashes, every material dimension and exceptional payout scenario. Reuse validation/comparison; no second settlement rules engine. |
| `app/fees/engine.py`, `app/arbitrage.py`, `app/depth.py` | Fee contexts and complete existing audit snapshots travel with signal records. No new fee, payout or depth arithmetic. Add runtime type checks to `Observation.quote` and `book_observations`; `book_ladders` enters through the latter. |
| `app/adapters/base.py` | Prediction `MarketUpdate` union remains unchanged. References are neither `Quote`, `OrderBook`, `RawPayload` nor `ReadOnlyAdapter`. No executable conversion is supplied. |
| `app/storage/replay.py`, `app/storage/store.py` | Existing detector replay reused in walkthrough. New isolated envelope uses the existing digest helper and exact decimal-text convention. No capture schema migration/import, store connection or historical format rewrite. |

## Wire and unknown-value conventions

Models are frozen dataclasses; nested collections are tuples. Constructors check declared scalar/model types, aware timestamps, finite Decimals and model-specific invariants. The allowlisted `dumps`/`loads` codec tags model/enum types, Decimal text, tuple values and ISO timestamps under a version and payload SHA-256. Unknown schema tags/versions, floats, nonfinite values and mismatched hashes fail. Hashes detect changed content; they do not authenticate a provider.

Raw JSON stays an immutable **exact text string**, including whitespace and numeric spelling. `ReferenceQuote.raw_sha256` derives its identity. Raw JSON numbers are parsed as Decimal when inspected. No JSON numbers are used for modeled monetary/probability values. Null is unknown except `MarketTerms.line=null`, which means not applicable for a moneyline. Missing material reference facts require `unknowns`; missing economic facts require reasons and null final net values. Empty tuples mean known empty lists, not unknown lists. In particular, `copied_from=null` is unassessed lineage; `copied_from=()` is explicitly assessed external-only lineage.

The executable fixture envelope is [walkthrough.json](../evidence/e1/walkthrough.json). The tagged representation is the schema example for all implemented records. `FairPrice.input_receipt_ids` is the ordered tuple derived from included decision rows; those rows carry each immutable receipt and its source/family. Excluded receipts remain auditable and cannot enter that input tuple.

## ReferenceQuote

| Fields | Meaning |
|---|---|
| `receipt_id`, `provider`, `underlying_source`, `source_family`, `copied_from`, `identity_evidence` | Provider delivery identity differs from bookmaker/exchange origin and independent information family. Known copies carry canonical originating source IDs (prediction venue IDs use `Venue.value`). Unknown lineage is ineligible. Identity aliases/lineage are assessed upstream, never guessed from display names. |
| `native_event_id`, `native_market_id`, `native_outcome_ids` | Preserve provider-native keys. Do not reuse prediction-market `NativeRef`, whose namespace is a prediction venue. |
| `terms` | Canonical event/market IDs may remain null while unmatched. NFL league, exact scheduled start, market type, full-game/period, phase, line and ordered canonical outcome IDs, plus assessed settlement profile. Overtime, tie, postponement, cancellation, deadlines and other material rules live in that existing profile. Equal unknown profiles do not establish compatibility. |
| `decimal_odds` | Two ordered **gross return / stake** decimal-odds slots, each Decimal greater than one or null. Not probabilities, contract purchase prices, asks, guaranteed payouts or executable depth. Original native odds convention/value remains in raw provenance. |
| `source_at`, `source_time_semantics`, `received_at` | Source snapshot/last-change time or unknown, distinct from aware local receipt time. One paired receipt does not by itself prove synchronized source-side updates. Provider-specific side times/pairing evidence belong in E2 normalization and E3 paired-line qualification. |
| `raw_source`, `raw_json`, `mode`, `coverage`, `permitted_use_evidence`, `limits`, `unknowns` | Immutable payload/endpoint, explicit Synthetic/Historical/Live class, delivered scope/gaps, entitlement evidence or unknown, optional non-executable limits with declared units. No guarantee that every upstream price change was observed. |

## FairPrice and input safety

Fields: `estimate_id`, `target_venue`, `terms`, `outcome_id`, `estimated_at`, `as_of`, `mode`, `decisions`, `method`, `version`, optional `probability`, `status`, `max_receipt_age_seconds`, `freshness`, `uncertainty`.

`as_of` is the inclusive local receipt cutoff. `estimated_at` cannot precede it. E1 covers a pregame cutoff before scheduled start. Every constructor/replay recomputes contract eligibility and verifies the stored decisions:

1. Receipt after cutoff is excluded even when its source timestamp is earlier. A source timestamp after cutoff is also excluded as clock uncertainty.
2. Explicit mode must match. Receipts older than the recorded, positive age bound are excluded. This bound is a fixture input, not an operational performance gate.
3. Exact terms must match and assessed rules must be complete. This conservative E1 boundary does not approve semantically equivalent but differently assessed profiles; that requires existing pair-bound matching/settlement review.
4. Target provider/origin/family or a listed copy is excluded. Unverified family/origin/lineage is excluded.
5. Both sides must exist. Among eligible receipts of one family, latest receipt wins; receipt ID breaks an exact-time tie. Newer ineligible receipts do not displace eligible history. Duplicate receipt IDs fail rather than silently overwrite.
6. Every retained input has an inclusion/exclusion reason. No probability can be populated with zero included receipts. No unavailable estimate carries a probability.

These checks are necessary input constraints, **not a production pricing baseline**. E3 owns paired-time checks, source freshness policies, de-vig, independent-source weighting, disagreement statistics and calibrated uncertainty. E1 allows an explicitly labeled fixture-assigned probability to illustrate the schema. Missing source timestamps cannot support lag/latency claims; receipt freshness alone does not establish fresh upstream information. Entitlement verification is an E2 collection gate, not something a synthetic receipt can establish.

## Four separate signal records

Common fields: `signal_id`, canonical market, `as_of`, `mode`, `status`, `evidence_ids`, immutable `settlement_profiles_json`, explicit `settlement_assumptions`, immutable existing `fee_inputs_json`, `economics`, `limitations`. Evidence IDs bind native receipts, estimate IDs and engine audit identities as applicable. `Status` supports available, degraded, unavailable, research-only and conditional; none means realized profit or owner acceptance. Unknown economics only permit unavailable/research-only records.

| Record | Additional fields | Economic interpretation |
|---|---|---|
| `Arbitrage` | `engine_audit_json`, fixed `worst_case_net` basis | Existing detector/depth audit owns outcome-aware worst-case net cashflows. |
| `Mispricing` | `fair_price_id`, `target_venue`, signed `probability_gap`, fixed `expected_net` basis | E4 must weight complete outcome cashflows, including exceptional outcomes. A binary fair price is insufficient when other material outcomes are unresolved. |
| `LeadLag` | target, movement receipt IDs, window start/end, optional lag seconds, clock/cadence uncertainty, optional trade-value model | Movement research. No modeled total without a trade-value model; absence of timing evidence stays null. E7 adds validated target-response behavior. |
| `MakerValue` | fair-price ID, target, limit price, optional fill probability, fill assumptions, adverse selection, inventory exposure | Net value conditional on fill. Does not imply passive validity, free fees, rebate eligibility, likely fills or realized expected profit. E9 owns those models. |

`Economics` distinguishes:

- `quantity`: verified contracts, not USD stake; unknown quantity prevents final net outputs.
- `dollars_per_contract`: signed `Money(USD)` per one acquired contract under the stated scenario.
- `total_dollars`: signed `Money(USD)` over the recorded quantity/allocation.
- `roi`: dimensionless net total divided by positive `capital_denominator: Money(USD)`, with `denominator_basis` describing cash commitment, fees and reserves. Multi-leg allocations remain in the engine audit; any aggregate quantity convention must be stated in assumptions.
- `unknowns`: any unresolved material costs/outcomes force per-contract net, total net and ROI to null. A probability gap can remain available separately.

Example units: probability gap `0.12` is 12 percentage points. On a $1 binary payout it can illustrate a **gross** $0.12 price difference per contract under binary assumptions, but is not a net profit or 12% ROI. A hypothetical known $12 net on $40 cash would be ROI `0.3` (30%); this is a unit example, not this event's economic result.

The records validate shape and declared unknowns; they cannot independently establish the completeness/truth of supplied assumptions or fee contexts. E4 must populate economic unknowns from existing fee/settlement engine results and retain full audits before any net ranking. They are not a substitute for engine qualification. No new calculation is performed by constructing a signal.

## Isolated walkthrough and replay

Run from Predict:

```sh
.venv/bin/python -m app.e1_example
.venv/bin/python -m unittest tests.test_edge_contracts -v
```

The one wholly **synthetic** Atlanta/Pittsburgh NFL pregame event reuses the existing Slice 10 fixture's canonical IDs, start time, invented rules and Kalshi/Polymarket US quote contexts. It creates native `OrderBook` shapes alongside nine reference receipts. Only `ref-001` enters the illustrated Kalshi fair price `0.5200`; its method explicitly says it is assigned, not calculated. Mispricing gap `0.1200` illustrates units. PMUS settlement-fee knowledge is deliberately removed from the existing context; detector replay and all four signal records preserve unknown net economics. Lead/lag and maker records contain no implemented strategy.

`loads(dumps(bundle))` reconstructs the same immutable models, raw text, Decimal scales, source decisions and native books. The embedded detector audit also passes its existing independent replay. This file is not imported into the owner database and historical/synthetic results cannot become current live opportunities through the new contracts.
