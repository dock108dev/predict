# NBA sporting-result and venue-settlement linkage

**COMPLETE — bounded engineering, offline verified September 22, 2026.** Existing reviewed NBA 2026–2027 full-game/H1 winner/spread/total only. **544 Python tests and two JavaScript suites PASS. Actual source qualification and full reference integration, market support remain open. Beta NOT READY FOR SIGNOFF.**

## Exact candidate and reconciliation

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA256 **`dea7e43aec71e4bca26dc1949d14a0c6336cbe792afe04b5d602f64c0f0dfd20`**, 351 files. [Identity](../evidence/b5-nba-resolution-20260922/implementation-identity.json) · [acceptance](../evidence/b5-nba-resolution-20260922/final-report.md).

Before editing, all 347 NFL implementation files, 75 immutable evidence files and six tracked documents matched their recorded hashes. [Pre-edit reconciliation](../evidence/b5-nba-resolution-20260922/pre-edit-reconciliation.json). The unrelated requirements-ci.txt edit, previous observations and consumed attempts are preserved. No commit, migration or existing-beta restart occurred.

## Ordinary product and shared implementation

Ordinary saved Details now displays NBA sporting score and period, rule-derived expected payouts, each native venue/outcome decision, missing/pending/conflicting/corrected evidence and explicit resolution cutoff/as-of controls. A final score never implies venue settlement; an observed payout never establishes a fill, balance or realized profit.

The NFL framework moved to `app/resolution/core.py`; `nfl.py` preserves its import interface, original record versions and view output. `nba.py` adds only NBA-specific score validation and exports the shared operations. Existing projection, collector admission/Stop, flat/segmented journal, saved history, correction graph, payout, fee/depth and calculation engines are reused. No second journal, calculation engine or dashboard was introduced. The shared Details interface is enabled for NBA and shows the selected score scope.

Prepared local JSON annotations can be imported through the existing ordinary resolution import control in an active session. Stop makes their completed package available to the resolution selector. Later evidence can live in a new ordinary session pointing to an older saved prediction; the old completed package remains byte-for-byte unchanged. Records retain original body/hash/path/provenance, evidence mode, source/publication/receipt clocks and explicit correction edges. The existing 16-record import and 128-record/8MB projection bounds remain. These are annotation contracts, not newly qualified native provider parsers.

## Supported score and identity contracts

NBA records use **nba-sport-result-1** and **nba-venue-settlement-1**. Shared target fields require original session, immutable prediction cutoff, exact game and market identity, reviewed NBA event and source-native event/market/outcome IDs. NBA 2026–2027, reviewed stage, home/away, original/current timezone-aware start, reschedule status and shared game ID must agree with every original source catalog. The existing 30-team alias registry is unchanged. Repeated opponents, stage/start conflicts, other competitions and incomplete legacy identity never match by names alone. Native winner predicates must bind reviewed team names; missing original evidence stays unbound and readable.

| Target | Required explicit sporting evidence | Unsupported alternatives |
|---|---|---|
| Pregame H1 | `score_scope=first_half_end_of_second_quarter`, `regulation_periods_completed=2`, `completion=first_two_quarters_definitively_completed`, integer home/away scores credited to that segment | Full-game totals, Q2 alone, generic period number, missing quarter completion, H1 reconstructed from final score |
| Full game | `score_scope=full_game_including_overtime`, four regulation periods completed, `completion=all_regulation_and_applicable_overtime`, `overtime_complete=true`, explicit nonnegative completed-OT count and integer final home/away scores | Regulation-only totals, missing OT completion/count, clock-zero-only evidence, tied normal NBA final |

A directly identified official H1 aggregate does not require inventing individual Q1/Q2 scores. Missing aggregate or completion evidence stays unavailable. A directly identified full-game aggregate does not reconstruct regulation totals or subtract unknown overtime points. Optional later regulation/final/OT fields never change H1 payouts. Regulation-only winner/line markets remain outside the existing supported market scope; their score records are visible unsupported, not silently treated as OT-inclusive.

Pending, suspended, shortened, abandoned, postponed, cancelled and unknown sporting statuses derive no normal payout. Void/refund venue decisions remain independent and do not invent a sporting score, dollar refund or fee return. The [source review](../evidence/b5-nba-resolution-20260922/source-review.md) distinguishes NBA sporting rules from retained source-specific contract terms.

