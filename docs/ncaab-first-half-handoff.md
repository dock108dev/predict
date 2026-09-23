# Men’s Division I NCAAB pregame first-half handoff

**COMPLETE — bounded engineering, offline verified September 22, 2026.** 494 Python tests and two JavaScript suites pass. Actual venue/model qualification, unsupported payouts and broader reference integration, market support remain open. **Beta NOT READY FOR SIGNOFF.**

## Exact implementation and product behavior

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA256 **`160a1c5226cd4ebc9ce51dc529996e117d076e3454132800c9f53f1f9229fceb`**, 342 files. [Identity](../evidence/b5-ncaab-first-half-20260922/implementation-identity.json) · [acceptance](../evidence/b5-ncaab-first-half-20260922/final-report.md). Before editing, all 339 accepted NBA-H1 implementation files and 81 immutable evidence files matched. [Reconciliation](../evidence/b5-ncaab-first-half-20260922/pre-edit-reconciliation.json). Existing work, historical attempts and unrelated requirements-ci.txt changes were preserved.

Ordinary Predict now routes explicitly reviewed men's inventory projection NCAAB pregame H1 winner/spread/total annotations through the shared payout, fee/depth, reference, Details, filtering and Stop/history paths. Titles identify **first 20-minute half**, gender/division, stage and neutral/home/unknown site. No second-half or overtime score enters H1 settlement. There is no new dashboard, calculator or collection path.

Coverage is unchanged: **Alabama, Alabama A&M, Miami (FL), Miami (OH), 2026–2027 only**. Existing reviewed aliases, school IDs, gender/division, competition ID, two-half event structure, tournament ID/round, season, game ID, original/current timezone-aware start, reschedule and site metadata must bind exactly. Ambiguous Miami, other schools/seasons, women and other divisions stay unsupported. No home advantage is inferred from listing order or unknown site. Regular season and explicitly identified in-season/conference/NCAA/other postseason tournaments remain distinct; repeated opponents cannot merge by names.

Source annotations bind native event/market/outcome, retained receipt hash and native paths to exact period/family, threshold, participant/sign, strict/inclusive predicate, equality/refund behavior and own fee evidence. Winner is unlined; its internal score partitions use margin zero. Full game, H1, H2, quarters and generic period numbers are isolated. The new college-specific completion marker is `first_20_minute_half_definitively_completed`; NBA/football two-quarter markers fail closed. Missing material terms reject the review. Explicit unknown exceptional terms leave only conditional normal-half calculations, not assumed equivalent settlement.

## Reviewed contracts and actual data gaps

[Native audit](../evidence/b5-ncaab-first-half-20260922/native-contract-audit.json) · [retained series](../evidence/b5-ncaab-first-half-20260922/retained-series.json) · [public document hashes](../evidence/b5-ncaab-first-half-20260922/public-document-manifest.json).

