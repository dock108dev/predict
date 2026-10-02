# Current source bindings and same-session correspondence

September 30, 2026. The authoritative requirement is 63 cells: 18 full-game W/S/T, 12 football/basketball H1 W/S/T, 12 MLB cumulative 3/5/6/regulation-9 W/S/T, nine NHL individual-period W/S/T and 12 conference/league championship cells. Each has four independently assessed sources. `app/fixtures/source-bindings-current.json` is the deterministic, bounded 252-source-cell ledger; `app/collection/source_bindings.py` rebuilds it from content-addressed retained originals. `/api/source-bindings` serves the ledger and its download. A selected capture/cutoff adds session-only metadata/quote counts without changing historical projections or promoting static evidence to current qualification.

| Source | Exact retained record cells | Implemented, awaiting real source evidence | External facts still missing | Qualified economics cells |
|---|---:|---:|---:|---:|
| Kalshi | 3 | 43 | 17 | 0 |
| Polymarket US | 3 | 3 | 57 | 0 |
| Novig via The Odds API | 14 | 31 | 18 | 0 |
| ProphetX via The Odds API | 13 | 32 | 18 | 0 |

The statuses describe source-binding engineering. Reviewed identity, complete delivery, eligible state, admitted books, settlement, fees and economics remain separate dimensions. A record can have evidenced identity and incompatible settlement, or exact outcome identity and invalid odds. No cell is classified as demonstrably unsupported by its selected source merely because a bounded page is empty or a key is unpublished. The fourth status exists for definitive source evidence; none of these missing facts establishes it.

## Implemented native catalog bindings

The complete retained Kalshi primary series catalog `evidence/phase-0/kalshi-series.json` establishes **110 exact series keys covering 46 required cells**. `native-scope-bindings-v1.json` preserves the catalog body hash, each original series hash, exact title, terms URL, settlement-source references and dated metadata. `native_scope_bindings.py` exposes typed series bindings and selectors for ordinary bounded collection. The winner-only legacy `SPORT_SERIES` remains unchanged. The adapter and catalog enable new family/period classification only under the explicit native scope policy, preserving historical interpretations.

The mapped cells include all six sports' full-game winner/spread/total, all four H1 winner/spread/total groups, MLB first-three winner and first-five W/S/T, and all 12 championship categories. Conference selector records retain the exact conference and distinct award variant: a college conference tournament winner does not become a regular-season champion. Archived/legacy rule references remain separate catalog selectors. None supplies an exact market predicate, oriented strike, home/away roles, completion/tie/push rules, current season, entrant field/revision, current membership or effective fees. New non-full-game or line/futures listings retain `native_scope_predicate_review_required` until those source facts are reviewed. This is a real source key integration, with precise remaining semantic evidence.

The 17 Kalshi cells without established retained series keys are MLB first-three spread/total, MLB first-six W/S/T, MLB regulation-nine W/S/T and NHL individual P1/P2/P3 W/S/T. No first-seven, full-game, or cumulative-period substitution is used.

Polymarket US supports existing exact game selectors for all six league families. Whole retained market objects contain football, baseball and hockey full-game winner types; the sole generic `moneyline` object is boxing event 54125/market 237388, outside this requirement. No complete retained NBA/CBB winner sides establish an additional basketball type or native participant mapping. The `cbb` league/tag identity identifies the family, while an actual men's Division I listing/membership/outcome binding remains necessary. The ledger keeps complete US BOS/NYY market 1081085 distinct from the retained Kalshi PHI/ATL sample and preserves event-only NFL/NHL associations.

The latest completed Kalshi NHL target v3 capture has complete metadata and two initial snapshots plus 52 price/quantity changes. Its failed US 524,288-byte response remains incomplete metadata with `native_response_byte_cap`. Earlier valid US NHL identity remains dated evidence; it does not become a book in the new capture. No engineering depends on event 127804 remaining pregame.

## Aggregate mapping facts

The existing 18 full-game and 27 documented segment keys are reused. The exact remaining 18 aggregate cells per selected book are six MLB first-six/regulation-nine cells plus six conference and six league championship cells. The September 30 public primary catalog review is retained in `source-binding-catalog-20260930.json`:

- The Odds API [market catalog](https://the-odds-api.com/sports-odds-data/betting-markets.html) publishes first-one/three/five/seven baseball keys. It does not establish first-six or regulation-nine keys. First-seven is not substituted for first-six.
- The [sports catalog](https://the-odds-api.com/sports-odds-data/sports-apis.html) establishes six league-winner sport keys and `outrights`. Exact selected-book availability, season, award, complete entrant field/revision and exceptional/no-award/shared payout meaning remain unestablished. An outright sport key is not a qualified championship contract.
- Conference championship keys and their event/schema identity remain unestablished. Provider omission does not prove the originating venue cannot offer a contract.

The real retained NFL H1 response supplies both books' two winner records and Novig's two spread records; ProphetX H1 spread and both H1 totals remain unobserved. Full-game Novig MLB spread records contain invalid prices, which remain identity evidence and excluded price observations. NBA/CBB responses lack selected-book observations; this is a sample fact, not venue absence. Aggregate rows have no executable depth, minimum/increments, fill semantics, active state or native payout/fee qualification.

## Versioned source correspondence

`correspondence_policy: source-correspondence-1` extends the ordinary source projection, comparisons, Details/downloads and watch provenance. Each native leg can correspond independently to Novig/ProphetX aggregate observations. A failed or missing other-native book is not a prerequisite. The extension uses existing per-source reviewed metadata admission, book formatting, purchase conversion and scoring descriptors. It requires the same session/cutoff, exact competition/participants/schedule/period/family, exact oriented scoring predicate and no ambiguous provider event IDs. MLB is withheld until its aggregate season/game-number/reschedule/pitcher identity is established; championships require exact season/award/field. Unknown canonical participants keep their provider-local comparisons.

Bindings freeze selected native review/market/book/receipt hashes and aggregate record/response/source IDs. Native and aggregate images must be within the unchanged five-second receipt alignment ceiling, and current clock changes recompute age and pregame validity. Metadata replacement, explicit closure, unsynchronized books and current failed/resynchronizing connections invalidate the affected native source. Unknown continuous market state, source delay and clock offset remain unqualified. References never supply a comparison leg.

Mixed rows label native dollars per $1 normal-win claim separately from decimal odds/raw implied odds. The numeric display gap is a display-scale comparison, not a cash hedge or executable arbitrage. Aggregate legs have no depth or supported sizing. Mixed net/EV, executable size and source-qualified watch signals remain unavailable until complete cashflow/fee/execution/probability evidence exists. Raw prices remain visible and downloadable with their exact binding.

## Validation

The source ledger tests verify exact 63/252 scope, deterministic rebuilding without network/credentials, original receipt hashes, invalid prices versus identity, latest incomplete delivery versus historical identity, independent book captures, selected-cutoff replay and bounds/tampering. Native scope tests verify every copied catalog key/field against its complete primary original, 46-cell coverage, distinct conference awards, policy isolation and no inferred line/completion/admission. Correspondence controls exercise single-native operation for either venue, shared US Short purchase conversion, reference isolation, receipt skew, unknown participants, changed schedules/metadata, closure/resynchronization, duplicate provider event ambiguity, clock-only staleness/kickoff, raw watch exclusions and exact journal reopening. These controls are explicit synthetic isolation over retained inputs, not real simultaneous four-source qualification.
