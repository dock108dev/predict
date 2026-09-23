# Shared full-game score lines — bounded engineering handoff

**COMPLETE: NBA and men’s Division I NCAAB integer/half-point full-game spread/total engineering.** Fixture/offline acceptance only. Actual venue/model qualification, full reference integration, market support and beta signoff remain open. **Beta NOT READY FOR SIGNOFF.**

Candidate: HEAD `c7204c98fc78cde2f314a3227c03c7d6d70fbe2a`, uncommitted implementation SHA-256 `3b21745ce1322dbc4fa54c3d4dd9979683fdf0b80533f91441b374ee32ddf05a`, 317 app/test/script files. [Identity](../evidence/b5-score-lines-20260921/implementation-identity.json) · [acceptance](../evidence/b5-score-lines-20260921/final-report.md). Before editing, all 312 NCAAB acceptance files matched their recorded hashes; the newer HEAD had committed that previously accepted working tree. No commit was made during this slice.

## Ordinary product behavior

The existing projection groups explicitly reviewed score lines by exact reviewed NBA/NCAAB game, season/stage/start, completed-game score definition, points domain and normalized threshold. Away spreads invert both signed handicap and comparator into home-minus-away margin. Totals use combined integer points. Different thresholds do not form a pair; title similarity is never evidence. Native descriptor, side orientation, equality rules and review receipt contribute to the game/assumption identity; source descriptors travel in the reference identity. Line revisions invalidate stale selection inputs. Existing NBA aliases and the four-school, 2026–2027 men’s Division I NCAAB bounds remain unchanged.

Ordinary Details show native side, signed spread or total, comparator, equality treatment, partition intervals, fee audits and unavailable reasons. Missing models leave price comparisons and conditional Arb available. Stop, source isolation, immutable cutoff links and disk reopening use the existing owner/journal/history paths.

`normalization/score_lines.py` validates an explicit retained review: source/event/market IDs, original body hash, native descriptor/terms/fee paths, competition-specific event paths, period structure and canonical identity. The pilot handles two opposing inequality outcomes, including inverted YES/NO/Long/Short orientation; no generic title parser or live discovery is added. Synthetic review annotations cannot qualify observation sessions. Actual native line annotations/listing evidence remain a venue integration data gap.

## Payout and probability contract

`opportunities/score_lines.py` dispatches to the existing `board.leg_value`, depth consumption and fee engine with partition payouts, bypassing the two-team winner enumeration and binary EV formula. Winner versions and outputs are preserved.

For a margin threshold 3, reachable partitions are integers ≤2, exactly 3 and ≥4:

| Contract | Below | Equal | Above |
|---|---:|---:|---:|
| Greater than | 0 | 0 | 1 |
| Greater than or equal | 0 | 1 | 1 |
| Less than | 1 | 0 | 0 |
| Less than or equal | 1 | 1 | 0 |
| Greater than, stake push | 0 | purchase stake | 1 |
| Less than, stake push | 1 | purchase stake | 0 |

At 3.5 only ≤3 and ≥4 exist: integer scoring proves equality unreachable. Combined totals have a nonnegative lower bound. Arbitrary different-line middles/portfolios, exact-count/range contracts, quarter-point split stakes, partial games, futures and in-play are outside this slice.

A push returns the sum of actual consumed price × quantity, **not face value**. Supported push economics retain entry fees; returned/unknown refund fees are explicitly unavailable where equality is reachable. Missing source fee basis, settlement levy, purchasable size or material payout produces unavailable dollars. Kalshi cent/direct account precision and no event override remain labeled what-if assumptions. PMUS uses only its own retained coefficient; Novig/ProphetX economics are not borrowed. All-outcome worst case is unavailable: cancellation, suspension, void, corrections and other exceptional outcomes are separately retained, with unknown probabilities and payouts.

`reference/score_lines.py` adds `score_distribution` to the existing retained-reference preparation/import contract. Original JSON must explicitly supply the exact market identity, native outcome participant, source event ID, reviewed event, completed-full-game-including-overtime meaning and a complete probability map over `below`/`equal`/`above` as reachable. Values are decimal strings in [0,1], summing exactly to 1. It retains the reference integration receipt, timing, version and independence fields. Wrong event/partition, ratings, season odds and projected scores/margins are rejected. No model is fetched or fitted. A labeled manual scalar probability supports half-point outcome EV; integer lines require imported equality mass. The browser preserves scalar assumptions in links and retains distributions by immutable reference ID.

## Official documents and retained evidence

Reviewed September 21 local time: [Kalshi basketball spreads](https://assets.kalshi.com/contract_terms/BASKETBALLSPREADS.pdf) and [basketball totals](https://assets.kalshi.com/contract_terms/BASKETBALLTOTALS.pdf). Retained PDFs/text and hashes are in the acceptance evidence. The contracts distinguish comparison operators and period scopes. They do not establish one universal basketball settlement rule: spread abandonment/resumption and delay provisions use 48 hours; totals use a 24-hour resumption provision and two-week delay window. Fair-price discretion is not a purchase-stake refund. Those provisions are not silently copied between venues or used to qualify synthetic reviews.

The prior [NCAAB catalog audit](../evidence/b5-ncaab-20260921/retained-native-audit.json) identifies separate `KXNCAAMBSPREAD`/`KXNCAAMBTOTAL` contract URLs. Catalog discovery does not provide actual selected game/line/outcome/fee/depth qualification. No new listing/model collection occurred. Fixture receipts deliberately annotate copied quote shapes; they are neither current prices nor official source-rule equivalence evidence.

## Remaining owners and next work

- **venue integration:** actual NBA/NCAAB native line listings, scoped review annotations, current source rules, quantities, fee applicability and exceptional/refund economics. Novig/ProphetX requests remain pending; ProphetX selected. No new credits, credentials, messages or collection.
- **reference integration:** actual explicitly bound cover/total distributions, provenance and independence. KenPom deferred. MoneyPuck dropped; NHL analytics missing/deferred. No acquisition prerequisite for independent engineering.
- **market support:** remaining roster/seasons, NFL/NCAAF point mappings, MLB run-line/pitcher/shortening mappings, NHL puck-line/shootout goal treatment; other periods/futures remain separate.
- **Next independent slice:** bounded **NFL full-game spread/total mapping**, using this shared partition engine, reviewed NFL event/season/start identity, native signed points and overtime/tie/shortening rules, then ordinary saved replay. NCAAF is a subsequent mapping with its own membership/site constraints.
