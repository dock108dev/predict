# B5 NFL sporting-result and venue-settlement linkage

**COMPLETE — bounded engineering, offline verified September 22, 2026.** Season 2026 NFL, existing full-game and pregame first-half winner/spread/total only. **516 Python tests and two JavaScript suites PASS. Actual sporting-result/venue-settlement source qualification remains open. Full B4/B5 open; beta NOT READY FOR SIGNOFF.**

## Exact candidate and ordinary product

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA256 **`eb0d72cdd5fcb6b2dc90c3782a77a3adb1fbdea074b636402adb0ffd29e3e266`**, 347 files. [Identity](../evidence/b5-nfl-resolution-20260922/implementation-identity.json) · [acceptance](../evidence/b5-nfl-resolution-20260922/final-report.md). Before editing, the latest NCAAB-H1 candidate matched all 342 implementation files, 84 immutable evidence files and six active document hashes. [Reconciliation](../evidence/b5-nfl-resolution-20260922/pre-edit-reconciliation.json). Prior work, saved observations, consumed attempts and the unrelated requirements-ci.txt edit were preserved.

Ordinary saved Details has **Sporting result & venue settlement**, with an explicit resolution evidence cutoff and timezone-aware as-of control. It separately displays the sporting score/status, rule-derived expected payout, each native venue/outcome decision, unresolved evidence and retained correction history. A score does not imply venue settlement; a payout does not imply any fill, balance or realized profit. Payouts use plain per-contract or purchase-stake labels. Hypothetical cashflows remain expandable and labeled.

The ordinary dashboard can import a prepared local resolution JSON file into an active product session. It makes no provider request. Existing collector admission, queue, hash-chain journal, byte/record bounds, Stop and cleanup own persistence. After Stop, verified saved history exposes the resolution view. Later evidence may be imported into a **new ordinary session bound to the original saved target**; it does not reopen or append to the completed prediction package. No competing journal, sidecar data store, migration, calculator or dashboard was introduced.

## Versioned record contracts

`app/resolution/nfl.py` defines distinct **nfl-sport-result-1** and **nfl-venue-settlement-1** records. The constructor reads an explicitly identified literal object inside a retained JSON annotation; this is an offline import contract, not a newly qualified provider parser. Every record carries a content-derived ID, kind, evidence mode, original bounded body/SHA256/provenance URL/JSON path, receipt time and payload. Hash/schema/literal replay must agree. Synthetic evidence cannot enter a real session or qualify a real prediction target. Imports are bounded to 16 records/1MB HTTP body; projection to 128 unique records/8MB resolution state, in addition to existing session limits.

Common payload fields: `target` (session ID, immutable prediction cutoff, game ID, exact market identity and reviewed NFL event object), `source`, `source_event_id`, `period`, `status`, `source_at`, `published_at`, and explicit `supersedes` ID list. Original receipt, source and publication times are distinct; null remains unknown. All known times require timezones.

Sporting records additionally carry `home_score`, `away_score` and explicit normal-completion evidence. A final result requires nonnegative integer period scores, exact season/stage/start/reschedule/home-away identity and the correct completed segment. Full game includes applicable OT; H1 requires the completed first two 15-minute quarters and never reconstructs H1 from a final score. Normal postseason full-game ties are unsupported. Pending/cancelled/suspended/abandoned/postponed/unknown status does not derive a normal payout.

Venue records additionally bind `contract` and exact `native` event/market/outcome IDs to their own source. Status is pending/settled/void/refund/cancelled/unknown; an optional reported payout retains fraction or purchase-stake-refund meaning and retained/returned/unknown fee treatment. A void/refund status alone never invents a dollar amount. A pending/cancelled record with a payout is conflicting/unsupported. An observed fractional payout can be retained without adding a new rule-derived fractional model.

Original source catalogs must already prove the reviewed NFL event identity. Legacy full-game winner observations missing shared game ID, stage or original-start/reschedule evidence remain **unbound**; annotations cannot backfill those historical fields. Unknown native participants/predicates, wrong events/periods/sources/sides, other sports/seasons, and reference-only targets cannot fabricate a prediction linkage. Existing original calculations still reopen.

## Corrections and as-of behavior

The journal remains append-only. `supersedes` names predecessor record IDs for the same kind/source/source-event/target/native outcome. A correction needs visible supported predecessors, strictly later publication, nonregressing source and receipt times, and cannot cross venue or contract identity. Invalid predecessor chains remain unsupported. Multiple competing active heads remain conflicting; there is no timestamp-based last-write-wins selection. Two branches require an explicit correction covering both. Journal arrival can be out of order when the retained clocks and correction edges prove the relationship; source/publication/receipt conflicts are not repaired by guessing.

