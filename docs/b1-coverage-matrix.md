# B1 — working source, sport and market coverage matrix

Assessment completed September 20, 2026. **B1 COMPLETE; beta NOT READY FOR SIGNOFF.** Companion: [B2 implementation handoff](b2-product-integration-handoff.md). This is an assessment of the current working tree, retained evidence and bounded public official-source research, not a new qualification. No credentials, accounts or authenticated market data were accessed. Provider availability below is not an entitlement claim.

## How to use the matrix

Each cell combines its code below with its source record and its row's next action. This avoids repeating access, units and evidence in every cell. Every required source has six sport rows and every required market family has a column. Full-game moneyline, spread and total are separate from first half, second half, other sporting periods and season/tournament futures. A half/period column means each of winner, spread and total; support for one never implies the other two.

- **P**: retained production observations for this cell; bounded history, not currently fresh or full coverage.
- **S**: retained sandbox catalog/observations; no production qualification or sized comparison implied.
- **F**: implementation/fixtures only; no observed production or sandbox evidence established here.
- **D**: public provider documentation describes the offering; no project ingestion evidence.
- **U**: unknown availability at the specific sport/market/period; no connected product support. This is not a finding of absence.
- **N/A**: the sporting format has no literal halftime; the period-equivalent requirement remains a B5 decision.
- **C**: connected only to the legacy saved comparison path. All new coverage-session current comparisons are missing, including P cells; B2 owns that connection.

Generic parsers and type names do not prove coverage. `MarketType` currently recognizes only moneyline and unknown. Unless explicitly shown as C, cells are not connected to ordinary comparison/history views. Full-game rules (regulation, overtime, ties) remain source-specific. Live/in-play across every row is unqualified and a stretch goal; no pregame result transfers to it.

## Prediction venues

| Source | Sport | Full-game winner | Full-game spread | Full-game total | First half W/S/T | Second half W/S/T | Other period W/S/T | Futures | Next action / owner |
|---|---|---|---|---|---|---|---|---|---|
| Kalshi K | NFL | P+C | U | U | U | U | U | U | B3 K discovery; B5 native family/period rules |
| Kalshi K | NBA | U | U | U | U | U | U | U | B3 catalog; B5 NBA identities and definitions |
| Kalshi K | MLB | F | U | U | N/A | N/A | U, innings | U | B3 MLB sample; B5 innings/run-line rules |
| Kalshi K | NHL | U | U | U | N/A | N/A | U, periods | U | B3 catalog; B5 regulation/OT and periods |
| Kalshi K | NCAAF | U | U | U | U | U | U | U | B3 catalog; B5 competition/season mappings |
| Kalshi K | NCAAB | U | U | U | U | U | U | U | B3 catalog; B5 competition and period choice |
| Polymarket US P | NFL | P+C, Long only sized | U | U | U | U | U | D example only | B3 Short/discovery; B5 families/rules |
| Polymarket US P | NBA | U | U | U | U | U | U | U | B3 US catalog; B5 identities/families |
| Polymarket US P | MLB | U | U | U | N/A | N/A | U, innings | U | B3 US catalog; B5 innings/run-line rules |
| Polymarket US P | NHL | U | U | U | N/A | N/A | U, periods | U | B3 US catalog; B5 regulation/OT and periods |
| Polymarket US P | NCAAF | U | U | U | U | U | U | U | B3 US catalog; B5 competition mappings |
| Polymarket US P | NCAAB | U | U | U | U | U | U | U | B3 US catalog; B5 competition and period choice |
| Novig N | NFL | F+D | D | D | D | U | U | D | B3 provisioning/wire; B5 family normalization |
| Novig N | NBA | D | D | D | D | U | U | D | B3 discovery extension; B5 families |
| Novig N | MLB | F+D | D | D | N/A | N/A | D first-five W/S/T; other U | D | B3 wire; B5 innings/settlement |
| Novig N | NHL | D | D | D | N/A | N/A | U | D playoffs; others U | B3 discovery; B5 periods/futures |
| Novig N | NCAAF | D football category | D football category | D football category | D football category | U | U | D football category | B3 confirm college-specific API listings; B5 mappings |
| Novig N | NCAAB | U | U | U | U | U | U | U | Sport documented for men/women; B3 verify each family; B5 competition choice |
| Fourth slot: ProphetX X, recommended only | NFL | S | S native catalog, type unknown | S native catalog, type unknown | S first-half moneyline; S native spread/total listings, normalization incomplete | U | S first-quarter W/S/T listings | U | B3 access/units/updates; B5 normalize native types |
| Fourth slot: ProphetX X | NBA | U | U | U | U | U | U | U | B3 tournament/catalog sample; B5 NBA mapping |
| Fourth slot: ProphetX X | MLB | U, sandbox tournament listed | U | U | N/A | N/A | U, innings | U | B3 event/books beyond tournament listing; B5 MLB mapping |
| Fourth slot: ProphetX X | NHL | U | U | U | N/A | N/A | U, periods | U | B3 tournament/catalog; B5 NHL mapping |
| Fourth slot: ProphetX X | NCAAF | U | U | U | U | U | U | U | B3 tournament/catalog; B5 college mapping |
| Fourth slot: ProphetX X | NCAAB | U | U | U | U | U | U | U | B3 tournament/catalog; B5 competition choice |

