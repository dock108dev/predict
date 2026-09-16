# Six-game independent math reconciliation

Completed September 15, 2026 EDT (September 16 UTC). **All 18 saved Arb rows reconcile: 12 conditional numeric results and six unavailable alternatives.** No saved economic value or rank changed. One exact-sorting precision defect was corrected; the real baseline is byte-identical before/after. Arithmetic agreement does not qualify account fees, exceptional settlement or profitability.

## Basis and independent method

Saved session `5c9b7dca-a813-4d77-80f5-0691d06068eb`; requested 100 whole contracts per leg; default `cent` what-if fee scenario. Each game uses its own saved default cutoff, not the scan finish time. Twelve calculable candidates use all 100 contracts; six unsupported pairs have no common purchasable size and remain unavailable. No probability is injected into the observed baseline.

The [rational oracle](../tests/test_math_reconciliation.py) reads retained native JSON directly, uses `Fraction` arithmetic for depth, fees and cashflows, and compares against dashboard output. It does not obtain expected economics from the application fee, depth or EV functions. ROI is an exact fraction converted to the application’s 100-significant-digit Decimal precision for comparison; displayed cents/percentages were also checked in the isolated browser. The [full comparison](../evidence/math-reconciliation/baseline.json) records exact values, consumed levels, per-contract profit, original book/listing IDs and receipt times, plus both rankings.

Reuse: the existing [native replay evidence](../evidence/multi-game/independent-replay.json) ties all 231 native book images and 474 quote packets to the saved journal. This review uses its verified Kalshi reconstructed bids and original US `marketData.offers`; it does not claim a second independent transport implementation. The journal hash remains `a991ed3799e0b934baa9ca42174e12c158692a44f196fb88213dbd72ba7b292d`.

| Game | Saved default cutoff (UTC, 2026-09-16) | Cross-leg receipt skew | Cross-venue usable then? |
|---|---|---:|---|
| DET Lions vs BUF Bills | 01:07:35.685652+00:00 | 3.841322 s | Yes |
| CAR Panthers vs ATL Falcons | 01:07:30.666376+00:00 | 0.113054 s | Yes |
| NO Saints vs BAL Ravens | 01:07:31.292057+00:00 | 6.296875 s | No: exceeds 5 seconds |
| MIN Vikings vs CHI Bears | 01:07:33.358614+00:00 | 2.862491 s | Yes |
| CIN Bengals vs HOU Texans | 01:07:42.998007+00:00 | 17.320943 s | No: exceeds 5 seconds |
| CLE Browns vs TB Buccaneers | 01:07:33.865575+00:00 | 9.223245 s | No: exceeds 5 seconds |

The selected books and latest listing records were retained by their cutoff. All selected books are within the 30-second receipt-age window; native source timestamps do not establish guaranteed upstream freshness. Receipt-skew exclusions remain independent of arithmetic. All results remain historical and non-executable.

## Per-candidate comparison

USD amounts below are displayed values; independent net/ROI are rounded only for this table. Every underlying supported cost, fee, entry cash, winner cashflow and ROI matches. K = Kalshi; U = US Long. A Kalshi NO means its native team does not win, conditional on the two normal winners for the complementary exposure.

