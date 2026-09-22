# B5 MLB full-game winner — bounded engineering complete

September 21, 2026. **COMPLETE — offline engineering only. Beta NOT READY FOR SIGNOFF. Full B5, full B4 and actual venue/model qualification remain open.**

[Acceptance report](../evidence/b5-mlb-20260921/final-report.md) · [implementation identity](../evidence/b5-mlb-20260921/implementation-identity.json) · [retained source audit](../evidence/b5-mlb-20260921/retained-native-audit.json) · [acceptance tests](../tests/test_b5_mlb.py).

## Ordinary product behavior

Predict's existing session projection, Details, filters, reference interface, settlement profiles, fee/depth engine and saved-history readers now accept reviewed MLB two-way, unlined, single full-game winners **including extra innings, with action conditions**. No separate dashboard or calculator. Negative results remain valid; missing model values do not block price comparisons or conditional Arb. Saved coverage says “retained at cutoff” after Stop.

All 30 existing MLB teams and prior native mappings are preserved. Added reviewed local aliases: LA Dodgers and LA Angels. City-only New York/Los Angeles remain ambiguous; no new provider team IDs were invented. Existing canonical entity IDs remain unchanged. Historical franchise names require a separate review; no fuzzy matching or relocation inference.

`mlb.event_key` requires competition MLB, sport baseball, explicit calendar season, regular season/playoffs, reviewed home/away, timezone-aware scheduled **and original** starts, a shared reviewed game ID, game number 1/2, and scheduled/rescheduled status. Games pair only when all identity fields agree. Exact instants with different timezone offsets agree. Doubleheaders and repeated opponents remain separate; conflicting IDs, duplicate native events, starts, season, stage, orientation or reschedule lineage fail closed. Current support conservatively requires both starts in the declared calendar year. Suspended/in-progress/cancelled event status is unsupported for this pregame slice.

`mlb_review` binds source, native event/market IDs, evidence mode, exact listing SHA256, event identity and retained JSON paths/literals for game ID, game number, original/current start, home/away, season, stage and schedule status. It also requires an explicit full-game scope literal and reviewed outcomes. Native Kalshi KXMLBGAME event/YES/NO and PMUS event/team/Long/Short orientation must agree. Review is an explicit local annotation interface; it does not manufacture provider metadata or automatically classify unfamiliar prose. Synthetic annotations cannot qualify real observations. Novig/ProphetX native MLB orientation remains unsupported pending evidence.

Full-game terms must explicitly cover extra innings, two-way outcomes, pitcher conditions, shortened games, suspension, postponement, cancellation, tie, void/refund, forfeit, venue change and corrections. Identical reviewed terms are required for pairing; differences stay visible as unmatched settlement. Listed-pitcher contracts, unknown terms, first-five and other innings, series winners, futures, spreads/totals and three-way contracts remain unsupported. No universal MLB settlement rule is asserted.

## Economics and references

The existing calculation engine receives MLB-specific settlement profiles and fee bases. Kalshi requires `KXMLBGAME`, the supported quadratic-with-maker-fees type and an explicitly evidenced 0.5 or 1 multiplier. The retained series snapshot specifies **0.5**; 1 is exercised only as an explicit synthetic scenario. PMUS needs its own supported coefficient evidence. No NFL/NHL series or third-venue fees are borrowed. Unknown asks, size, fees or material payouts remain conditional/unavailable. Account precision, absent event overrides and PMUS settlement-charge assumptions remain labeled what-ifs. Exceptional probabilities and unconditional EV are unavailable; conditional profit is not qualified all-outcome arbitrage.

The existing B4 original-input importer accepts an explicitly published **home-win** MLB probability with exact reviewed game, date, game number, home/away, full-game, extra-innings and action meaning. No away complement is generated. Ratings, ranks, season/playoff odds, projected standings, wrong-game and unreviewed legacy inputs cannot supply EV. The test's 60% input is synthetic, not an actual FanGraphs forecast or a claim of provider independence. Manual probability plus basis remains labeled what-if. Native input and reference clocks are checked against cutoff; later observations cannot enter an earlier saved prefix.

## Actual source evidence and gaps

| Source | Established | Remaining qualification |
|---|---|---|
| Kalshi | Retained KXMLBGAME series, fee-change response and BASEBALLGAMEWIN contract; hashes verified | Exact MLB native game/participant/period/action terms, current listing and fee override binding, usable book |
| Polymarket US | Existing native side and fee/depth handlers, MLB review path fixture-tested | Actual US MLB winner listing, event/game discriminator, action/status rules and fee binding; international Polymarket is not a substitute |
| Novig | Generic adapter; public offering distinguishes MLB moneyline and first-five markets | Actual native MLB identity/period/settlement/economics; request sent, pending |
| ProphetX | Retained sandbox MLB tournament 109 and historical public MLB rule amendment | Production event/market/outcome binding, contract applicability, quantity ownership/units and fees; selected, request pending |
| MLB model | Explicit game-probability interface verified synthetically | No actual forecast or provider independence qualified; no acquisition performed |
| Pinnacle | Prior authorized NFL sample preserved | No MLB sample or compatible MLB reference-EV qualification; no additional request/credit |

Official documentation informs review, not current listing qualification. Kalshi's [BASEBALLGAMEWIN filing](https://kalshi-public-docs.s3.us-east-1.amazonaws.com/regulatory/product-certifications/BASEBALLGAMEWIN.pdf) separates full-game and inning scopes, includes extra innings unless excluded, specifies tie treatment and official shortened-game outcomes, and contains 48-hour resumption/postponement and makeup-game rules. Its general contract does not establish a particular listing's pitcher conditions. The retained [ProphetX amendment](../evidence/phase-0/prophetx-mlb-rules-amendment.pdf), pages 6–7, instead specifies local-calendar-day postponement voiding, a 36-hour suspension rule with exceptions, and moneyline-specific shortened-game treatment. Its internal 4.5-innings cross-reference needs confirmation against an applicable current listing. These documents are **not equivalent settlement evidence**. [MLB team directory](https://www.mlb.com/team) and [Novig offering documentation](https://support.novig.com/en/articles/10336189-what-sports-are-available-on-novig) support names/market distinctions only.

## Next independent slice and boundaries

The subsequent [NBA full-game winner engineering slice](b5-nba-handoff.md) is complete offline. Its [reconciliation](../evidence/b5-nba-20260921/mlb-reconciliation.json) verified this MLB implementation before edits and reproduced the prior saved snapshot and all Arb/EV results exactly afterward. The subsequent [NCAAF slice](b5-ncaaf-handoff.md) is also complete offline, with MLB exact replay preserved. Next independent slice: **NCAAB full-game winners**, beginning with competition/gender/division scope.

Broader B5 still includes MLB listed-pitcher qualification/economics, spreads/totals, innings and futures, other sports and result/settlement linkage. No beta exclusion is implied. MoneyPuck remains dropped; NHL analytics and KenPom remain deferred. Pinnacle allowance remains consumed. No market/model collection, credential access, provider messages, spending, beta restart, migration, trading, commit, push or publication occurred. Historical evidence, consumed attempts and unrelated changes are preserved.
