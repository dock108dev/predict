# E3 handoff — bounded offline our-price baseline

September 15, 2026. **Prepared only; E3 is not implemented or started.** E2's [offline implementation report](e2-implementation-report.md) and [source qualification](e2-source-qualification.md) are the prerequisites. Neither The Odds API nor Pinnacle is qualified for live fair-price inputs.

## One concrete next action

After separate authorization, implement an **offline, target-specific proportional de-vig baseline for the same synthetic NFL pregame event**, consuming the receipt-bound E2 replay output. Produce one explainable, versioned synthetic estimate and exact persisted replay. No provider account or owner input is needed for that offline scope.

## Inputs and boundaries

- Read the Desktop tracker, roadmap, E1 contracts, E2 report and qualification first. Preserve the existing uncommitted candidate and evidence. E2's exact identity is in its report and `evidence/e2/implementation/candidate-implementation.json`.
- Use `ReferenceStore.replay(cutoff)` / `records.as_of`, not raw `ReferenceQuote` objects divorced from their enrichment/source records. The latter do not carry enrichment knowledge times in the E1 schema.
- `reference-bundle-1` preserves all arrivals, immutable source revisions, mapping registries, rule profiles, pairing evidence and gaps. Replay recomputes enrichment using the saved registry and assessment. All fixture data and positive knowledge are explicitly synthetic.
- Select the latest snapshot per source/event as known at the cutoff before eligibility checks. A newer one-sided/rejected observation must not be bypassed by falling back to a stale complete pair. E1's structural family selection is not this E3 current-snapshot policy.
- Apply both local receipt and knowledge cutoffs. Keep effective times distinct from known-at times. Historical download receipts cannot be backdated to the archived snapshot. Later source, alias or rule revisions cannot alter an already persisted estimate.
- The same bookmaker through multiple providers is one information family. Exclude the target venue and its known copies. Unknown family/copy lineage remains ineligible.
- Check exact target terms using the existing settlement interfaces, including tie, overtime, void/refund and exceptional outcomes. Two moneyline prices alone do not establish compatible binary payout probabilities.
- Enforce assessed pairing, source/receipt freshness and pregame timing. Market `last_update` means provider last-read; side times and upstream synchronization remain unknown in unassessed inputs. The E2 synthetic pair marker is an invented test assumption and cannot qualify live input.

## Bounded implementation and evidence

1. Define a versioned E3 policy for freshness, source-family selection, pairing and exclusions. Record its complete parameters rather than invent a confidence score.
2. For eligible synthetic paired decimal odds, calculate exact Decimal implied probabilities and proportional margin removal. Explicitly document Decimal precision/rounding and output units. Preserve the original odds and their text scale.
3. Use a transparent one-family baseline. Report insufficient diversity and other supported limitations; do not invent independent sources, calibrated uncertainty or learned weights.
4. Add `fair_price` and input-link persistence only in that authorized E3 package, with receipt/enrichment/source/rule hashes, considered and excluded inputs, policy/version, target, as-of and estimated-at times. Enforce dependency cutoffs before persistence.
5. Test complete/missing/invalid/stale pairs, unknown pairing/lineage/rules, target copies, duplicate delivery paths, newer invalid snapshots, late receipts and later-known corrections. Prove deterministic calculations, valid probabilities, explicit unavailable/degraded states and byte-exact fresh-store replay.
6. If durable checks are authorized, create and identity-check another disposable socket-only PostgreSQL cluster and remove it afterward. The E2 cluster has already been removed. Do not use the owner database or its service.

## Separate future live qualification

Account entitlement, actual event identity and delivery, upstream pairing, copy lineage, source-to-target rules, permitted scope and owner-selected game/session/cost bounds remain unverified. Documentation qualification and synthetic engineering success do not answer them. No signup, credentials, subscription, outreach or provider requests are part of this handoff.

Stop after the bounded E3 implementation/report if subsequently authorized. E4 net economics, UI work, sustained live collection, lead/lag, maker models, trading and publishing remain separate. Keep the former 250 ms gate deferred.
