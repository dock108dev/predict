# B5 NCAAF pregame first-half winner/spread/total handoff

**COMPLETE — bounded NCAAF pregame first-half winner/spread/total engineering, offline verified September 22.** 424 Python tests and two JS suites pass; original 18-Arb/96-EV and prior saved results remain exact. Bounded engineering only; actual venue/model qualification and full B4/B5 remain open. **Beta NOT READY FOR SIGNOFF.** Pregame H1 W/S/T remains required for beta; second-half offered at halftime is stretch.

## Identity and ordinary behavior

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; app/test/script SHA-256 **`bc4939ec356c6b9d5830463e72e22103d30494aec39d2be2caf6301f67c7176e`**, 336 files. [Exact manifest](../evidence/b5-ncaaf-first-half-20260922/implementation-identity.json) · [acceptance](../evidence/b5-ncaaf-first-half-20260922/final-report.md). Before editing, all 332 NFL H1 implementation files and 84 immutable evidence files matched. Existing changes, including an unrelated `requirements-ci.txt` edit, were preserved. No commit or publication.

The six-school **2026** boundary is unchanged: Alabama, Miami FL, Miami OH and North Dakota State are FBS; Alabama A&M and South Dakota State are FCS. Existing reviewed aliases, ambiguous “Miami,” unreviewed-school exclusions, subdivision membership, original/current timezone-aware starts, season/stage, shared game ID, reschedules and neutral/home/unknown site use `ncaaf.event_key`. No school census or fuzzy matching was added. Home/away designations do not imply home advantage.

Ordinary Predict now accepts explicit NCAAF H1 winner, spread and combined-total reviews. Each binds native source/event/market, retained body hash, event/descriptor/terms/fee paths, selected period, spread participant/sign or exact total, native outcome orientation and equality/refund behavior. H1, full game, H2 and quarters cannot collide. Winner remains unlined and evaluates a zero-margin partition internally. College completion and subdivision gates live in `ncaaf_first_half.py`; competition-neutral H1 payout/result mechanics are shared in `first_half.py`, preserving NFL output.

First-half titles show the period, subdivisions and site. Existing Details, period/family filters, source health, unsupported coverage, Start/Stop, immutable cutoff links and saved reopening are reused. Missing models leave comparisons and supported conditional Arb available. No duplicate calculator, dashboard or collection path.

## College contracts and settlement

[Native/document audit](../evidence/b5-ncaaf-first-half-20260922/native-contract-audit.json) · [public document hashes](../evidence/b5-ncaaf-first-half-20260922/public-document-manifest.json).

