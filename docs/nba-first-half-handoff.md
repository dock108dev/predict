# NBA pregame first-half winner/spread/total handoff

**COMPLETE — bounded engineering, offline verified September 22, 2026.** 471 Python tests and two JavaScript suites pass, including original 18-Arb/96-EV reconciliation and prior saved results. Actual venue/model qualification, exceptional payouts and broader reference integration, market support remain open. **Beta NOT READY FOR SIGNOFF.**

## Exact implementation and ordinary behavior

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA256 **`c22ab97cc4dc0392daa2b69aa1f63463cbfda79cb19e79b901fafd2691c288cf`**, 339 files. [Identity](../evidence/b5-nba-first-half-20260922/implementation-identity.json) · [acceptance](../evidence/b5-nba-first-half-20260922/final-report.md). All 336 accepted NCAAF implementation files and 81 evidence files matched before editing. Prior work and the unrelated `requirements-ci.txt` edit were preserved; no commits or publication.

Ordinary Predict accepts explicitly reviewed NBA pregame H1 winner, spread and combined-total annotations. NBA-specific scope validation feeds the existing H1 payout partitions, fee/depth engines, reference interface, Details, filters, source health and Start/Stop/history paths. Titles identify the end of the second quarter and exclude second-half/OT scoring. No new dashboard, calculator or collection path.

Existing 30-team reviewed NBA aliases and conservative consecutive-season `YYYY-YYYY` identity remain unchanged: September–July schedule envelope, regular season/play-in/playoffs/NBA Cup, shared game ID, original/current timezone-aware starts, reschedule status, home/away and native participants. H1 fixtures use 2026–2027. Repeated opponents, different starts/stages and reschedules cannot merge by names. NBA is separate from WNBA/NCAAB/other leagues; ambiguous Los Angeles, summer league/preseason and unsupported schedules remain excluded. No new team census or native IDs.

Every annotation binds source/event/market, retained receipt hash, native paths, exact H1 descriptor, family, participant/sign, predicate, equality/refund behavior and own fee evidence. H1 winner stays unlined, with internal zero-margin partitions. Full game, H1, H2 and quarters remain distinct. A generic period number cannot establish H1. Missing completion/period terms fail closed; explicit unknown exceptional terms permit only conditional normal-period calculations, never evidence of equivalent exceptional settlement.

## NBA-specific rule review and remaining native gaps

[Retained catalog and contract audit](../evidence/b5-nba-first-half-20260922/native-contract-audit.json) · [downloaded public documents](../evidence/b5-nba-first-half-20260922/public-document-manifest.json).

