# Predict — current beta gap assessment

Updated September 21, 2026. **NOT READY FOR BETA SIGNOFF.** Reconciled B2 implementation and current B3 offline/native-fixture evidence. No B3 authenticated access or external market collection occurred.

**B1 COMPLETE:** [coverage matrix](b1-coverage-matrix.md) and [B2 implementation handoff](b2-product-integration-handoff.md) delivered. **B2 COMPLETE, fixture-backed. B3 IN PROGRESS; production qualification blocked.**

## Confirmed target

At least four prediction venues: **Kalshi, Novig, Polymarket US, plus one to select**. Two reference types: **independent power-index/model line** and **free delayed Pinnacle data**. Sports: **NFL, NBA, MLB, NHL, NCAAF, NCAAB**. Markets: **win/loss, spreads, totals, halftime, futures**. **Live/in-play is a stretch goal.** The full [beta definition](product-roadmap-review.md) owns acceptance; [B1–B7](data-coverage-plan.md) owns delivery order.

## Current capability versus goal

| Beta area | What exists | What remains |
|---|---|---|
| Kalshi | Bounded production discovery/books/stream evidence; qualified offline diagnostic | Fresh B3 production overlap; broader sports/markets and practical sustained coverage |
| Polymarket US | Bounded production discovery/streaming evidence | Coverage completeness unknown; B3 Short conversion verified offline; no fresh Short qualification; broader sport/market qualification |
| Novig | Native adapter integrated into shared runtime, history and ordinary fixture comparisons | Provisioned QA/production access, real wire confirmation and native listing-period association |
| Fourth venue | Provisional shared REST producer and retained sandbox price replay; fourth slot remains unselected | ProphetX recommended, owner selection pending. Quantity/value units, actual selection-update delivery and production remain unqualified |
| Independent model reference | Generic reference records/research scaffolding | B4 assess FPI/BPI independence and outputs, MoneyPuck NHL probabilities, FanGraphs MLB futures and KenPom access; MLB game forecasts and other unsupported cells stay open |
| Free delayed Pinnacle | The Odds API documents a free tier and website-sourced, possibly delayed Pinnacle; not integrated | B4 verify free entitlement, actual populated cells, delay/time semantics and quota fit; retain provenance and integrate |
| Sports | NFL-centered observed pipeline; NFL/MLB identity registry work | NBA/NHL/NCAAF/NCAAB identities and real feeds; MLB product/data qualification; six-sport acceptance evidence |
| Market families | Predominantly NFL pregame full-game winner flow | Spreads/totals, exact half/period definitions, futures identity and settlement; corresponding cross-venue matching and math |
| Opportunity product | Saved multi-game views, sorting/filtering/detail, what-if EV, historical page research; 18 Arb rows/96 EV scenarios independently reconciled | Four-venue current comparisons, model/Pinnacle inputs and broader market UI in one ordinary product |
| Collection/history | Segmented journals, exact replay and finite refresh/Stop/resource controls | B2 shared collector-to-comparison integration complete; representative useful real session duration/recovery, broader retention, result/settlement linkage |
| Beta acceptance | Several bounded component successes | Complete agreed scope and integrated evidence, then owner review; no beta signoff recorded |

The independent model source and Pinnacle are two distinct requirements. Existing VegasInsider/DraftKings saved-page research does not satisfy either named integration merely by being reference data. No positive Arb/EV finding is required; negative, zero, near-miss and unavailable outputs are valid when original-input arithmetic is correct.

## Current implementation evidence

[B2 completion](b2-product-integration-handoff.md) supplies ordinary current/saved coverage comparisons, immutable cutoffs and common history. [B3 engineering](b3-native-integration.md) adds native REST acquisition branches, source states, purchase semantics and original-body replay. [Per-venue evidence](../evidence/b3-native-integration-20260920/final-report.md) distinguishes synthetic tests, historical QA and production observations. No source status is promoted by a fixture.

Novig access and real listing period/rules are unresolved. ProphetX remains recommended and unselected; retained sandbox price interpretation is usable but quantity/value ownership is unknown. Source-specific fee applicability and settlement gaps remain null. Actual model/Pinnacle acquisition remains B4. Broader native canonical matching and economics remain B5.

## Retained diagnostic success

[Offline final report](../evidence/delivery-launcher-preflight-20260919/final-report.md): 105 guarded checks, one consumed attempt, refresh +120.003s, closure +240.028s, cleanup 1.96ms, finalization 4.71s, 74.80 MiB collector peak, 1,446 exact replayed books. This is a reusable technical foundation, not six-source, six-sport beta readiness. Retained failures remain intact. No overall completion percentage is warranted while source feasibility and major integrations are unresolved.

## Source findings and assistance

The [B1 matrix](b1-coverage-matrix.md) records the checked official links, exact evidence classes, per-sport/family limitations and owner-help ledger. ProphetX is recommended because of reusable sandbox ingestion and observed NFL overlap; owner selection/access and economic qualification remain B3. Sporttrade's official site reports its May 2026 market closure; Betfair requires separate access/economics work and does not improve the immediate integration path.

The Odds API lists a free tier and Pinnacle website-sourced odds with possible delay. This is a plausible free delayed Pinnacle route, not tested entitlement, an established delay or a substitute bookmaker. B4 owns actual acquisition, populated coverage, time semantics, retention and free-quota viability. FPI/BPI, MoneyPuck, FanGraphs and KenPom are candidates with different outputs/access. In particular, FPI's published preseason methodology uses betting-market inputs; independence must be verified rather than inferred from the word model. Raw rankings do not supply market probabilities.

Owner help is limited to Novig issued provisioning, fourth-venue selection/approved access, and B5's halftime/period, futures and NCAAB competition preferences. Existing model access or a known Pinnacle URL is optional useful information, not homework. No secrets in chat, provider message or new account check. Engineering owns remaining acquisition and mapping research.

## Concrete next action

Obtain the fourth-venue selection and Novig provisioning references, then finalize and seek one approval of the [bounded B3 qualification proposal](b3-native-qualification-proposal.md). No secrets in chat. Native engineering and isolated fixture verification have progressed; B3 is not complete and beta is NOT READY FOR SIGNOFF.

Independent work remains in native listing-period/rule association and native REST segmented replay. Preserve B2, old evidence and consumed attempts. B4 model/Pinnacle acquisition and B5 broader sport/market semantics remain separate slices.
