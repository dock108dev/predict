# B5 NFL pregame first-half winner/spread/total handoff

**COMPLETE — bounded NFL pregame first-half winner/spread/total engineering, offline verified September 22.** 403 Python tests and two JavaScript suites pass, including original 18-Arb/96-EV and exact prior saved replay. Isolated browser checks cover all three families, conditional/unavailable results, period/family filters, Stop and exact reopening. This handoff covers only the bounded engineering slice; actual venue/model qualification and full B4/B5 remain open. **Beta NOT READY FOR SIGNOFF.**

The owner's September 22 scope is now the active product definition: pregame first-half winner, spread and total are required for beta and come first. Second-half markets offered at halftime are later stretch. No MLB/NHL equivalent or in-play collection is selected. Active plans were replaced before implementation; their prior versions and NHL reconciliation are retained in [evidence](../evidence/b5-nfl-first-half-20260922/pre-edit-reconciliation.json).

## Exact implementation and product behavior

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA-256 `ba28dc84fc7133dd864ab6644a9c79d8f8ec0e80e88738e154aafa63a3e3967e`, 332 files. [Manifest](../evidence/b5-nfl-first-half-20260922/implementation-identity.json). Prior NHL 329 implementation files and 62 immutable evidence files matched before editing; preexisting changes were preserved. No commit or publication.

Ordinary Predict now projects explicitly reviewed NFL first-half moneyline/spread/combined-total markets into the existing score-partition calculation path. The retained annotation binds the source/event/market, raw body hash, descriptor/term/fee paths, native side and operator. Existing 32-team aliases and season-2026 regular/postseason game identity require a shared game ID, original/current timezone-aware starts, home/away orientation and reschedule status. Team names alone cannot merge repeated games. First-half identity differs from full game, second half and quarters; winner stays unlined and uses zero home-margin internally.

`nfl_first_half.py` requires pregame offering, first two 15-minute quarters definitively completed, first-half-only score and excluded overtime. Pregame receipt/start gates remain enforced. Later scoring never enters a first-half partition; the offline score checker requires the exact reviewed event and completed H1 result and ignores separately supplied H2/OT scores. It is not a result collector or automated venue settlement.

Details name First half, native inequalities, equality treatment and conditional results. Period and family filters distinguish H1 winner/spread/total from full-game markets. Unknown native reviews and three-way winner structures remain visible in coverage gaps; unknown size, Short purchase applicability, fees and reachable refund/equality payouts remain unavailable. Stop and immutable saved links reuse ordinary owner/history paths. Missing forecasts do not block comparisons or conditional Arb.

## Reviewed payout structures

Only explicit two-outcome annotations are supported. These are not universal NFL rules. A team-specific binary contract binds strict win (`gt`) and not-win (`le`, including tie). A reviewed two-way draw-no-bet structure binds strict opposing predicates with stake refunds. Three-way markets and unreviewed tie strikes remain unsupported; no conversion to two teams is inferred. Opposite-team positive win legs lose together on a tie and cannot claim guaranteed Arb. The postseason H1 tie state is retained even though normally completed postseason full games cannot tie.

Independent payout table, per $1 face-value contract, with `S` the actual purchase stake:

| H1 contract | Away leads | Tie | Home leads |
|---|---:|---:|---:|
| Home strictly wins | 0 | 0 | 1 |
| Home does not win | 1 | 1 | 0 |
| Away strictly wins | 1 | 0 | 0 |
| Home draw-no-bet | 0 | S | 1 |
| Away draw-no-bet | 1 | S | 0 |
| Both positive team wins purchased | 1 | 0 | 1 |

For spread threshold 3, below/equal/above represent home margins ≤2 / 3 / ≥4. `gt` pays 0/0/1; `le` pays 1/1/0; `ge` pays 0/1/1; `lt` pays 1/0/0. Away handicaps invert both sign and predicate. For total 20.5, ≤20 / ≥21 are the only reachable partitions; integer totals retain equality. Stake refunds return consumed purchase price × quantity, not face value; supported refund scenarios retain entry fees. Returned or unknown refund fees remain unavailable where reachable.

