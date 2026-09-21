# D1 implementation — independent offline coverage inventory

Completed September 16, 2026. D1 tooling is complete; **current full venue counts remain unavailable**. No D2 collection was performed. Starting HEAD: `edad00dd980cc8535d69a815d1199b82dd0e83cb`, plus the existing uncommitted roadmap/plan, owner walkthrough and saved session. Exact implementation/input/output hashes are in [verification.json](../evidence/d1-coverage/verification.json).

## Delivered and usage

`app.collection.coverage` builds both catalogs independently, then annotates event identity overlap and counterpart market presence. It never invokes a client, credentials, the beta, scan selection or database. Existing adapter event conversion was extracted into reusable `parse_event` functions; existing market parsers and `participant_mapping`/registry are reused. The running discovery policy is unchanged. Coverage is a projection of shared native models, not a replacement model for calculations or a second collector.

From the repository root, choose a **new** output directory:

```sh
.venv/bin/python -m app.collection.coverage \
  --input evidence/multi-game/sessions/5accf9ee-94b9-4b09-8130-6849f842155e/saved-observations.json \
  --as-of 2026-09-16T16:00:00Z \
  --output /tmp/predict-d1-coverage
```

Produces `coverage.json` and `coverage.md`. `--as-of` is an explicit historical scope/age reference, not a claim that the input was retrieved at that time; it cannot precede the latest retained retrieval. The command refuses existing output directories. Use the same arguments to reproduce the retained report byte-for-byte, apart from choosing the output location. For synthetic output substitute `evidence/d1-coverage/synthetic-pages.json` as input and a different output directory. JSON carries native IDs/slugs, schedules, participants/canonical keys, state, period, terms, page hashes/query/retrieval provenance, duplicate occurrences, exclusions and counterpart IDs.

Saved reports: [retained inventory](../evidence/d1-coverage/retained/coverage.md) · [machine-readable inventory](../evidence/d1-coverage/retained/coverage.json) · [synthetic inventory](../evidence/d1-coverage/synthetic/coverage.md).

## Observed retained coverage

| Retained denominator | Kalshi | Polymarket US |
|---|---:|---:|
| Unique events / in-scope events | 32 / 32 | 32 / 32 |
| Event identity overlaps | 32 | 32 |
| Retained markets / in-scope markets | 12 / 12 | 32 / 32 |
| Markets with retained counterpart market(s) | 12 | 6 |
| Markets missing retained counterpart details | 0 | 26 |
| Purchase sides: supported / unsupported / unknown | 24 / 0 / 0 | 32 / 32 / 0 |
| Events without any retained markets | 26 | 0 |
| Historical markets with collected books | 6 | 6 |

All retained event/market exclusions and duplicate counts are zero for this input. Each market is counted once by venue/native market ID; two Kalshi winner markets can link to one US market, so market totals need not be equal. Side totals describe adapter purchase reconstruction, not live liquidity. Unsupported US Short sides stay in inventory. Every event and market has exactly one matching status and one primary exclusion (or none); extra identity/duplicate/provenance fields retain details. Totals assert `discovered = in_scope + excluded = sum(matching buckets)`, `raw occurrences = unique + duplicates`, and side/exclusion reconciliation.

Kalshi's one retained event page ends with an empty cursor. Six separate market-query pages terminate likewise; **26 events have unknown market discovery**, not zero upstream markets. US has seven event pages (5+5+5+5+5+5+2), exhausting the adapter's offset/short-page rule. Its 32 embedded markets are labeled `embedded_only`; that does not prove independently exhausted market discovery. Open/active endpoint filters also exclude unopened, closed or hidden listings from this retained denominator. There are no observed unmatched event identities in this particular historical sample; isolated synthetic cases exercise unmatched/unresolved inventories without inventing historical findings.

The command validates contiguous cursors/offsets and retained body hashes, preserves usable prefixes on failed HTTP/pages, and distinguishes exhausted, bounded/truncated, failed and unknown. It uses the first traversal of each exact non-pagination query, explicitly counting later unused pages; it does not merge refresh cycles into a fictitious instantaneous snapshot. Identical rows collapse with occurrence provenance; conflicting versions of an ID are excluded instead of choosing a favorable version. Unknown participants remain visible and in scope when the event's declared NFL scope/schedule is otherwise supported, with unresolved matching. Kickoff, phase, schedule conflicts, type/period and inactive/unknown market states remain exclusions.

