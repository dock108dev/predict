# NCAAF full-game/H1 result and venue-settlement linkage

**COMPLETE — bounded engineering, offline verified September 22, 2026.** Existing six-school 2026 NCAAF winner/spread/total, full game and pregame H1 only. **575 Python tests and two JavaScript suites PASS. Actual source qualification and full reference integration, market support remain open. Beta NOT READY FOR SIGNOFF.**

## Exact implementation and reconciliation

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA256 **`a6cc90c3870f3fa8a14f0743f9ea2e5d8c15158fbd01cc8bcc3a9898d6b10fb4`**, 354 files. [Exact identity](../evidence/b5-ncaaf-resolution-20260922/implementation-identity.json) · [acceptance](../evidence/b5-ncaaf-resolution-20260922/final-report.md).

Before editing, all 351 latest NBA implementation files, 100 immutable evidence files and six tracked documents matched their recorded hashes. [Reconciliation](../evidence/b5-ncaaf-resolution-20260922/pre-edit-reconciliation.json). The unrelated requirements-ci.txt edit, historical observations and consumed attempts are preserved. No commits or migrations.

`app/resolution/ncaaf.py` adds college identity/scope and score validation through the existing shared `core.py` framework. NFL/NBA record versions, correction graphs, view outputs and saved calculations remain exact. Existing projection, retained import admission, flat/segmented journal, history, payout functions, fee/depth and calculation engines are reused. No parallel journal, calculator or dashboard was added.

Ordinary saved Details now shows college sporting score/period, revision type, rule-derived expected payout, native venue decision and missing/pending/conflicting/corrected evidence. The existing resolution selector carries a separate immutable evidence cutoff and explicit timezone-aware as-of. Prepared JSON annotations enter an active ordinary session through the existing import control; Stop exposes its saved history. A later session can link to an older saved prediction without changing the old package. A final score never establishes venue settlement; an observed payout never establishes an executed position or realized profit.

## School, competition and native binding

The six-school boundary is explicit and unchanged: Alabama, Miami FL, Miami OH and North Dakota State are reviewed FBS members for 2026; Alabama A&M and South Dakota State are FCS. Canonical IDs remain ALA, MIAFL, MIAOH, NDSU, AAMU and SDAKST under NCAAF. No roster or alias was added. Ambiguous Miami, SDSU, USC and State cannot resolve by display-name similarity.

Records bind the original session, prediction cutoff, exact market/game identity, source-native event/market/outcome IDs and reviewed college event. Season, game stage, school/subdivision, designated home/away, neutral/home/unknown site, shared game ID and timezone-aware original/current start/reschedule fields must agree with every original source catalog. Repeated opponents remain distinct. Home/away designation never infers home advantage. NFL, NBA, NCAAB, other competitions and unreviewed seasons/schools stay outside this slice.

**FCS-only resolution contracts remain unsupported for all sources**, including a historical winner fixture that can still reproduce its original calculation. No FBS/NFL or generic college template fills the missing FCS contract. H1/line projection gates remain unchanged. FBS/FBS and explicitly bound FBS/FCS examples exercise the interface, not actual contract qualification. Missing original game/stage/start/site/subdivision or native-side evidence remains readable and unbound; annotations never backfill legacy packages.

## Versioned score contracts

Record schemas are **ncaaf-sport-result-1** and **ncaaf-venue-settlement-1**. Shared provenance retains original bounded body/hash/path/URL, mode, source event, source/publication/receipt timestamps and explicit correction edges. Synthetic evidence cannot qualify a real target. Existing 16-record import and 128-record/8MB resolution-state bounds remain. This is a prepared retained-annotation interface, not a newly qualified native result parser.

| Scope | Required final score evidence | Rejected or unavailable alternatives |
|---|---|---|
| H1 | `score_scope=first_half_only`, `score_representation=official_period_points`, two regulation periods completed, `completion=first_two_quarters_definitively_completed`, `result_basis=on_field_period_score`, explicit nonnegative integer home/away points | Q2 alone, unknown completion, full-game score used as H1, reconstructed half scores |
| Full game | `score_scope=full_game_including_college_overtime`, `score_representation=official_final_points_including_all_extra_period_tries`, four regulation periods completed, `completion=all_regulation_and_applicable_college_overtime`, `result_basis=on_field_period_score`, explicit extra-period count and completed flag, reviewed 2026 NCAA overtime format | Regulation-only totals, unknown possession-series/try representation, missing count/completion, inferred regulation score, normal final tie |

The full-game overtime format is `ncaa_2026_possession_series_second_period_two_point_third_alternating_tries`, matching the existing reviewed line descriptor. Official cumulative final points are used directly. Extra-period/try event arrays are not added again; absent regulation or H1 scores are not reconstructed. An independently supplied H1 aggregate is sufficient with explicit completion; later second-half, regulation, final or extra-period fields cannot change it.

