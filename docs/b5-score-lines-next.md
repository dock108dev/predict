# Next B5 slice — shared full-game spread/total calculations

**Completed bounded proposal:** [implementation and acceptance handoff](b5-score-lines-handoff.md). The original scope below is retained for traceability. [NFL mapping is subsequently complete](b5-nfl-lines-handoff.md); [NCAAF mapping is subsequently complete](b5-ncaaf-lines-handoff.md); next independent work is MLB full-game run-line/total mapping.

**Original implementation proposal:** add score-line outcome partitions to ordinary Predict, piloted with NBA and men’s Division I NCAAB full-game spread/total fixtures. Reuse their reviewed game identities and the existing fees, depth, settlement evidence and saved-history paths. No acquisition or provider response is prerequisite to this independent engineering.

## Why this is the next shared gap

`session_projection.py` currently permits only full-game moneyline. `opportunities/board.py` creates normal outcomes from two team winners; `settlement.py` has no push outcome. The reference importer rejects projected margins/totals as probabilities. Therefore merely adding spread/total family labels would produce incorrect settlement and EV. Retained Kalshi catalog rows separately identify `KXNCAAMBSPREAD` and `KXNCAAMBTOTAL`; ProphetX sandbox catalogs contain full-game spread/total subtypes. These are discovery evidence, not qualified terms, line orientation or economics.

The coherent slice is a shared score predicate and payout partition, then ordinary dispatch. Preserve existing winner hashes/results and keep line-market evidence independently versioned.

## Implement and verify

1. Define a reviewed full-game line identity: exact game, scoring unit, spread participant/sign or total, exact decimal threshold, strict/inclusive inequality, native YES/NO/Long/Short orientation, source rules and original-input hash. Keep every line revision and cutoff distinct; never match different thresholds just because titles resemble each other.
2. Partition the possible final integer margin or combined score at all selected contract thresholds. Compute each leg’s evidenced payout in every reachable interval and at equality. A binary “greater than” NO contract can win at equality; a sportsbook-style push can refund stake. They are not equivalent. Require source-specific equality, refund and settlement-fee behavior; unmodeled equality outcomes remain unavailable.
3. Feed each partition’s payout/cashflow into the existing fee and depth engines. Support ordinary conditional Arb for evidenced compatible integer/half-point lines, including negative and unavailable results. Keep exceptional cancellation/suspension/void outcomes separate and unknown when missing. Do not force the existing two-winner complement logic onto line markets.
4. Extend the explicit reference contract for supplied cover/over/under probabilities or a supplied discrete outcome distribution bound to the exact threshold and payout partition. Require equality probability when material. A projected margin/score alone cannot produce cover probability; no distribution fitting or model acquisition in this slice. Preserve labeled manual scenarios.
5. Exercise exact boundaries, inverted sides/signs, different lines, nonzero equality probability, mismatched refund rules, fee/size gaps, future clocks, source failure and positive/negative/unavailable results. Run original 18-Arb/96-EV and all winner regressions, then ordinary Details/filter/Stop/immutable-reopen browser checks.

## Bounded pilot and remaining sports

NBA and NCAAB provide a useful shared point-score pilot while retaining separate game identity, period structures and source rules. Official native spread/total contract research and retained-field review belong inside implementation; no actual venue qualification is implied by fixtures. Support only explicitly reviewed full-game integer/half-point score predicates. Partial games, quarter-point split stakes, arbitrary middles/portfolios, futures and live trading remain separate.

| Sport | Additional mapping still required after the shared pilot |
|---|---|
| NFL / NCAAF | Points and spread orientation; tie/push/equality and overtime/shortening rules; NCAAF membership/site constraints retained |
| NBA / NCAAB | Pilot point thresholds; actual listing/economics qualification still open; college gender/division and halves distinct |
| MLB | Runs/run lines; action versus pitchers, extra innings, shortened/suspended games and doubleheaders |
| NHL | Goals/puck lines; regulation versus OT/shootout score and shootout goal treatment |

Deliver an exact-candidate handoff, truth-table evidence, ordinary conditional calculations and saved replay. Complete only that shared engineering slice after checks pass. Actual data/model qualification, full B4/B5 and beta signoff remain open. No live collection, credits, credentials, provider outreach or existing-beta restart is authorized by this proposal.
