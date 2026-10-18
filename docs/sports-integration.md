# Sport and market integration

The current native comparison pipeline supports NFL, NCAAF, NBA, NCAAB, MLB
and NHL winner/moneyline, spread and total contracts when their source facts
establish the required meaning. The default sample selects NFL; configuration
can select other supported leagues. Normalization and retained-session engines
also support additional sporting results and market structures. Sporting scores stay
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
`scripts/ci/suites.json`. See [data limitations](market-data-gaps.md) for source and model limits and [development](development.md) for test commands.

## Current native discovery and comparison



The same current-row normalization, comparison and ordinary price display also
accept exact first-half core contracts in NFL, NCAAF, NBA and NCAAB, and Kalshi
MLB first-three-inning winner and first-five-inning core contracts. A typed
source period and explicit exclusion of later scoring are required; absent or
contradictory clauses retain unavailable comparison meaning. This representation
support does not expand the saved full-game acquisition scope. Team totals still
lack the required native subject binding; futures and other period gaps remain
visible in the shared capability inventory.

Ordinary Odds links to [Coverage](http://127.0.0.1:8783/current/coverage). The
[retained coverage contract](broad-coverage.md) describes the independent bounded
PostgreSQL summary, separate exact-query windows, cohort denominators, reference
role, deduplicated outcome/pair/direction units and overlapping gap explanations.
A shared registry describes the complete known matrix, including configured cells
with no prices and unsupported encountered types. Filters use retained local
data and leave global totals visible.

## Exact matching and publication

The shared `same_outcome` owner binds occurrence, league, family, period, scoring,
participant or score subject, canonical predicate, equality treatment and normal
payout units. Original numbers and descriptions remain separate. Integer score
sets can prove `>3.5` equivalent to `>=4`; `>3` differs from `>=3`. Away handicap
orientation reverses the margin predicate. An integer total with a refund differs
from a half-point total with a loss. Unknown push/refund terms withhold comparison.
A named team's `not_win` remains distinct from the opponent's `win`.

Explicit source links join a venue's family-specific event IDs to the same game.
Repeated games and doubleheaders retain separate identities. Similar titles never
establish equivalence. SQL reprojection and new ingress use the same resolver.

Current peers and lowest observed peers are selected separately using the existing
exact price normalization and subtraction, deterministic ties and original source
freshness limits. Frozen Details retains both captured native inputs while ages
advance. The difference is before costs; optional estimates remain independent.

Publication checks the same canonical outcome condition as matching. Relevant
peer additions/removals, source metadata, scoped governing rules, health, Stop,
configuration, runtime failure and epoch changes revoke affected authority.
Unrelated games and routine status clocks preserve unchanged results. Rule data
changes wake background reconciliation without a new provider request.

## Configuration and bounds

`native_sports` and `native_families` control only native collectors. Empty values
retain the legacy `sports` and `families` fallback. Aggregate sports continue to
use `aggregate_sports` or the legacy `sports`; aggregate families continue to use
`families`. Widening native scope neither widens aggregate requests nor changes a
held request, reservation or hold.

Discovery, metadata selection and subscriptions share each source's existing
request, connection, byte, event, market, cadence and process limits across all
leagues and families. Recurring league/family/period round-robin selection prevents permanent
starvation. Dense embedded Polymarket market lists receive rotating family-fair
exact metadata selection inside the same existing three-request allowance. Known useful cross-venue overlap receives priority within fair cells.
No per-sport copy of a source budget is created.

Both native collectors select whole current records before expanding a dense
catalog: at most 24 events and 72 market records, inside the unchanged 200-event,
512-market and 2 MiB source inventory guard. Conservative raw reservations and an
exact final size check defer whole records; they never shorten contract wording
or issue extra requests. Proposal rotation advances even when no record fits.
A capacity-only infeasible replacement retains the existing catalog, subscription
leases, stream, books, pending publication and original clocks. It reports
`query_capacity` with unknown offered counts and waits for the ordinary due pass.
Selection preserves observed duplicate IDs/slugs and original receipt row indices.

Ordinary discovery also retains a bounded diagnostic identity trace with exact
raw JSON pointers and receipt hashes. It samples one rotating record per present
league, keeps missing source fields separate from normalized blockers, and makes
all truncation/omission explicit. Trace plus existing identity exclusions share the
prior 24 KiB per-source diagnostic allowance; the trace itself is at most 12 KiB.
The trace grants no admission or shared occurrence identity.

If an owned native ID has observed changed terms while its replacement cannot
fit, that ID is quarantined. Its new books cannot reuse the old predicate. Old
price, wording and clocks remain stale with an explicit comparison block, which
survives annotation, SQL and the ordinary APIs. Unrelated owned books continue.
A feasible complete catalog replacement restores admission. Bounded witness
markers use 32 KiB reserved inside the existing inventory ceiling; detailed
replacement bodies do not enter status. Identical repeated milestone witnesses
and reviewed mutable observations do not manufacture material changes.

Explicit nested and flat native season forms share one reader. A retained integer
`season_year=2026` stays the exact source year label; `season_type=REG` uses the
existing regular-season decoder. Declared full season names remain distinct.
Contradictory or unsupported witnesses block admission; no calendar-based
multi-year season or provider namespace is inferred. Admission implementation
changes invalidate observation/publication code bindings for reprojection.

Odds uses local league, game, market and period filters. Counts distinguish
underlying covered outcomes/pairs, signed comparison directions and retained
observations. Configured, queried, discovered, admitted, fresh, comparable, empty,
unsupported and budget-limited states describe different evidence.

The app reads committed source frames. Page navigation, filters, Details and age
updates make no provider requests. SQL, disk, process and payload bounds remain in
force; source observations publish independently of financial estimates.
