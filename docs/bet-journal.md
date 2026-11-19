# My Bets and opportunity logging

My Bets records both EV trades and two-leg arb trades. The ordinary board still
reads committed source data. Recording a trade never submits an order or calls a
provider.

## Workflow

1. Open an exact comparison on Opportunities or Browse odds and choose the
   venue's **Save to My Bets** button. Arbitrage inspection saves both original
   legs together.
2. In **My Bets**, confirm the stake placed. Negative odds default to a stake
   that wins $100 before fees; positive odds default to a $100 stake. Arbs default
   to $200 total stake, split to approximately balance the two modeled decisive
   payouts. Existing recorded stakes remain unchanged. These defaults are editable
   suggestions, not order submissions or verified fills.
3. **Save changes** records the trade as Placed by default. The server uses the
   saved odds, calculates fees from the quote's pinned book schedule with the
   existing rounding rules, and records placement time automatically. **Change
   odds** allows a different actual fill price; **More options** holds the decision
   placement-time correction and notes. Previously recorded fees survive an unchanged stake and price.
   Missing fee terms do not block recording a stake: those charges and after-fee
   metrics remain unavailable. Corrections append revisions; stale edits conflict.
4. Quote tracking continues without a browser. Expand the price comparison to
   inspect observed, actual and latest/closing prices, reference clocks, CLV
   and the retained quote timeline. Zero and negative subsequent comparisons
   remain eligible observations even after disappearing from opportunity lists.
5. Expand **Record result** after settlement and enter net cash returned per leg,
   including returned stake and after all settlement charges. Settlement time is
   recorded automatically for a new result. Use zero for an ordinary losing leg and a
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
Original opportunity snapshots, decision revisions and compact source quote
observations are retained without automatic journal pruning. **Delete bet** asks
for confirmation and removes that record and its corrections in one transaction,
subject to the same revision check as editing. Other records and shared quote
history remain intact. A deleted automatic log record stays suppressed during
subsequent sampling; an explicit manual save can create a new decision.
Different arb allocations are not inserted as separate source price observations.

Journal writes reserve a SQLite write transaction before looking up or changing
records. Entry changes, correction history and the returned applied revision
share that transaction; a failure before commit rolls them back together. Reads
pin one WAL snapshot for their entries, history, quote observations and metrics.
A lost network response can still follow a commit: retry an identical saved
quote, or reload the current correction revision before retrying an edit.

Manual save identity excludes only read-time `ranking` metadata, so viewing the
same quote under another sort cannot create another bet. The original first
snapshot is retained. A compatible lookup reuses existing ranked-save IDs and
their corrections without rekeying or merging records. Actual quote, reference,
fee and clock changes retain their prior distinct-snapshot semantics. Already
existing duplicate decisions are not deleted automatically.

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

Exports use one connection and one read snapshot instead of paging the changing
journal through separate requests. JSON includes full history; CSV reads only
the summary records it exports. The transaction ends before response serialization
and network delivery. The original export schema and CSV formula escaping remain
unchanged.

## Verification boundary

Portable tests cover calculations, prospective cutoff clocks, fee unknowns,
corrections, conflicts, persistence, paging, exports and HTTP origin enforcement.
Disposable PostgreSQL tests exercise the real sampler over admitted current
rows, pending rebuild suppression and durable SQLite capture. Browser checks
cover desktop/mobile saves, edits, arb legs, cash results and quote history.
Local snapshot integration is separate from hosted installation, ongoing
provider updates, real user fills and a month of results.

Exports use a consistent read snapshot even while another connection saves or
corrects entries. Backup/restore tests cover committed WAL data, original quotes,
corrections and observations. Those fixtures do not establish production-scale
throughput or recovery from host failure.

## Closing prices and alternate-line estimates

Each closed bet shows two separate values: the last retained pregame price for
its exact pick at the placed venue, and the closing no-vig fair odds from the
best eligible reference book under the board's existing conservative policy.
The sportsbook's posted price is distinct from its fair odds. Source times are
shown separately; a sportsbook update never renews the venue quote's clock.

The sampler reads the eligible sportsbook universe for tracked selections even
when their exchange quote disappears. A complete exact-line reference takes
priority. If that line is unavailable, it finds the nearest alternate below and
above the target **within each book**, requiring a complete same-book two-way
pair at both endpoints. It removes margin from each pair, then linearly
interpolates win probability by the target's distance between the alternate
lines. Contradictory non-monotonic brackets are excluded. It does not combine
one book's lower line with another book's upper line or extrapolate outside a
bracket.

At least two trusted books must independently support the estimated target.
Their estimates compete under the existing lowest-no-vig-probability policy.
The UI labels the selected value **Estimated fair close**, shows the book,
both alternate lines and fair odds, the estimated posted book odds, and the
endpoint fair probability range. Posted odds interpolate the two quoted implied
probabilities separately; fair odds interpolate their no-vig probabilities.
Closing EV and fair-value CLV are also labeled estimated. The range describes
the alternate endpoints; it is not a statistical confidence interval. Linear
interpolation is an approximation, not an observed exact-line price or a
calibrated score-distribution model. It does not replace the exact reference
used to measure reported entry EV.

When a two-sided bracket is unavailable, a qualified nearest harder line can
still supply an explicitly labeled conservative bound. The same two-trusted-book
minimum applies at that line. Without qualified inputs the value remains
unavailable. Price CLV always uses the actual retained exact-pick market price.

All source, receipt and capture clocks must precede kickoff. New bracket details
survive journal storage and JSON export. Old records cannot acquire missing
alternate prices retrospectively from post-kickoff observations. A previously
retained one-sided bound remains a bound when no two-sided bracket was captured.

`DELETE /api/bet-journal/{id}` accepts `{revision}` under the same private
authentication and same-origin JSON boundary. Stake-only updates use
`trade: {automatic: true, legs: [{quote_id, stake}]}`; a leg may optionally include
`price` and `units`. The saved response contains resolved prices, fee amounts and
`fee_basis`. The existing explicit-cashflow update format remains supported.
