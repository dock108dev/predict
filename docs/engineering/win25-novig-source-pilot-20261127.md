# Win $25 Novig public source pilot

On November 27, 2026, the installed Predict collector container on Hetzner reached Novig production's unauthenticated v3 API. The public market list and detailed book gave the same best buy price and quantity on all 16 paired observations. Four exact selections also matched the price and rounded size on the Novig order slip. The pilot sampled books ahead of the scheduled decisions. The prospective T−10 comparison needs its own receipts.

## Coverage and source behavior

The sample used a paginated NCAAB pregame event inventory and queried full-game spreads and totals by event. It covered 24 unique upcoming game IDs. All 16 games from the November 27 early and evening groups had listed spreads and totals. Eight November 28 game IDs appeared as pregame events with no spread or total returned when sampled. This matters for preparation. A linked native event can exist before its contracts appear. Forced five-item pagination returned two disjoint pages and a further cursor. The normal 240-item event reads fit on one page in this sample. [Novig list markets](https://docs.novig.com/api-reference/public/list-markets)

The initial installed-container run received HTTP 429 during the event-market scan with approximately 80 ms between consecutive game reads. The request failed before the response's Retry-After header was recorded. Two paced runs with approximately 650 ms between requests completed 76 successful reads. The adapter spaces request starts by 650 ms, bounds concurrency and request duration, and suppresses further reads for the provider's Retry-After interval on 429. The cutoff independently ends decision-time attempts.

| Route | Successful reads | Median | P95 | Max | Public max-age |
|---|---:|---:|---:|---:|---:|
| Events | 10 | 132 ms | 224 ms | 233 ms | 15 s |
| Event-filtered markets | 32 | 138 ms | 224 ms | 313 ms | 10 s |
| Market book | 34 | 130 ms | 148 ms | 237 ms | 5 s |

All 76 responses reported CloudFront misses and advertised stale-while-revalidate equal to max-age. The decision lane uses the earlier clock implied by HTTP Date and Age, checked through the decision cutoff. It caps age at 10 seconds for catalog and 5 seconds for book, tightened by any shorter declared max-age. It preserves the stale-while-revalidate header as evidence and requires fresh receipts. Two of six delayed repeats 13–16 seconds later had the same body despite a later Date, a different ETag and an edge miss. Four had changed bodies. An unchanged book sequence cannot identify cache reuse by itself. [Novig public book](https://docs.novig.com/api-reference/public/get-the-order-book)

## Price and quantity checks

The API sends bids by outcome. The buy price of the selected outcome is one minus the opposite outcome's best bid, and the API quantity counts $0.01-payout contracts at that level. Seven of the 16 paired observations had multiple orders at their best price. Two detailed observations reached the 20-price-level cap. A book returns all orders at each retained price level in venue priority order. [Novig monetary representations](https://docs.novig.com/api/concepts/money) · [Novig public book](https://docs.novig.com/api-reference/public/get-the-order-book)

| Exact selection | Public buy price | Native contracts at best | Available cost at that price | Novig slip |
|---|---:|---:|---:|---:|
| Gonzaga −18.5 at Creighton | 17.0% | 10,060 | $17.10200 | 17.0%, $17 |
| Virginia −6.5 at Xavier | 49.5% | 234,809 | $1,162.30455 | 49.5%, $1,162 |
| Virginia–Xavier Over 182.5 | 8.5% | 1,494 | $1.26990 | 8.5%, $1 |
| Iowa State +1.5 vs. St. John's | 49.0% | 106,600 | $522.34000 | 49.0%, $522 |

The Gonzaga buy level combined resting Creighton bids of 60 and 10,000 contracts at 83.0%. At a 17.0% buy limit, 10,060 displayed contracts would cost $17.102 and had $83.498 in gross win capacity. Virginia–Xavier Over 182.5 illustrates a short best level. Its $1.2699 available cost had $13.6701 in gross win capacity. The slip checks observed displayed capacity only.

The 16 priced games supplied 644 contracts and 1,267 populated sides. At the best displayed price, 67 of 711 sides within the −250 to +250 band supported less than $25 gross win profit. The same held for 144 of 255 sides above +250 and 218 of 301 sides below −250. These are lines available before the decision and include both sides. They demonstrate why the collector needs the book even inside the band. The odds-cap recommendation requires the frozen T−10 candidates, their net EV, and the outcomes of reranking.

## Fee evidence

Production game-market terms showed a 0.06 coefficient charged only in-game, and the public help center still described pregame straight takes as free. The API's December 1 schedule says 0.03 for pregame game lines and 0.06 for live. The v3 API uses the actual fill price, a $0.01 unit and per-fill rounding up to $0.00001. The consumer help page describes a VWAP calculation with half-up rounding. The depth experiment models the v3 API terms and preserves their version and native fields. [Novig v3 fee schedule](https://docs.novig.com/api/concepts/fees#from-december-1-2026) · [Novig consumer fee help](https://support.novig.com/en/articles/16195057-fees-on-novig)

The fee announcement gives a December 1 date without a time zone or clock. The separate maker-credit and taker-rebate programs specify midnight Eastern. The adapter keeps the pregame fee unresolved where the transition time is ambiguous and when a later market still advertises conflicting legacy terms. Observing the production market fee fields after the announced change, or obtaining a venue clarification of the effective instant and terms, would resolve that gap. [Novig taker rebate terms](https://docs.novig.com/taker-rebate-program) · [Novig maker credit terms](https://docs.novig.com/maker-credits/overview)