| Game | Candidate / purchases | Cost | Fees | Entry cash | Display net / ROI | Independent net / ROI | Match |
|---|---|---:|---:|---:|---|---|---|
| DET Lions vs BUF Bills | cross-yes: K YES + U Long | 101.00 | 2.86 | 103.86 | -3.86 / -3.72% | -3.86 / -3.72% | Yes |
| DET Lions vs BUF Bills | kalshi-pair: K YES + K NO | 101.00 | 3.08 | 104.08 | -4.08 / -3.92% | -4.08 / -3.92% | Yes |
| DET Lions vs BUF Bills | cross-no: K NO + US Short unsupported | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Yes |
| CAR Panthers vs ATL Falcons | cross-yes: K YES + U Long | 100.50 | 3.20 | 103.70 | -3.70 / -3.57% | -3.70 / -3.57% | Yes |
| CAR Panthers vs ATL Falcons | kalshi-pair: K YES + K NO | 101.00 | 3.45 | 104.45 | -4.45 / -4.26% | -4.45 / -4.26% | Yes |
| CAR Panthers vs ATL Falcons | cross-no: K NO + US Short unsupported | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Yes |
| NO Saints vs BAL Ravens | cross-yes: K YES + U Long | 100.50 | 2.18 | 102.68 | -2.68 / -2.61% | -2.68 / -2.61% | Yes |
| NO Saints vs BAL Ravens | kalshi-pair: K YES + K NO | 101.00 | 2.38 | 103.38 | -3.38 / -3.27% | -3.38 / -3.27% | Yes |
| NO Saints vs BAL Ravens | cross-no: K NO + US Short unsupported | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Yes |
| MIN Vikings vs CHI Bears | cross-yes: K YES + U Long | 100.00 | 2.84 | 102.84 | -2.84 / -2.76% | -2.84 / -2.76% | Yes |
| MIN Vikings vs CHI Bears | kalshi-pair: K YES + K NO | 101.00 | 3.08 | 104.08 | -4.08 / -3.92% | -4.08 / -3.92% | Yes |
| MIN Vikings vs CHI Bears | cross-no: K NO + US Short unsupported | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Yes |
| CIN Bengals vs HOU Texans | cross-no: K NO + U Long | 101.00 | 3.16 | 104.16 | -4.16 / -3.99% | -4.16 / -3.99% | Yes |
| CIN Bengals vs HOU Texans | kalshi-pair: K YES + K NO | 101.00 | 3.41 | 104.41 | -4.41 / -4.22% | -4.41 / -4.22% | Yes |
| CIN Bengals vs HOU Texans | cross-yes: K YES + US Short unsupported | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Yes |
| CLE Browns vs TB Buccaneers | cross-no: K NO + U Long | 100.76 | 2.11 | 102.87 | -2.87 / -2.79% | -2.87 / -2.79% | Yes |
| CLE Browns vs TB Buccaneers | kalshi-pair: K YES + K NO | 102.00 | 2.33 | 104.33 | -4.33 / -4.15% | -4.33 / -4.15% | Yes |
| CLE Browns vs TB Buccaneers | cross-yes: K YES + US Short unsupported | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Yes |

Native orientation was checked against retained market identities/rules and US `marketSides` team names/Long flags. The Kalshi YES teams are Buffalo, Atlanta, Baltimore, Chicago, Cincinnati and Cleveland respectively. US Long teams are Detroit, Carolina, New Orleans, Minnesota, Cincinnati and Cleveland. Thus the final two games correctly pair **Kalshi NO with US Long**. No US bid or Short quote is converted into a purchase ask. Kalshi purchase asks are `1 − opposite bid`, retaining contract quantity.

**Depth matters in Cleveland:** US Long consumes 48 at $0.205 and 52 at $0.210, costing $20.76, not $20.50. Raw fees are $0.469368 and $0.517608; per-fill half-even charges are $0.47 and $0.52, within the cumulative rounded cap of $0.99. Kalshi NO costs $80 with $1.12 fee. Total $102.87 gives −$2.87, or −$0.0287 per paired contract and −2.79% on entry cash. Every other supported baseline leg consumes only its first price level. All ladder capacities, top quantities and consumed levels match the retained JSON.

For either normal winner, each complementary pair pays $100 gross. Profit is `100 − purchase cost − net modeled fees`; per-pair-unit profit is that amount / 100, and ROI is profit / entry cash × 100. Each individual leg’s winning payout is $100 and losing payout $0; subtract its entry cash for net cashflow. Supported tie gross payout is $50 per leg. Exceptional discretionary payouts remain unknown, so all-outcome worst-case profit remains null. No supported stake refund is assumed for fair-price settlement.

## Fee and input qualification

| Classification | Inputs / treatment |
|---|---|
| Observed | Retained native prices, quantities, book/listing identities and receipt times; US listing coefficient 0.06. Full depth means the supplied ladder, not guaranteed fillability. |
| Evidenced formulas | Retained fee documentation and market-specific payout terms. Kalshi taker model 0.07 × q × p × (1−p); six-decimal ceiling, balance-grid rounding and per-order rounding refunds. US 0.06 × q × p × (1−p), cent half-even with cumulative order cap that can only reduce fill charges. |
| Explicit assumptions | Kalshi multiplier 1, no event override, cent balance; US no settlement levy; no extra account charges/rebates; one new taker order per leg and one fill per consumed price level; both legs filled; normal winner settlement for net/EV. |
| Unknown | Actual account precision/charges, Kalshi effective event override history, actual fill partition and execution, US independent settlement levy, exceptional probabilities and discretionary payouts. These are not verified by matching arithmetic. |

