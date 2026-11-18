# My Bets and opportunity logging

My Bets records both EV trades and two-leg arb trades. The ordinary board still
reads committed source data. Recording a trade never submits an order or calls a
provider.

## Workflow

1. Open an exact comparison on Opportunities or Browse odds and choose the
   venue's **Save to My Bets** button. Arbitrage inspection saves both original
   legs together.
2. In **My Bets**, enter the actual stake/purchase cost, price, placement time,
   entry fee and additional win/loss fees for each leg. American odds and
   contract prices between 0 and 1 are supported. Price changes do not change
   the selection, signed line or venue; save a different quote for a different
   bet. Blank fees stay unknown. The optional copy button copies the original
   modeled comparison amounts, which still need confirmation against actual fees.
3. Choose Saved, Passed or Placed and record your reasoning. A placed trade
   requires complete actual cashflows. Corrections append revisions; the
   original quote and previous reports remain retained. Simultaneous stale
   edits return a conflict instead of silently overwriting another correction.
4. Quote tracking continues without a browser. Expand the price comparison to
   inspect observed, actual and latest/closing prices, reference clocks, CLV
   and the retained quote timeline. Zero and negative subsequent comparisons
   remain eligible observations even after disappearing from opportunity lists.
5. After settlement, enter net cash returned per leg, including returned stake
   and after all settlement charges. Use zero for an ordinary losing leg and a
   negative amount for an additional debit. Results are reported cashflows,
   including pushes, refunds and partial outcomes; the journal does not infer
   actual venue settlement from the sporting winner.

**Opportunity log** includes automatically observed positive main-line EV
opportunities and positive arb pairs, plus manual saves. Automatic entries are
deduplicated by exact occurrence, selection/line and venue(s). Their first
snapshot stays fixed; later observations form quote history. Saving an inspected
quote creates a separate decision snapshot and links the automatic opportunity
when one exists. A later return to positive prices does not create another
automatic entry for that same occurrence/selection/venue combination.

## Measurements

Let `C = stake + entry_fee`, `W = stake × decimal_odds − additional_win_fee`,
and `L = −additional_loss_fee`.

| Measurement | Meaning |
| --- | --- |
| Observed EV | The original row's pinned modeled Net EV; never rewritten by trade edits. |
| Actual entry EV | `(p_entry × W + (1 − p_entry) × L − C) / C`, using the latest exact fair reference retained by reported placement time. Missing inputs remain unavailable. |
| Entry EV at close | The same entry cashflows evaluated using the last retained pregame fair reference. It does not substitute closing acquisition prices into your fill. |
| Closing market EV | The retained closing offer's modeled cashflows evaluated at its closing fair reference, separately exported from entry EV at close. |
| Price CLV | `entry_decimal / closing_market_decimal − 1`, before fees, per leg. |
| Fair-value CLV | `entry_decimal × p_close − 1`, before fees, per leg. |
| Price slippage | Actual decimal payout divided by observed decimal payout, minus one. |
| Arb minimum profit | Minimum of the two decisive-state net receipts, less combined actual entry cash. This can become negative after editing actual prices. |
| Closing arb return | Uses each leg's stored closing comparison cashflows, normally $100 per leg. Its cash basis is shown; it is neither a repriced actual-size fill nor a rebalanced order. |
| Realized net result | Sum of reported net returned cash, minus actual stake and entry fees. Settlement fees are already included in reported returned cash. |

Arb EV requires consistent complementary fair probabilities from the same
reference input set. A paired minimum can be available while EV remains
unavailable. Closing legs can have different source times; their arithmetic
does not establish synchronized execution. All modeled cashflows condition on
decisive completed-game outcomes. Reported cash results can include other states.

Summary figures use all placed entries, independently of page filters. Mean
price CLV counts legs with retained closes. Expected totals count trades with
qualified entry EV. Realized-minus-expected uses only settled entries with both
measurements, so an unresolved trade cannot distort that comparison. Sample
counts and closing coverage accompany the figures; they do not establish a
profitable strategy or calibration from a small sample.

## Closing observations and sampling

