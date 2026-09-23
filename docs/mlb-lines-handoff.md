# MLB full-game run-line/total handoff

**COMPLETE — bounded offline engineering and isolated synthetic acceptance, September 22, 2026.** Actual venue/model qualification and full reference integration, market support remain open. **Beta NOT READY FOR SIGNOFF.**

[Acceptance report](../evidence/b5-mlb-lines-20260922/final-report.md) · [implementation identity](../evidence/b5-mlb-lines-20260922/implementation-identity.json) · [prior reconciliation](../evidence/b5-mlb-lines-20260922/prior-reconciliation.json).

HEAD `c7204c98fc78cde2f314a3227c03c7d6d70fbe2a`; uncommitted app/test/script SHA-256 `4b6b131e88813e0ffb5fee12af0379268f7550d56847ec784ef6dde1efbd0585`, 326 files. Before editing, all 323 NCAAF accepted implementation files matched SHA `09d57d420ee619bcb2b62b81670aba379289661ab7f0eb8988954416d7800f80`. All 60 NCAAF and 58 NFL recorded evidence files remain unchanged. No commit made.

## Product and supported semantics

Ordinary Predict now supports explicitly reviewed MLB full-game integer/half-run spreads and combined-run totals through the existing projection, score partitions, fee/depth/refund calculations, references, Details, filtering, Stop and saved-history paths. There is no separate calculator or dashboard. Titles display extra innings, action, game number and runs; contract rows display native side, signed subject, normalized inequality and equality behavior. Missing models do not block supported conditional price comparisons.

The unchanged MLB registry/event key covers the existing 30 teams and aliases, calendar season, regular season/playoffs, explicit home/away, reviewed shared game ID, game number 1/2, timezone-aware original/current start and scheduled/rescheduled status. Both dates must fall in the declared calendar year. This is a generic identity bound, not historical season qualification: fixtures exercise 2026. Line reviews additionally bind native competition/sport paths. Repeated opponents and doubleheaders remain distinct; conflicting dates, game numbers, stage, season or reschedule lineage cannot match by name.

A retained line review binds exact native source/event/market IDs, original body hash, descriptor/event/terms/fee paths and outcome IDs/operators. Run lines normalize signed home/away handicap to home-minus-away margin; totals use combined runs. Different lines/reviews retain distinct identities. Full-game nine-inning format, all extra-inning runs including automatic runners, action pitcher conditions and normal completed-game scope must be explicit. Ordinary completion includes the home-leading final-half exemption and walk-off finish; it does not imply every game plays all nine home half-innings.

`mlb_lines.py` requires a line-specific normal completion review and explicit exceptional-term keys. Shortened/format-changed, suspended/resumed, postponed, cancelled, abandoned, forfeited, tied, void/refund, venue-change and correction outcomes retain each source's terms. Missing exceptional payouts/probabilities remain unknown and **all results are conditional**. Listed-pitcher or unknown pitcher scope, shortened-game calculation scope, scheduled-innings-only, first-five/other innings, team totals, series/futures and in-play are unsupported. No winner completion rule is inherited.

Zero-margin equality is retained, even at a zero run line. The engine does not assume ties impossible. Binary complements, strict pairs with stake pushes, and unknown equality remain separate. Material integer equality requires its probability mass. Half-run equality is unreachable under integer run scoring. Supported push cashflows return actual consumed purchase stake and retain entry fees; returned/unknown refund fees remain unavailable at material equality. Other exceptional outcomes are excluded from conditional EV rather than forced into binary payouts.

Kalshi line fees require their own `KXMLBSPREAD`/`KXMLBTOTAL` series, supported type and explicit multiplier; `KXMLBGAME` fees are refused. The retained catalog has quadratic type and multiplier **0.5** for both line series. Tests independently verify that case. Shared-oracle/browser fixtures explicitly use hypothetical multiplier 1 and maker-fee type to preserve the unchanged arithmetic oracle; they do not assert current MLB fees. PMUS uses only its own fee coefficient and observed purchase shape; Short remains unavailable in the fixture. Unknown fees/size/settlement charges cannot supply dollars.

The existing reference integration `score_distribution` interface accepts explicit complete exact-line partition probabilities bound to the reviewed game, native side, line and extra-innings/action conditional meaning. No probability fitting occurs. Predicted runs/scores, moneyline, ratings and season outputs cannot supply line EV; wrong-game/doubleheader and missing equality inputs are rejected. Manual half-run scenarios remain labeled. Fixture FanGraphs identity is a synthetic provider-shaped receipt, not an actual forecast or independence claim. Publication/receipt/cutoff gates and immutable reference links are preserved.

## Official contracts and retained evidence

[Native audit and document hashes](../evidence/b5-mlb-lines-20260922/native-contract-audit.json) separate catalog/documentation from actual selected listing qualification.

- Retained catalog rows independently link `KXMLBSPREAD` to [BASEBALLSPREAD](https://assets.kalshi.com/contract_terms/BASEBALLSPREAD.pdf) and `KXMLBTOTAL` to [BASEBALLTOTALS](https://assets.kalshi.com/contract_terms/BASEBALLTOTALS.pdf). First-five, inning, team-total and series-game-count rows are separate. Sharing a document URL does not establish full-game scope.
- Both current documents count extra-inning runs, specify predicates and official shortened results, and contain 48-hour interruption provisions with fair-market-price discretion. This is not automatically a purchase-stake refund. Spread explicitly addresses pitcher changes, tied zero differential, format/home-away changes and protests. Total has different venue wording and does **not independently establish action pitcher conditions**. Selected total listing evidence remains necessary; no missing clause is inferred.
- The [retained ProphetX MLB amendment](../evidence/phase-0/prophetx-mlb-rules-amendment.pdf), pages 6–7, distinguishes general nine/8.5-inning completion from moneyline five/4.5-inning shortening. It describes same-local-day postponement voiding, 36-hour suspension, extra innings and integer spread/total voids. Its truncated “or” and incorrect 4.5-inning cross-reference remain unresolved. Collateral return wording does not qualify purchase-stake/fee cashflows. No current production applicability or equivalence is asserted.

No fresh market/model acquisition occurred. Existing native adapters remain unchanged; the review interface consumes retained explicit annotations, not guessed listing titles. Synthetic annotations cannot qualify observation mode. No actual compatible cross-venue MLB line pair is qualified.

## Remaining owners and next work

- **venue integration, market support:** actual MLB native run-line/total listings, game discriminators, side/sign/period fields, applicable source contracts (especially total pitcher conditions), fee history/overrides, usable quantities, and exceptional/refund economics. PMUS US-specific rules remain missing; Novig/ProphetX requests pending.
- **reference integration:** actual exact-line distributions, provenance/independence and compatible MLB Pinnacle inputs. Prior NFL h2h sample is preserved; no additional credit/request.
- **market support:** unsupported pitcher/shortened/refund economics, innings/team totals, portfolios/quarter stakes, series/futures, actual historical qualification and result/settlement linkage remain open.
- **Next independent engineering:** bounded **NHL full-game puck-line/total mapping**, including overtime/shootout goal treatment, using the shared partition engine.

MoneyPuck dropped/NHL analytics deferred; KenPom deferred; ProphetX selected. No collection, credentials, outreach, spending, existing-beta restart, migrations, trading, commits, pushes or publication. Beta remains NOT READY FOR SIGNOFF.