The [source review](../evidence/b5-ncaaf-resolution-20260922/source-review.md) identifies retained 2026 NCAA rules and their original hashes. The current public PDF was too large for the web reader; no new download or actual result collection is claimed. Sporting rules establish neither exchange refund policy nor native selected-contract qualification.

## Corrections and separate venue decisions

Sporting records explicitly identify `revision_type`: original (no predecessors), score_correction (explicit predecessors), or administrative_change (explicit predecessors and administrative_change status). Missing/conflicting revision meaning remains unsupported. Administrative records may be retained as corrections but never become on-field final scores or normal expected payouts. Forfeit, shortened, suspended, abandoned, postponed, cancelled and unknown statuses derive no normal payout. No new exceptional economics was implemented.

Shared append-only correction edges require identical kind/source/event/period/target/native contract binding, visible supported predecessors, strictly later publication and nonregressing source/receipt clocks. Multiple active records stay conflicting; arrival order does not decide. Superseded originals remain inspectable. A score correction changes only the labeled rule expectation at its selected resolution cutoff, never an independently retained venue decision. An administrative revision leaves venue pending/settled records unchanged.

As-of admission requires all known source/publication/receipt/journal times to be no later than the requested time. Unknown and conflicting timestamps cannot select a result. Future evidence is excluded; out-of-order arrival requires explicit valid relationships. Pregame books, references, assumptions and calculations remain immutable. An older evidence cutoff never adopts a newer correction; an earlier as-of on a later prefix reproduces pending evidence.

## Independent payouts and cashflows

Existing winner and score-partition payout functions determine expectations. Home strict win pays only on a lead; home not-win includes H1 ties. Opposite positive-win legs both lose at H1 tie. A normally completed college full game is winner-producing; tied exceptional results do not activate an assumed fractional payout. H1 fractional/three-way structures remain excluded by existing mapping rules.

At a margin threshold 3, below/equal/above are ≤2 / 3 / ≥4. gt pays 0/0/1, ge 0/1/1, lt 1/0/0 and le 1/1/0. Total equality is treated the same way. Away signs and predicates remain bound to their native outcome. Half-point lines have no integer equality. A 30–28 final explicitly including third-extra-period tries reaches margin 2 / total 58 exactly once, even when the original annotation also retains regulation and try-event data.

Supported pushes/DNB return consumed purchase stake and retain entry fees. Independent 100-contract H1 expectations: Kalshi .33→$33 gross/−$1.55 net; Kalshi .68→$68/−$1.53; PMUS Long .33→$33/−$1.33. Unknown equality/refund fees remain unavailable; Short purchase size remains unknown. No source borrows another venue’s fees or quantity. Forfeits, fair-price, returned-fee and exceptional settlements remain separate gaps.

Browser fixtures retain original quotes: H1 conditional pair nets **−$3.86 / −$68.88 per 100**, full-game supported pair **−$3.86**, with Short alternatives unavailable. Full-game face payouts can be known while hypothetical leg dollars remain unavailable because original source-time progress is missing. No output claims realized profit.

## Validation, gaps and next slice

[Acceptance](../evidence/b5-ncaaf-resolution-20260922/final-report.md) · [NCAAF saved replay](../evidence/b5-ncaaf-resolution-20260922/final-reconciliation.json) · [NFL replay](../evidence/b5-ncaaf-resolution-20260922/nfl-resolution-reconciliation.json) · [NBA replay](../evidence/b5-ncaaf-resolution-20260922/nba-resolution-reconciliation.json) · [prior-sport replay](../evidence/b5-ncaaf-resolution-20260922/prior-reconciliation.json).

All 31 college linkage checks, original 50 NFL/NBA linkage checks, 18-Arb/96-EV oracle and affected product integration, venue integration, reference integration/sport/history/fee/depth regressions pass. Ordinary browser runs separately cover H1 and full-game pending/resolved/conflicting/corrected states and earlier as-of, with all eight DOM comparisons exact. Both sessions stopped manually; fresh-process disk replay after preview shutdown reproduces the original snapshots, calculations and every resolution view. Administrative changes, FCS gates and later-try scoring are offline test evidence, not browser or venue qualification.

Actual sporting source completion/score representation, native venue settlement/payout/refund fields, publication/correction clocks and exceptional fees remain venue integration, market support qualification gaps. Incomplete legacy bindings and broader college coverage remain open. Reference integration models and Pinnacle qualification are unchanged. MoneyPuck dropped/NHL analytics deferred; KenPom deferred; ProphetX selected and requests pending. No new collection, credits, credentials, account settlement, outreach, spending, existing-beta restart, migration, trading, commits, pushes or publication.

**Next independent slice: bounded men’s Division I NCAAB 2026–2027 full-game/H1 result and venue-settlement linkage**, preserving the existing four-school scope and its first 20-minute half/completion/tie semantics. Recommendation only; no other-sport resolution implemented here. [Remaining market support backlog](market-data-gaps.md) keeps futures, unsupported economics and undecided MLB/NHL periods open. **Full reference integration, market support open; beta NOT READY FOR SIGNOFF.**