- [2026 NCAA rules, Rule 3-2-1](https://ncaaorg.s3.amazonaws.com/championships/sports/football/rules/PRMFB_RulesBook.pdf) define the first half as the first two 15-minute periods, with referee/dead-ball and final-play review completion. The supported descriptor requires those periods definitively completed. H2 and possession-series overtime/tries never contribute to H1 scoring. The offline result check requires the exact event and explicit completed-H1 score; it is not a result collector or venue settlement authority.
- Retained **college** catalog entries link `KXNCAAF1H`, `KXNCAAF1HSPREAD`, `KXNCAAF1HTOTAL` to current [winner](https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf), [spread](https://assets.kalshi.com/contract_terms/FOOTBALLSPREAD.pdf), [total](https://assets.kalshi.com/contract_terms/FOOTBALLTOTALS.pdf) templates. Their own retained fee type is quadratic, multiplier 1, not the full-game college fee context. Native listing/period/tie/fee/depth qualification remains missing.
- The winner template distinguishes strict period wins and a listed tie strike; where that strike is listed, tied-period team strikes lose. Full-game fractional tie rules do not transfer. Templates retain completed-period exceptions to suspension/abandonment and separate postponement, shortened/official-final, forfeit, venue-change, correction and discretionary fair-price provisions. The total's malformed amendment wording remains unresolved. Fair price is not a stake refund; 55-minute full-game rules do not establish completed H1.
- `FOOTBALLARCHIVED` again returned **404**. Archived `KXNCAAF1HWINNER` and FCS contracts are not interchangeable with current college rows. **FCS-only H1 remains unsupported for every source in this slice**, even when a fixture supplies a generic FBS review. FBS/FBS and explicitly bound cross-subdivision inputs can exercise the reviewed interface, without actual venue qualification.
- PMUS H1 rules, DNB availability, Short quantity, current fees and exceptional/refund applicability remain unqualified. Fixtures use explicit hypothetical annotations with its own retained coefficient/Long conversion. Novig/ProphetX economics remain unsupported; NFL ProphetX catalog evidence cannot qualify college H1. No source economics or rules are borrowed.

## Independent payout and probability contract

Normal H1 ties remain reachable for every college stage. The full-game winner-producing college tiebreaker never removes them. Supported annotations describe binary strict team-win/not-win or two-way draw-no-bet with explicit stake refunds. Three-way/unknown structures and unreviewed tie strikes remain visible and unsupported.

Per $1 face-value contract, `S` means actual consumed purchase stake:

| Contract | Away ahead | Tie | Home ahead |
|---|---:|---:|---:|
| Home strictly wins | 0 | 0 | 1 |
| Home not-win | 1 | 1 | 0 |
| Away strictly wins | 1 | 0 | 0 |
| Home draw-no-bet | 0 | S | 1 |
| Away draw-no-bet | 1 | S | 0 |
| Both positive team-win legs | 1 | 0 | 1 |

The last pair loses its entire entry cash at tie. It cannot claim guaranteed Arb. For a margin threshold 3, below/equal/above are ≤2 / 3 / ≥4: `gt` pays 0/0/1, `le` 1/1/0, `ge` 0/1/1 and `lt` 1/0/0. Away spreads invert signed handicap and comparator. Total 20.5 has only ≤20 / ≥21; integer totals retain equality.

Supported refunds return purchase stake and retain entry fees. Returned/unknown refund fees remain unavailable where equality is reachable. Unknown size, source fee/settlement levy and material payout remain unavailable. Exceptional probabilities/payouts remain unknown, so normal-period calculations are conditional, with no unconditional EV or all-outcome guarantee.

Independent one-contract complementary fixtures use Kalshi .47/.48/.49, US .49 and entry fees .02 + .01: net +.01 / .00 / −.01. The browser retains the original hypothetical .68/.33 quotes: complementary pairs net −$3.86 per 100; same-predicate minimum −$68.88. US Short pairs are unavailable. No original price was changed to manufacture a positive browser result.

The existing B4 `score_distribution` receipt requires `completed_first_half_only`, exact college game/site/subdivision, native side, family/line/predicate and complete partition probabilities. H1 winner/integer equality mass is mandatory. Full-game forecasts, ratings/ranks, season probabilities, projected final scores and wrong-period distributions are rejected. Source/publication/receipt/start clocks and replay enforce cutoff isolation. No model is acquired or fitted. Browser probabilities are explicitly synthetic: .3 below/.1 equal/.6 above produces −$29.53 for the .68 inclusive winner/spread contract; total .4/.6 likewise yields −$29.53. Manual total p=.6 yields −$9.53 and retains its what-if basis.

## Remaining owners and next slice

B3/B5 owns actual selected college H1 listings, source period/tie/completion rules, FCS applicability, native outcomes, current fee/override/depth and exceptional/refund economics. B4 owns actual H1 distributions and independence; missing analytics is not an engineering blocker. B5 retains broader schools/seasons, explicit tie-strike portfolios and result/settlement linkage.

**Next independent slice: NBA pregame first-half winner/spread/total**, preserving NBA identity and reviewing its own half/completion/tie/fee semantics. Men D1 NCAAB follows separately. H2-at-halftime remains stretch; quarters, futures, in-play and unselected MLB/NHL equivalents are outside this slice. MoneyPuck dropped/NHL analytics deferred, KenPom deferred, ProphetX selected and provider requests pending. No market/model collection, credits, credentials, outreach, spending, existing-beta restart, migrations, trading, commits, pushes or publication.