- [NBA Rule 5](https://official.nba.com/rule-no-5-scoring-and-timing/) specifies 12-minute regulation periods. End-period in-flight shots, prior whistles and shooting-foul penalties can affect official completion. This slice requires the first two quarters definitively completed and the official score credited to that segment. Q3/Q4 and five-minute overtime do not enter H1 results. The offline sporting-score helper requires exact event, explicit H1 and completed status; it is not a result collector or automated venue settlement.
- Retained **KXNBA1HWINNER** points to [ACHIEVEMENTS](https://assets.kalshi.com/contract_terms/ACHIEVEMENTS.pdf), not BASKETBALLGAMEWIN. It uses an explicitly listed achievement, shared-winner allocations, cancellation/fair-allocation clauses and official results for truncation. Its generic template alone does not establish the selected H1 tie outcome. **No KXNBA1H series is invented.** Actual winner listing/achievement/tie meaning is a venue integration, market support gap.
- The separately reviewed [BASKETBALLGAMEWIN](https://assets.kalshi.com/contract_terms/BASKETBALLGAMEWIN.pdf) template expressly pays 0.50 to YES and NO for a tied selected period. It distinguishes completed segments from incomplete segments and 48-hour interruption provisions. This is neither a strict-win binary tie nor a purchase-stake refund. Fractional/shared-winner and three-way structures remain visible unsupported in this slice, including the browser's fractional-tie gap. The template is not reassigned to the retained ACHIEVEMENTS series.
- **KXNBA1HSPREAD** uses [BASKETBALLSPREADS](https://assets.kalshi.com/contract_terms/BASKETBALLSPREADS.pdf); **KXNBA1HTOTAL** uses [BASKETBALLTOTALS](https://assets.kalshi.com/contract_terms/BASKETBALLTOTALS.pdf). Both support explicitly selected segments and native comparison predicates. Spread cancellation/abandonment/resumption and delay terms use 48 hours; totals use 24-hour resumption and a two-week delay window. Their correction, fair-price, shortening and already-reached-strike provisions remain distinct. Completed NBA H1 never inherits football's exception carveouts or a universal refund.
- Each of these three retained NBA H1 series has its **own quadratic fee type, multiplier 1**. This differs from the full-game NBA winner fee context. Current overrides, exact selected native outcome/period/terms, usable depth and fee applicability remain missing. Fixtures deliberately exercise hypothetical binary/DNB structures and compatible normal-period annotations; they are not real venue opportunities or a qualification of ACHIEVEMENTS tie semantics.
- PMUS requires actual US NBA H1 listing, native Long/Short purchase semantics, period/tie/refund rules and own fees/depth. Its hypothetical annotations reuse only its own retained coefficient and conversion path; Short remains unavailable. Novig/ProphetX NBA H1 rules, units/fees and production bindings remain unqualified; no economics are borrowed.

## Independent payout and arithmetic expectations

Per $1 face-value contract; `S` means the actual consumed purchase stake:

| Reviewed structure | Away ahead | Tie | Home ahead |
|---|---:|---:|---:|
| Home strictly wins | 0 | 0 | 1 |
| Home not-win | 1 | 1 | 0 |
| Away strictly wins | 1 | 0 | 0 |
| Home draw-no-bet | 0 | S | 1 |
| Away draw-no-bet | 1 | S | 0 |
| Both positive team-win legs | 1 | 0 | 1 |
| Fractional tie / shared achievement / three-way | Unsupported | Unsupported | Unsupported |

Ties remain material for every NBA stage. Buying both positive team-win legs leaves tie unpaid: normal minimum net is negative entry cash, with no guaranteed arbitrage. DNB requires explicit opposing strict predicates and stake-refund terms; its availability at any actual venue is unqualified.

For a home-margin threshold 3, partitions are ≤2 / exactly 3 / ≥4. `gt` pays 0/0/1, `ge` 0/1/1, `lt` 1/0/0 and `le` 1/1/0. Away spreads invert sign and comparator. Half-point boundaries have no equality state; total 110.5 partitions are ≤110 / ≥111. Supported pushes return actual purchase stake and retain entry fees. Returned/unknown refund fees remain unavailable where equality is reachable. Unknown quantities, fees, settlement charges and material payouts remain unknown.

Independent one-contract complementary fixtures use Kalshi .47/.48/.49, US .49 and fees .02 + .01: net +.01 / .00 / −.01. The browser keeps original hypothetical .68/.33 prices: supported pairs net −$3.86 or −$68.88 per 100, and two Short combinations are unavailable. No quote was changed to manufacture a positive result. Exceptional payouts/probabilities are unresolved, so unconditional EV and all-outcome guarantees remain unavailable.

The generic reference integration interface requires `completed_first_half_only`, exact NBA game/market/native side and complete reachable partition probabilities. Winner/integer equality mass is required; full-game probabilities, rankings, ratings, season forecasts and projected final scores are rejected. Receipt/publication/start/cutoff clocks prevent future leakage. No model is acquired. Synthetic BPI-shaped .3 below/.1 equal/.6 above references produce −$29.53 for the retained inclusive winner/spread; total .4/.6 produces −$29.53. A separately labeled manual total p=.6 yields −$9.53. Missing models do not block supported comparisons or conditional Arb.

## Verification and next work

[Browser and exact replay](../evidence/b5-nba-first-half-20260922/final-reconciliation.json) covers all three H1 families, unavailable winner/Short structures, period/family filters, Stop and reopening. All three reference Details DOMs reproduce exactly; the manual result and basis are preserved. Fresh-process disk replay after preview shutdown reproduces snapshot, 16 Arb/16 EV baseline rows, filters and calculations. [Prior replay](../evidence/b5-nba-first-half-20260922/prior-reconciliation.json) preserves prior sport and NFL/NCAAF-H1 snapshots/calculations/evidence. Failed test/harness attempts are retained with [repair notes](../evidence/b5-nba-first-half-20260922/repair-record.md).

Venue integration, market support owns actual selected H1 listings, ACHIEVEMENTS tie applicability, current native rules/fees/depth, fractional/three-way portfolios and exceptional/refund payouts. Reference integration owns actual H1 distributions and independence. Existing full-game forecasts or Pinnacle h2h cannot substitute. Broader reference integration, market support remains open.

**Next independent engineering slice: men's Division I NCAAB pregame first-half winner/spread/total**, preserving the existing four-school 2026–2027 bounds and reviewing its first 20-minute half separately. Pregame H1 W/S/T remains required for beta. H2 offered at halftime is later stretch; quarters/futures/in-play and unselected MLB/NHL period equivalents are outside this slice. MoneyPuck dropped/NHL analytics deferred, KenPom deferred, ProphetX selected and requests pending. No collection, credits, credentials, outreach, spending, existing-beta restart, migrations, trading, commits, pushes or publication.
