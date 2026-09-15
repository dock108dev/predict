# Slice 10 — top-of-book arbitrage detection

Completed September 12, 2026 UTC. Detector `top-of-book-1`.
**Next: Slice 11 — full-depth arbitrage calculation and sizing. Stop before Slice 11.**

The finite offline detector consumes current Slice 7 event decisions and Slice 8
moneyline decisions, adapter acquisition asks, and the Slice 9 fee engine. Ten
production structural pairs remain settlement-UNKNOWN. They produce 20 candidate
leg combinations, not 20 independent liquidity opportunities. Zero production
opportunities qualify. No onboarding or new settlement/fee research was performed.

## Results and coverage

The output distinguishes three results for every supported exposure relationship:

1. A pricing diagnostic retains native identities, instrument and event liquidity
   families, source-body hashes, original receipt/source times, asks and visible
   quantities. Its `1 - ask_sum` is explicitly a $1 reference gap, not a payout promise.
2. A conditional calculation retains every matcher-supplied material outcome,
   acquisition cost, entry fees, cash requirement, separate fee-engine credits,
   outcome charges, net payouts, profit and cash-denominated ROI. Missing inputs
   remain null with reasons. All fee audits and their registry snapshots survive.
3. Qualified modeled arbitrage requires current confirmed matching, supported
   complementary payouts, eligible observations and quantities, documented-scenario
   fee results, and strictly positive profit in every material outcome. It assumes
   both new orders fill once at the stated prices; it promises neither fills nor
   actual profit. Historical and synthetic results cannot become current opportunities.

[Readable report](../evidence/slice-10/report.md),
[complete detector example](../evidence/slice-10/detector-example.json).

Historical coverage uses the actual Slice 4 ATL/PIT Kalshi book and the first
retained Slice 2 authenticated images for ATL/PIT, BAL/IND and CHI/CAR. Those
images alone do not replay subscription recovery, so their reconstruction remains
unknown. No historical books were invented for missing markets. One candidate
has both asks: Kalshi Pittsburgh YES .7100 plus PMUS Atlanta long .3000 = 1.0100.
Their receipt skew is 6194.036398 seconds. It has no raw pricing edge and also lacks
qualification evidence. Other candidates retain one-sided or absent-book diagnostics.
All captures remain historical even at a caller-selected replay time.

The 12 synthetic demonstrations include positive, zero, negative, fee-erased gap,
exceptional loss, unknown fees, unavailable size, stale receipt, skew, inactive
market, duplicate liquidity and maker-dependent cases. The positive real-fee-model
scenario has $16.88 conditional worst-case profit on $83.12 required cash at 100
contracts. Existing Kalshi account/effective-date conditions and PMUS settlement
fee assumptions still prevent qualification; they are not overridden to manufacture
a synthetic qualified fee integration. A separate **test-only zero-fee stub** tests
the positive qualification branch and synthetic isolation. It is not used by the
example or production detector and is not evidence about venue fees.

## API and policies

```python
from datetime import datetime, timezone
from app.arbitrage import detect, Policy, book_observations
from app.arbitrage_example import synthetic_inputs

parents, matcher, observations, fee_templates, _ = synthetic_inputs()
result = detect(
    parents, matcher, observations, fee_templates,
    evaluation_time=datetime(2026, 9, 12, 2, tzinfo=timezone.utc),
    fill_grouping='single_fill_per_leg',
    policy=Policy(max_receipt_age_seconds='30',
                  max_observation_skew_seconds='5'),
)
```

`detect` calls `matcher.report(parents)` every time. Cached pair IDs or dictionaries
cannot substitute for current Matcher objects. Returned pair revisions, market
hashes and parent snapshot hashes bind the result to its exact decision inputs.
Rule/parent revisions withdraw or re-evaluate eligibility. Matcher decision history
may advance in memory; the detector does not save or mutate persisted stores.

Observations wrap immutable shared `Quote` objects with explicit environment,
evidence class, reconstruction/depth, locks, clock semantics and economic sizing
facts. `book_observations` uses the existing Kalshi quote transformation and only
native supplied asks elsewhere. PMUS short-side asks remain unavailable because
the current adapter does not transform long bids into short acquisitions. Bids
are never simply treated as ask prices. Only cross-venue opposing outcomes,
opposite predicates or proven complementary relationships are enumerated; opposing
team names alone never establish settlement complementarity.

The default policy is a **local screening policy, not an empirically qualified
latency budget**:

