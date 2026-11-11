# SportsGameOdds free evaluation

November 10, 2026 · experimental, offline analysis · **not a production benchmark**

## Updated direction

After this sample, the owner clarified that the immediate evaluation is whether
SportsGameOdds makes Predict's large datasets cleaner and easier to collect,
integrate, operate and use. The vendor's fair odds are a useful independent
comparison and baseline, not the primary question or a reason to require an
extended model-accuracy study before assessing the data platform. The findings
below remain the historical results of the first experiment. Continue with the
[updated engineering evaluation](sportsgameodds-evaluation-plan-20261110.md#updated-direction-after-the-initial-sample).
The owner will always retain direct Kalshi and Polymarket US implementations.
Paid-tier breadth across P2P venues and US sportsbooks is an opportunity for
future EV research; actual availability and coverage remain to be verified.

## Decision

Continue targeted free experimentation and retain the existing source and Pinnacle benchmark for now. A two-sided, line-specific median is transparent enough to investigate, but one afternoon's prices do not establish accuracy, independence, reliable freshness, or an improvement in realized outcomes. The vendor's fair odds are an interesting second candidate; the responses did not expose a timestamp or contributors for that estimate, and sometimes its fair line differed from the market being evaluated. A paid Rookie purchase is not supported or ruled out by this sample.

## Account and sample

At approximately 3:49 p.m. Eastern the active key's usage endpoint reported **10 requests/minute and 2,500 objects/month**, with zero monthly objects already used. That matches the published Amateur limits, but the response did not identify the subscription, trial state, or reset date; the limit alone cannot prove billing status or rule out a trial. The vendor says the monthly period rolls from first use; the account response here did not confirm its specific reset time. [Vendor limits](https://sportsgameodds.com/docs/info/rate-limiting) · [Vendor FAQ](https://sportsgameodds.com/docs/faq)

Three event calls returned five NBA and five NHL games, all pregame, plus an empty live query across NBA, NHL, NCAAB, NCAAF and NFL. Final usage was **11/2,500 objects**, an increase of 11: ten returned events and one minimum-charge empty response. Usage reads did not increase the observed object count. Both five-event results had a `nextCursor`; this was a bounded first-page sample, not a complete league census. An empty live query at this time is not proof that live odds are unavailable. The NBA and NHL responses respectively reported 23,693 and 19,498 bookmaker odds omitted due to the key's access; that is the provider's response notice, not a count independently verified here.

The nine distinct bookmaker IDs actually returned with available odds in these two samples were **betmgm, bovada, caesars, draftkings, espnbet, fanduel, pointsbet, unibet and williamhill**. Pinnacle, Circa and P2P venues did not appear in these sampled responses; no conclusion follows about other leagues, markets, times, or paid plans. SGO returned available full-game moneyline, spread and total sides in both leagues, as well as other periods, team totals and player markets. The five NBA and five NHL events each had ten available full-game moneyline sides and ten spread sides. Total-side counts include team totals as well as game totals. Availability of a side alone does not prove an exact two-sided pair is usable.

The NBA response was received at 20:49:18 UTC and the NHL response at 20:49:19 UTC. Bookmaker entries contain individual `lastUpdatedAt` timestamps, prices, availability and, where applicable, lines. Vendor fair odds have availability and, for spreads/totals, a fair line, but no fair-odds source timestamp was present in these observations. Receiving a recent bookmaker timestamp does not independently verify actual update cadence, latency, or freshness of the consensus.

## Reproducible comparison

The [offline evaluator](../scripts/sgo_free_evaluation.py) reads cached observations only. It matches exact NBA team names, league, scheduled start, full-game period, pregame phase, market, selected side and signed line. It accepts only a complete available SGO book pair at the exact line with both source clocks at most 30 minutes old and not in the future relative to the SGO receipt. The current Predict Pinnacle pair must have both original source clocks within the same bound. This is a conservative analysis threshold, not a verified SGO freshness guarantee. The existing Predict snapshot was read locally without provider requests, and its original Pinnacle clocks and odds are retained. The page was limited to the first 100 ranked outcome groups; counts below are not all possible matches. Normal full-game meanings align at the level described by the feeds, but exceptional bookmaker-specific settlement terms and clock synchronization were not independently established.

**Observed structurally matched sample:** 16 directed outcomes, or eight two-sided markets, across the five NBA games: five moneylines, two totals and one spread. Each had a complete existing Pinnacle pair and at least three eligible SGO bookmaker pairs on the same line. These are observations, not independent games or evidence of predictive accuracy. Fair odds at the same line were returned for 12 of the 16 outcomes; their unreported source clock makes their temporal comparability unverified. Sixteen Pinnacle-to-book-median comparisons have qualifying displayed clocks; exceptional settlement equivalence remains a qualification. NHL was inventoried, not included in this comparison; abbreviated team names in the Predict view were not automatically joined.

Each bookmaker probability is proportional no-vig: convert both American prices to implied probabilities, then divide the selected side's implied probability by their sum. The multi-book estimate is the median of these individual values. It does not assign sharpness based on bookmaker names. For the examples the evaluated venue was Novig, absent from the nine contributing bookmakers; the code can explicitly exclude a named venue. Books may share ownership or feed sources, so nine entries are not necessarily nine independent opinions. All estimates are conditional on decisive win/loss, not complete probabilities for pushes, voids or exceptional settlements.

| Example, selected side | Pinnacle | SGO fair | SGO book median | Difference: median minus Pinnacle |
| --- | ---: | ---: | ---: | ---: |
| Bucks at Knicks, Bucks moneyline | 12.415% | 11.962%* | 12.000% | −0.415 percentage points |
| Magic at Kings, Magic moneyline | 68.233% | 67.105%* | 67.278% | −0.955 points |
| Clippers at Suns, under 224.5 | 51.671% | 50.000%* | 50.000% | −1.671 points |
| Heat at Jazz, over 227.5 | 51.161% | unavailable: fair line 228 | 51.081% | −0.080 points |
| Magic at Kings, Magic −6.5 | 50.000% | unavailable: fair line −6 | 50.000% | 0 points |

\* The fair estimate's original clock is unknown; these figures are indicative, not verified contemporaneous comparisons.

For Bucks moneyline, Pinnacle's decimal pair was 7.76 and 1.10 with source time 20:45:01 UTC. All nine listed books contributed to the median. DraftKings' +670/−1040 pair gave 12.462%, with both sides timestamped 20:48:50.599 UTC; FanDuel's +750/−1200 pair gave 11.304%, both timestamped 20:47:45.211 UTC. At the captured Novig cost of 25/238 per $1 normal claim, the gross conditional return `probability / cost − 1` is **18.19%** using Pinnacle, **14.24%** using the median, or **13.88%** using the indicative vendor fair probability. These are not execution or after-fee claims.

For Clippers at Suns under 224.5, Pinnacle's two decimal prices were 2.01 and 1.88, selected under 1.88, both at 20:45:01 UTC. BetMGM, DraftKings, ESPN Bet and FanDuel contributed at exactly 224.5; Bovada, Caesars and PointsBet had a different line and were excluded. Their included clocks ranged from 20:47:45.211 to 20:48:59.215 UTC. At the captured Novig cost 25/49 per $1 normal claim, gross conditional return changes from **+1.28%** with Pinnacle to **−2.00%** with the median or the timestamp-unknown vendor fair estimate. This illustrates sensitivity, not which reference is right or whether the offer remains available.

All original pairs, exclusions, clocks, event identities and probabilities are retained in the [local analysis](../.local/sgo-evaluation-20261110/analysis.json) and the [NBA](../.local/sgo-evaluation-20261110/nba.json), [NHL](../.local/sgo-evaluation-20261110/nhl.json), [live query](../.local/sgo-evaluation-20261110/live.json), and [Predict snapshot](../.local/sgo-evaluation-20261110/predict-page.json). Reproduce with:

```text
.venv/bin/python scripts/sgo_free_evaluation.py .local/sgo-evaluation-20261110/nba.json .local/sgo-evaluation-20261110/predict-page.json .local/sgo-evaluation-20261110/analysis.json
.venv/bin/python -m pytest -q tests/test_sgo_free_evaluation.py
```

Five tests passed, covering exact proportional arithmetic, missing/unavailable and stale/future sides, mismatched total/spread lines, outliers, venue exclusion, and incompatible period/opposing market. Lint passed. No app financial calculation, paid collection, production venue, native connection, source control or quota/hold record was changed for this evaluation. Existing fee coverage and its paused in-game validation remain open.

## What is still missing

- Repeated prospective samples, including actual in-game periods, wider leagues, exact market and settlement audits, measured source latency and stable timestamp behavior. Compare against closing prices and settled outcomes with an appropriate sample before claiming calibration or superiority. Inspect correlated books, contributor sensitivity and leave-one-out results.
- Verify account plan, trial and reset in the account portal if a billing conclusion is needed. This key's limits and observed response do not establish Rookie entitlement, P2P coverage, update cadence, depth or prices.
- For a later Rookie investigation, verify actual price, billing commitment, trial, tax and plan-specific access; whether Polymarket means Polymarket US; executable sides, timestamps, precision, depth, fees and settlement. Measure event/object demand across real slates and schedule live and imminent games more frequently than distant games. Compare coverage, freshness, reliability and total cost against The Odds API. Preserve native Kalshi and Polymarket US for audit, reconciliation and depth until their role is explicitly assessed. No subscription, source replacement or new production venue is authorized by this evaluation.
