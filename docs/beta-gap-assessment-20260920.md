# Predict — current beta gap assessment

September 20, 2026. **NOT READY FOR BETA SIGNOFF.** Reviewed current local source, retained reports and public provider documentation. No runtime test, live collection, account/credential access or owner demo was performed.

**B1 COMPLETE:** [coverage matrix](b1-coverage-matrix.md) and [B2 implementation handoff](b2-product-integration-handoff.md) delivered. **B2 NEXT; not implemented.**

## Confirmed target

At least four prediction venues: **Kalshi, Novig, Polymarket US, plus one to select**. Two reference types: **independent power-index/model line** and **free delayed Pinnacle data**. Sports: **NFL, NBA, MLB, NHL, NCAAF, NCAAB**. Markets: **win/loss, spreads, totals, halftime, futures**. **Live/in-play is a stretch goal.** The full [beta definition](product-roadmap-review.md) owns acceptance; [B1–B7](data-coverage-plan.md) owns delivery order.

## Current capability versus goal

| Beta area | What exists | What remains |
|---|---|---|
| Kalshi | Bounded production discovery/books/stream evidence; qualified offline diagnostic | Broader sports/markets, practical sustained coverage and integrated dashboard flow |
| Polymarket US | Bounded production discovery/streaming evidence | Coverage completeness unknown; Short purchase depth unsupported in current normalized path; broader sport/market and product integration |
| Novig | Offline-tested adapter, book/lifecycle/recovery logic | Recorded handoff lacks provisioned QA/production access and real wire confirmation; product integration |
| Fourth venue | ProphetX sandbox REST prices and authenticated transport/recovery are partially implemented | ProphetX recommended, owner selection pending. Quantity/value units, actual selection-update delivery and production remain unqualified |
| Independent model reference | Generic reference records/research scaffolding | B4 assess FPI/BPI independence and outputs, MoneyPuck NHL probabilities, FanGraphs MLB futures and KenPom access; MLB game forecasts and other unsupported cells stay open |
| Free delayed Pinnacle | The Odds API documents a free tier and website-sourced, possibly delayed Pinnacle; not integrated | B4 verify free entitlement, actual populated cells, delay/time semantics and quota fit; retain provenance and integrate |
| Sports | NFL-centered observed pipeline; NFL/MLB identity registry work | NBA/NHL/NCAAF/NCAAB identities and real feeds; MLB product/data qualification; six-sport acceptance evidence |
| Market families | Predominantly NFL pregame full-game winner flow | Spreads/totals, exact half/period definitions, futures identity and settlement; corresponding cross-venue matching and math |
| Opportunity product | Saved multi-game views, sorting/filtering/detail, what-if EV, historical page research; 18 Arb rows/96 EV scenarios independently reconciled | Four-venue current comparisons, model/Pinnacle inputs and broader market UI in one ordinary product |
| Collection/history | Segmented journals, exact replay and finite refresh/Stop/resource controls | Shared collector-to-comparison integration, representative useful session duration/recovery, broader retention, result/settlement linkage |
| Beta acceptance | Several bounded component successes | Complete agreed scope and integrated evidence, then owner review; no beta signoff recorded |

The independent model source and Pinnacle are two distinct requirements. Existing VegasInsider/DraftKings saved-page research does not satisfy either named integration merely by being reference data. No positive Arb/EV finding is required; negative, zero, near-miss and unavailable outputs are valid when original-input arithmetic is correct.

## Implementation evidence behind the gaps

- `app/collection/venue_access.py` defines the ordinary source destinations/credential references for Kalshi and Polymarket US; it is not a four-venue runtime.
- `app/collection/multi_game.py` constructs explicit Kalshi/US pairs and native side identities; expansion needs more than registering an adapter.
- `app/dashboard/multi_game_server.py` excludes sessions with `status_coverage` from its ordinary current multi-game dataset branch. Coverage controls and diagnostic success do not establish the current comparison flow.
- `app/collection/odds_http.py` explicitly restricts its provider path to numeric loopback mocks. Reference scaffolding is not live provider activation.
- [ProphetX handoff](slice-3.md): actual sandbox REST and recovery, unresolved size semantics, no selection-update frames in retained bounded tests. [Novig handoff](slice-5.md): offline tests and absent issued credentials at the recorded inspection, not a new account check.
- [Personal-beta report](personal-beta-operation-report.md) and [math report](math-reconciliation-report.md) establish useful retained product/calculation work. Their old operational next actions are not current authorization.

## Retained diagnostic success

[Offline final report](../evidence/delivery-launcher-preflight-20260919/final-report.md): 105 guarded checks, one consumed attempt, refresh +120.003s, closure +240.028s, cleanup 1.96ms, finalization 4.71s, 74.80 MiB collector peak, 1,446 exact replayed books. This is a reusable technical foundation, not six-source, six-sport beta readiness. Retained failures remain intact. No overall completion percentage is warranted while source feasibility and major integrations are unresolved.

## Source findings and assistance

The [B1 matrix](b1-coverage-matrix.md) records the checked official links, exact evidence classes, per-sport/family limitations and owner-help ledger. ProphetX is recommended because of reusable sandbox ingestion and observed NFL overlap; owner selection/access and economic qualification remain B3. Sporttrade's official site reports its May 2026 market closure; Betfair requires separate access/economics work and does not improve the immediate integration path.

The Odds API lists a free tier and Pinnacle website-sourced odds with possible delay. This is a plausible free delayed Pinnacle route, not tested entitlement, an established delay or a substitute bookmaker. B4 owns actual acquisition, populated coverage, time semantics, retention and free-quota viability. FPI/BPI, MoneyPuck, FanGraphs and KenPom are candidates with different outputs/access. In particular, FPI's published preseason methodology uses betting-market inputs; independence must be verified rather than inferred from the word model. Raw rankings do not supply market probabilities.

Owner help is limited to Novig issued provisioning, fourth-venue selection/approved access, and B5's halftime/period, futures and NCAAB competition preferences. Existing model access or a known Pinnacle URL is optional useful information, not homework. No secrets in chat, provider message or new account check. Engineering owns remaining acquisition and mapping research.

## Concrete next action

**B2 — implement the delivered [collector-to-product handoff](b2-product-integration-handoff.md).** Connect acknowledged coverage records to a common current/saved projection, remove product-level two-venue assumptions with explicit source handlers, and support ordinary updates, comparison details, Stop and reopening. Use isolated fixtures and retained inputs; unavailable B3/B4 sources must not block this work. B5 still owns the actual breadth definitions and mappings. B1 completion is assessment/handoff completion only; no implementation or beta readiness is implied.

This report and the active plans replace the prior contradictory optional-reference/NFL-only/deferred-venue direction. [Old planning snapshots](history/beta-reset-20260920/README.md) are inactive history; prior evidence and uncommitted implementation remain preserved. No implementation or new run was performed in this documentation reset.
