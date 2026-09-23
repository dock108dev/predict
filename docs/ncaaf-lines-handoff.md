# NCAAF full-game spread/total — bounded engineering handoff

**COMPLETE — offline engineering and isolated synthetic acceptance, September 21, 2026 local time.** Actual venue/model qualification and full reference integration, market support remain open. **Beta NOT READY FOR SIGNOFF.**

[Acceptance](../evidence/b5-ncaaf-lines-20260921/final-report.md) · [exact implementation](../evidence/b5-ncaaf-lines-20260921/implementation-identity.json). HEAD `c7204c98fc78cde2f314a3227c03c7d6d70fbe2a`; uncommitted app/test/script SHA-256 `09d57d420ee619bcb2b62b81670aba379289661ab7f0eb8988954416d7800f80`, 323 files. All 320 accepted NFL implementation files matched before editing. Original winner, basketball line and NFL saved outputs remain exact. No commits or publication.

## Scope and ordinary behavior

The existing six-school **2026** identities are preserved: Alabama (FBS), Alabama A&M (FCS), Miami FL (FBS), Miami OH (FBS), North Dakota State (FBS in 2026) and South Dakota State (FCS). Aliases, ambiguous “Miami,” season-specific subdivision, original/current timezone-aware start, stage, reschedule status, reviewed shared game ID and explicit neutral/home/unknown site status use `ncaaf.event_key` unchanged. Home/away are designations, not invented home advantage. Remaining schools/seasons/subdivisions are visible coverage gaps.

Ordinary Predict now dispatches explicitly reviewed NCAAF full-game integer/half-point spreads and combined totals through the existing score-partition, fee, depth, reference, Details, filtering and Stop/history paths. Each source review retains native event/market IDs, exact body hash, original descriptor/event/terms/fee paths, native side IDs/labels, signed handicap or total, points unit, strict/inclusive operator, equality and refund-fee behavior. Away spreads invert comparator and sign into home-minus-away margin. Different lines and revisions remain distinct. Title similarity does not establish equivalence.

Only explicitly reviewed all-regulation-plus-college-overtime scoring is supported. The descriptor must bind the 2026 NCAA possession-series rules, official final points including all extra-period tries, source-specific subdivision scope and the normal completed-game boundary. Regulation-only, half/quarter/overtime-only, team totals, conference/season futures, quarter stakes, portfolios and in-play remain separate. A conference championship game is distinct from a conference-winner future.

FBS/FBS and explicitly reviewed FBS/FCS scope can use the integration interface. **Kalshi FCS-only line contracts remain unsupported**, even if a fixture attempts to reuse the generic college series. No FCS contract is inferred from FBS or NFL terms. The six schools are identity coverage, not a claim that all pairings or venues are supported. Missing PMUS/Novig/ProphetX contract mappings remain their own qualification gaps.

Normal completed college games use a winner-producing tiebreaker. Zero-spread equality is excluded only when the retained review explicitly binds that completion and college overtime meaning. Nonzero integer boundaries retain equality mass; half-points have no integer equality. Shortened/suspended or mutually ended tied games are exceptional, not silently forced into a normal winner result. Their source terms/payouts remain separate and unsupported where unknown.

Binary complements, stake pushes and unknown equality remain distinct. Supported refunds return actual consumed purchase stake and retain entry fees; returned/unknown fee refunds remain unavailable at material equality. Source-specific fee applicability, quantities and settlement fees cannot be borrowed. Kalshi line series use their own retained series/type/multiplier; the NCAAF winner-fee branch is bypassed only for score-line payouts. Exceptional probabilities and payouts remain unknown, so calculations are conditional with no unconditional EV or all-outcome guarantee.

The existing reference integration `score_distribution` interface accepts explicitly supplied complete partition probabilities bound to the exact event, schools, subdivisions/site, line, source predicates and participant. Wrong-event, moneyline, score/margin, ranking/rating and season inputs cannot supply line EV. Missing equality mass is unavailable. Manual half-point inputs remain labeled what-if. No actual model is acquired or fabricated; college-model independence remains unverified. Source/publication/receipt cutoffs and exact immutable reopening remain enforced.

## Reviewed documents and native evidence

[Audit and retained hashes](../evidence/b5-ncaaf-lines-20260921/native-contract-audit.json) separate documentation/catalog evidence from actual selected market qualification.

- [2026 NCAA rules, Rule 3-1-3](https://ncaaorg.s3.amazonaws.com/championships/sports/football/rules/PRMFB_RulesBook.pdf): college overtime uses possession series, mandatory two-point tries after touchdowns from the second extra period and alternating two-point tries from the third. Regulation and extra-period points determine the winner. This establishes scoring, not exchange payout/refund policy.
- Retained Kalshi catalog rows independently link **KXNCAAFSPREAD** to [FOOTBALLSPREAD](https://assets.kalshi.com/contract_terms/FOOTBALLSPREAD.pdf) and **KXNCAAFTOTAL** to [FOOTBALLTOTALS](https://assets.kalshi.com/contract_terms/FOOTBALLTOTALS.pdf). Both retained fee contexts are quadratic-with-maker-fees, multiplier 1. The shared document URLs were verified from college rows, not assumed from NFL.
- These templates distinguish period, participant/combined score, comparison operators and OT. They separately discuss 55-minute/official-final completion, 48-hour interruption/postponement provisions, venue changes, forfeits and discretionary fair-price settlements. Their wording is not identical; the total document contains malformed duplicated interruption text. No repair or universal settlement equivalence is inferred.
- No dedicated FCS full-game line contract is established by the retained catalog. The historical FCS winner `FOOTBALLARCHIVED` gap remains open and is not fixed by these general templates. Actual selected listing sign, comparator, participants, series/fees and depth still require native evidence.

Fixtures contain clearly labeled hypothetical college review annotations and copied quote shapes. They deliberately invert native YES/NO orientation and leave US Short purchase unsupported. They do not assert official PMUS college line semantics or qualify actual cross-venue terms. Novig economics remain unsupported; ProphetX is not configured. Adapters and collection defaults remain unchanged; no title parser or fresh market collection was added.

## Remaining owners and next work

- **venue integration, market support:** selected native college line listings, applicable FBS/cross-subdivision/FCS contracts, side/period bindings, fee history, purchasable quantities and exceptional/refund economics for each venue. Broader school coverage remains market support work.
- **reference integration:** actual exact-line probabilities/distributions, provenance and independence; actual compatible NCAAF Pinnacle inputs. Existing h2h data and moneyline probabilities are not substitutes.
- **Next independent slice:** bounded **MLB full-game run-line/total mapping**, preserving doubleheaders, action/listed-pitcher conditions, extra innings and source-specific shortened-game rules while reusing the shared partition engine.

MoneyPuck dropped/NHL analytics deferred, KenPom deferred, ProphetX selected and Novig/ProphetX requests pending remain unchanged. No collection, credits, credentials, outreach, spending, existing-beta restart, migrations, trading, commits, pushes or publication. Full reference integration, market support remain open.
