# NCAAF full-game winner — bounded engineering complete

September 21, 2026. **COMPLETE — offline engineering only. Beta NOT READY FOR SIGNOFF. Actual venue/model qualification and broader reference integration, market support remain open.**

[Acceptance report](../evidence/b5-ncaaf-20260921/final-report.md) · [exact implementation](../evidence/b5-ncaaf-20260921/implementation-identity.json) · [NBA reconciliation](../evidence/b5-ncaaf-20260921/nba-reconciliation.json) · [tests](../tests/test_ncaaf.py).

## Ordinary Predict behavior

Reviewed NCAAF two-way, unlined, single full-game winners including college overtime now use the existing projection, comparison, Details, filtering, reference and fee/depth/settlement paths. Conditional Arb works without analytics. Unknown schools, rules, fees, sizes and model meaning stay visible and unavailable where material. The ordinary title includes both participants' subdivisions and neutral/home/unknown site status. Stop, immutable cutoff links and saved reopening retain the exact original inputs and results. No separate dashboard or calculation engine.

The reusable review plumbing now shares NBA's event-conflict and explicit home/away-probability checks. NBA and MLB saved snapshots and complete Arb/EV outputs reproduce exactly. Existing NFL/NHL and product integration, venue integration, reference integration regressions pass. The old normalization example incorrectly described NCAAF/NBA/NHL as absent from the registry; it now distinguishes reviewed identity from actual venue coverage, with explicit assertions for supported NCAAF and unsupported NCAAB league identity.

## Explicit school and competition coverage

This is a **six-school, 2026-season reviewed registry**, not exhaustive college coverage. Any pair of reviewed schools can be considered, including FBS–FBS, FCS–FCS and cross-subdivision games; all other game and source gates still apply.

