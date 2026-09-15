# Slice 11 offline depth results

321 offline tests and all eleven examples passed. All prices and payout rules in the table below are invented; actual versioned Kalshi/PMUS fees are used. Fee and fill-partition conditions prevent these from becoming current production opportunities.

| Synthetic case | Profit-max quantities | Worst modeled profit | ROI-max quantities | Deployment-max quantities | Search |
|---|---|---:|---|---|---|
| shrinking-edge-and-distinct-objectives | 3 / 3 | 1.7300 | 3 / 3 | 6 / 6 | proven-optimal-within-supplied-grid-and-fill-model |
| unequal-improves-with-incompatible-grids | 4 / 3 | 1.5200 | 4 / 3 | 6 / 6 | proven-optimal-within-supplied-grid-and-fill-model |
| fractional-final-level | 4.00 / 4 | 1.740000 | 1.00 / 1 | 4.00 / 4 | proven-optimal-within-supplied-grid-and-fill-model |
| order-grouped-rounding | 1 / 1 | 0.0600 | 1 / 1 | 2 / 2 | proven-optimal-within-supplied-grid-and-fill-model |
| partial-depth-binding-cash | 3 / 3 | 1.7300 | 3 / 3 | 3 / 3 | proven-optimal-within-supplied-grid-and-fill-model |
| unknown-fees | 0 / 0 | 0 | 0 / 0 | 0 / 0 | objective-unresolved-material-cashflows-unknown |
| unknown-settlement-conditional-sizing | 0 / 0 | 0 | 0 / 0 | 0 / 0 | objective-unresolved-material-cashflows-unknown |
| multi-level-refund | 2 / 3 | 0.8400 | 2 / 3 | 7 / 7 | proven-optimal-within-supplied-grid-and-fill-model |
| nonmonotonic-roi-from-rounding | 4 / 4 | 1.5100 | 3 / 3 | 4 / 4 | proven-optimal-within-supplied-grid-and-fill-model |
| exceptional-outcome-loss | 0 / 0 | 0 | 0 / 0 | 0 / 0 | proven-optimal-within-supplied-grid-and-fill-model |
| no-profitable-allocation | 0 / 0 | 0 | 0 / 0 | 0 / 0 | proven-optimal-within-supplied-grid-and-fill-model |
| search-budget-exhausted | 3 / 3 | 1.7300 | 3 / 3 | 8 / 8 | best-found-search-limit |

Zero shown for unresolved objectives is the no-trade fallback, not a proof that positive quantities lose. The separate minimum-known diagnostic remains available. Deployment is total required cash, and the first scenario requires at least 10% modeled ROI. All objectives use the same cash constraints within each scenario.

## Equal-quantity depth curve: shrinking edge

| Quantity per leg | Required cash | Worst modeled profit | ROI |
|---:|---:|---:|---:|
| 0 | 0 | 0 | undefined |
| 1 | 0.4300 | 0.5700 | 1.3255813953 |
| 2 | 0.8500 | 1.1500 | 1.3529411764 |
| 3 | 1.2700 | 1.7300 | 1.3622047244 |
| 4 | 2.590000 | 1.410000 | 0.5444015444 |
| 5 | 3.930000 | 1.070000 | 0.2722646310 |
| 6 | 5.260000 | 0.740000 | 0.1406844106 |
| 7 | 6.580000 | 0.420000 | 0.0638297872 |
| 8 | 7.920000 | 0.080000 | 0.0101010101 |
| 9 | 9.240000 | -0.240000 | -0.025974025 |
| 10 | 10.570000 | -0.570000 | -0.053926206 |

ROI display is shortened; complete Decimal values are in the JSON. These are evaluated points, not a monotonic interpolation. The top screen sees only three contracts at .20 on each leg. It agrees with the 3/3 depth result; additional depth eventually loses money.

## Unequal quantity arithmetic

The incompatible 2-contract / 3-contract grids select 4/3: $1.40 acquisition cost, $0.05 Kalshi fee and $0.03 PMUS fee. Normal terminal profits are $2.52 and $1.52; half-payout exceptional outcomes return $3.50, producing $2.02. The worst of all outcomes is $1.52. The complete common-grid equal baseline is evaluated independently.

## Fill assumptions and unknowns

Each leg is one new taker order, with one assumed fill per consumed price level in ascending price order. Actual fragmentation can change rounded fees, so no fragmentation-independent conservative bound or guaranteed profit is claimed. Fee audits retain grouping, order accumulators, credits, schedule versions and source snapshots. Refunds use exact entry cost; unknown settlement and fees remain null.

The explicit fractional allocation consumes 1.25 contracts at .20 and .75 at .40 on its Kalshi leg, for exactly $0.55. The partial-depth cash scenario limits total cash to $1.70 and the left venue to $0.70. The unconstrained maximum deployment exceeds those inputs; the constrained result uses only supplied liquidity.

The [grouping comparison](fee-grouping-comparison.json) independently records $0.04 PMUS fees for one order versus $0.05 for two separate orders, using the same .50 × 1 and .60 × 2 acquisitions. Both are explicit hypothetical partitions; the main sizing model uses one order.

## Retained production evidence

10 structural pairs remain settlement-UNKNOWN; 20 related candidate combinations, 0 qualified current opportunities. There are 1 two-ask diagnostics, with sums: 1.0100. Missing books, verified units, reconstruction, fee contexts and sizing rules are not fabricated.

Related candidates share liquidity: never sum their capacities. Actual-fill reconciliation remains unverified. No new collection, account activity or settlement research occurred.

## Handoff

Next action: **Slice 12 — PostgreSQL historical capture**. Stop before Slice 12.
