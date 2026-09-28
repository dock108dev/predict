# Sport and market integration

The shared projection supports MLB/NHL sporting results separately from venue payouts, cumulative baseball 3/5/6/regulation 9 and individual hockey period W/S/T, current-season conference/league championship fields and pending outcomes, systematic current college membership, shared equality/fractional payouts and bounded saved-history loading. Existing six-sport winners/lines, football/basketball H1, references, fee/depth engines, Details, filtering and Stop paths remain shared.

Implementation entry points: [resolution dispatch](../app/resolution/core.py), [MLB/NHL validation](../app/resolution/diamond_ice.py), [championship results](../app/resolution/championship.py), [period descriptors](../app/normalization/score_periods.py), [futures descriptors](../app/normalization/futures.py), [college registry](../app/normalization/college_registry.py), [shared score payouts](../app/normalization/score_lines.py), [ordinary projection](../app/dashboard/session_projection.py), [saved history](../app/dashboard/session_history.py). Focused regression modules are `test_diamond_ice_resolution`, `test_periods`, `test_futures`, `test_college_expansion` and `test_payout_extensions`; the existing CI script includes them.

Unknown native rules, quantities, fees, exceptional probabilities and payouts remain unavailable/conditional. Actual listings/models/results, ternary purchase and cross-strike tie bindings, amended hockey winner-period terms, FCS-only contracts, pitcher changes and refund/fair-value economics still need specific source evidence. Current college membership does not establish native venue aliases. Fixtures and public documents never qualify production data.


These implemented handlers do not establish live venue coverage or release
acceptance. See the [coverage matrix](coverage-matrix.md) for source-specific
gaps. Candidate-specific counts, identities and original results are retained in
the [engineering record](history/maintenance-20260928/sports-integration.md).