| Canonical school | 2026 subdivision | Reviewed aliases / primary source |
|---|---|---|
| Alabama Crimson Tide | FBS | Alabama, University of Alabama, ALA; [athletics](https://rolltide.com/sports/football/) |
| Alabama A&M Bulldogs | FCS | Alabama A&M, Alabama A&M University, AAMU; [2026 program](https://aamusports.com/news/2026/8/27/football-alabama-am-begins-2026-season-on-national-stage.aspx) |
| Miami (FL) Hurricanes | FBS | Miami (FL), Miami FL, Miami Hurricanes, University of Miami; [2026 program](https://miamihurricanes.com/news/2026/01/26/hurricanes-release-2026-football-schedule) |
| Miami (OH) RedHawks | FBS | Miami (OH), Miami OH, Miami RedHawks, Miami University; [2026 program](https://miamiredhawks.com/news/2026/3/24/2026-football-schedule-announced) |
| North Dakota State Bison | FBS | North Dakota State, North Dakota State University, NDSU; [2026 move](https://gobison.com/news/2026/2/9/ndsu-football-joining-mountain-west-conference) |
| South Dakota State Jackrabbits | FCS | South Dakota State, South Dakota State University; [athletics](https://gojacks.com/sports/football) |

“Miami” is explicitly ambiguous. Mascot-only names, “SDSU,” “USC,” “State,” unreviewed schools and historical aliases do not resolve. No native school IDs were invented. Registry membership reviews are season-specific, so North Dakota State's prior FCS classification cannot carry into 2026. Other seasons and schools need their own reviewed entries; Division II/III, NAIA, junior college and other competitions remain explicit coverage gaps, not beta exclusions. Extend the existing validated registry with school-specific aliases and dated subdivision evidence; no fuzzy learning or nickname-only matching.

`ncaaf.event_key` requires NCAAF/football, a season year, regular-season/conference-championship/bowl/playoff **game** stage, two resolved schools, designated home/away, both season-specific subdivisions, a shared reviewed game ID, timezone-aware original/current starts, scheduled/rescheduled status and explicit site status. The conservative calendar window is August through the following January. Site values mean supplied neutral venue, supplied non-neutral home venue, or explicitly unknown; home/away designations alone never establish home-field advantage. Missing/invalid fields, conflicting site/subdivision evidence, duplicate events, repeated-opponent identity conflicts and inconsistent reschedules remain unsupported. Names alone do not establish game equivalence.

`ncaaf_review` binds source, native event/market IDs, evidence mode, exact retained listing SHA256, complete event identity, native JSON paths/literals, explicit full-game scope and native outcomes. Kalshi YES/NO and Polymarket US team/Long/Short associations must reproduce from the native listing. Synthetic annotations cannot qualify observation mode. Kalshi KXNCAAFGAME and KXNCAAFCSGAME are the only reviewed series identities; the FCS-only series rejects a cross-subdivision or FBS participant binding. No undocumented milestone type or start time is inferred, and collection defaults are unchanged. Novig/ProphetX native NCAAF outcomes remain unsupported pending evidence.

## Settlement, fees and probabilities

Only identical, explicitly evidenced source terms can pair. Required terms cover overtime, outcome set, ties, postponement, suspension, cancellation, abandonment, shortened games, voids, refunds, forfeits, venue changes and result corrections. Regulation-only, halves, quarters, overtime-only, spreads/totals, conference/season winners and other futures remain separate. A conference championship **game** is not a conference-winner future.

The [2026 NCAA rules, Rule 3-1-3](https://ncaaorg.s3.amazonaws.com/championships/sports/football/rules/PRMFB_RulesBook.pdf) use possession-series overtime, including two-point tries in later extra periods. This is distinct from NFL overtime and does not establish exchange payout/refund policy. The [Kalshi FOOTBALLGAMEWIN contract](https://kalshi-public-docs.s3.us-east-1.amazonaws.com/regulatory/product-certifications/FOOTBALLGAMEWIN.pdf) covers explicit periods, includes overtime unless specified otherwise, and describes ties, 55-minute interruption distinctions, 48-hour postponement, forfeit and venue-change conditions. The [PMUS AEC amendment](https://www.cftc.gov/filings/orgrules/rules03262641984.pdf) can cover games or broader competitions and uses expiration-dependent postponement/cancellation and discretionary settlement. These are **not asserted equivalent**. The retained FCS series points to FOOTBALLARCHIVED; that public terms URL returned **404**, so its current contract remains unverified. [Document hashes and gap](../evidence/b5-ncaaf-20260921/public-document-manifest.json).

The compatible integration fixtures deliberately provide identical **synthetic** terms. They do not qualify an actual cross-venue combination. The retained series catalog establishes distinct fee context: KXNCAAFGAME quadratic-with-maker-fees, multiplier 1; KXNCAAFCSGAME quadratic, multiplier 1. Each must match its own native listing and explicit fee evidence. Existing fee engines handle both; NFL series applicability is never transferred. PMUS requires its own supported coefficient. Event overrides, account charges/precision and settlement-charge assumptions remain conditional; unknown depth/size/fees are not replaced with another source's values. Unknown exceptional payouts/probabilities prevent unconditional EV and qualified all-outcome arbitrage.

The reference integration importer accepts explicitly supplied home-win or away-win probabilities bound to the exact game/season/stage/start, schools, subdivisions, site status and overtime meaning. No complement is invented. Ratings, rankings, projected margins/totals, playoff/championship/season probabilities, wrong-event and legacy unreviewed records cannot supply game EV. The 60% ESPN-shaped test receipt is synthetic, not an acquired FPI forecast. College-model inputs and independence remain unverified; no NFL-specific dependency claim or “independent” label is transferred. Manual probabilities retain the what-if label. Source and receipt clocks plus immutable journal prefixes prevent later observations entering earlier cutoffs.

## Remaining work and next slice

| Owner | Gap / next action |
|---|---|
| venue integration, market support Kalshi | Actual college game listing/participants/milestones/start/stage/site/scope, applicable current rules and event fees/book. FCS current contract missing; DIII and bowl-qualification series not supported. |
| venue integration, market support PMUS | Actual US NCAAF single-game listing, schools/subdivisions/site/native outcomes, applicable compatible terms and economics. International Polymarket is not a substitute. |
| venue integration, market support Novig / ProphetX | Requests remain pending. Native college competition/outcomes/rules, purchase quantity ownership/units and fees remain unqualified. |
| market support school breadth | Remaining schools, seasons, membership transitions and other subdivisions require reviewed entries; unresolved coverage stays visible. |
| references | Actual dated NCAAF game-win forecasts and independence, plus actual compatible NCAAF Pinnacle input, remain missing. No model acquisition or Odds API request/credit used. |
| Broader market support | Spreads/totals, half/quarter economics, regulation-only, futures, in-play and result/settlement linkage remain open. |

The subsequent [NCAAB full-game winner slice](ncaab-handoff.md) is complete offline for the owner-selected men’s Division I scope, bounded to four reviewed teams in 2026-2027. Its [NCAAF reconciliation](../evidence/b5-ncaab-20260921/ncaaf-reconciliation.json) preserves this six-school 2026 football implementation and exact saved calculations. Next: [shared full-game spread/total engineering](score-lines-next.md).

MoneyPuck remains dropped, NHL analytics and KenPom deferred. ProphetX is selected; requests pending. Pinnacle sample/key setup and consumed allowance are preserved. No new market/model collection, credential access, provider messages, spending, existing-beta restart, migrations, trading, commits, pushes or publication. Isolated preview stopped and closed; historical evidence and unrelated changes preserved.
