# Multi-game saved-page research

Completed September 16, 2026. [Open saved research list](http://127.0.0.1:8783/?view=research&capture=5c9b7dca-a813-4d77-80f5-0691d06068eb&quantity=100&scenario=cent&sort=dollars). **All six saved games are covered** by exact same-column DraftKings full-game moneyline pairs; no missing or ambiguous pairs in this retained page. No new source or target data was fetched.

## Results and independent arithmetic

100 requested Kalshi YES contracts, historical cent-balance scenario. All six have enough retained depth at this size. Net dollars and ROI below are display-rounded; ranking uses exact stored values. Source implied probabilities and overround are calculated before proportional de-vig. The existing 50-digit calculation stores probabilities to 18 decimals; 100-digit cashflow arithmetic uses those stored probabilities. Exact rational odds/probabilities remain in the evidence.

| Game / Kalshi YES team | DraftKings pair (page order) | YES probability | Ask | Cost | Fee | Conditional net | ROI |
|---|---|---:|---:|---:|---:|---:|---:|
| CLE Browns vs TB Buccaneers / Cleveland Browns | Cleveland Browns +310 / Tampa Bay Buccaneers -395 | 23.409790% | $0.22 | $22.00 | $1.21 | $0.20 | 0.86% |
| CIN Bengals vs HOU Texans / Cincinnati Bengals | Cincinnati Bengals +120 / Houston Texans -142 | 43.650794% | $0.42 | $42.00 | $1.71 | $-0.06 | -0.14% |
| CAR Panthers vs ATL Falcons / Atlanta Falcons | Carolina Panthers -135 / Atlanta Falcons +114 | 44.855889% | $0.44 | $44.00 | $1.73 | $-0.87 | -1.91% |
| NO Saints vs BAL Ravens / Baltimore Ravens | New Orleans Saints +320 / Baltimore Ravens -410 | 77.150538% | $0.79 | $79.00 | $1.17 | $-3.02 | -3.77% |
| MIN Vikings vs CHI Bears / Chicago Bears | Minnesota Vikings +185 / Chicago Bears -225 | 66.364812% | $0.68 | $68.00 | $1.53 | $-3.17 | -4.55% |
| DET Lions vs BUF Bills / Buffalo Bills | Detroit Lions +180 / Buffalo Bills -218 | 65.747523% | $0.68 | $68.00 | $1.53 | $-3.78 | -5.44% |

[Per-row rational reconciliation](../evidence/multi-page-research/reconciliation.json) includes exact probabilities, overround, fees, net, ROI, capacities and observation times. The oracle reads saved native opposite-side Kalshi bids, converts asks as 1 − bid, walks each ladder, and applies the retained quadratic taker formula with six-decimal ceiling, selected balance grid and order rounding refunds. It does not call the application fee/EV functions for expectations. Original page odds are asserted against the inspected six pairs. All five newly supported rows and Detroit–Buffalo agree, including first-level/depth boundaries and both cent/0.0001 scenarios.

## Per-event assessment and limitations

[Six separate assessments](../evidence/multi-page-research/assessments.json) bind event ID, schedule, both participant identities, full-game source market, source hash, target YES team/predicate, market ID, exact book ID and retained terms hash. Each target’s native first rule explicitly names its actual team winning its actual game on its scheduled Eastern date. Buffalo, Atlanta, Baltimore and Chicago use the second page side; Cincinnati and Cleveland use the first. Each event-specific conclusion reuses only applicable general rule evidence from the prior September 16 assessment: DraftKings football/two-way-moneyline overtime semantics and the retained official NFLGAME PDF. The prior DraftKings HTML was an application shell; its recorded official-search excerpts are reused honestly, with no new rules retrieval or historical ticket certification.

Ordinary completed-game winner comparability includes overtime. Full settlement equivalence remains false: sportsbook tie pushes differ from Kalshi $0.50 payouts; cancellations, interruptions, postponement windows, refunds and fair-price/review discretion remain explicit. Unknown exceptional mass/cashflows keep unconditional EV unavailable. Unassessed ordinary-winner terms suppress conditional net while retaining the page probability.

Every row is **retrospective and time-mismatched**. The shared source receipt is `2026-09-16T03:26:29.205210+00:00`; the earlier per-game target receipts and cutoffs remain unchanged. Bookmaker update time, delay, upstream synchronization and independence are unknown. Proportional margin removal and pinned historical fees are assumptions; this is not current fair value or an executable edge. Cleveland’s small conditional positive is an arithmetic result, not a profitability qualification.

## View and focused verification

The separate Page-derived research view shows target purchase, probability, ask, requested/available size and conditional net/ROI. Sorting uses the same requested quantity and selected fee scenario, before rounding; unavailable values sort after all numbers. Negative results and near misses stay visible even if the Arb view had positive/venue/freshness filters selected. Search remains available. Insufficient depth never reduces the modeled research order; available native capacity is shown separately. Unknown material fees suppress net and ROI.

Details contains source/target timestamps, original odds, de-vig arithmetic, fee basis and settlement exceptions. Clicking a row opens the existing game detail with the same source, target, quantity and scenario, then returns with selected row and list settings intact. Research probability is never sent as a manual-input URL parameter, never written into owner assumptions, never added to live rankings and never written to prospective prediction/scoring records.

42 focused tests pass: six-row rational checks, cross-game isolation/reversed ordering, malformed/missing/duplicate book pairs, schedule and assessment binding, depth/unknown fees, positive/negative/exact-zero sorting, preserved clocks, manual/live/prospective separation, and the unchanged 18-candidate/96-scenario reconciliation. Two JavaScript presentation/persistence checks and syntax validation pass. Actual browser verified research list → dollar sort → Cleveland Details → return, selection/quantity/scenario/sort retention, blank manual probability and 390px list/detail layouts (document width 390, including expanded list Details). No browser warnings/errors; viewport reset.

All original observations and assessments are preserved. 1,729 of 1,730 preexisting evidence files are byte-identical; the sole change is the old running beta’s operational log flushing its startup banner on shutdown. The original log is retained. [Verification](../evidence/multi-page-research/verification.json). Existing uncommitted work remains.

Only confirmed-idle beta PID 21610 was restarted, replaced by PID 25527. It is left open on the saved research list at 100 contracts/cent fees/dollar sort, feeds stopped and cleanup complete. No scan, provider request, credentials, backfill, database change, unrelated service change, trade, commit, push or publishing. Implementation verification does not record owner acceptance.