- The current [NCAA men's 2026–27 rulebook](https://ncaaorg.s3.amazonaws.com/championships/sports/basketball/rules/men/PRMBB_RulesBook.pdf), August 2026, Rule 5 specifies two 20-minute halves. End-period shot/foul activity can affect definitive completion. A tied first half remains a tie; overtime follows a tied second half. Interrupted-game continuation and forfeit sporting rules do not determine venue payout, refund or cancellation. This slice accepts only an exact-event, explicitly completed H1 sporting score; the helper is not an automatic result collector or venue settlement engine.
- Retained **KXNCAAMB1HWINNER → [ACHIEVEMENTS](https://assets.kalshi.com/contract_terms/ACHIEVEMENTS.pdf)**. The generic achievement template contains shared-winner allocations, cancellation/fair-allocation and shortened-official-result provisions. It does **not** establish the actual selected first-half winner tie interpretation. Binary/DNB fixtures are hypothetical supported structures, not qualification of that series. Fractional/shared-winner and three-way payouts remain unavailable; no NBA winner template is reassigned.
- **KXNCAAMB1HSPREAD → [BASKETBALLSPREADS](https://assets.kalshi.com/contract_terms/BASKETBALLSPREADS.pdf)** and **KXNCAAMB1HTOTAL → [BASKETBALLTOTALS](https://assets.kalshi.com/contract_terms/BASKETBALLTOTALS.pdf)** preserve selected segment and comparator. Spread interruption/delay provisions use 48 hours; total resumption uses 24 hours and delay two weeks. Fair-price settlement is not purchase-stake refund. Shortening, already-reached strikes and correction clauses remain source/contract-specific; football's completed-segment exceptions are not transferred.
- Each of those three retained college H1 series has its **own quadratic fee type, multiplier 1**. Full-game college winner fees are not reused. Actual selected native H1 period/achievement/tie/strike/side, current fee applicability/overrides and usable depth remain missing. PMUS requires its own US college H1 Long/Short, tie/refund and economics evidence; hypothetical Long uses its own existing fee/conversion path, and Short stays unavailable. Novig/ProphetX college native rules, quantities and fees remain unqualified. No borrowed venue economics.

## Independent payout and arithmetic tables

Per $1 face contract; `S` is actual consumed purchase stake, excluding retained entry fees:

| Structure | Away ahead | Tie | Home ahead |
|---|---:|---:|---:|
| Home strictly wins | 0 | 0 | 1 |
| Home not-win | 1 | 1 | 0 |
| Away strictly wins | 1 | 0 | 0 |
| Home draw-no-bet | 0 | S | 1 |
| Away draw-no-bet | 1 | S | 0 |
| Both positive team-win legs | 1 | 0 | 1 |
| Fractional/shared achievement/three-way | Unsupported | Unsupported | Unsupported |

Two positive team-win contracts leave the tie unpaid; their normal minimum net is negative entry cash, not guaranteed arbitrage. DNB requires opposing strict outcomes and explicit purchase-stake refunds. Unknown/returned refund fees remain unsupported when equality is reachable.

| Predicate at home margin 3 | Margin ≤2 | Margin =3 | Margin ≥4 |
|---|---:|---:|---:|
| gt | 0 | 0 | 1 |
| ge | 0 | 1 | 1 |
| lt | 1 | 0 | 0 |
| le | 1 | 1 | 0 |

Away spread orientation reverses sign/comparator. Integer boundaries retain equality; total 70.5 has only ≤70 / ≥71. Later-period score changes do not alter these first-half partitions. Supported pushes return purchase stake while entry fees remain charged. Missing size, fees, completion or material outcome cashflows remain unknown/conditional/unavailable.

Independent one-contract complementary examples: Kalshi .47/.48/.49 + PMUS .49 + own fees .02/.01 produce **+.01 / .00 / −.01**. The browser preserves hypothetical original .68/.33 inputs: supported pairs **−$3.86 / −$68.88 per 100**, two Short combinations unavailable in each family. No positive result was manufactured. Unknown exceptional payouts/probabilities prevent unconditional EV and all-outcome guarantees.

The reference integration interface requires `completed_first_half_only`, exact college game/market/native side and every reachable partition probability. Winner/integer equality mass is required. Full-game probabilities, rankings, projected scores and tournament/season probabilities cannot substitute. Receipt/publication/start/cutoff gates prevent future leakage. No model acquired; KenPom remains deferred. Labeled synthetic BPI-shaped distributions (.3 below/.1 equal/.6 above for winner/spread; .4/.6 for total) produce **−$29.53** for the selected inclusive Kalshi side. A separately labeled manual total p=.6 gives **−$9.53**; scalar winner .6 remains unavailable for missing tie mass. Missing analytics does not block supported comparisons or conditional Arb.

## Acceptance and remaining work

[Acceptance report](../evidence/b5-ncaab-first-half-20260922/final-report.md) links all 23 new checks, full regressions, original18-Arb/96-EV oracle, independent arithmetic and browser evidence. [Saved replay](../evidence/b5-ncaab-first-half-20260922/final-reconciliation.json) reproduces snapshot, 16 Arb/16 EV baseline rows, all filters, Details/reference/manual calculations after Stop and preview shutdown. [Prior replay](../evidence/b5-ncaab-first-half-20260922/prior-reconciliation.json) preserves prior winner/line and NFL/NCAAF/NBA-H1 evidence and outputs.

Only this four-school college H1 engineering slice is complete. Venue integration, market support owns actual native listings, tie/period/completion terms, fees/depth and exceptional/fractional/refund payouts; reference integration owns actual forecasts/independence. Broader college teams/seasons, futures, result linkage and undecided MLB/NHL periods remain visible in the [reconciled backlog and next slice](market-data-gaps.md). **Recommended next: bounded NFL sporting-result and venue-settlement linkage for existing full-game/H1 winner/spread/total**, offline first. No new period choice is implied. H2-at-halftime is stretch. MoneyPuck dropped/NHL analytics deferred; KenPom deferred; ProphetX selected, requests pending. No acquisition, credits, credentials, outreach, spending, existing-beta restart, migrations, trading, commits, pushes or publication. **Beta NOT READY FOR SIGNOFF.**
