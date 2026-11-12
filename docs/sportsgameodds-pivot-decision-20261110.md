# SportsGameOdds pivot: engineering and operating assessment

November 10, 2026 · Decision analysis, not a source cutover

**November 11 status:** SGO Rookie is the running aggregate. The current desk
uses best-payout same-book de-vig from FanDuel, DraftKings, BetMGM and Caesars
as its starter sportsbook basis. Direct Kalshi and Polymarket US remain active.
Additional P2P expansion is backlog work. The [execution queue](../NEXT_STEPS.md)
tracks the 99% target, exact matching, fee applicability and the clean-profile
journey. The [dated evidence](sgo-paid-observation-20261111.md) records measured
freshness, costs and limitations. The first-of-month 00:00 UTC boundary remains
a provisional pacing assumption.

## Recommendation — revised after owner confirmation

**Pivot to SportsGameOdds.** The owner confirmed that the three questions that drove the earlier recommendation are resolved affirmatively: the paid plan supplies the required venues and exact markets, a defensible replacement reference is available, and the object allowance supports a useful schedule. On that basis, the broader common-format dataset and potential to simplify aggregate collection outweigh the cost and work of a migration. This is an owner-provided premise; the free captures and trial evidence in this report do not independently establish its details. The earlier recommendation to continue as-is was contingent on those unknowns and is superseded.

Retain direct Kalshi and Polymarket US. Replace The Odds API and transition its Pinnacle-based reference explicitly to the confirmed alternative, with clear attribution, exact-market eligibility and unavailable states. The integration, database migration, object-aware scheduling and validation described below remain real work; they are not reasons to impose a separate waiting period. The figures and coverage caveats below record what this evaluation independently observed, and identify engineering details to incorporate rather than reopen the owner's decision. A paid subscription and production source cutover remain owner decisions under the original task boundaries; this recommendation itself does not execute them.

## Current and proposed paths

| Stage | Existing system | Proposed single aggregate plus permanent direct feeds |
| --- | --- | --- |
| Collect | The Odds API: one featured batch per league already requests Novig, ProphetX and Pinnacle together, for moneyline, spread and total; separate event-specific alternate requests when enabled. Kalshi and Polymarket US use independent native collection. | SGO event pages with configured league, time, market and bookmaker filters; one response can include multiple books and markets. Native Kalshi and Polymarket US remain independent. Alternate lines may still require different plan, payload or requests. |
| Interpret | Strictly parse the aggregate frame once, admit venue and reference independently, normalize source identities, outcomes and signed lines. Native catalogs and books have their own formats. | One aggregate adapter maps SGO event/odd/book IDs, sides, per-book lines, availability and clocks into the same internal facts. It replaces the Odds API adapter, not the native adapters. |
| Match | Match sporting occurrence and settlement predicates between independent providers, then exact event, side, line, phase and opposite reference pair. | SGO's shared event ID can avoid some joins **inside the aggregate feed**. It does not prove an SGO listing matches a direct native occurrence or contract, nor that two venues settle identically. |
| Store and calculate | Current event, contract, offer, source status, native book and native depth rows; separate replaceable acquisition payloads/raw display and compact latest board. Current Pinnacle pair supplies conditional no-vig reference; exact fees and settlement qualify EV. | Retain current-row model and native book/depth owners. Add SGO provenance and versioned reference inputs; upsert changed facts rather than rewrite every nested quote. Replace Pinnacle-only binding with explicitly named eligible reference policies. |
| Publish | Independent data process calculates and publishes latest compact results; app reads them. Raw prices can remain visible when finance is unavailable. | Same publication architecture; show reference method, contributors and source clocks, and unavailable EV when a suitable reference or financial input is absent. |

Code: [aggregate policy](../app/collection/current_aggregate_policy.py), [aggregate collection](../app/collection/current_aggregate.py), [aggregate admission](../app/collection/current_aggregate_admission.py), [alternate collection](../app/collection/alternate_acquisition.py), [current-row owner](../app/storage/current_rows.py), [occurrence matching](../app/comparison/occurrence_matching.py), [Pinnacle line reference](../app/comparison/line_reference.py), [current-row storage](current-row-storage.md), [acquisition](acquisition.md), and [benchmark semantics](benchmark-ev.md). The configured league scope is NFL, NCAAF, NBA, NCAAB, MLB and NHL, each with moneyline, spread and total; actual returned market coverage differs by event and plan.

### Database and operational consequences