## Corrections, clocks and immutable predictions

Shared append-only correction semantics are unchanged: explicit predecessor IDs must be visible, supported and identically bound to source/event/period/native contract; publication strictly advances and receipt/source clocks cannot regress. Competing active records remain conflicting. Arrival order cannot choose a winner; valid out-of-order arrival is accepted only when explicit relationships and clocks establish order. Superseded versions remain inspectable.

Resolution prefix and timezone-aware as-of are separate from the prediction cutoff. All known source/publication/receipt/journal clocks must be no later than as-of. Future records are excluded; unknown or conflicting clocks cannot select a result. An earlier as-of on a later prefix reproduces pending evidence. Reopening an older correction link does not adopt the latest record. Original prices, models, reference cutoffs, assumptions and calculations remain unchanged.

## Independent payout expectations

Existing reviewed payout functions determine expectations; observed venue payouts never replace them. Strict home-win pays 1 only when home leads; home-not-win includes H1 ties. Opposite positive-win legs both lose on a tied half. Integer boundaries preserve strict/inclusive equality: gt pays 0/0/1, ge 0/1/1, lt 1/0/0 and le 1/1/0 across below/equal/above. Away predicates and signs remain native-bound. A total of 103 at 53–50 reaches equality; half-point totals have no integer equality state.

Explicit supported pushes/DNB return consumed purchase stake, not face value, and retain entry fees. Independent 100-contract H1 refund checks expect Kalshi .33 purchase→$33 gross/−$1.55 net, Kalshi .68→$68/−$1.53, PMUS Long .33→$33/−$1.33. Unknown refund fees/equality yield unavailable expectations; Short purchase quantity remains unavailable. Fractional/shared-achievement and three-way H1 structures remain excluded by existing mapping tests. No new exceptional payout model was added. A normally completed OT-inclusive NBA game cannot use a tie result to activate an exceptional fractional rule.

Browser fixtures preserve original prices: H1 conditional pair nets **−$3.86 and −$68.88 per 100**, with Short cases unavailable; full-game supported pair net **−$3.86**, with the other pair unavailable. Full-game expected face payout can be known while hypothetical leg dollars remain unavailable because retained source-time progress is missing. Unknown size, fee or cashflow evidence remains unknown. These are hypothetical calculations, never realized account results.

## Acceptance and remaining work

[Acceptance report](../evidence/b5-nba-resolution-20260922/final-report.md) · [NBA saved replay](../evidence/b5-nba-resolution-20260922/final-reconciliation.json) · [NFL exact resolution replay](../evidence/b5-nba-resolution-20260922/nfl-resolution-reconciliation.json) · [prior-sport replay](../evidence/b5-nba-resolution-20260922/prior-reconciliation.json).

All 28 NBA checks, original 22 NFL linkage checks, 18-Arb/96-EV reconciliation and affected sport/reference/history/fee/depth regressions pass. Separate ordinary H1 and full-game browser sessions imported six labeled records each, stopped, then demonstrated pending, resolved, conflicting, corrected and earlier-as-of views. All eight final DOM comparisons are exact; fresh-process disk replay after shutdown reproduces every saved view and pregame calculation. Initial fixture/focus issues and repairs remain recorded, without changing historical inputs or weakening checks.

Actual NBA sporting score/completion feeds, native venue settlement/payout fields, source/publication/correction semantics and exceptional/refund fees remain venue integration, market support qualification gaps. No provider parser, selected native contract, account settlement or real result source was qualified. Incomplete legacy bindings remain explicit. Reference integration model/Pinnacle qualification is unchanged; MoneyPuck dropped/NHL analytics deferred, KenPom deferred, ProphetX selected and requests pending. No collection, credits, credentials, outreach, spending, trading, commits, pushes or publication.

**Next independent slice: bounded 2026 NCAAF full-game/H1 sporting-result and venue-settlement linkage**, preserving the existing six-school boundary and reviewing college completion/overtime/forfeit semantics separately. This is a recommendation, not implementation. [Remaining market support backlog](market-data-gaps.md) keeps broader college coverage, futures, unsupported economics and undecided MLB/NHL periods open. **Full reference integration, market support open; beta NOT READY FOR SIGNOFF.**