| Check | Default and interpretation |
|---|---|
| Receipt age | At most 30 seconds; future receipts fail |
| Cross-leg receipt skew | At most 5 seconds |
| Source snapshot age | At most 30 seconds, only with snapshot-clock semantics |
| Last-change source time | Old quiet-book timestamps do not imply disconnection |
| Source problems | Missing/unknown semantics, regression, future source clocks and supplied sticky problems remain reasons |
| State and locks | ACTIVE and explicit `locks_clear=True` |
| Reconstruction/depth | Synchronized adapter image and partial/full observed depth |
| Production scope | Explicit production environment and compatible evidence class |
| Reporting thresholds | Minimum after-fee profit and ROI default to zero; positive profit still required |
| Execution reserve | Defaults to zero; separate cash reserved and conservatively consumed in every outcome, never a venue fee |

All age/skew limits are inclusive. Evaluation time must be timezone-aware and is
caller-supplied; no wall clock or network access occurs. Source age is never called
transport latency. The stateless caller must carry any known upstream clock problem
in `source_time_problem`; a new receipt or reconnect does not waive it. Unknown
lock/status facts fail closed; callers must not treat their absence as clearance.

## Quantity, fees and precision

Without `quantity`, select the largest equal quantity on the common increment grid
that fits both visible tops and both minimums. Increments are multiples from zero;
minimums are lower bounds. Rational-grid LCM uses exact Decimal/integer arithmetic
and rounds down. Missing visible size, units, increments or sizing evidence produces
an unsized diagnostic. Zero available size is distinct from unknown size.

An explicitly supplied positive `quantity` is a hypothetical count of $1 payout
contracts. It may calculate despite unknown sizing or exceed visible capacity, but
those reasons prevent qualification. Verified contracts are supported; verified
Novig payout cents convert by .01. Unknown/native stake units are not inferred.
ProphetX's native conversion remains unsupported by the fee engine. Current native
market matching only supports the established Kalshi/PMUS full-game NFL mappings.

Fee templates are keyed by `(native_market_key, native_side)`. They must supply
venue, environment, native market, product and the applicable schedule/account
context. The detector verifies identity and supplies trade/calculation time from
`evaluation_time`, outcome fractions from the current matcher, quantity and ask
price. Refund outcomes use acquisition cost as the refunded amount; unknown or
discretionary payouts remain unknown. Fee templates cannot contain fills or market
cashflows: these would conflict with the modeled new acquisitions.

`fill_grouping='single_fill_per_leg'` explicitly models one fill for each new order,
with no prior order history. Without this assertion no fee calculation is made.
There is no invented fragmentation and no real-fill reconciliation claim. Fee
engine conditional/unsupported results retain every reason and cannot qualify.
Immediate rounding credits affect the engine's entry debit/cash amounts according
to its timing rules; deferred credits are preserved but do not fund acquisition or
profit. Account assumptions are not silently classified as verified.

`worst_case_profit` and its ROI are null if any material outcome is unknown.
`minimum_known_profit` separately preserves unfavorable known outcomes even then.
ROI uses total required entry cash plus the separately disclosed reserve; a
nonpositive or unknown denominator gives null ROI. Known zero/negative profits
and ROIs are retained and classified as no net edge. Threshold filters never hide
pricing diagnostics or change modeled economics.

A fresh 100-digit Decimal context isolates detector and matcher arithmetic from
caller precision, rounding and traps. Numeric inputs follow the fee engine's
24-significant-digit/12-decimal-place bound. No float monetary inputs are accepted.
Candidate IDs derive from sorted scoped native market/side identities, not prices
or timestamps. Exact duplicate observations collapse; conflicting variants fail
closed instead of selecting favorable prices. Related native listings retain shared
liquidity families and must never be summed as independent capacity.

Equal quantities can miss profitable unequal allocations when fees differ.
Deeper levels, unequal sizing, streaming scans, execution, databases, dashboards
and historical analytics remain outside this slice.

## Verification and preservation

Run from the repository root:

```sh
.venv/bin/python -m app.arbitrage_example
.venv/bin/python evidence/slice-10/verify.py
```

The final verification includes the complete existing suite, 40 new detector tests,
all nine existing examples and the new detector example. Financial oracles use
independent literal arithmetic; the $16.88 gain, fee-erased loss and exceptional
loss are not generated by the detector as expected values. Tests exercise ask
selection, quantity grids/units, unknowns, ROI/denominators, fees, clock boundaries,
status/locks/sync, scope, deduplication, precision and current parent/rule revisions.

[Verification logs](../evidence/slice-10/verification.json),
[preservation comparison](../evidence/slice-10/preservation.json),
[artifact manifest](../evidence/slice-10/manifest.json).
PLAN.md, prior code/tests, credentials and historical evidence are preserved.
Credentials were neither read nor changed. No dependencies, accounts, live requests,
orders, balances/history, funds, purchases, outreach, commits, pushes or publishing
were involved. README and the Desktop tracker are updated.