- **Remove or simplify:** Odds API-specific query/response mapping and its featured-versus-event-alternate fan-out can go, insofar as the subscribed SGO payload actually returns those lines. Within one SGO event, books already share event identity and a field structure; adding a book need not require another format adapter. Odds API credit headers and its specific reservation/reconciliation behavior can be retired only with that source, after preserving its account/audit history. SGO still needs object accounting, rate controls, uncertainty handling, reserves and Stops.
- **Remain:** current event/contract/offer indexing, ordering, exact-match and settlement checks, financial eligibility, expiry, authoritative complete-scope withdrawals, separate source and receipt clocks, and bounded recovery. Current acquisition stores replaceable featured and alternate payloads and native images, and a separate raw display index; typed rows and raw display have different jobs, so the existing duplication cannot simply be deleted. The latest calculation and board projections are compact replacements, not a full history. See [storage migrations](../app/storage/migrations/019_current_acquisition.sql) and [raw display migration](../app/storage/migrations/028_raw_display.sql).
- **Add:** a new mapping and paging/availability protocol, SGO quota ledger and scheduling, completeness tracking, reference-policy/contributor records, database migrations and app labels. Broader responses create more parse memory, entries, indexes, comparisons, and potentially writes. Filter at source where supported and after parsing, preserve original clocks, write changed rows only, bound response sizes, and don't append every full payload indefinitely. Preserve the old source's accounting and historical evidence during transition.
- **Performance judgment:** common-format collection may reduce operational joins and requests, but current featured collection already batches three books, and no measured end-to-end replay proves lower latency, faster recovery or less disk. Native book ingestion, depth and partial publication remain substantial independent work. Full payloads could increase disk or memory; only a measured paid-tier replay through comparable database paths can establish the net effect.

**Direct Kalshi and Polymarket US are permanent.** They provide independently sourced discovery, original books and depth, event and contract evidence, executable sides and reconciliation/audit against aggregate quotes. An aggregate quote is not proof of available size, a fill, contract equivalence, or current execution. Fee schedules, payout rules, YES/NO and long/short semantics, source timing and settlement continue to require venue-specific handling. Broader P2P rollout would require the same work for each additional execution venue.

### What running live already demonstrates

In the November 10 pregame capture, 910/910 current offers had fee values, but only 192 had exact Pinnacle reference and after-fee EV; publication was partial. A 1 p.m. NBA aggregate 502 without usable quota headers stopped the aggregate worker, left an uncertain three-credit hold and coincided with 32 current offers and no exact reference/EV. Native collection continued. Guarded recovery preserved the then-existing 19 holds / 52 credits, and the next scheduled cycle returned all six leagues. Those are historical observations, not today's hold census or a forecast of SGO failure rates. See [F09](f09-coverage-20261110.md). In-game fee validation remains paused and native publication limitations remain open. Normal continued use can reveal actual freshness, interruptions, matching gaps and operating effort; it cannot establish a different provider's paid coverage.

## SportsGameOdds data and evidence

