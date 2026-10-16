# Sport and market integration

The normalization and retained-session engines support sporting results and
market structures beyond the ordinary NFL comparison board. Sporting scores stay
separate from venue settlement: a final result alone cannot establish a contract's
payout, fees or refund terms.

| Area | Implemented scope | Entry points |
| --- | --- | --- |
| Game markets | NFL, NCAAF, NBA, NCAAB, MLB and NHL winners, spreads and totals; football/basketball first half | [Score payouts](../app/normalization/score_lines.py), [resolution dispatch](../app/resolution/core.py) |
| Baseball and hockey | Explicit MLB/NHL score and completion validation; baseball first 3/5/6 and regulation 9 innings; individual hockey periods | [Result validation](../app/resolution/diamond_ice.py), [period descriptors](../app/normalization/score_periods.py) |
| Championships | Explicit conference/league championship fields, pending results and state tables | [Futures descriptors](../app/normalization/futures.py), [championship results](../app/resolution/championship.py) |
| College membership | Canonical entities, conference membership and scoped event validation | [College registry](../app/normalization/college_registry.py) |
| Retained sessions | Shared projection, bounded history, filtering and selected Details | [Projection](../app/dashboard/session_projection.py), [saved history](../app/dashboard/session_history.py) |

Resolution and championship validation are bounded to the declared seasons in
source: 2026 for NFL/NCAAF/MLB and 2026–2027 for NBA/NCAAB/NHL. They do not
automatically roll forward to a new season. College membership alone does not
establish native venue aliases.

Unknown native rules, quantities, fees, exceptional probabilities and payouts
remain unavailable or conditional. Actual listings, models and results require
their own exact source inputs. Ternary purchase, cross-strike tie bindings, amended
hockey winner-period terms, FCS-only contracts, pitcher changes and refund/fair-value
economics have separate unresolved dependencies. Fixtures and public documents do
not establish present provider coverage.

Focused regression modules include `test_diamond_ice_resolution`, `test_periods`,
`test_futures`, `test_college_expansion` and `test_payout_extensions`, registered in
`scripts/ci/suites.json`. See [data limitations](market-data-gaps.md) for the ordinary
application's narrower scope and [development](development.md) for test commands.