Closing value means the last observation actually retained before scheduled
kickoff. The source, received and journal knowledge clocks must all precede
kickoff. Late receipts and post-kickoff imports cannot reconstruct a missing
close. Each source quote and fair reference keeps its own original clocks;
viewing a frozen quote again does not refresh those clocks. The UI shows the
gap to kickoff and reference age. A book change between entry and close remains
visible. Source outages and a frozen local dataset can leave a distant or
missing close.

The sampler reads PostgreSQL in a repeatable read, read-only transaction and
releases it before a batched SQLite journal write. It runs after committed
collector processing and in the app lifecycle, independently of page visits.
A one-second rate limit and source-revision gate avoid repeated whole-slate
reads. Positive arb discovery runs approximately every 15 seconds, reusing the
existing revision cache; tracked individual legs remain observable after the
pair stops being profitable. This is sampled retained data, not every exchange
tick. Monitoring failures preserve saved records and appear in tracking status.

## Storage, exports and access

The private SQLite journal is `.local/predict-personal/bets.sqlite3`, with WAL
transactions, restricted file permissions and a configurable absolute
`PREDICT_BET_JOURNAL_PATH`. It is separate from the source database, so
`dev-snapshot pull` does not erase bets and source connections remain read-only.
Full original opportunity snapshots, append-only decision revisions and compact
source quote observations are retained without automatic journal pruning.
Different arb allocations are not inserted as separate source price observations.

The web and collector containers share this journal through the existing state
mount. The hosted `/my-bets` page and `/api/bet-journal*` routes use existing
private operational authentication; public board prices remain public. Install
the updated Caddy site file through the documented [hosted workflow](hetzner.md)
when deploying this feature. Each installation has its own journal; there is no
implicit Mac/server synchronization.

`GET /api/bet-journal` supports `view=bets|log`, `kind`, `decision`, `search`,
`limit` (up to 500) and `offset`. `POST /api/bet-journal` saves `{kind,snapshot}`.
`GET /api/bet-journal/{id}` returns the entry, correction history and quote
observations. `POST` to that route applies an update with the current `revision`.
Same-origin JSON and bounded request sizes are enforced.

CSV exports provide one summary row per entry; JSON exports include original
snapshots, revisions, quote history and computed metrics. Exports cover the
whole journal. Back up the journal with SQLite's backup mechanism, or stop both
writers before copying the database and its WAL files; a live copy of the main
file alone is not a complete WAL backup.

## Verification boundary

Portable tests cover calculations, prospective cutoff clocks, fee unknowns,
corrections, conflicts, persistence, paging, exports and HTTP origin enforcement.
Disposable PostgreSQL tests exercise the real sampler over admitted current
rows, pending rebuild suppression and durable SQLite capture. Browser checks
cover desktop/mobile saves, edits, arb legs, cash results and quote history.
Local snapshot integration is separate from hosted installation, ongoing
provider updates, real user fills and a month of results.

## Missing exact lines at close

The journal now samples the eligible sportsbook reference universe for tracked
selections even when their original exchange quote has disappeared. It chooses
the lowest no-vig probability among complete eligible exact-line same-book pairs,
using the existing reference policy, independently of the original benchmark book.
Reference-only observations never create a new market quote or renew its clock.

If no eligible exact pair remains, the closest harder nested line can provide a
labeled conservative probability bound. For home spreads, a more negative spread
is harder; away spreads reverse the canonical home-line direction. Over bets use
a higher total and under bets a lower total. The bound assumes monotonic nested
outcomes in the existing decisive-game model; it is not an observed exact close
or a calibrated score-distribution estimate. An easier main line alone is
insufficient. The UI labels the resulting closing EV and fair-value CLV as bounds.
No linear interpolation or extrapolation is silently substituted. Price CLV stays
based on actual retained market prices, with their original clocks visible.

The two-trusted-book minimum also applies to exact closing references and to the
neighboring line used for an estimated bound. A single trusted book plus any
number of untrusted books does not qualify. Original saved signals remain
immutable; entry/closing EV and fair-value CLV are unavailable when retained
reference evidence does not satisfy the minimum.
