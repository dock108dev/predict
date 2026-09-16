# E3 receipt-bound our-price baseline

E3 is a bounded **synthetic, offline** implementation. The original E1 `FairPrice` record remains readable and retains its illustrative structural policy. It is not used to calculate E3 estimates: it lacks receipt-bound enrichment knowledge and uses a different latest-eligible selection rule. E3 uses `app.pricing.baseline.Estimate` and `fair-price-bundle-1`, retaining complete `reference-bundle-1` dependencies. Neither format silently changes E1 or prediction capture records.

## Policy and calculation

Every estimate stores the entire `offline-eligibility-1` policy, including fixed method and semantics, not just a version name:

| Parameter | Offline value / meaning |
|---|---|
| Receipt freshness | Inclusive maximum age of 30 seconds at the cutoff |
| Provider-read freshness | Inclusive maximum age of 45 seconds at the cutoff; source read must also be no later than ingress |
| Pregame buffer | Unavailable at or after scheduled start minus 1 second |
| Pairing | Explicit E2 `synthetic_verified` evidence only; co-delivery is insufficient |
| Latest snapshot | Fixed E2 provider/event/book scope, ordered by exact receipt time then receipt ID, descending; before eligibility |
| Family selection | One underlying bookmaker is one family across delivery sessions; one selected snapshot, weight 1 |
| Target exclusions | Target venue appearing as provider, origin, family or any known copy; unknown lineage is ineligible |
| Arithmetic | Decimal, 50 significant digits, `ROUND_HALF_EVEN`; probabilities quantized to 18 fractional digits |
| Time arithmetic | Fixed 80-digit Decimal context; retained native source-time text determines freshness, not the microsecond projection |
| Probability basis | Conditional on an ordinary team-winner result under the assessed matched terms |

The three time bounds are explicit configurable positive integers. Other changes require a new policy implementation/version; unsupported versions or parameter changes are rejected. **These are test thresholds, not qualified live-feed settings or a latency gate.**

For paired decimal odds `a, b`, implied probabilities are `1/a, 1/b`. Normalize each by their sum. Independently, the first normalized probability is `b/(a+b)`. Thus odds `1.90, 2.1000` give `21/40 = 0.525000000000000000` and `19/40 = 0.475000000000000000`. The actual E2 fixture retains `1.90000000000000000001` and `2.1000`, yielding those same outputs after documented rounding. Reciprocal implied probabilities, implied sum and overround are preserved as Decimal strings. Both rounded probabilities must be in [0,1] and sum to one.

Original odds retain their Decimal spelling/scale; exact raw response bytes remain in the embedded E2 receipt and existing artifact table. Decimal odds mean gross return per stake. Probabilities and overround are dimensionless fractions. There is no USD gap, ROI or economic-return calculation in this package.

## Receipt, knowledge and target binding

`calculate` accepts the canonical result of `ReferenceStore.replay(cutoff)` or `records.as_of`, never detached quotes. It verifies that the entire supplied bundle is its own exact as-of reconstruction. E2 replay re-runs normalization and settlement enrichment from the saved registry, source and assessment, retaining their IDs and hashes.

Every receipt known at the cutoff gets a candidate row, including errors, one-sided pairs and arrivals without a then-known enrichment. A newer rejected arrival takes the current snapshot slot and excludes older complete pairs. Multiple sessions are delivery paths, not independent source opinions. E2's existing format is intentionally restricted to one provider/book/event, so this does not claim cross-provider ingestion or a multi-book consensus. Broadening the source format requires a later version and additional tests.

Receipt arrival, enrichment/source knowledge and effective time must satisfy the saved cutoff. Source/assessment facts must be effective at the observation's receipt; later-known facts may form a new estimate at a later cutoff. A historical snapshot's archive timestamp never substitutes for its actual download receipt. Candidate hashes cover receipt, enrichment, source, normalization registry and assessment; complete rule profiles and their retained evidence are inside dependencies. The target also stores its venue, terms, predicate/outcome, known-at/effective-at and explicitly synthetic evidence.

At initial persistence, the store compares the saved dependency bundle against the complete current reference as-of reconstruction while holding reference-table locks. This prevents a caller from dropping the latest invalid arrival or other excluded candidates. It then verifies each durable dependency exactly. A persisted estimate is content-addressed, immutable and independently recomputed; subsequent knowledge cannot rewrite it.

## Settlement and availability

Target/source profiles pass the existing settlement comparator across overtime, tie, void/cancellation, refund and every supported exceptional scenario. Different target identities, schedules, periods, phases, outcomes or material rules remain ineligible. The existing settlement payout interface records both ordinary and exceptional target cashflows. A refund remains a cost-dependent refund symbol.

| Status | Exact E3 meaning |
|---|---|
| `degraded` | An eligible single-family pair supplies conditional team-winner probabilities. Diversity is limited, inputs are synthetic, the method is uncalibrated and exceptional probability mass is unknown. |
| `unavailable` | No eligible current pair, unsupported target terms or pregame cutoff reached. Conditional probability and calculation are null; individual exclusions remain available. |
| `available` | Intentionally unreachable under this one-family synthetic policy. E3 never upgrades the result to full evidence adequacy. |

`conditional_target_probability` supports the target's `win` or `not_win` predicate within the normal-winner conditioning set only. `unconditional_target_probability`, `target_fair_value_usd`, exceptional scenario probabilities and `net_expected_profit` remain null. The original synthetic fixture assigns 0.5 payouts to exceptional scenarios; these are invented rule assumptions, not evidence that their probability is zero or that any real venue uses those rules. Separate matched-refund and incompatible-refund cases are tested.

One family cannot supply an independent-source disagreement statistic. No learned weights, calibrated confidence, statistical uncertainty or source-change latency is invented. Provider last-read time is retained separately from unknown bookmaker change time. De-vigging does not remove prediction trading fees or establish net expected profit.

## Durable format and replay

Migration `005_fair_price.sql` adds `fair_price` and `fair_price_input`. The parent contains the canonical, content-hashed full estimate; input rows link **all considered receipts**, including exclusions, to existing receipt/source/enrichment records. SQL triggers reject updates/deletes. The existing Store provides atomic immutable inserts; caller-supplied explicit connections are required.

Export/restore order for a fresh store:

1. Apply current migrations using an explicitly authorized disposable connection.
2. Restore the full `reference-bundle-1` with `ReferenceStore.restore`.
3. Restore each `fair-price-bundle-1` with `FairPriceStore.restore`.
4. Read/export the durable record, validate every link and recompute from its saved dependencies; compare canonical bytes.

`recompute` and `restore` use only retained dependencies, never today's aliases/rules. Full reference exports preserve later observations too; each estimate's embedded snapshot preserves only information known at its own cutoff. Version, hash, parameters, decisions and numeric output must all match. Existing `edge-contracts-1`, `reference-bundle-1` and pre-E2/E2 `capture-bundle-1` remain readable. Capture migration compatibility now accepts only exact known migration prefixes, preserving original migration hashes.

Runnable verification:

```sh
.venv/bin/python -m unittest tests.test_pricing tests.test_reference tests.test_edge_contracts -v
.venv/bin/python -m app.pricing.verify_storage
```

The second command creates, identity-checks, restarts and removes its own socket-only PostgreSQL cluster. It does not use the owner connection helper. It writes new E3 evidence; existing E2 evidence is read-only. No provider request, live qualification, owner service change or E4 economics is performed.