The resolution reader verifies the existing flat or segmented package and uses the same durable cursor hash algorithm. It reads only the selected prefix for the view while validating the package. As-of inclusion requires journal observation, receipt, publication and source times all at or before the requested time. Future rows are excluded; unknown timing stays visible unsupported and cannot select a result. Superseded records remain inspectable. Bound venues remain independent; incompatible source scores block the expectation, while observed venue decisions remain visible.

Resolution selection is explicit in `resolution_session`, `resolution_cutoff`, `resolution_asof`; those parameters are separate from the original prediction `session`/`cutoff`. Original books, models, fee assumptions and calculations are never updated from result evidence. Selecting an earlier as-of on a later resolution prefix reproduces the earlier pending state. Reopening an older resolution link does not adopt a later correction. Unrelated corrupt resolution packages are isolated; requested corrupt evidence is never published.

## Independent expected payouts and cashflows

The expectation path calls existing `normalization.score_lines.payout`, legacy `settlement.payout` and the ordinary calculation/fee/depth engines at the original prediction cutoff. It never dispatches observed venue payouts into an account calculation. Missing fees, size, refund economics or exceptional cashflows leave hypothetical dollars unavailable even if a face-value rule payout is known.

| Reviewed rule | Below threshold / home loses | Equality / tie | Above threshold / home wins |
|---|---:|---:|---:|
| Strict home win / gt | 0 | 0 | 1 |
| Home not-win / le | 1 | 1 | 0 |
| ge | 0 | 1 | 1 |
| lt | 1 | 0 | 0 |
| Draw-no-bet or reviewed push | Losing payout | Original purchase stake | Winning payout |
| Legacy full-game Kalshi tie profile in fixture | Normal rule | 0.50 per contract | Normal rule |

These are explicit reviewed structures, not universal NFL/venue rules. H1 inverted fixture YES is home-not-win and pays 1 on a tie; NO strictly wins and pays 0. Opposite-positive-win contracts both lose on a tied half. Integer spread/total equality stays material; half-point lines have no equal integer score. Away spread signs/orientation reuse the existing native predicates. Unknown exceptional statuses never become a normal score or inferred refund.

At 100 hypothetical contracts, supported refund examples independently expect Kalshi .33 purchase→$33 returned, net−$1.55 entry fee; Kalshi .68→$68, net−$1.53; PMUS Long .33→$33, net−$1.33. Short quantity remains unavailable. Gross returned purchase stake is not $100 face value. A full-game .50 tie means $50 gross per 100, not a refund. Observed `0.50` and expected `0.5` compare numerically equal. None of these amounts is a realized account cashflow.

Browser fixture: sporting pending→final 14–14; venue pending→reported0 on inclusive YES (different from expected 1); second unlinked sporting final 17–14 creates conflict; an explicit correction superseding both finals selects10–14. Venue decision remains independently reported0. Original pregame conditional pair results remain **−$3.86 / −$68.88 per 100**, with two Short combinations unavailable. No quote or original probability was changed.

## Evidence and remaining limits

[Acceptance](../evidence/b5-nfl-resolution-20260922/final-report.md) · [browser/disk replay](../evidence/b5-nfl-resolution-20260922/final-reconciliation.json) · [prior replay](../evidence/b5-nfl-resolution-20260922/prior-reconciliation.json) · [source review](../evidence/b5-nfl-resolution-20260922/source-review.md). The 22 linkage checks include all six scope combinations, independent cashflows, correction/clock/source isolation, flat/segmented prefixes, later-session linkage without changing old packages, Stop and exact pregame reopening. Final 516 Python tests/two JS suites preserve the original 18-Arb/96-EV oracle and affected prior-sport/history results. Browser pending/resolved/conflicting/corrected DOMs match exactly on reopening and final-candidate recheck; fresh-process disk replay passes after preview shutdown.

Actual NFL sporting scores/segment completion, native venue settlement/payout/refund fields and correction/publication clock semantics are unqualified. Public Kalshi schema fields and historical rule profiles are documentation, not a retained real settlement sample. PMUS/Novig/ProphetX have no new qualification; source-specific exceptional payouts and unknown fees remain unresolved. No actual result/market/model collection, account settlement, credentials, credit, spending, outreach, existing-beta restart, migration, trading, commit, push or publication occurred.

**Next independent slice: bounded NBA sporting-result and venue-settlement linkage for existing 2026–2027 full-game/H1 winner/spread/total**, with NBA-specific quarter/OT/completion/tie rules and the same separate correction/as-of view. Do not implement it in this handoff. Broader college rosters/seasons, futures definitions and pending resolution, unsupported payouts, practical integration and undecided MLB/NHL periods remain in [B5 backlog](b5-remaining-backlog.md). MoneyPuck dropped/NHL analytics deferred; KenPom deferred; ProphetX selected and requests pending. **Full B4/B5 open; beta NOT READY FOR SIGNOFF.**
