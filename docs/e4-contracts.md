# E4 — bounded offline shared Arb/Mispricing service

`offline-opportunities-1`, exported as `opportunity-bundle-1`. This service supports the existing **synthetic NFL pregame moneyline event**, Kalshi and Polymarket US taker acquisition books. No network, execution, UI or owner-database entry point is added.

## Dependency and time boundary

`OpportunityStore.evaluate(estimate_id, inputs)` reads and replays a persisted E3 estimate, calculates both signals, and saves their complete immutable audit atomically. The pure `service.evaluate(inputs)` entry supports offline tests/recomputation; it validates the embedded E3 export but does not itself assert durable persistence.

Inputs retain the exact E3 export and reference history; native event/market matching envelopes; identified synthetic book receipts, raw source text, normalized acquisition levels and transformation; full fee registry and venue/product/account context; explicit sizing; model (or null); policy; receipt cutoff and evaluation time. Every top-level input has a content hash and durable dependency link. Book identities separately hash their observations, levels, timing and provenance. Reference prices cannot enter executable books.

An explicit synthetic knowledge/effective receipt binds the market metadata, rules and fee context snapshot. Nested receipt/review/retrieval times must not exceed the cutoff. Book receipts and estimate creation must already be known. Later knowledge forms a new immutable input/result; it cannot rewrite a saved result. Missing, changed, late or mismatched dependencies are rejected. Matching is refreshed from the saved envelopes; target rules are looked up using the detector's **exact market revision hashes**, never by whichever retained revision appears last.

Policy is fully retained and fixed for version 1: Decimal precision 100 with half-even arithmetic; maximum book receipt/snapshot age 30 seconds inclusive; maximum inter-book receipt skew 5 seconds; estimate age 30 seconds; pregame cutoff one second before kickoff. These are synthetic test thresholds. The deferred 250 ms performance gate remains deferred.

## Economics and statuses

Both outputs use one declared positive quantity of $1 payout contracts. Arb acquires that quantity on each leg; Mispricing acquires it on the estimate's target leg. The existing finite depth search remains available in the full audit, but headline economics use the explicit quantity rather than a zero-trade optimizer result. Invalid increments, minimums, depth or unknown quantity produce unavailable economics with reasons.

| Output | Calculation | Denominator |
|---|---|---|
| Arb | Minimum of summed state-specific net cashflows over **all** material outcomes, with the existing separately consumed execution reserve | Both legs' entry cash plus reserve |
| Mispricing | Sum of unconditional state probability × target-leg net cashflow | Target-leg entry cash requirement |

Each result records total USD, USD per declared contract quantity, return as a fraction, and its exact USD denominator. For Arb, per-contract means per equal-quantity two-leg unit; it does not divide by the sum of both leg quantities. A probability-minus-top-ask gap is a dimensionless conditional diagnostic, never net dollars or ROI.

Existing settlement, fee and depth engines retain fee applicability, state payouts, refunds, fees, credits, raw rounding and grouping traces, consumed levels, usable depth, cash requirements, conditional calculations and qualification reasons. Depth impact is already included in walked acquisition prices; no extra impact deduction is made. Kalshi order rounding refunds remain distinct from maker rebates. PMUS uses the existing US schedule and explicit settlement-fee assumption. No maker exemption, maker rebate, international schedule or actual fill guarantee is inferred.

- **Conditional:** all inputs necessary for the displayed modeled number are present. It remains wholly synthetic and conditional on the specified fill partition, fee assumptions and settlement. Negative results remain displayed.
- **Unavailable:** material economics or eligibility are unsupported. Null is retained along with precise reasons, state cashflows, known-outcome diagnostics and any conditional calculation.
- `current_production_opportunity` is always false. Existing engine qualification reasons remain separate from arithmetic availability.

E3's conditional probabilities do not enter Arb. With no separate scenario model, Mispricing always retains E3's unknown exceptional mass, unconditional target value and expected profit. E3's saved export is unchanged, including exclusions and reasons.

## Explicitly invented scenario models

`invented-unconditional-scenarios-1` binds the exact target hash and enumerated payout hash. It records its own name, content identity, knowledge/effective times and synthetic evidence. The fixture explicitly assumes disjoint final settlement paths: one normal winner or one named exceptional resolution, exhaustive by invention. These categories are **not empirical event probabilities**.

A complete model supplies a finite [0,1] Decimal probability for each of the two normal winners and seven exceptional paths, totaling exactly one. Extra outcomes, invalid probabilities, excess mass, unsupported versions, wrong target/payout dependencies or a claimed value inconsistent with the payout-weighted probabilities are rejected. Missing states, null probabilities or missing mass leave expected economics unavailable. An unknown material payout or fee remains unknown even when its model probability is zero.

The test model invents ATL 0.60, PIT 0.33 and 0.01 for each exceptional path. Under the existing invented 0.5 exceptional payout, target value is **0.635 USD per contract**. This is an independent fixture, not a completion or correction of the saved E3 0.525/0.475 estimate. Refunds use acquisition-cost cashflows rather than a fabricated fixed payout fraction.

## Ranking and shared liquidity

`rank(audits)` recomputes each audit, deduplicates exact audit IDs, and forms separate lists by signal class, event, cutoff, contract quantity and model identity. Within each list it sorts supported conditional total net USD descending with audit-ID tie breaking. Unavailable rows remain in a separate explicit list with reasons. Expected and worst-case returns are never combined.

Every row retains venue event liquidity families. Different models/prices/strategies using the same books are alternatives. `aggregate_attainable_profit_usd` is always null. This package does not allocate a portfolio or sum overlapping scenarios.

## Durable restore order and compatibility

Migration `006_opportunities.sql` adds immutable `opportunity_dependency`, `opportunity_audit` and `opportunity_input` tables, foreign keys and mutation-rejection triggers. It leaves the existing capture/reference/pricing formats unchanged.

1. Apply migrations through an explicitly authorized connection.
2. Restore the full `reference-bundle-1` and all required `fair-price-bundle-1` estimates.
3. Restore `opportunity-bundle-1` exports. Saving requires the exact durable E3 record and its linked reference dependencies.
4. Read and verify every durable dependency/link, export, and recompute using the retained inputs. Compare exact canonical bytes.

Version 1 exports include complete input values; restore materializes their immutable content-addressed objects and links. Existing E1, reference, fair-price, and pre-E2/E2/E3 capture exports retain their original meanings and hashes. Capture compatibility accepts only exact known migration prefixes.

## Bounded limitations

One event, one target leg per audit, explicit equal Arb quantities, one modeled taker order per leg and one fill per consumed level. Both candidate ladders are required for this shared evaluation; an unsized companion leg conservatively makes both headline results unavailable. Broader independent single-leg execution evaluation and portfolio sizing are outside this package. No calibrated probabilities, live source qualification, observed fill partition, empirical exceptional mass, attainable profitability, owner acceptance or release acceptance is established.
