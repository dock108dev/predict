# Novig NFLWIN public product basis, revision 2

`novig-nflwin-public-model-20261022-2`, reviewed October 22, 2026. Effective
October 22 through October 28 UTC; review before October 29, the next NFL
scheduling week. This short operational review horizon limits reliance on mutable
public terms; it does not imply stable probabilities. Withdraw earlier on changed
terms or kickoff. The prior expiry is not extended.

## Documented rules and applicability

Exact [NFL Winner Series, NFLWIN / NFL-004](https://novig.intercom-attachments-1.com/i/o/y5ui11zw/2574338241/138190d9b820637c62eaad1d0718/NFL%2BWinner%2BSeries.pdf),
Public Appendix A, retrieved October 22; no printed revision date. The downloaded
PDF and SHA-256 are retained in the validation evidence. References below use
physical PDF pages, starting at 1.

- Payout Criterion (p5) and Official Game and Winner Rule (p6–7): full-game
  overtime included; winner receives $1, loser $0, tie $0.50 per face.
- Scheduling/Postponement and No Result (p7), Contingencies (p8): delayed,
  canceled or forfeited sports games do not map mechanically to exchange voids.
- Fair Value Settlement (a)–(g), p8–10: uses a pre-disruption reference time,
  normally a preceding 30-minute composite-price window; fair value is bounded
  by $0 and $1. Unreliable components are excluded. Fallbacks use a prior reliable
  window, then related contracts, then return funds at risk when no reliable value
  can be established. Refund is the final fallback, not an equally likely branch.

The [fee schedule, Official fee schedule and FAQ](https://support.novig.com/en/articles/16195057-fees-on-novig)
confirms zero pregame straight maker/taker trading fees for app/web and API, with
full winning payout. Account, transfer and tax costs are outside this estimate.
The page has inconsistent live coefficients in its later VWAP example; live and
futures remain outside this binding.

The Odds API Novig pregame NFL h2h observation is mapped at the public-product
estimate level only. Participant orientation, full-game scope, original two-way
benchmark and clocks must pass existing checks. This is not an authenticated
individual NFLWIN listing or execution binding. Native bound rules are never
overwritten. Hypothetical risk A, rounded down to cents, implies face A*d at
decimal odds d; residual cents are unspent. Legal grid, liquidity and fills are
not established.

## Historical evidence and its limits

Reproducible [nflverse game dataset](https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv),
retrieved October 22, 2026; retained CSV, hash, analysis and per-season IDs in
`test-results/sc07-v-model-validation-20261022/`. One row per game, REG only,
2017–2025 seasons with both final scores present; ties require equal final scores.
Preseason, postseason, unscored/canceled games and incomplete 2026 season excluded.
The 2022 canceled BUF–CIN game is not a completed-game denominator or evidence of
a Novig void. The denominator is all completed eligible games, not overtime games,
team-games, listed contracts or observations.

| Season | Completed games | Ties |
|---|---:|---:|
| 2017 | 256 | 0 |
| 2018 | 256 | 2 |
| 2019 | 256 | 1 |
| 2020 | 256 | 1 |
| 2021 | 272 | 1 |
| 2022 | 271 | 2 |
| 2023 | 272 | 0 |
| 2024 | 272 | 0 |
| 2025 | 272 | 1 |

2017–2024: 7/2111 = 0.3316%, descriptive 95% Wilson interval
0.1607%–0.6829%. The [2025 rule change](https://operations.nfl.com/the-rules/nfl-rulebook)
allowed both teams possession subject to ten minutes; pooling across that change
would obscure applicability. 2025 alone: 1/272 = 0.3676%, interval
0.0649%–2.0528%. [Current rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook)
remains the authority for current play. Postseason has no tied final outcomes and
is not part of these frequency estimates.

These intervals assume independent common-rate Bernoulli games and describe
sampling uncertainty only. Team strength, game conditions, observation selection,
rule changes and known disruption information violate simple transport to the
required at-observation terminal probability. No out-of-sample calibration was
performed. Neither frequency is installed as a forecast. The 0.5% tie reference
remains explicitly hypothetical, not validated by lying within an interval.

Official [FVS explanation](https://support.novig.com/en/articles/16163706-what-is-fair-value-settlement-fvs)
and [methodology](https://support.novig.com/en/articles/16200428-how-novig-calculates-the-fair-value-price)
were checked, along with targeted NFLWIN/void settlement searches. They explain
procedures and examples, not a usable listing-level settlement cohort. No applicable
void numerator/denominator, refund branch count or fair-value sample was obtained.
The methodology describes refunds as rare, without a measured rate. Thus 0.1%
void is a scenario only, and the earlier 50/50 mixture is removed. Missing history
is not zero risk. Even a martingale argument for unconditional future prices would
not identify expected fair value conditional on the selected void event, its
reference time, exclusions and fallback selection. Original decisive p is not
reused as that conditional expectation.

## Installed calculation and sensitivity

Conditional net EV C = A*(p*d-1), using the original two-way proportional no-vig
benchmark conditional on decisive outcomes. This benchmark is not newly calibrated.
Full scenario EV uses unconditional exclusive tie t and void v masses, refund
share r within void, and expected selected fair value f conditional on non-refund
void:

```
EV = (1-t-v)*C + t*A*(d/2-1) + v*A*(r+(1-r)*d*f-1)
buffered EV = EV - buffer
```

All arithmetic is exact. t+v <= 1, all probabilities and f in [0,1]; absent f is
allowed only for r=1. The displayed reference is t=.005, v=.001, r=1 (hypothetical
refund-only void), with f unavailable. This is an inspectable scenario, not a
preferred or evidence-supported full-EV forecast. It avoids inventing a future
fair-value expectation. Conditional EV remains independently visible.

Details also shows the exact corner range over hypothetical t=0–2.5%, v=0–1%,
r=0–1 and f=0–1, after one buffer. Probability limits are illustrative, neither
confidence bounds nor inferred settlement rates; the tie range spans the observed
sampling intervals without claiming calibration. Fair-value endpoints come from
the public rule. The expression is multiaffine, so corner evaluation spans this
box; refund receipts lie between zero and face and do not widen its extrema.
This expected-value range is never used as a covered settlement minimum.

At t=.005 and v=.001, the break-even expected void receipt per face is
`[buffer-(1-t-v)*C-t*A*(d/2-1)+v*A]/(v*A*d)`.
A second threshold fixes zero void receipt and solves the break-even void rate.
Out-of-feasible-range roots are labeled unattainable. Sign changes are explicit.
Shared cashflow/cost/probability owners calculate the displayed scenario and
conditional EV; exact algebra supplies parameter sensitivity checked against them.

Publication, HTTP and Details retain basis, scenario inputs and sensitivity; cards
rank the disclosed hypothetical refund scenario. Source clocks and last-known
status are unchanged. Actual void receipt and complete covered minimum remain
unknown. No calibrated full forecast, execution claim or covered arbitrage follows.
Owner acceptance remains **changes requested**.
