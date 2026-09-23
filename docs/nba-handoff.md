# NBA full-game winner — bounded engineering complete

September 21, 2026. **COMPLETE — offline engineering only. Beta NOT READY FOR SIGNOFF. Actual venue/model qualification, full reference integration and broader market support remain open.**

[Acceptance report](../evidence/b5-nba-20260921/final-report.md) · [exact implementation identity](../evidence/b5-nba-20260921/implementation-identity.json) · [MLB reconciliation](../evidence/b5-nba-20260921/mlb-reconciliation.json) · [tests](../tests/test_nba.py).

## Supported ordinary behavior

Predict's existing projection, matching, Details, filters, reference interface and fee/depth/settlement engines support explicitly reviewed NBA two-way, unlined, single full-game winner markets including overtime. Price comparisons and conditional Arb do not require a model. Unsupported listings, rules and inputs remain visible with reasons. Start/Stop, immutable cutoffs and exact saved reopening use the existing product paths. No separate dashboard or calculation engine was added.

All 30 current teams have reviewed league-scoped aliases, including LA Clippers and Sixers. Los Angeles is ambiguous; NBA, WNBA, college and other competitions cannot share an identity. No native participant IDs were invented. The only added native registry mapping is the retained ProphetX **sandbox** NBA tournament 132; it does not establish production support. Names were checked against the [NBA team directory](https://www.nba.com/teams).

`nba.event_key` requires NBA/basketball, consecutive `YYYY-YYYY` season, explicit regular-season/play-in/playoffs/NBA-Cup stage, two reviewed teams, home/away, a shared reviewed game ID, timezone-aware current and original starts, and scheduled/rescheduled status. All fields must agree across sources. Repeated matchups remain distinct; duplicate native events, conflicting same-day bindings, stage/season/start conflicts and reschedule inconsistencies fail closed. The conservative season envelope is September through July; exceptional historical schedules, preseason, summer league, all-star and in-play/status transitions remain unsupported. NBA Cup game identity is distinct from a Cup tournament-winner contract.

`nba_review` binds exact source/event/market IDs, native receipt SHA256, evidence mode, event key and retained JSON paths/literals for competition, sport, season, stage, game ID, home/away, original/current start and status. Full-game scope and native outcome orientation require explicit review. Kalshi must match KXNBAGAME/event and native YES/NO participant; Polymarket US must match event and both native team/Long/Short sides. Synthetic mappings cannot qualify observations. Novig/ProphetX native NBA outcomes remain unsupported pending review. The annotation interface never guesses missing terms from names or titles.

Kalshi's retained NBA series can be parsed without expanding collection defaults. NBA milestone schema is unverified, so that adapter leaves start unknown; a reviewed native start is required before ordinary comparison. Shared native-review and settlement plumbing was extracted from MLB; NHL is unchanged and MLB's prior saved snapshot and complete Arb/EV outputs match exactly.

## Rules, economics and model meaning

Pairing requires identical explicit terms for overtime, outcome set, tie, cancellation, postponement, suspension, abandonment, shortened games, voids, refunds, forfeits, venue changes and corrections. Regulation-only, halves, quarters, overtime-only, spreads/totals, series, futures and three-way contracts remain unsupported. Unknown terms never establish equivalence.

The [Kalshi BASKETBALLGAMEWIN filing](https://kalshi-public-docs.s3.us-east-1.amazonaws.com/regulatory/product-certifications/BASKETBALLGAMEWIN.pdf), dated June 23, 2026, separates entire-game/OT and regulation/partial scopes. It specifies equal half-dollar tie settlement, 48-hour interruption conditions, NBA-specific completion/official-result criteria and different pregame/in-game forfeit treatment. The [Polymarket US AEC amendment](https://www.cftc.gov/filings/orgrules/rules03262641984.pdf) includes official-rule overtime but also permits game, series and season events. Its postponement/cancellation provisions depend on expiration and exchange discretion, with separate truncation, no-contest, replay and forfeit treatment. **These contracts do not establish equivalent exceptional settlement.** The [NBA overtime rule](https://official.nba.com/rule-no-5-scoring-and-timing/) establishes sporting overtime only, not a venue's refund policy. Retained documents and hashes are in the [public-document manifest](../evidence/b5-nba-20260921/public-document-manifest.json).

The compatible integration case deliberately supplies **identical synthetic terms**, not a claim that current Kalshi and PMUS contracts match. Kalshi economics require its own evidenced KXNBAGAME quadratic-with-maker-fees basis and supported multiplier 1; the retained series snapshot supplies that multiplier. PMUS needs its own coefficient evidence. No other venue's fees or quantity are borrowed. Account precision, absent event overrides and settlement charges remain labeled assumptions. Unknown asks/size/fees leave outputs unavailable; unknown material payouts and exceptional probabilities prevent unconditional EV or qualified all-outcome arbitrage.

The reference integration original-input interface accepts explicitly supplied **home-win or away-win** probability with exact NBA event, season, stage, start, team orientation and overtime meaning. No complement is invented. Ratings, power rankings, projected margins/totals, playoff/season odds, wrong-game and legacy unreviewed inputs cannot supply EV. The fixture's 60% ESPN-shaped receipt is synthetic, not an acquired BPI forecast or independence qualification. Manual what-if inputs remain labeled. Native receipt/exchange/observation clocks and reference publication/receipt clocks preserve cutoff isolation.

## Remaining data gaps and owners

| Work item | Missing evidence / next action |
|---|---|
| venue integration, market support Kalshi NBA | Actual listing, native participants/milestone schema, game/start/stage/status/full-game applicability, current fee overrides and usable book |
| venue integration, market support Polymarket US NBA | Actual US single-game listing, native orientation, exact event/rule applicability, matching exceptional terms and fee/depth evidence; international Polymarket is not a substitute |
| venue integration, market support Novig NBA | Native full-game identity, rules, orientation, purchase size/fees; owner request pending |
| venue integration, market support ProphetX NBA | Production event/market/participant bindings, applicable current rules, quantity ownership/units and fees; selected, request pending |
| reference integration NBA model | Actual dated game-win output and independence; no model acquired |
| reference integration, market support NBA Pinnacle | Actual NBA side/event/settlement binding; prior NFL sample and consumed credit preserved, no additional request |
| Broader market support | NBA spreads/totals, half/quarter economics, regulation-only/series/futures and result/settlement linkage |

The subsequent [NCAAF full-game winner engineering slice](ncaaf-handoff.md) is complete offline. Its [reconciliation](../evidence/b5-ncaaf-20260921/nba-reconciliation.json) verified all 306 NBA implementation files before edits and reproduced the saved NBA snapshot and all Arb/EV outputs exactly afterward. The subsequent [bounded NCAAB slice](ncaab-handoff.md) is also complete offline. Next: [shared full-game spread/total engineering](score-lines-next.md).

MoneyPuck remains dropped, NHL analytics and KenPom deferred. No new market/model collection, credential access, provider messages, spending, existing-beta restart, migration, trading, commits, pushes or publication occurred. The synthetic preview was stopped and closed. Historical evidence and consumed attempts remain intact.