Sources retained locally: [Kalshi rounding](../evidence/slice-9/research/kalshi-rounding.md), [US fee formula/grouping](../evidence/slice-9/research/pmus-fees.md), [pinned schedules](../app/fixtures/fee-schedules-v1.json), and each selected market’s original terms in the session. The US July 1 schedule and retained 0.06 coefficient cover this historical scenario. The later 0.0695 announcement recorded in the opportunity-board report is not applied retrospectively. Kalshi’s July 7 document has no precise effective timestamp in the registry; applicability remains explicitly conditional, not proven from a pinned version alone.

The same-market pair’s missing exceptional assessment also remains unknown; this review does not turn the conservative unresolved classification into full qualification. Unknown-fee mode leaves net/break-even null. Fractional US fill support remains unavailable even though native books contain fractional quantities; whole requested size does not make fractional intermediate fills supported.

## EV and focused boundaries

**96 explicitly entered test cases**, separate from the observed baseline: every supported side in every game at p=0, 0.2, 0.4, 1 and its exact break-even; every unsupported Short at p=0.4. All 24 sides also checked with no probability and with unknown fees. Positive, negative, exact zero and unavailable results agree with the rational oracle.

For supported normal binary settlement, expected payout = p × q; expected profit = p × q − entry cash; break-even p = entry cash / q; ROI = expected profit / entry cash × 100. For Kalshi NO, p is the probability of the opposing normal winner, not the native YES team. The explorer preserves the entered probability and labels it user-entered, conditional on normal winners, with no independently discovered fair price. Unknown tie/void/refund/discretionary mass is excluded explicitly; these numbers are not unconditional EV.

Example: Minnesota US Long at 100 costs $32 + $1.31 = $33.31. At p=0.4: payout $40, net $6.69, ROI 20.08%; at p=0.2: −$13.31; at p=0.3331: exactly zero; endpoints: −$33.31 / $66.69. Break-even 33.31%. These assumptions are test inputs only.

Depth checks use separate copies: 99/100/101 around a 100-contract level at $0.20 followed by $0.30, yielding US costs $19.80/$20.00/$20.30 and fees $0.95/$0.96/$0.97; 200 fills fully, 201 is unavailable in the uncapped evaluator and correctly caps to 200 in the dashboard. A three-level Kalshi order costs $1.80 plus $0.05 net fees after a $0.01 rounding refund. Existing independent half-even, grouping, direct-precision, missing/stale/skewed, invalid increment and fractional-US checks were reused.

## Correction and verification

The ranking key used unary `-Decimal(n)` outside the calculation’s 100-digit context. Python applies ambient Decimal precision (normally 28 digits) to that operation, collapsing distinct values before sorting. For explicit test values `1.00000000000000000000000000001` and `1.00000000000000000000000000002`, the lower row incorrectly won the ID tie-break, although both display 1.00. Replaced it with exact `Decimal(n).copy_negate()` in `app/dashboard/multi_game.py`. Both dollar and ROI regression checks now put the higher value first. No fee, probability, observation or settlement assumption was changed.

Before/after: the regression order changes from `a-lower, z-higher` to `z-higher, a-lower`. The [before baseline](../evidence/math-reconciliation/baseline-before.json) and [after baseline](../evidence/math-reconciliation/baseline.json) are identical, including all 18 rows, 96 EV cases and both real rankings. No saved candidate was close enough for the defect to affect its order.

**29 focused tests passed** ([output](../evidence/math-reconciliation/focused-tests.txt)). Browser verification used a separate file-only instance on port 60397 with POST routes and credentials blocked: all 18 visible dollar/ROI values and ROI/dollar ordering matched; historical/conditional labels and disabled Start persisted; no console warnings/errors. The temporary instance was stopped. Existing services were not restarted and therefore have not been forced to load the one-line fix.

Preservation: all 1644 preexisting evidence files are byte-identical ([record](../evidence/math-reconciliation/verification.json)). Existing uncommitted work remains; only the ranking line, new review tests/evidence/report and Desktop tracker were changed by this review. No new collection, provider request, credential use, database change, guard reset, trade, commit, push or publishing.

Limits: this is a focused reconciliation of one saved six-game baseline and compact boundary scenarios, not a proof for every input or a qualification of live execution, fee applicability, full exceptional settlement or owner acceptance. No positive Arb result was found or required. Stop after this review.
