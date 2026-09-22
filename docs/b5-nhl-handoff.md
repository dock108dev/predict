# B5 NHL full-game winner — bounded engineering complete

September 21, 2026. **Offline verified only. Beta NOT READY FOR SIGNOFF. Full B5 and full B4 remain IN PROGRESS.**

[Acceptance evidence](../evidence/b5-nhl-20260921/final-report.md) · [source audit](../evidence/b5-nhl-20260921/retained-native-audit.json) · [tests](../tests/test_b5_nhl.py).

## Supported product behavior

The existing registry now includes all 32 current NHL teams, explicit abbreviations and reviewed aliases, including accented/unaccented Montréal and historical Utah Hockey Club (2024–2025 only at the event gate). New York alone is ambiguous. Arizona is not silently mapped to Utah. Existing entity IDs, aliases, native mappings and retained `hockey` vocabulary remain intact. A retained ProphetX **sandbox** tournament ID 234 maps to NHL; this is not a production mapping or team-ID qualification.

`app/normalization/nhl.py` validates explicit season `YYYY-YYYY`, regular season versus playoffs, home/away identities and timezone-aware start. A conservative September–July season envelope rejects unsupported historical scheduling exceptions. Duplicate same-source games and same-opponents/same-day cross-source start, season, stage or home/away conflicts fail closed. No nearest-time or fuzzy-name matching. Old stored canonical keys are not rewritten; the NHL projection uses an additive reviewed identity. Provider team IDs and unfamiliar aliases need retained evidence before adding them.

The ordinary shared projection supports unlined, full-game, **two-way winners including overtime**, with shootouts explicitly included for regular-season games and explicitly inapplicable for playoff games. Regulation-only, three-way, preseason, missing periods, lines and unknown terms remain visible gaps. Two outcomes alone never prove this scope. Normal winner orientation is checked against retained Kalshi YES/NO and Polymarket US native team/Long/Short fields. No complement price or unsized depth is invented.

A source-specific `nhl_review` annotation binds source, native event/market IDs, evidence mode, exact retained listing SHA256, explicit native outcomes, outcome literal, and literal evidence for overtime, shootout, outcome count, tie, cancellation, postponement, abandonment and forfeit. Review annotations must be based on the exact source terms; they are not permission to relabel football metadata. Synthetic annotations cannot qualify a real session. Differing reviewed exceptional terms do not pair. Unmapped sources stay unavailable.

Conditional calculations reuse existing depth, fee and settlement engines. NHL never inherits the hard-coded NFL series: a supported Kalshi scenario needs explicit `KXNHLGAME` fee basis; PMUS needs its own coefficient evidence. Unknown fees, asks and size stay unknown. Tie payouts are known only if explicitly reviewed; other exceptional payouts, unconditional EV and exceptional probabilities remain unknown. Existing modeled account/fee assumptions remain labeled what-ifs. Negative EV is valid. No all-outcome arbitrage qualification follows.

## Model-reference contract

The existing annotated published-value importer and original-input validation remain intact. NHL eligibility is checked at projection cutoff, preserving historical reference IDs rather than rewriting old receipts. A usable NHL model reference needs an explicit home-win probability, reviewed home/away names and canonical event, season, stage, exact start, two-way winner identity, and retained literal evidence establishing overtime/shootout meaning. No away complement is generated. Ranks, ratings, season odds, expected goals, projected scores and retrospective metrics remain unsupported for this calculation.

`nhl_model_review` carries the reviewed event plus `published_outcome=home_win`, `home_name`, `away_name`, `home_literal`, `away_literal`, `semantics_literal`, and explicit overtime/shootout values. Missing/conflicting review stays visible. Source/model time and receipt remain separate; future source times cannot enter an earlier cutoff, and publication later than receipt is unsupported. References are source-specific, never Arb legs. Exact stored cutoffs rederive the same result after Stop and reopening.

## Actual evidence and gaps

| Source | Established | Still required |
|---|---|---|
| NHL | Official team directory and 2026–2027 rulebook §§84.1, 84.4, 84.5 reviewed | Sporting rules alone cannot establish any venue's settlement equivalence |
| Kalshi | Retained KXNHLGAME series, quadratic-with-maker-fees, multiplier 1, NHL settlement source and ACHIEVEMENTS contract link | Exact NHL event/season/native side and market-specific OT/shootout and exceptional terms; current event fee overrides remain unknown |
| Polymarket US | Existing native side handling offline verified; public hockey **totals** illustration found | Actual NHL winner listing/rules, native IDs, period and fee binding; totals rules do not qualify winner contracts |
| Novig | Existing read-only adapter and unknown-economic behavior preserved | Actual reviewed NHL listing, period, outcomes, fees and settlement; request sent/pending |
| ProphetX | NHL tournament 234 in retained sandbox catalog | Production identity, size ownership/units, fees, winner terms; selected, request sent/pending |
| NHL analytics | Synthetic explicit home-win interface works | MISSING/deferred. MoneyPuck dropped; no actual model values or independence established |
| Pinnacle | Original NFL sample remains reproducible | Compatible prediction observations and settlement equivalence; NHL not collected; no additional credits authorized |

Official sources: [NHL teams](https://www.nhl.com/info/teams/), [2026–2027 NHL rulebook](https://media.d3.nhle.com/image/private/t_document/prd/i9yumvyaojps5kixzaxz.pdf), [Kalshi ACHIEVEMENTS](https://assets.kalshi.com/contract_terms/ACHIEVEMENTS.pdf), [PMUS totals filing](https://www.cftc.gov/filings/orgrules/rules03272642617.pdf), [Novig rules landing page](https://support.novig.com/en/articles/9612523-market-rules).

The NHL rulebook distinguishes regular-season overtime/shootout from repeated playoff overtime. Kalshi's linked generic ACHIEVEMENTS contract contains postponement/suspension, cancellation and discretionary allocation provisions; it does not justify copying football's 48-hour terms into an NHL market. The fixture's 48-hour/fair-value/tie values are **synthetic test conditions**, not asserted Kalshi or PMUS NHL rules. PMUS's reviewed filing concerns totals and explicitly defers to contract terms. Novig's rules landing page did not establish a complete NHL winner contract. These are source-specific gaps, not a reason to stop other engineering.

<a id="moneypuck-proposal--pending-approval-not-executed"></a>

## NHL analytics — missing/deferred

**Owner decision — September 21:** MoneyPuck dropped from the active plan. NHL analytics/model data is **MISSING — deferred**, with no replacement search, license inquiry or further MoneyPuck request queued. Preserve completed NHL engineering and historical evidence. Continue independent B5 sport/market work; missing NHL analytics does not block it. KenPom remains deferred; Novig/ProphetX replies remain pending.

Historical [MoneyPuck capture](../evidence/b4-moneypuck-sample-20260921/final-report.md) is preserved; its old acquisition/next-step instructions are superseded. No actual model values were obtained.

## Remaining B5 scope

Actual NHL source/venue qualification, regulation/three-way economics, spreads, totals/push distributions, half/period definitions, futures, result/settlement linkage, remaining MLB markets and NBA/NCAAF/NCAAB mapping and the wider six-sport coverage/history exit remain open. No exclusion from the beta floor is implied. B6 integrated readiness and B7 owner signoff remain separate.
