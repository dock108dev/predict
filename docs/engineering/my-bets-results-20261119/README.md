# My Bets outcomes and entry-price clarity

My Bets records Win, Loss or Tie/refund for each actual leg and calculates returned
cash, net profit and ROI. The compact card and editor show the actual entry before
fees, the effective price after fees, win return, fees and total paid together.
ProphetX and Novig show percentage prices with American odds underneath. Closing
prices, model comparisons, CLV and quote history remain in expandable details.
Save and Close stay visible while the editor body scrolls.

## Calculation contract

`trade.result.outcomes` stores choices, not generated returned-cash amounts. Exact
Fraction arithmetic derives each receipt from the actual pre-fee fill and recorded
fees. Correcting the stake or odds therefore recalculates outcome-based results.
Win returns `stake * decimal_price - win_fee`; Loss returns `-loss_fee`; Tie/push
returns the stake. Total profit is the sum of receipts minus all stakes and entry
fees; ROI uses that total entry cost. A push does not assume an entry fee refund.

Existing explicit receipts stay authoritative and editable under Adjust returned
cash. They are not reinterpreted as outcomes. Choosing Pending sends an explicit
null result, clearing the prior settlement. Unsupported or missing fee schedules
stay unavailable instead of becoming zero. An unused unknown outcome charge does
not prevent a result when its own receipt and entry cost are known.

`POST /api/bet-journal/{id}/preview` runs the same normalization and metrics as Save
against one SQLite read snapshot. It does not change entries, events or tracking,
collect prices, or request provider data. The browser debounces previews and rejects
stale replies; saved records keep their revision-conflict protection.

## Verification

- Backend settlement/API tests: 55 passed plus 15 subtests collectively, including
  outcome corrections, positive entry fees, legacy refunds, incomplete fee terms,
  summary aggregation and preview non-persistence.
- Browser tests use a real disposable SQLite Journal for finance. They cover all
  outcomes, changed stakes, Pending corrections, independent arb legs, legacy
  receipts, service errors, revision conflicts, quote details and fixed controls
  at phone/tablet/desktop widths. All 20 My Bets cases passed collectively; the delayed-save success/failure
  regressions and existing delete-recovery case passed together (3 cases).
  A prior write cannot close, relabel or unlock a reopened editor, including
  the same record ID. Inputs lock while their own write is pending.
- Five shared price-format browser cases passed for ProphetX/Novig across EV,
  Browse odds, comparison and Arb, including preserved pre-fee sizing defaults.
- Engineer-led CUA exercised the actual local API/HTML on a disposable fixture:
  $100/+110 with a frozen 2% winning commission returned $207.80/$107.80 profit,
  $0/-$100 on Loss and $100/$0 on Tie. Only fixture records were edited.
- A broader discovery run passed 78 tests and 15 subtests, with six PostgreSQL
  cases requiring a disposable database skipped locally. An unrelated archival
  transport-journal efficiency test could not find its ignored September JSONL
  evidence file; it is not a My Bets settlement failure.

No existing personal record is converted or settled by this change. Historical
actual inputs and reported cash receipts remain the owner's recorded values.
