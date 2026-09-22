# B5 NCAAB full-game winners — bounded engineering complete

September 21, 2026. **COMPLETE — offline engineering only. Beta NOT READY FOR SIGNOFF.** Actual venue/model qualification and broader B4/B5 remain open.

[Acceptance and exact identity](../evidence/b5-ncaab-20260921/final-report.md) · [tests](../tests/test_b5_ncaab.py) · [next shared spread/total slice](b5-score-lines-next.md).

## Scope and visible behavior

The owner selected **men’s Division I** during this slice. Ordinary Predict supports reviewed single full-game winners including college overtime, price comparisons without a model, conditional Arb/EV, explicit unsupported cases, filtering, source health, Stop and immutable saved reopening. It uses the existing dashboard, reference importer and fee/depth/settlement engines. There is no new collection default, provider connection or separate calculator.

The registry contains **four men’s Division I teams for 2026-2027 only**. This is a bounded reviewed roster, not broad NCAAB coverage. Women’s teams, other divisions, unreviewed schools and other seasons remain unsupported. No broader beta exclusion is inferred beyond the owner’s men’s Division I selection for this slice.

| Team / canonical suffix | Reviewed aliases | Dated membership evidence |
|---|---|---|
| Alabama Crimson Tide / ALA | Alabama, University of Alabama, ALA | [NCAA 2026-2027 directory](https://web3.ncaa.org/directory/orgDetail?id=8), [men’s program](https://rolltide.com/sports/mens-basketball) |
| Alabama A&M Bulldogs / AAMU | Alabama A&M, Alabama A&M University, AAMU | [NCAA directory](https://web3.ncaa.org/directory/orgDetail?id=6), [men’s program](https://aamusports.com/sports/mens-basketball) |
| Miami (FL) Hurricanes / MIAFL | Miami (FL), Miami FL, Miami Hurricanes, University of Miami | [NCAA directory](https://web3.ncaa.org/directory/orgDetail?id=415), [men’s program](https://miamihurricanes.com/sports/mbball) |
| Miami (OH) RedHawks / MIAOH | Miami (OH), Miami OH, Miami RedHawks, Miami University | [NCAA directory](https://web3.ncaa.org/directory/orgDetail?id=414), [men’s program](https://miamiredhawks.com/sports/mens-basketball/roster) |

Team IDs are local `NCAAB:M:D1:<suffix>` identities with separate local school IDs. They are not fabricated venue participant IDs. “Miami” is explicitly ambiguous. Mascot-only names, USC/SDSU, satellite-campus names and unreviewed schools cannot resolve. Football membership and NBA identities are not reused as basketball membership evidence.

## Event and native review contract

`app/normalization/ncaab.py` requires basketball/NCAAB plus explicit `gender=men`, `division=I`, `competition_id=NCAA:M:D1`, consecutive season years, two season-reviewed school teams, school bindings, designated home/away, aware original/current starts, shared game ID and consistent scheduled/rescheduled status. The conservative calendar envelope is November through the following April. Site status is supplied neutral, supplied home, or explicitly unknown; designations never imply home advantage.

Regular-season games use explicit not-applicable tournament/round values. In-season, conference, NCAA and other postseason tournament **games** require a reviewed tournament ID and round. Every field enters the event key and exact native JSON-path/literal/hash binding. Same opponents, different dates, rounds, reschedules or competitions do not establish equivalence. Conflicting and duplicate bindings fail closed. Generic names-only matching cannot qualify NCAAB because its observations lack this college context; ordinary reviewed matching remains the supported path.

The `ncaab_review` interface requires exact source/event/market IDs, evidence mode, original listing hash, all event identity paths, full-game scope and native outcome orientation. Kalshi must be the separately reviewed `KXNCAAMBGAME` series with the correct YES participant; PMUS requires its own event and both team/Long/Short bindings. Women’s `KXNCAAWBGAME`, college baseball `KXNCAABBGAME`, NBA and football series cannot substitute. Native milestone/start schemas remain unverified, so the adapter leaves start unknown. Novig/ProphetX native college outcome mappings remain unsupported pending evidence. Synthetic review annotations cannot qualify observation mode.

## Rules, economics and references

The [NCAA period comparison](https://ncaaorg.s3.amazonaws.com/championships/sports/basketball/rules/common/2025-26PRXBB_MajorRulesDifferences.pdf) distinguishes men’s 20-minute halves and five-minute overtime from women’s quarters. The [2026 rules committee report](https://www.ncaa.org/media-center-mens-basketball-rules-committees-discuss-state-of-the-game/) discusses a possible future move to quarters, not a completed change. Only two 20-minute halves plus repeated five-minute overtime is implemented here. Regulation-only, halves, quarters, tournament/conference winners and futures remain separate markets.

The retained Kalshi catalog points `KXNCAAMBGAME` to [ACHIEVEMENTS](https://assets.kalshi.com/contract_terms/ACHIEVEMENTS.pdf), **not the NBA game contract**. Its broad achievement definition does not itself establish a particular single-game/OT listing. It has distinct postponement/suspension horizons, cancellation allocation, co-winner, forfeiture and early-ending provisions. The [PMUS AEC amendment](https://www.cftc.gov/filings/orgrules/rules03262641984.pdf) permits game and broader competition scopes and uses its own expiration/discretionary rules. Neither source’s exceptions are asserted equivalent. Actual game-specific applicability remains a data gap.

Comparisons require identical, explicitly evidenced source terms for overtime, regulation/overtime format, outcome set, tie, suspension, postponement, cancellation, abandonment, shortened game, void, refund, forfeit, venue change and result corrections. The sporting format is retained in the shared settlement profile’s overtime dimension, avoiding a new payout engine or silent loss of format evidence. The compatible fixture terms are deliberately synthetic; they do not qualify any actual cross-venue combination. Unknown exceptional payouts/probabilities stay unknown; unconditional EV and all-outcome arbitrage remain unavailable.

Kalshi calculations require their own evidenced `KXNCAAMBGAME` quadratic-with-maker-fees basis and multiplier 1, corroborated by the retained catalog. PMUS needs its own supported coefficient evidence. Women’s, NBA and NCAAF fee applicability cannot transfer. Unknown fees, quantity or purchase asks remain unavailable; account precision, overrides and settlement charges remain conditional assumptions.

B4 references accept only explicit home-win or away-win game probabilities with exact event, team, competition/gender/division, school, season, site, round and overtime evidence. No probability complement, home advantage or independence is invented. Ratings/ranks, projected scores/margins/totals, tournament/season probabilities and unreviewed legacy values cannot supply game EV. Manual what-if inputs remain labeled. The ESPN-shaped 60% input is synthetic, not an acquired BPI forecast. Original receipt/publication/exchange clocks and journal prefixes enforce cutoff isolation.

## Remaining work

- **B3/B5:** actual NCAAB listings, participant IDs, current contract applicability, native game/round/site fields, usable books and source fees. Retained catalog evidence is not a qualified game observation. Novig/ProphetX requests remain pending.
- **B5:** remaining men’s Division I schools/seasons; spreads/totals, partial-game economics, futures, in-play and result/payout linkage. Women’s and other divisions are outside this bounded selection.
- **B4:** actual dated game forecasts/independence and compatible NCAAB Pinnacle input. KenPom stays deferred; no login, model acquisition or Odds API request/credit used.
- **Preserved:** NCAAF six-school 2026 limit and missing FCS rules; MoneyPuck dropped/NHL analytics deferred; completed prior-sport/B2/B3/B4 engineering and immutable evidence.

Next: [shared full-game score-line settlement and calculations](b5-score-lines-next.md), piloted through NBA and men’s Division I NCAAB spread/total fixtures. Six bounded winner slices do not complete six-sport coverage or B5. No new collection, credentials, messages, spending, existing-beta restart, migrations, trading, commits, pushes or publication occurred.
