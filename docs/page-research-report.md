# Saved-page probability and outcome research

Implemented September 16, 2026. File-only; no new requests, feed scan, credential access, service/database changes or beta restart.

**Page-derived estimate — bookmaker update time and delay unknown.**

VegasInsider event 32144330, Detroit Lions–Buffalo Bills, September 18 at 00:15 UTC; full-game moneyline, same displayed DraftKings column. Source retrieved September 16 at 03:26:29.205210 UTC. Original source HTML/hash/metadata remain unchanged.

| Team | Original odds | Exact decimal odds | Raw implied probability | Proportional de-vig |
|---|---:|---:|---:|---:|
| Detroit Lions | +180 | 14/5 = 2.8 | 5/14 ≈ 35.714286% | 795/2321 ≈ **34.252477%** |
| Buffalo Bills | −218 (raw `-218`) | 159/109 ≈ 1.4587155963 | 109/159 ≈ 68.553459% | 1526/2321 ≈ **65.747523%** |

Combined implied probability is 2321/2226 ≈ 104.2677448%; overround is 95/2226 ≈ 4.2677448%. Exact rational American conversion and raw price spelling are retained alongside E3's 50-significant-digit HALF_EVEN calculation. Probabilities are stored to 18 decimal places: Detroit `0.342524773804394657`, Buffalo `0.657475226195605343`. Display rounding never feeds arithmetic. Cashflow and score calculations use 100 significant digits.

[Calculation JSON](../evidence/page-research/calculation.json) · [real saved prediction journal](../evidence/page-research/real-journal) · [synthetic workflow evaluation](../evidence/page-research/current-synthetic-evaluation.json) · [target comparison](../evidence/page-research/target-comparison.json).

Timing, upstream synchronization, independence and ordinary-winner rule assessment remain unknown. The de-vig estimate assumes proportional margin removal and ordinary two-team winner conditioning; it is not verified current fair value, independent evidence or an executable edge. No exact delay is assumed. The old parser and strict live/research eligibility policies are unchanged; the new arithmetic path validates identity and both prices independently of those eligibility gates.

## Commands

Run from `/Users/michaelfuscoletti/Desktop/prediction-arb`. All commands read local files only. Use a new directory for each synthetic demonstration.

```sh
.venv/bin/python -m app.reference.research_loop calculate evidence/public-nfl-reference
.venv/bin/python -m app.reference.research_loop save evidence/public-nfl-reference /tmp/predict-page-journal
```

The save response contains `id` and actual `saved_at`. Substitute that ID below:

```sh
.venv/bin/python -m app.reference.research_loop reopen /tmp/predict-page-journal PREDICTION_ID
.venv/bin/python -m app.reference.research_loop annotate /tmp/predict-page-journal PREDICTION_ID sporting /path/to/sporting.json
.venv/bin/python -m app.reference.research_loop annotate /tmp/predict-page-journal PREDICTION_ID settlement /path/to/settlement.json
.venv/bin/python -m app.reference.research_loop evaluate /tmp/predict-page-journal
```

Annotation JSON requires `source` (result URL or artifact reference), `published_at`, `observed_at`, `final` and `synthetic`. Sporting records additionally require `result` (exact team name, `tie`, `cancelled` or `unresolved`) and `score`. Settlement records require `contract_id`, `payout_per_contract` (null when unresolved) and `basis`. Use ISO timestamps with timezone. Actual recording time is generated locally; there is no CLI clock override. No real result is supplied in this package.

Corrections use the same save or annotate command with `--supersedes-id OLD_ID --reason 'correction explanation'`. Prior records remain intact. Annotation corrections must extend the latest annotation of that kind; prediction corrections are exploratory and never replace the predeclared primary. Evaluation commands append versioned results with the exact prediction and sporting-annotation IDs used.

A complete invented-clock/invented-result example using the actual saved page:

```sh
.venv/bin/python -m app.reference.research_loop demo evidence/public-nfl-reference /tmp/predict-page-demo
.venv/bin/python -m app.reference.research_loop evaluate /tmp/predict-page-demo
```