The [events endpoint](https://sportsgameodds.com/docs/endpoints/getEvents) supports league, event, bookmaker, odds, availability, time and pagination filters, and opt-in alternate lines. An event contains odds keyed by `oddID`; [odds documentation](https://sportsgameodds.com/docs/data-types/odds) describes the stat/entity/period/bet-type/side identity and opposing ID. The line is separately associated with the book/side, so oddID alone is not an exact spread or total contract. Validate signed opposite sides, exact line, period and settlement. Event IDs have aliases for changes; do not assume an immutable identifier without recording aliases and occurrence facts.

The cached free sample contains five NBA and five NHL pregame events, nine observed bookmaker IDs and moneyline, spread and total sides in both leagues. Both responses had another cursor; they are not a census. No P2P venue was seen, and no conclusion about other plans follows. The vendor reported substantial omitted bookmaker odds due to access. An empty live query is not proof of absent live coverage. Original per-book `lastUpdatedAt` and availability were present; fair odds had no source clock in these captures. SGO documents retaining unavailable odds: price presence alone cannot mean an open market. A complete, unchanged-filter pagination pass must be distinguished from partial or moving results before any withdrawal; SGO warns that changing pages while events move can duplicate or miss them ([batching guide](https://sportsgameodds.com/docs/guides/data-batches)). Verify actual close/reopen behavior and timestamp semantics.

The [pricing page](https://sportsgameodds.com/pricing) lists all six target leagues, moneylines, spreads, totals, pregame and live, but exact event/book/family/line availability is unverified beyond the sample. It advertises Rookie with 77 books, 100,000 objects and three-minute update frequency. The [vendor's full bookmaker list](https://sportsgameodds.com/bookmakers) includes Kalshi, Polymarket, Novig and others; inclusion on that general list does not prove Rookie access, full markets, executable quotes, or that Polymarket means **Polymarket US**. SGO explicitly advertises [Pinnacle on Pro and above](https://sportsgameodds.com/bookmakers/pinnacle-odds-api); this could preserve a Pinnacle-based reference through SGO, though exact coverage and clocks must be checked. Rookie's alternate-line entitlement is unclear from the accessible pricing rendering and must be confirmed. These are vendor claims, not paid observations.

### Payload measurement

Local cached response wrappers, no network, measured with [sgo_capture_measure.py](../scripts/sgo_capture_measure.py):

| First page | Raw JSON bytes | Local gzip bytes | Events | Odds objects | Book entries | Candidate full-game odds / book entries | Parse median / peak |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| NBA | 7,318,737 | 356,187 | 5 | 5,091 | 8,583 | 90 / 390 | 0.088 s / 18.94 MiB |
| NHL | 10,344,468 | 472,954 | 5 | 7,257 | 13,342 | 78 / 338 | 0.114 s / 26.42 MiB |

Reproduce from repository root:

```sh
.venv/bin/python scripts/sgo_capture_measure.py .local/sgo-evaluation-20261110/nba.json .local/sgo-evaluation-20261110/nhl.json
.venv/bin/python -m pytest -q tests/test_sgo_free_evaluation.py
```

The script runs `json.loads` three times with `tracemalloc` and reports median time and peak traced allocation, including the saved wrapper; hardware, instrumentation and warm caches affect results. Candidate counts filter `game`, `ml`/`sp`/`ou` and `all`/`home`/`away`; they are a superset, not verified paired markets. Gzip is local compression, not measured wire compression. Paid breadth, endpoint-side filtering, production parsing, DB writes and concurrent working set were not measured. This illustrates the cost of carrying unneeded nested markets, not an end-to-end benchmark.

## Reference transition and EV

The existing reference is a named exact two-sided Pinnacle pair, proportionally de-vigged into a decisive conditional probability. A pivot removes **The Odds API's** Pinnacle feed; it need not make Pinnacle permanently impossible if SGO Pro actually supplies a qualifying pair. Trial-check SGO Pinnacle before relying on that option.

For Rookie or markets without a qualifying Pinnacle pair, implement a separately named, versioned multi-book reference: select eligible independent-enough books with complete available opposite prices for the same game, phase, period, outcome, exact signed line and compatible settlement; reject unknown/future/stale clocks; calculate each book's two-sided proportional no-vig probability and take a median. Disclose contributors, original timestamps, exclusions, method and minimum contributor rule; exclude the evaluated venue where applicable. A minimum such as three eligible pairs is a conservative initial product policy, not a claim of statistical accuracy or independent opinions. If insufficient pairs, unknown settlement or stale clocks, publish prices with reference/EV unavailable. Do not carry over an old Pinnacle label or silently fall back. Preserve conditional push/void limitations and existing exact fees and payout checks.

SGO's [fair odds](https://sportsgameodds.com/docs/info/consensus-odds) provide a separately attributed comparison: vendor describes selecting a balanced line using regression, a median and margin removal. `fairOddsAvailable` matters; the fair spread/total may not equal the offered line and no original fair clock appeared in this sample. Its composition and independence are unverified, so show it as indicative with unknown age rather than as an automatically executable benchmark. Future outcome research can test calibration; it is not a prerequisite for choosing between the paths.

The [free evaluation](sportsgameodds-free-evaluation-20261110.md) found eight exact pregame NBA two-sided markets, 16 directed outcomes, with at least three qualifying SGO bookmaker pairs; vendor fair odds were same-line on 12 outcomes, with unknown fair clock. Clippers–Suns under 224.5 illustrated the consequence: Pinnacle 51.671% versus book median 50.000% changed an illustrative Novig gross conditional return from +1.28% to −2.00%. This is a sensitivity example, not evidence which estimate is correct. A broader set of US books and P2P sources could improve discovery, group comparisons, leave-one-out analysis and future model tuning, but correlated feeds, stale inputs and differing venue fees and settlement can still mislead.

## Schedule, objects and cost

SGO charges returned top-level objects with a minimum of one per response, including empty responses; batching reduces request count but does not make returned event objects free ([limits](https://sportsgameodds.com/docs/info/rate-limiting)). The free-account sample observed 11 objects for ten events and one empty call. Its reported 2,500 limit does not establish paid entitlement. SGO describes a rolling monthly period; its FAQ's 30-day wording and calendar-day example should be checked against the account before assuming a reset. The 28–31 day table below is deliberately conservative calendar-duration sensitivity, not a statement of the vendor's actual billing period.

Use the captured November 10 The Odds API slate of **187** events, **111** within 72 hours, as a fixed illustrative input, not an SGO census or a forecast. Current slots are 56/day, 09:00–23:00 Eastern, every 15 minutes. Assumptions: each requested event is returned once per refresh, no overlap, no failed/empty responses or extra discovery; real slate and eligibility change. All counts below are objects, not Odds API credits.

| Scenario | Objects/day | 28 days | 29 days | 30 days | 31 days |
| --- | ---: | ---: | ---: | ---: | ---: |
| All 187 at current 56 slots/day | 10,472 | 293,216 | 303,688 | 314,160 | 324,632 |
| Illustrative selective schedule | 2,944 | 82,432 | 85,376 | 88,320 | 91,264 |

Selective example: hypothetical 8 live events every 15 minutes all day (96/day), 30 imminent every 30 minutes (48/day), 73 other near games every three hours (8/day), and 76 distant games every 12 hours (2/day). The live/imminent split is invented for modeling; it is not an observed snapshot. In 31 days it leaves 8,736 objects (8.7%) for discovery, empty calls, other endpoints, retries, bursts and safety reserve. Actual live/imminent volumes and overlapping windows could make it exceed budget. Moving all 187 to every three minutes for 24 hours implies 89,760 objects per day; even limiting that cadence to the current 14-hour window would be 52,360/day. Neither is supported by Rookie's allowance. With 31 days at 56 slots/day the full allowance averages 57.6 returned events/slot, or 51.8 with a 10% reserve, before other usage.

Current Odds API schedule combines three books in a league request: six successful three-market featured responses imply **18 credits per full slot**, or **1,008 credits/day** for all 56 slots, before alternate and other requests. This is theoretical schedule arithmetic, not observed billing or a currency conversion. Historical local owner-confirmed material recorded a 100,000-credit plan at **$59/month** in October ([historical plan](../.local/ci-review-20261007/clean-v2/PLAN.md)); current billing and taxes are not independently verified. The current application ceiling is not proof of account terms. The SGO vendor's [pricing comparison](https://sportsgameodds.com/blog/comparing-odds-api-providers) states Rookie **$149 month-to-month or $99/month billed annually ($1,188/year)**, and Pro **$499 month-to-month or $299/month billed annually ($3,588/year)**. Confirm checkout, taxes, trial and commitment; do not infer actual current spend or net savings. The advertised three-minute update frequency is an upstream plan characteristic, not a guarantee of three-minute freshness or affordable full-slate polling.

## Proposed integration and bounded trial

Build an SGO adapter beside the existing collector with bounded page parsing and explicit complete scopes; map event aliases, book/odd/line and availability into typed current facts with source and receipt times. Keep existing independent native feeds and their depth. Use separate quota/Stop state, changed-row upserts, bounded raw retention, and observable parser/queue/disk metrics. Add versioned reference policies and a side-by-side comparison view before choosing a cutover. Preserve existing account ledger, holds, settings and data; a future database migration must preserve provenance and old references, and allow rollback without replaying or altering financial history. Production cutover is a separate owner decision.

A paid trial should check, on representative active and quiet slates across all six leagues and three families:

1. Actual plan, trial, reset, alternate-line, fees and commercial terms; access and per-market two-sided availability for Novig, ProphetX, Kalshi, Polymarket **US**, relevant US books and, on Pro if considered, Pinnacle. Record absent markets, not merely venue names.
2. SGO event/contract matching to both native feeds, settlement and executable side, precision, depth availability, source and receipt clocks, availability/removal/reopen behavior, pagination completeness and live delay. Direct native books remain execution authority.
3. Exact reference coverage and contributor distribution, leave-one-out behavior and differences against contemporaneous Pinnacle; disclose stale or missing fair clocks. Compare EV behavior rather than claiming model superiority.
4. Returned objects per actual schedule, empty/discovery calls, account reset, bursts and reserve; measure filtered payloads, parse memory, upserts, queue lag, database size and recovery using disposable replay and comparable workloads. Avoid duplicate event fetches; preserve production Stops and holds.

No paid subscription, production pivot, expanded P2P rollout, new provider request or source-control change was made for this assessment. Offline reference tests passed: five tests. The original free capture and its comparison remain the evidence base; all paid-tier and end-to-end performance claims remain unverified.
