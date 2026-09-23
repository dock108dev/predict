# B5 NHL full-game puck-line/total handoff

**COMPLETE — bounded offline engineering and isolated synthetic browser acceptance, September 22, 2026.** Actual venue/model qualification and full B4/B5 remain open. **Beta NOT READY FOR SIGNOFF.**

[Acceptance](../evidence/b5-nhl-lines-20260922/final-report.md) · [implementation identity](../evidence/b5-nhl-lines-20260922/implementation-identity.json) · [prior retained replay](../evidence/b5-nhl-lines-20260922/prior-reconciliation.json).

HEAD `0f8c034eb7734c69b44690d25128f7da7888d71e`; uncommitted app/test/script SHA-256 `314cb8a7813956d01df09a38b494a8e4c8442ea9e1f675782ccb0eee9543882c`, 329 files. The newer HEAD contains the accepted MLB baseline; all 326 accepted MLB implementation files and 56 evidence files matched before edits. Existing winner and line outputs are preserved; no commits or publication.

## Ordinary product and identity

Ordinary Predict supports explicitly reviewed NHL full-game integer/half-goal puck lines and combined totals through the existing score partitions, fee/depth/refund engines, references, Details, filtering and Stop/history paths. Titles show OT/shootout and the single winner-goal scoring convention; native sides display signed participant/line, normalized inequality and equality treatment. Unsupported native score conventions, missing size/fees and unreviewed sources remain visible. Missing analytics does not prevent supported conditional price comparisons.

`nhl_lines.py` extends the existing 32-team NHL registry and winner identity for lines only. Reviewed **2026–2027**, regular season/playoffs, home/away, timezone-aware original/current starts, explicit shared game ID and scheduled/rescheduled status are required. The inherited September–July envelope is conservative; playoffs require April–July 2027. Existing winner identities and historical Utah handling are unchanged. Repeated opponents and reschedules require exact game/lineage agreement; names alone cannot match. Conflicting same-day identities are refused, not resolved by nearest start. Other seasons and scheduling exceptions remain unqualified.

Every source review binds native event/market IDs, raw receipt hash, native event/descriptor/term/fee paths, source series, native outcome IDs/labels, sign, unit, strict/inclusive predicate and equality convention. Away puck lines invert into home-minus-away margin. Different lines/revisions retain separate identities. Synthetic annotations cannot qualify actual observations. No title parser, native collection expansion or new adapter was added.

## Numeric score contract

Supported reviews explicitly require three 20-minute periods and applicable overtime: regular season five-minute 3-on-3 then shootout, or repeated playoff sudden-death 20-minute periods with no shootout. Regular-season line settlement uses regulation/OT goals plus **one** goal to the shootout winner. Playoffs use regulation/all OT goals only. Regulation-only, partial periods, team totals, shootout-attempt totals, series/futures and in-play are outside scope. Unknown numeric conventions cannot inherit winner-market eligibility.

Two explicit native score representations can map to the same reviewed settlement convention:

| Original representation, home shootout win | Observed score | Adjustment | Settlement score |
|---|---:|---:|---:|
| On-ice regulation + OT | 3–3 | home +1 | 4–3 |
| Official final including shootout award | 4–3 | zero | 4–3 |

The pure `settlement_score` mapping preserves the original record and separate adjustment. A non-tied pre-award shootout score, unknown basis/winner, individual attempt count, already-transformed record or playoff shootout is refused. An ordinary playoff 4–3 OT score is unchanged. This is a tested normalization interface, **not new result ingestion or automatic settlement linkage**. Pregame probabilities describe the final reviewed partition directly; the calculation engine does not add a shootout goal to forecasts or attempt scores.

Normally completed games are the conditional calculation boundary. Each source separately retains completion, shortened/suspended/resumed/postponed/cancelled/abandoned, forfeit, tie, void/refund, venue-change, corrections and settlement-fee terms. Unknown exceptional payouts/probabilities keep unconditional EV and all-outcome guarantees unavailable. Official shortened results are not silently treated as normal completion. Zero-margin equality remains conservatively represented; no tie outcome is erased by winner rules.