This saves and reopens the prediction, uses a clearly synthetic September 17 23:50 UTC pregame clock, then appends an **invented** Detroit 24–21 result and a separate **invented** $1 synthetic DET-YES settlement. These are not actual game facts. The original real source receipt, actual estimate time and actual disk save time remain visible. The demonstrated Detroit Brier is `0.432273673060962410229726486210147649`, against 0.25; synthetic scores never enter prospective aggregates.

`--primary` on `save` designates the first primary for this one game. Prospective classification requires source receipt, estimate and save in the declared 30-to-20-minute pregame window; a historical capture reused then is retrospective. Saves at/after kickoff minus 60 seconds are retrospective. A cutoff preceding source receipt is rejected. The delivered real record was actually saved September 16 at 03:58:01.045886 UTC and is **exploratory**, not a retrospectively backdated forecast. The journal is intentionally one-event scope, not a multi-week pilot manager.

Records embed source bytes and capture metadata, validate content hashes on reopen and recompute the result. Writes use exclusive creation and flush before returning success. Local hashes establish integrity, not external proof of creation time. Keep a journal single-writer; concurrent-writer coordination and production hardening are outside this POC.

## Conditional EV

```sh
.venv/bin/python -m app.reference.research_loop compare evidence/public-nfl-reference evidence/multi-game/sessions/5c9b7dca-a813-4d77-80f5-0691d06068eb
```

**Retrospective, time-mismatched research comparison.** The identified Kalshi Buffalo YES target is `KXNFLGAME-26SEP17DETBUF-BUF`, received September 16 at 01:07:35.681097 UTC; its cutoff is 01:07:35.685652 UTC. The reference arrived at 03:26:29.205210 UTC. It is never inserted into that earlier cutoff or prospective scoring.

The existing purchase/depth/fee/cashflow code supplies diagnostics for 10 contracts: $6.80 purchase cost, $6.96 entry cash under the pinned historical cent fee scenario. The scenario assumes multiplier 1, no event override and a hypothetical new taker order; it does not verify current account applicability. The saved comparison retains original target listing/book dependencies, receipt/source times, mapping, fills, assessment and fee audit. Buffalo receives Buffalo's probability, despite reversed source ordering.

**Page-to-target conditional EV is unavailable:** DraftKings ordinary-winner rules and their comparability to the target have not been assessed. Exceptional probability mass and material exceptional cashflows also remain unknown, so unconditional EV is null. The package does not invent this missing evidence.

The standalone synthetic scenario function reuses depth walking and the shared state-cashflow expectation calculation. It accepts explicitly named total-fee/payout assumptions, never infers a venue schedule. [Plan example](../evidence/page-research/plan-example.json): odds 1.8/2.1 give 7/13; 6×$0.54 + 4×$0.55 + assumed $0.16 fee = $5.60 cash. Exact rational EV is −14/65; stored-probability EV is `-0.215384615384615380` (−$0.22), ROI approximately −3.85%. Missing fees, payouts or depth produce unavailable net calculations; exceptional mass never defaults to zero. These invented inputs remain separate from page-derived estimates.

## Evaluation and verification

Ordinary-result Brier uses one designated primary per game and a predeclared 0.5 baseline on the same games. Complementary sides are not separate samples. Repeated/exploratory, retrospective, synthetic, tie, cancelled and unresolved observations retain distinct designations/reasons. Settlement annotations do not change sporting scores. Neither modeled cashflow nor probability accuracy is realized trading profit. No calibration or profitability claim follows from this one-game demonstration.

Focused verification: 82 reference/pricing/opportunity/parser/research tests pass; four existing reconciliation tests reproduce the 18 candidates and 96 EV scenarios byte-for-byte with the baseline write intercepted. Independent rational assertions cover both the actual pair and plan example, reversal, invalid identity/odds, unknown timing, positive/zero/negative/unavailable calculations, depth/fees, replay integrity, late receipt/save, historical reuse, append-only corrections, separate annotations and one-score-per-game behavior. Original evidence hashes were checked unchanged; see [verification](../evidence/page-research/verification.json). No broad fault matrix or UI rerun.

**Practical next action:** inspect the saved-page result and run the synthetic `demo` command in a fresh local directory. No new capture or real outcome backfill is needed.
