# Men’s Division I NCAAB result and settlement linkage

**COMPLETE — bounded offline engineering, September 22, 2026.** Four reviewed schools, 2026–2027 men’s Division I, existing full-game and pregame first-half winner/spread/total only. **606 Python checks and two JavaScript suites pass. Actual source qualification and full reference integration, market support remain open; beta NOT READY FOR SIGNOFF.**

## Identity and reconciliation

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA256 `4750ed93d736142944c6dce36f55a9ba87c5d572398620793c7552ddb8399307`, 357 files. [Exact identity](../evidence/b5-ncaab-resolution-20260922/implementation-identity.json). Before editing, the latest NCAAF candidate’s 354 implementation files, 96 immutable evidence files and six documents matched. [Reconciliation](../evidence/b5-ncaab-resolution-20260922/pre-edit-reconciliation.json). Existing unrelated requirements edit, historical observations and consumed attempts are preserved.

`app/resolution/ncaab.py` adds college basketball validation through the shared resolution core. Revision validation is shared with NCAAF; its previous outputs remain exact. Existing projection, native binding, retained import, bounded journal, history, expected payout, fee/depth and calculation paths are reused. Ordinary saved Details now displays the college score period, revision meaning, expected payout and independent venue decision, including missing, pending, conflicting, corrected and unsupported evidence.

The four canonical schools remain Alabama, Alabama A&M, Miami FL and Miami OH (`NCAAB:M:D1:ALA`, `AAMU`, `MIAFL`, `MIAOH`). No roster expansion. Gender/division, competition ID, season, school map, tournament/stage/round, site, designated home/away, shared game ID, original/current timezone-aware starts and reschedule evidence bind to the original prediction and every native source. Repeated matchups cannot merge by names. Ambiguous aliases and incomplete legacy bindings remain unbound; annotations never backfill old packages.

## Explicit score contracts

Schemas: `ncaab-sport-result-1`, `ncaab-venue-settlement-1`; view `ncaab-resolution-view-1`. Raw body/hash/path/URL, evidence mode, source/publication/receipt clocks and explicit predecessors remain retained. This is the existing prepared-annotation interface, not a qualified native result parser.

| Period | Required final evidence |
|---|---|
| First half | `score_scope=first_20_minute_half`, `score_representation=official_period_points`, `period_format=first_20_minute_half`, one regulation period completed, `completion=first_20_minute_half_definitively_completed` |
| Full game | `score_scope=full_game_including_overtime`, `score_representation=official_final_points_including_all_overtime`, `period_format=two_20_minute_halves`, two regulation periods completed, `completion=all_regulation_and_applicable_overtime`, `overtime_format=repeated_5_minutes`, explicit extra-period count and completed flag |

Both require explicit nonnegative integer points and `result_basis=on_field_period_score`. H1 uses one completed 20-minute half, never NBA Q1+Q2. Later H2/regulation/OT arrays cannot alter H1. Full-game cumulative official points are used once; missing regulation/H1 scores are not reconstructed, and extra-period arrays are not added again. Missing or ambiguous representation/completion remains unsupported; a tied full-game final is not a normal completed OT result. [Rules review](../evidence/b5-ncaab-resolution-20260922/source-review.md).

## Revisions, clocks and venue isolation

Sporting revision types are original, score_correction or administrative_change. Corrections require explicit valid predecessor relationships; administrative status and revision meaning must agree. Vacated/administrative decisions do not become on-field scores or overwrite venue payouts. Shortened, forfeit, suspended, postponed, abandoned, cancelled and unknown statuses derive no normal expected payout. Multiple active branches remain conflicting until explicitly superseded; arrival order does not choose a winner.

Shared correction edges enforce exact source/event/period/target/native binding and valid publication/source/receipt ordering. Original and superseded records remain inspectable. Unknown clocks cannot select a result. All source/publication/receipt/journal clocks must fit the requested as-of; future observations are excluded. Original prediction books, reference inputs, fee assumptions, calculations and links remain immutable. Sporting final with venue pending/missing remains two independent facts. A score correction updates only the labeled rule expectation; an independently reported payout is preserved even when they disagree.

## Independent payout expectations

Existing W/S/T engines preserve native orientation. Strict home win excludes an H1 tie; not-win includes it. Opposite positive-win bets both lose on a tie. At margin or total threshold 3, below/equal/above payouts are gt 0/0/1, ge 0/1/1, lt 1/0/0, le 1/1/0. Away signs remain native-bound; half-point lines have no integer equality. An 80–78 final with two completed extra periods reaches margin 2 / total 158 once, even with separate regulation/OT arrays retained.

Supported pushes/DNB refund consumed stake while retaining entry fees. Literal 100-contract checks: Kalshi .33 gives $33 gross/−$1.55 net; Kalshi .68 gives $68/−$1.53; PMUS Long .33 gives $33/−$1.33. Unknown refund fees and Short purchase size remain unavailable. No venue borrows another’s economics. Fractional/three-way, forfeits and unreviewed exceptional/fee-return models remain outside scope.

Original browser H1 conditional pair nets remain −$68.88 and −$3.86 per 100; full-game pair remains −$3.86. Short alternatives remain unavailable. Full-game expected face payouts may be known while hypothetical cashflows remain unavailable because original source-time progress is missing. None establishes executed trades, account settlement or realized profit.

## Acceptance and remaining work

[Acceptance report](../evidence/b5-ncaab-resolution-20260922/final-report.md) records 31 new NCAAB checks, 81 NFL/NBA/NCAAF resolution checks, original 18-Arb/96-EV reconciliation and affected sport/reference/history/fee/depth regressions. Two isolated ordinary browser sessions each imported six labeled records, stopped manually and verified pending, resolved, conflicting and corrected Details plus earlier as-of. All eight saved DOM comparisons and fresh-process saved replays are exact. Administrative changes and multi-OT scoring are offline test evidence, not browser or venue qualification.

Actual sporting scores/completion/clock representation, native settlement/payout/refund/revision fields and exceptional fees remain venue integration, market support qualification gaps. Incomplete legacy bindings, additional schools/seasons and reference integration model qualification remain open. MoneyPuck dropped/NHL analytics deferred; KenPom deferred; ProphetX selected and requests pending. No collection, credits, credentials, account settlement, outreach, spending, existing-beta restart, migrations, trading, commits, pushes or publication.

**Next independent slice: MLB full-game winner/run-line/total sporting-result and venue-settlement linkage**, reusing reviewed game/doubleheader/reschedule, pitcher/action, extra-inning and completion identities. No first-five/inning scope is selected. [Remaining backlog](market-data-gaps.md). **Full reference integration, market support open; beta NOT READY FOR SIGNOFF.**