Historical subscription requests retain all six native targets per venue in JSON, with six markets having retained books. Both saved streams closed around 14:57:30 UTC. Present active subscriptions remain unknown because no process/feed was inspected. Retrieval range and exact snapshot age at the declared reference are in both reports. This is a historical, partial market catalog, not current full coverage or live qualification.

## Official documentation versus local evidence

Reviewed public documentation September 16, 2026; no market-data endpoint was called.

| Source | Documented capability | Existing implementation / retained observation |
|---|---|---|
| [Kalshi events](https://docs.kalshi.com/api-reference/events/get-events) | Cursor pagination, event page maximum 200, optional nested markets and milestones; empty cursor ends results. | Adapter event page size 200, max two pages in beta; retained 32-event terminal page. D1 retains every event regardless of six-game scan selection. |
| [Kalshi markets](https://docs.kalshi.com/api-reference/market/get-markets) | Cursor pagination, maximum 1,000 markets/page; event/series filters. | Adapter conservatively shares a 200 page-size ceiling; beta fetched two markets for each of six selected events only. No evidence for the remaining 26 event market catalogs. |
| [Kalshi rate limits](https://docs.kalshi.com/getting_started/rate_limits) | Authenticated token buckets; endpoint costs and account budget determine sustainable rate, not simply requests/second. | Beta checks a minimum refill rate, which alone does not establish a scalable request rate. D2 must cost requests against verified limits. D1 did not read credentials or refresh account limits. |
| [Kalshi WebSocket](https://docs.kalshi.com/websockets/websocket-connection), [order books](https://docs.kalshi.com/websockets/orderbook-updates) | Authenticated connection, ticker arrays, subscription updates, initial snapshots then deltas. | Local adapter/reconstructor caps groups at 20 markets. Six tickers requested in this capture. No hard exchange-wide subscription maximum was established from the reviewed pages. Local cap is not a venue entitlement. |
| [US events](https://docs.polymarket.us/api-reference/events/get-events) | `limit`/`offset`, event filters including fine-grained sports type, embedded markets; hidden events default excluded. | NFL adapter uses generic `/v1/events`, five events/page, max ten pages; seven pages observed. Short-page termination is the adapter rule. Reviewed reference gives no numeric event-page maximum or guarantee of complete nested markets. |
| [US rate limits](https://docs.polymarket.us/api-reference/rate-limits) | Retail global 20 requests/second per API key; unauthenticated public limit 20/second per IP; back off on 429. | These are documented ceilings, not measured sustainable throughput or additional access authorization. Seven catalog requests in this saved run. |
| [US market WebSocket](https://docs.polymarket.us/api-reference/websocket/markets) | Market-slug arrays, full/lite data and debouncing; documents Long/Short order intents. | Existing full-data parser supports native Long offers; it does not reconstruct Short purchase depth. Local request builder allows 100 slugs; six were requested here. Neither that ceiling nor documented Short order intent proves supported Short purchase ingestion. Numeric venue subscription ceiling was not established. |

Evidence pointers: `app/collection/multi_game.py:Discovery`, `prediction_discovery.py:NFLPolymarketAdapter`, both native adapters and stream modules, and the retained input's discovery/command/book/finished records. ProphetX/Novig and international Polymarket are outside D1. No offline capability is promoted to new live support.

## Next D2 task and proposed finite bounds

Implement independent discovery and an explicit single-owner collector using these catalogs; retain the current transport/journal and normalization. First validate complete event **and market** pagination for the declared open/active NFL pregame universe. Preserve unopened/hidden/status-filter gaps in the denominator unless separately included and validated. Use an explicit 5-minute pre-kickoff subscription safety margin; keep such events in inventory with a `kickoff_margin` subscription exclusion, and unsubscribe at cutoff or on phase/schedule changes.

Recommended initial pilot configuration (new authorization required for the live run):

- Maximum **180 seconds from Start**, including discovery; start idle, no autoresume or scheduler. Manual Stop and browser-independent lifetime required. Catalog refresh every 60 seconds; skip a refresh if one is still running.
- Kalshi: 200 events/page, at most ten event pages; 200 markets/page, at most ten pages per event, within **100 total REST requests per venue per pilot**, including retries/limits/resync. US: initially preserve five events/page, up to ten pages, with explicit truncation at 50; enumerate/validate market completeness independently within that same per-venue request cap. Raise the US discovery bound only through measured payload evidence, not an implicit six-game selection.
- At most **2 REST requests/second per venue**, further reduced by verified account token cost/budget. Two attempts per request; exponential 1/2-second backoff on transient limits, honoring longer retry instructions only within the overall deadline. No new paid source or spend.
- Propose at most **100 subscribed market IDs per venue**. Kalshi groups of at most 20 using the existing parser bound (up to five connections); US one group of at most 100. Thus at most six simultaneous connections and twelve total connection attempts (one reconnect each). These are local proposal bounds: validate exchange permission/acknowledgements before increasing from observed six-market support. If a limit is lower, keep all catalog rows and report partial subscriptions using earliest kickoff then native ID priority; no rotating-full-coverage claim.
- Explicit aggregate limits: 1 MiB/frame or HTTP body, 32 MiB ingress, 256 MiB process RSS, queue 48 records/4 MiB, and a pilot output reservation of 128 MiB with at least 1 GiB free. Preserve the current 32 MiB/4,096-record journal stop in the first pilot, reserving terminal-record space and charging serialized/base64 expansion and finalization copies to the output budget. Stop at the first cap; do not drop silently. Broader journaling follows D3. Measure actual RSS, byte growth, cadence and gaps; 180 seconds is a maximum, not a promised achieved duration.
- Disconnect invalidates books immediately; fresh snapshots/resync precede reuse. Report discovered, eligible, requested, acknowledged, receiving and usable counts separately, plus per-market missing-side/gap reasons. Validate new/departed/rescheduled markets and reconnect offline before any authorized pilot. Do not impose a 250 ms target.

This deliberately may produce a partial pilot. Discovery bounds, transport bounds and actual usable coverage are separate reported quantities. Changing the existing producer/stream limits and lifecycle needs D2 implementation; this report does not activate those settings.

## D3 persistence decision

**Extend the existing append-only file journal and native replay.** This is the beta's authoritative history, already retaining original frames, receipts and hash chains with exclusive file ownership and per-record fsync. Reusing the separate SQL research history now would require a second contract mapping/migration without improving the immediate single-user pilot.

For D3, add bounded segments and a versioned manifest linking segment hashes, original raw observations and normalized catalog/coverage transitions; index files should be rebuildable projections. Record incomplete segments and interruption gaps, start a new segment/session on restart, and retain every original input ID/value and calculation-assumption version. Store sporting outcome records separately from venue settlement/payout/void records, linking both by native IDs and provenance. Reserve disk and stop before limits; no automatic deletion of evidence. Validate exact replay across segmentation/restart before any durability claim. No storage migration or persistence implementation occurred in D1.

## Verification and remaining gaps

Focused command:

```sh
.venv/bin/python -m unittest tests.test_coverage tests.test_kalshi tests.test_polymarket_us tests.test_multi_game tests.test_math_reconciliation -q
```

64 tests pass, including 12 D1 checks: cursor/offset exhaustion, bounds/gaps/repeated cursors, failed/incomplete bodies, hash failures, duplicates/conflicts, unmatched/ambiguous/unresolved identities, unknown schedules, unsupported type/period/sides, >6-event inventory, missing counterpart markets, reconciled retained counts and deterministic CLI output/refusal to overwrite. An explicit socket prohibition covers the retained inventory test. Existing saved-math reconciliation remains unchanged. Python compilation and `git diff --check` pass. Existing aiohttp AppKey/asyncio timing warnings remain non-failing.

Changed application files: new `app/collection/coverage.py`; shared parser extraction in `app/adapters/kalshi.py` and `polymarket_us.py`. Added `tests/test_coverage.py`, isolated synthetic input, saved reports and verification. Updated plan, SSOT/architecture, roadmap and Desktop tracker. Retained calculation code, prices, fees, quantities and saved baselines were not edited. No live data, credentials, beta restart, migration, background job, trading, commit, push or publishing.

Remaining D2 gaps: fresh denominators; Kalshi market discovery for all events; independently proven US market completeness/filter behavior; wider subscription acknowledgement and payload/resource measurements; live reconnect/resync and finite browser-independent Start/Stop. D1 is complete within its offline boundary. Stop here.