Integer boundaries retain below/equal/above mass. Half-goal equality is unreachable. Binary complements, strict push pairs and unknown equality are distinct. Supported refunds return actual consumed purchase stake and retain entry fees; returned/unknown fees remain unavailable at material equality. Kalshi requires its own `KXNHLSPREAD`/`KXNHLTOTAL` fee basis; retained catalog type is quadratic, multiplier 1. Winner-series fees are rejected. PMUS uses only its own retained coefficient; no Novig/ProphetX economics are borrowed.

The existing B4 exact-partition importer now checks NHL event, stage, native side, exact line and explicit settlement-score convention. Expected goals, projected scores, ratings, moneyline and season probabilities are not line probabilities; missing equality mass is unavailable. Source/receipt/cutoff gates remain in force. `synthetic_partition` is an explicitly synthetic-only test receipt source, never an actual model or observation source. Existing historical model receipts are preserved. MoneyPuck remains dropped; no NHL model acquisition, replacement search or fitting occurred.

## Reviewed official evidence

[Audit and retained hashes](../evidence/b5-nhl-lines-20260922/native-contract-audit.json) separate public documents/catalogs from actual selected listings.

- [NHL 2026–2027 rulebook](https://media.d3.nhle.com/image/private/t_document/prd/i9yumvyaojps5kixzaxz.pdf), rules 84.1/84.4/84.5, distinguishes regular-season shootouts and playoff OT. The official final score awards the shootout winner one more goal than the opponent; attempt goals are not ordinary individual scoring. This defines sporting statistics, not venue payout equivalence.
- Retained Kalshi rows independently link `KXNHLSPREAD` to [HOCKEYSPREADS](https://assets.kalshi.com/contract_terms/HOCKEYSPREADS.pdf) and `KXNHLTOTAL` to [HOCKEYTOTALS](https://assets.kalshi.com/contract_terms/HOCKEYTOTALS.pdf). They distinguish periods, combined/team scope, operators and OT, and include 55-minute/official-result and 48-hour interruption provisions plus discretionary fair-price settlement. **Neither template explicitly resolves numeric shootout treatment**; exact selected listing evidence remains necessary. Fair price is not a purchase-stake refund.
- [PMUS Total Score Contracts amendment](https://www.cftc.gov/filings/orgrules/rules03272642617.pdf), March 26, 2026, illustrates one additional goal for a hockey shootout winner, subject to applicable contract terms. It does not qualify an actual selected NHL total, native score representation, or puck-line rules. Source deadlines/void/refund economics remain separate.

Fixtures are hypothetical review annotations and copied quote shapes, not real NHL books or production cross-venue compatibility. Actual Kalshi shootout clauses, PMUS US-specific puck-line mappings, source fees/overrides/quantities and Novig/ProphetX bindings remain B3/B5 gaps. NHL model/Pinnacle line inputs remain B4 gaps; the NFL Pinnacle h2h sample and consumed credit are preserved.

## Remaining periods and next slice

The tracker still distinguishes first-half markets, second-half markets and evaluation at halftime. The last requires a separate in-play decision; it is not pregame partial-market scope. **Proposed next slice: NFL pregame first-half winner/spread/total mapping**, using explicit native half IDs and partial-score/equality rules. This proposal requires the owner's first-half versus second-half definition before period-specific implementation; no answer is assumed. Baseball innings and hockey periods are not silently chosen as halftime equivalents. Their selection can wait until their owning slices. No new half/period implementation is included here.

Period/team-total/quarter-stake/portfolio, regulation-only and series/futures economics, actual venue/model qualification and result linkage remain broader B5 work. MoneyPuck dropped/NHL analytics deferred; KenPom deferred; ProphetX selected; Novig/ProphetX requests pending. No new collection, credits, credentials, outreach, spending, existing-beta restart, migrations, trading, commits, pushes or publication. Beta remains NOT READY FOR SIGNOFF.