Independent arithmetic fixtures (not observed venue opportunities): one complementary half-point contract per venue, Kalshi price .47/.48/.49 and US price .49, entry fees .02 + .01, produce net +.01 / .00 / −.01 respectively. Original fixture prices were not changed to manufacture a browser result. Browser complementary pairs cost $103.86 per 100 contracts and pay $100 in each normal partition: net −$3.86. Same-predicate legs have minimum −$68.88. Two positive team-win legs include the uncovered tie loss. All-outcome worst case remains unknown because exceptional payouts/probabilities are unqualified.

## Source evidence and limits

Reviewed September 22: current official [Kalshi winner](https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf), [spread](https://assets.kalshi.com/contract_terms/FOOTBALLSPREAD.pdf) and [total](https://assets.kalshi.com/contract_terms/FOOTBALLTOTALS.pdf) documents. PDFs/text retained locally; web PDF access failed, direct official download succeeded. Catalog bindings are `KXNFL1H`, `KXNFL1HSPREAD`, `KXNFL1HTOTAL`, each retained quadratic multiplier 1. The archived `KXNFL1HWINNER` catalog entry is not treated as interchangeable. [Audit](../evidence/b5-nfl-first-half-20260922/native-contract-audit.json).

The winner contract distinguishes strict period winners and a listed tie strike, under which tied-period team strikes lose. Its full-game fractional tie payout does not transfer to H1. Templates distinguish selected periods and completed-period exceptions from incomplete-game/discretionary fair-price clauses. Explicit first-half scope and OT exclusion remain required; generic defaults do not prove a selected listing. Suspension/abandonment/postponement, cancellation, forfeits, venue changes, corrections and void terms remain source-specific. Fair price is not a stake refund; no 55-minute full-game rule settles an incomplete H1 automatically. Totals template amendment/formatting ambiguity is retained as a rule-review gap.

Fixture annotations exercise hypothetical source-specific payout structures and the existing venue fee/depth engines. They do **not** qualify a current Kalshi listing or establish PMUS H1 settlement rules, draw-no-bet availability, Short size, fees or overrides. Retained ProphetX catalog has H1 moneyline/spread/total subtypes (IDs 64/66/68); reused template IDs require event/strike association. Novig/ProphetX economics remain unsupported. No new listings, model outputs, credits, credentials or provider messages were collected.

## References, validation and remaining work

The existing B4 `score_distribution` interface requires `completed_first_half_only`, exact H1 market/event/native outcome and complete reachable partition probabilities. Winner and integer boundaries require equality mass. Full-game distributions/probabilities, projected scores/margins, ratings and season outputs cannot substitute. Receipt/publication/start clocks and schema replay prevent future leakage. Browser reference examples are labeled SYNTHETIC, not ESPN forecasts: .3 below/.1 equal/.6 above yields −$29.53 for the retained $0.68 inclusive contract per 100; the half-point total reference .4/.6 also yields −$29.53. Manual total probability .6 yields −$9.53 and retains its explicit what-if basis. Unconditional EV remains unavailable.

[Acceptance report](../evidence/b5-nfl-first-half-20260922/final-report.md) records checks, browser evidence, repairs and exact reopening. B3 owns actual current H1 selected listings, period/tie evidence, native annotations, source fees/depth and exceptional/refund applicability. B4 owns actual H1 partition forecasts and independence. B5 retains other seasons, tie-strike/three-way portfolios, result linkage and remaining sports. No full B4/B5 or beta upgrade follows from fixture acceptance.

**Next independent engineering slice: NCAAF pregame first-half winner/spread/total**, reusing the existing bounded college identity/site/subdivision checks with separately reviewed first-half contracts and equality/tie partitions. Second-half-at-halftime remains stretch; quarters, MLB/NHL equivalents, futures and in-play remain separate. MoneyPuck dropped/NHL analytics deferred; KenPom deferred; ProphetX selected and access requests pending.