ProphetX's [retained native market catalog](../evidence/slice-3/sandbox-qualification-20260912/verification-fixed/sandbox-20260912T010141Z/market-004.json) explicitly contains full-game, first-half and first-quarter winner/spread/total subtypes. These are catalog evidence only; no full-game/half spread/total calculation is implemented. B3 must retain specific listing IDs before upgrading individual cells. The fourth slot remains **unselected**, including all six rows above.

### Source records: implementation, evidence, access and economics

**K — Kalshi.** [Adapter](../app/adapters/kalshi.py), [stream](../app/adapters/kalshi_stream.py) and shared collector exist. Base adapter recognizes `KXNFLGAME` and `KXMLBGAME`; current coverage discovery is explicitly NFL. Native identity is series/event ticker/market ticker/YES or NO. REST catalog pagination and native bid books are retained; opposite bid complements create purchasable asks with original quantities. Probability fractions and contract quantities use Decimal. Production endpoints are fixed in [venue_access](../app/collection/venue_access.py); this assessment did not refresh credentials or account limits. [D1 retained inventory](../evidence/d1-coverage/retained/coverage.md) distinguishes 32 event identities per venue from six markets per venue with retained books; market discovery was not complete for all Kalshi events. [Bounded live validation](data-coverage-supervised-5m-live-validation-report.md) is evidence of its exact candidate/session only. Receipt and source clocks exist where supplied, with source-time regressions/unknowns preserved. NFL fee scenarios and assessed listing terms are not general fee/settlement qualification for other series. **Next:** B3 fresh permitted catalog/book qualification and actual limits; B5 per-series market/period/settlement mapping; B2 product projection. [Official market schema](https://docs.kalshi.com/api-reference/events/get-multivariate-events) illustrates native identifiers/rules; it is not evidence of six-sport listings.

**P — Polymarket US, never international Polymarket.** [Adapter](../app/adapters/polymarket_us.py), [stream](../app/adapters/polymarket_us_stream.py) and [NFL discovery](../app/collection/prediction_discovery.py) feed the collector. IDs are native event, market and market-side IDs, retaining slug and Long/Short orientation. NFL full-game winner filtering is explicit. Long offers have purchasable asks; Short purchase ladders remain unsupported. Probability/USD-price and native quantity semantics are retained; no unsupported complement is manufactured. D1 found 32 embedded markets but only six with captured books: offset exhaustion does not prove upstream market completeness. Same retained live evidence as K; no broader production claim. Fee coefficient/settlement assumptions are scoped to retained listings. [Current US documentation](https://docs.polymarket.us/getting-started/welcome) has an NFL championship example, not qualified futures ingestion. **Next:** B3 US-only discovery/depth/terms and current contract reconciliation; B5 sport/period/futures mapping; B2 connection. Actual current entitlements, complete listing universe and sustained cadence are unknown.

**N — Novig.** [Adapter](../app/adapters/novig.py) implements NFL/MLB pregame discovery, CASH order images, PLACE/CANCEL/lifecycle/locks and bounded recovery. Only `MONEY` normalizes as moneyline; other types remain unknown. Native event/market/outcome/order IDs and raw bytes retained. Documented prices are probability fractions; quantity is **payout_cents**, not contracts/stake. Current normalized asks unavailable and sync/depth unknown, even after local reconstruction; B3 must establish purchase conversion before sized comparisons. [Slice 5](slice-5.md) and its linked test/access evidence are **synthetic/offline**, not QA or production. The initial socket book envelope is an unverified wire assumption. Issued OAuth/QA/production provisioning was missing at that retained inspection; no new secret check occurred. [Official offerings](https://support.novig.com/en/articles/10336189-what-sports-are-available-on-novig) support D cells, not API entitlements. NHL period offerings and NCAAB market families remain unknown. [Authentication](https://docs.novig.com/api-reference/authentication) requires issued credentials. **Next:** B3 provisioned instructions and bounded wire validation, then purchase/fee/settlement semantics; B5 college/period/futures mapping. Not in the shared production runtime or ordinary dashboard.

**X — ProphetX.** [Adapter](../app/adapters/prophetx.py) and stream/recovery implementation are reusable, outside the shared runtime. [Slice 3](slice-3.md) retains NFL event `19458`, 139 parent objects/447 leaf strikes; composite event:market:strike avoids reused template-ID collisions. NFL/MLB tournament IDs were returned; this is not MLB book evidence. American odds conversion was corroborated against sandbox UI. Native `quantity`/`value` ownership and units remain unknown, so quotes are unsized and shared book sync unknown. First-half moneyline subtype is distinguished; other native family types stay unknown. Three bounded runs received no selection-update messages despite acknowledged subscriptions/reconnect; do not repeat quiet captures as a substitute for resolving the contract. Production access, liquidity, timestamps, fees and listing settlement remain unqualified. [Production guide](https://docs.prophetx.co/docs/prophetx-service-api-switch-to-production) requires production keys/API approval; [Market Data API](https://docs.prophetx.co/docs/getting-started) is another read-only integration option, not evidence that Trading V4 units transfer. **Next:** B3 confirm chosen API/access and field semantics, use known REST images as the bounded starting point, qualify real updates independently; B5 breadth.

## Fourth-venue recommendation

**Recommend ProphetX; owner selection is still pending.** It has the lowest demonstrated implementation effort: native discovery, sandbox price interpretation, retained NFL overlap and recovery already exist. This recommendation is conditional on accessible production data and useful overlap, not on sandbox success alone. Do not require streaming before offering honestly dated REST observations if a permitted bounded REST path is sufficient; missing size still prevents sized opportunity claims.

| Candidate | Access and useful overlap | Existing work / effort | Decision |
|---|---|---|---|
| ProphetX | Documented production approval/keys; actual owner entitlement unknown. NFL sandbox overlap observed; six-sport production matrix unknown | Partial adapter/transport and retained samples; medium remaining effort in units, rules, runtime and production validation | Recommended B3 first choice; owner has not selected |
| Sporttrade | [Official site](https://getsporttrade.com/) says all wagering ceased May 25, 2026; future exchange plans do not establish a usable current source | No repo adapter; high/new access and integration uncertainty | Do not choose for current beta; revisit only on evidence of an active service |
| Betfair Exchange | [Official developer guidance](https://support.developer.betfair.com/hc/en-us/articles/360009638032-When-should-I-use-the-Delayed-or-Live-Application-Key) distinguishes delayed development access from live access. Account/region eligibility and required six-sport overlap unknown for this owner | No adapter; new back/lay economics, commission and rules. [Live activation](https://support.developer.betfair.com/hc/en-us/articles/115003864651-How-do-I-get-started) requires verified/funded access and a fee | Plausible exchange alternative, weaker fit for current pregame prices and existing-work advantage; no purchase proposed |

Stop research here: an actionable first recommendation exists. If ProphetX access fails, B3 compares a newly accessible independent venue using the same matrix. Another frontend to Kalshi is not automatically a fourth independent liquidity source. International Polymarket cannot silently replace Polymarket US.

## Reference matrix and acquisition findings

No requested reference is integrated. **F-ref** below means existing synthetic NFL Pinnacle/reference scaffolding, not a live provider. **D-route** means documented aggregator sport/market vocabulary, with Pinnacle-specific populated cells and free entitlement still unverified. **M** points to the model candidate table; published model outputs are not retained project observations.

| Reference type | Sport | Full-game winner | Spread | Total | First half W/S/T | Second half W/S/T | Other period | Futures | Next action / owner |
|---|---|---|---|---|---|---|---|---|---|
| Independent model | NFL | M / U acquisition | U | U | U | U | U | M / U acquisition | B4 FPI candidate independence/output check; B5 rules |
| Independent model | NBA | M / U acquisition | U | U | U | U | U | M / U acquisition | B4 BPI candidate dated outputs; B5 rules |
| Independent model | MLB | U game forecast | U | U | N/A | N/A | U innings | M FanGraphs | B4 forecasts/acquisition; B5 categories |
| Independent model | NHL | M MoneyPuck | U | U | N/A | N/A | U periods | M MoneyPuck | B4 dated probabilities/acquisition; B5 OT/categories |
| Independent model | NCAAF | M / U acquisition | U | U | U | U | U | M / U acquisition | B4 FPI output/independence check; B5 competition |
| Independent model | NCAAB | M / U acquisition | U score-margin applicability | U | U | U | U | U current output | B4 BPI/KenPom; B5 men/women/division scope |
| Free delayed Pinnacle | NFL | F-ref + D-route | D-route | D-route | U Pinnacle listing | U Pinnacle listing | U | U selected competitions | B4 free entitlement/sample/delay; B5 market mapping |
| Free delayed Pinnacle | NBA | D-route | D-route | D-route | U Pinnacle listing | U Pinnacle listing | U | U | B4 acquisition; B5 mapping |
| Free delayed Pinnacle | MLB | D-route | D-route | D-route | N/A | N/A | U innings | U | B4 acquisition; B5 innings/run-line mapping |
| Free delayed Pinnacle | NHL | D-route | D-route | D-route | N/A | N/A | U periods | U | B4 acquisition; B5 OT/period mapping |
| Free delayed Pinnacle | NCAAF | D-route | D-route | D-route | U Pinnacle listing | U Pinnacle listing | U | U | B4 acquisition; B5 competition mapping |
| Free delayed Pinnacle | NCAAB | D-route | D-route | D-route | U Pinnacle listing | U Pinnacle listing | U | U | B4 acquisition; B5 competition/gender mapping |

### Model candidates: recommend a sport-specific portfolio, not one invented universal model

| Candidate | Known output evidence | Unverified or unsupported for this assessment | B4 action |
|---|---|---|---|
| ESPN FPI/BPI | [Analytics index](https://www.espn.com/analytics/) lists NFL/NCAAF FPI and NBA/college BPI. | Acquisition, current dated outputs, market-specific probabilities and independence need verification; no totals/halves inferred. | First football/basketball candidates, conditional on usable outputs and independence; retain model date/version and exact competition. |
| ESPN NFL FPI dependency caveat | [2025 methodology](https://www.espn.com/nfl/story/_/id/45272576/nfl-football-power-index-2025-season-projections-super-bowl-chances-playoff-draft) uses preseason betting-market inputs. | Statistical model does not necessarily mean bookmaker-independent. | Record dependency; do not label independent without current-method verification. |
| FanGraphs | [MLB projections](https://www.fangraphs.com/standings/playoff-odds) expose division, playoff and World Series probabilities and projected records. | Not proof of game moneyline, run-line, totals or innings probabilities; current game forecast acquisition unknown. | Leading MLB futures candidate; inspect dated game forecasts separately and preserve projection-system identity. |
| MoneyPuck | [Methodology](https://www.moneypuck.com/about.htm) describes NHL pregame home-win probabilities, power ratings and season simulations. | Model-based expected goals are not automatically pregame totals or puck-line probabilities; period outputs/acquisition rights unknown. | Leading NHL game-winner candidate; verify OT/shootout scope and dated season-category outputs before matching. |
| KenPom | [Subscription](https://kenpom.com/register-kenpom.php) documents Division I game predictions; [API](https://kenpom.com/register-api.php) advertises archived FanMatch predictions. | Access is separate from public ranks; current forecasts, women's coverage, market probability distributions and rights unknown. | NCAAB fallback if existing access is useful; do not buy. Verify men/women/division and current-vs-archived output. |

Specific FPI/BPI output boundaries from official pages:

- [NFL FPI](https://www.espn.com/nfl/story/_/page/Football-Power-Index/espn-nfl-football-power-index): ratings underpin game/season projections; the linked table is historical, not a current feed.
- [NCAAF FPI](https://www.espn.com/college-football/fpi): dated September 20, 2026; ratings, projected records and conference/playoff/championship probabilities.
- [NBA BPI](https://www.espn.com/nba/story/_/page/Basketball-Power-Index/espn-nba-basketball-power-index): points-above-average ratings; the displayed historical table does not establish current game probabilities.
- [Men's college BPI](https://www.espn.com/mens-college-basketball/bpi): ratings and season projections; last updated April 7, 2026. Women's coverage is not established here.

B4 should start with MoneyPuck's explicitly described winner output and the football/basketball candidates in parallel where accessible. FanGraphs supplies a distinct MLB futures candidate, not the missing MLB game probability. No model portfolio above presently covers all required cells. A projected margin cannot supply cover probability without an independently validated distribution; predicted score sums cannot supply total-market probability; ranks cannot supply either. Any new conversion needs a named/versioned method, dated inputs and validation, with unsupported outputs staying null. Public pages are leads, not a promise of free automated ingestion or permission to republish. A Massey public-page check returned 403; no coverage inference or bypass pursued.

### Free delayed Pinnacle: promising documented route, not yet verified usable

**B4 first candidate: The Odds API, bookmaker `pinnacle`, website-sourced.** Its [bookmaker list](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html) explicitly warns of possible website delay. Its [free plan](https://the-odds-api.com/) advertises 500 monthly credits, all sports/markets and most bookmakers; Pinnacle is listed without a paid-only marker. Therefore free eligibility is a defensible inference, **not an account-tested fact**. NFL/NBA/MLB/NHL/college sport coverage is advertised in the aggregate; this does not establish every Pinnacle cell. This preserves Pinnacle as the underlying bookmaker, not an alternative sportsbook.

The [V4 guide](https://the-odds-api.com/liveapi/guides/v4/) provides sport/event IDs, bookmaker keys, outcome names, points, prices, last-update fields and credit headers. B4 can build on [reference adapter](../app/reference/adapter.py), [records](../app/reference/records.py) and [edge contracts](../app/edge_contracts.py); current records enforce synthetic NFL scope and [odds_http](../app/collection/odds_http.py) permits numeric loopback only. None is a production connector. Native decimal/American odds must remain separate from de-vigged estimates. This reference supplies no executable exchange depth; quantity is unknown/not applicable, and margin removal is not true win probability.

Missing precisely: (1) free account entitlement actually returns `pinnacle`; (2) current requested sport/market/period/competition samples; (3) upstream publication timestamp versus aggregator `last_update` meaning; (4) actual delay or honest unknown-delay label; (5) allowed retention/use and repeatable free quota fit. An update interval alone is not end-to-end delay. No fixed 15-minute delay is assumed.

B4 sequence: implement isolated fixtures and free-budget accounting first; after separately authorized local key setup, retrieve a bounded representative Pinnacle response, retain request/receipt/native times and credit cost, and populate this matrix from actual returned fields. If no upstream clock exists, display **“Pinnacle via The Odds API — website-sourced; delay unknown”** and forbid synchronized/current fair-value claims. Accepting delayed data does not authorize fabricating a delay. For planning only, six sports × three full-game families is roughly 18 credits per all-sport refresh under one-bookmaker billing; 500 credits cannot support frequent all-day polling. B4 must verify actual charges, cache and prioritize selected events; halves/futures add cost. No paid upgrade is proposed.

[Pinnacle's own API page](https://www.pinnacle.com/en/api) describes bespoke, variable-cost access; [current help](https://support.pinnacle.com/hc/en-us/articles/47844554499345-Accessing-Pinnacle-s-Betting-API) directs personal-project requests to its team. Neither establishes a free direct endpoint. Unauthenticated Pinnacle web/export use remains another unverified path, not permission to bypass access controls. Stop public research here: a concrete free candidate and exact B4 verification dependencies exist. No signup, API request, provider message or purchase occurred.

## Owning-slice dependency ledger and owner help

| Item | Responsible next action | Exact owner help, only when needed | Completion check |
|---|---|---|---|
| B3 Novig provisioning | Engineering reconciles issued environment/auth contract and initial-image/ask units; provider supplies provisioning | Obtain issued QA/production access instructions and OAuth client provisioning using [unsent request](novig-access-request.md); enter secrets locally, never chat | Environment-specific wire evidence and health/history; real ask/size/fee limits explicit |
| B3 fourth venue | Engineering recommends ProphetX and resolves its units/update contract using retained examples; provider supplies missing contract answers | Select ProphetX or name the preferred alternative; if selected, make approved production API access available locally. Provider clarification may use Slice 3's unsent request | Selected source records actual production observations and comparable participation; unknown quantities remain unknown |
| B4 model outputs | Engineering verifies dates, outputs, independence and acquisition for candidates above | Only an existing preferred provider/access, if any; no owner research required. A paid-access decision only if a concrete need later emerges | Supported event/market probability or line, provenance and dependency recorded; unsupported outputs explicit |
| B4 Pinnacle | Engineering verifies free candidate, quota, delay and coverage | If already known, provide intended public URL/export; otherwise future local free-key setup when requested by B4, no secrets here | Actual Pinnacle rows from repeatable free route with time/delay labels; no substitution |
| B5 halftime | Engineering maps explicit periods separately from observation time | Choose first-half markets, second-half markets, at-halftime evaluation, or a combination; whether MLB innings/NHL periods are desired equivalents | Approved definition plus native rule/period IDs; in-play dependency identified separately |
| B5 futures | Engineering proposes team championship and make-playoffs first, then division/conference and season-win totals where applicable | Confirm desired categories, including whether player awards are wanted | Season/category/participant/settlement horizon and multi-outcome rules mapped |
| B5 NCAAB | Engineering inspects each source's competition IDs | Confirm men's, women's or both, and Division I versus broader competition scope | Distinct competition IDs/period rules with evidence; no inferred universal college coverage |
| B5 results and settlements | Engineering identifies sporting results and separate venue payouts, including pending futures | No initial owner action | Results and payout/void records independently linked, seasonal gaps retained |
| B6 practical session | Engineering measures authorized bounds/cadence, then proposes 30-minute integration and representative viewing session | Desired normal viewing duration before B6 scoping | Reviewed finite allowance and measured useful coverage, not automatic live authorization |

None of these blocks independent B2 implementation. B2 fixture acceptance proposes two simultaneously comparable events, at least three venue IDs and two different venue combinations, with a fourth unavailable and both reference roles visible. This is an integration threshold, not beta breadth acceptance. Keep current finite bounds; UI refresh may retain 1.5 seconds and discovery its configured cadence. Reference refresh must respect free quotas. B6 owns actual sustained duration/cadence; no longer session is authorized here.

## B1 validation and completion record

Assessment delivered with both matrices (36 source/sport rows total), explicit period columns, source evidence records, bounded recommendations, a dependency/owner-help ledger and the linked B2 module/contract/acceptance handoff. The Desktop tracker, product definition, delivery plan and gap assessment agree on **B1 COMPLETE / B2 NEXT / beta NOT READY FOR SIGNOFF**. Local Markdown links and heading targets across all six active documents were checked; no missing targets. Documentation whitespace checks passed. No application tests or runtime were executed for this documentation-only change; historical test results remain attributed to their retained reports. Existing application changes, retained evidence and historical attempts were not modified.
