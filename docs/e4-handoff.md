# E4 handoff — bounded offline net opportunity service

September 15, 2026. **Prepared only; E4 has not started.** Read the Desktop tracker, roadmap, [E3 report](e3-report.md), [E3 contracts](e3-contracts.md), original E1 contracts and existing settlement, fee, detector, sizing and capture interfaces first. Preserve the uncommitted E1–E3 candidate and evidence. Neither reference provider is live-qualified.

## One concrete next action

After separate authorization, implement **one offline shared Arb/Mispricing service for the existing synthetic NFL event**, consuming the persisted E3 estimate and existing prediction-market fixture books. Reuse existing settlement/fee/depth calculations and save an explainable, exactly replayable result for each signal class.

### Required boundary

- Use the exact E3 candidate and durable estimate IDs from `evidence/e3/candidate-implementation.json` and `evidence/e3/durable/storage-verification.json`. Recheck working-tree identity before implementation.
- E3's roughly 0.525/0.475 values are **conditional on a normal team-winner result**. Do not insert them as unconditional payout probabilities. Exceptional mass, target fair value and net expected profit are null. Single-family and synthetic limitations must survive into E4 results.
- For Mispricing, enumerate exact outcome cashflows with the existing settlement interface. Missing unconditional scenario probabilities, fee context or verified quantity must produce unavailable net economics with precise reasons. A diagnostic probability gap is not net profit or ROI.
- A positive expected-value fixture, if useful, must introduce separately identified and explicitly invented complete scenario probabilities and cost/quantity assumptions; never rewrite or silently complete E3's saved record. Such a fixture is engineering evidence only.
- For Arb, use the existing detector/depth outcome audit and worst-case result. Do not substitute a model probability or expected return for modeled worst-case net profit. Preserve fill/settlement qualification and unknowns.
- Use venue/product/account/order-role fee schedules, exact Decimal rounding/grouping and quantity units. Do not assume maker fees/rebates or apply international Polymarket economics to Polymarket US. Avoid double-counting book impact already represented by depth walking.
- Keep Arb and Mispricing results separate and ranked only by supported net values within each class. Record dollars per contract, total dollars and return on a stated capital denominator separately.

### Enough to complete that future package

One synthetic event flows through saved E3 dependency replay plus existing prediction books into both service outputs, immutable saved audits and exact fresh-store replay. Test known/unknown/negative economics, exceptional outcomes, fee rounding, shared-liquidity sizing and late-knowledge exclusions. Unavailable Mispricing due to unsupported outcome mass is a correct result; profitable opportunities are not a completion requirement.

Durable checks would require a separately authorized newly created identity-checked disposable PostgreSQL cluster, followed by cleanup. Never access the owner database by default. Report exact candidate identity and engineering evidence separately from live-source qualification, calibration, owner acceptance or release.

Stop after the authorized E4 package if subsequently requested. No current authorization for E4 implementation, provider requests, credentials, subscription, outreach, owner data/services, UI expansion, sustained collection, trading, commits, push or publishing. The deferred 250 ms gate stays deferred.
