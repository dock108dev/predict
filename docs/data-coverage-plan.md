# Delivery plan

Predict is not ready for beta signoff. The [product definition](product-roadmap-review.md)
sets the required scope. This plan describes implementation status; real collection requires a run-specific specification and approval.

## What works

The shared dashboard, collection, Stop, saved history and calculations have been
verified with offline fixtures. Implemented market support covers six sports,
full-game winners and lines, selected partial periods, championship futures, and
separate sporting results and venue settlement. The integrated offline workload
completed ten bounded segments totaling approximately 30 minutes.

These checks establish software behavior. Actual source coverage and owner
acceptance remain open.

## Remaining work

| Area | Current gap | Next action |
| --- | --- | --- |
| Prediction venues | Novig and ProphetX production access and native data remain unqualified; provider replies are pending | Review issued access and exact native fields, then prepare a bounded qualification run |
| Fees and settlement | Historical Kalshi rule/fee priority and Polymarket US contract applicability or additional mandatory charges remain unresolved | Evaluate authoritative exchange replies against the exact contracts and observation dates |
| References | One historical NFL Pinnacle sample is retained; broader coverage, delay and independent model outputs remain unqualified | Establish supported, dated inputs and map them to the same markets as the prediction observations |
| Sport and market coverage | Software support exists; actual listings, rules, quantities, fees and forecasts still need verification | Qualify native inputs through the existing shared product paths |
| Integrated operation | Offline behavior is verified; useful joint operation with all required sources is not | Define a real session from supported coverage, cadence and resource limits |
| Owner review | No beta acceptance recorded | Present the working product after the required source and market checks are complete |

KenPom and NHL analytics are deferred. MoneyPuck is dropped. No replacement search
is queued. Second-half markets offered at halftime and live/in-play remain stretch
work. Unknown inputs stay visible; negative, zero and unavailable results are valid.

## Current handoff

The September 23 public investigation and supported engineering are complete.
The Polymarket US rule hierarchy is established, while historical applicability
and mandatory-charge gaps remain. All four retained net comparisons remain
unavailable. Earlier failed attempts and missing historical state/clock evidence
remain recorded; they are not new research targets.

The next dependency is authoritative exchange evidence. Prepared inquiries remain
unsent, no further acquisition package is queued, and the monitoring automation is
paused. Public research authorization does not authorize provider outreach or a
new book collection.

## Details and evidence

- [Coverage matrix](coverage-matrix.md) and [market data gaps](market-data-gaps.md)
- [Venue integration](native-integration.md) and [access status](venue-access-status.md)
- [Reference integration](reference-integration.md) and [source contracts](reference-source-contracts.md)
- [Sports integration](sports-integration.md) and [offline validation](offline-integration.md)
- [Public research handoff](public-research-handoff.md)
- [Retained public investigation](../evidence/b6-native-review-20260923-v7/review.md)
