# D2 — implemented, live validation incomplete

September 16, 2026. **D2 is not complete.** The one authorized pilot failed during discovery; it was not repeated. The local defect is repaired and checked offline. D3 remains pending. Both venue resources were finalized; the beta is idle with its pilot allowance consumed.

## Actual live outcome

Pilot `8c4da682-f611-4c83-b401-e8a4e6b43a2e`, starting HEAD `edad00dd980cc8535d69a815d1199b82dd0e83cb` plus preserved uncommitted D1 work and D2 edits. Start-to-cleanup: **2.434 seconds**, including credential resolution/discovery. Journal receipts: **15:57:05.739403–15:57:08.071930 UTC** (11:57 AM EDT).

| Actual observation | Kalshi | Polymarket US |
|---|---:|---:|
| REST attempts / 100 ceiling | 2 | 0 |
| Successful limit-check responses | 2 | 0 |
| Event / market catalog requests | 0 / 0 | 0 / 0 |
| Discovered event / market records retained | 0 / 0 | 0 / 0 |
| Actual event / market denominator | **Unknown** | **Unknown** |
| Eligible denominator | **Unknown** | **Unknown** |
| Requested / acknowledged markets | 0 / 0 | 0 / 0 |
| Receiving / usable books | 0 / 0 | 0 / 0 |
| Connection attempts / opened connections | 0 / 0 | 0 / 0 |
| Native HTTP body bytes charged | 1,303 | 0 |
| Additional spending | $0 | $0 |

All markets are missing from this pilot because catalog pagination failed locally before its first request, not because either venue had zero markets. `Discovery.pages_for` referenced an undefined local `s` while attaching the session to its client. Both independent discovery tasks recorded `NameError`; the session ended as `discovery_failure:ValueError`. Kalshi's two existing read-only account-budget endpoints returned HTTP 200: read refill 200 tokens/second, bucket 600, default request cost 10. No market availability, US completeness, expanded subscription entitlement or book cadence was observed.

Resource outcome: **8,006 serialized ingress bytes**, **9,615 journal bytes**, **22,005 total pilot-directory bytes** including manifest/report, **113,033,216 bytes process peak RSS at finalization** (about 107.80 MiB). Five ingress records were accepted and durably acknowledged; six journal records include the terminal record. Zero rejected/unresolved writes, zero pending queue records, zero cleanup errors. The pre-repair monitor recorded a queue sample maximum of one; this was not an exact queue high-water measurement. The repaired candidate reports the queue's own record/byte high-water counters. No resource ceiling triggered.

The browser page was actually closed and reopened, but the first post-close status already showed the collector stopped. **Live browser-closure independence is unverified. Manual Stop is unverified** because the failure ended the run first; no manual-Stop request or second pilot was made. No live reconnect, refresh, kickoff transition or discovery completeness evidence was obtained. The entire intended market-observation interval is a coverage gap; lost/upstream update counts remain unknown. There are no new calculation inputs or economic results.

## Implemented capability (offline evidence)

- `app/collection/continuous.py` extends the existing `TransportSession`; `CoverageOwner` is the production mode of the existing `MultiOwner`, using its Start/Stop routes and one finalizer. It starts idle, uses a process lock plus an exclusive persistent attempt record, rejects overlap, and never autoresumes. `/coverage` supplies a small status/control surface; saved calculation views remain separate. Broad dashboard integration remains D4.
- Both venues discover independently before matching or subscribing. D1 `coverage.catalog`, shared event/market parsers and normalization produce inventory/completeness/exclusion records. Kalshi fetches paginated market details for every discovered in-scope event. US independently paginates `/v1/markets` by each event's native `gameId`; embedded-only or missing-game-ID coverage stays unestablished. Matching does not exclude subscription candidates.
- Discovery refreshes on Start-relative 60-second ticks, serially; overrun ticks are skipped. Stable metadata does not churn subscriptions. New, departing, inactive and rescheduled markets trigger reconciliation; inventory snapshots retain their native metadata. A 250 ms local control check applies the five-minute kickoff margin even between REST refreshes; this is a cutoff check, not a promised feed/update cadence. Excluded markets remain in inventory.
- Earliest kickoff then native ID prioritizes eligible markets under the cap. Kalshi groups contain at most 20 IDs; US has one group of at most 100. Up to six concurrent sockets and twelve total attempts; each group permits one reconnect. Changed subscriptions consume the same connection budget. Local caps never imply upstream permission, and rotation is not claimed as simultaneous coverage.
- Coverage separates discovered, eligible, selected, requested, acknowledged, receiving and synchronized/receipt-recent usable markets; lifetime IDs and peak simultaneous counts are distinct. Kalshi acknowledgements require matching request/channel/SID; US counts valid current-request market images as acknowledgement, with that weaker basis explicit. Disconnect immediately clears usability; native parsers require a new synchronized image before reuse. US Short purchase ladders remain unavailable.
- Native bodies, commands, frames, receipt/source timestamps and derived packets stay in the existing fsynced, hash-chained file journal. Group-specific replay reuses the existing native replay verifier. No segmentation, migration, outcome/settlement ingestion, database writes or calculation changes.

Bounds retained: 100 REST attempts per venue including retries, at most two requests/second reduced by verified Kalshi token costs/budget; two attempts per request with bounded backoff/Retry-After within the same deadline. Kalshi 200 rows/page, ten event pages and ten market pages/event; US five rows/page, ten event pages and ten market pages/game. Maximum 100 selected IDs/venue, 1 MiB body/frame, 32 MiB aggregate native-body budgets (16 MiB/venue), 256 MiB RSS, 48 records/4 MiB queue, 128 MiB output reservation and 1 GiB free-disk floor. The existing **stricter 16 MiB/2,048-record serialized ingress ceiling** also remains. Journal 32 MiB/4,096 records, with 64 KiB/64 records reserved for termination. Replay materialization is refused if its conservative memory reservation exceeds the RSS ceiling. The sole observed pilot did not approach these bounds.

The failed candidate and repaired candidate differ: the repair corrects the pagination session reference, adds a full local HTTP/WebSocket path test, yields metadata work/drains the existing consumer between books to avoid startup queue starvation, reports exact queue high-water values, and shows the previous pilot's failure after idle restart. None of these repairs has fresh live validation.

## Checks and exact evidence

Before live access: **66 offline tests passed**, JavaScript syntax and concise-dashboard regression passed. The initial discovery test substituted the whole venue traversal, so it missed the undefined variable inside the pagination helper. This test gap is recorded rather than treating the preflight pass as proof of that path.

After repair: **67 focused tests passed**, including an additional local-only end-to-end transport test. With only endpoints/credentials substituted, it executes actual discovery, 24 Kalshi and eight US market subscriptions across three sockets, native images, unchanged refresh, manual Stop, closure and exact 32-book/packet replay. Other checks cover pagination/truncation/retries, unmatched markets, missing game IDs, acknowledgements, changed/departed/closed/rescheduled markets, exact kickoff margin, reconnect/resynchronization, resource stops, client-closure lifetime, idle restart/one-attempt enforcement and saved-math regressions. Negative/zero/unavailable saved calculations are unchanged. These checks do not replace missing live evidence.

- [Pilot manifest](../evidence/d2-coverage/8c4da682-f611-4c83-b401-e8a4e6b43a2e/manifest.json) and [actual machine report](../evidence/d2-coverage/8c4da682-f611-4c83-b401-e8a4e6b43a2e/report.json).
- Journal chain: `262e27eb664dce1c0413b99e6e4ba877f1c647cb8ce423735235abc3e111aafd`.
- [Pilot source hashes](../evidence/d2-coverage/pilot-code-sha256.json), frozen copies under `evidence/d2-coverage/pilot-source/`, and [final verification/current source hashes](../evidence/d2-coverage/verification.json). Frozen pilot copies are evidence, not executable entry points.
- [Pre-pilot checks](../evidence/d2-coverage/offline-checks.log), [post-repair checks](../evidence/d2-coverage/post-repair-offline-checks.log), [browser closure result](../evidence/d2-coverage/browser-closed-status.json).
- Preexisting evidence hashes were checked read-only. Existing D1 edits, saved sessions and original math evidence were preserved. No commit, push, publishing, new source, paid access, scheduling or trading.

Documentation basis checked September 16: [US market discovery parameters](https://docs.polymarket.us/api-reference/markets/get-markets), [US market stream](https://docs.polymarket.us/api-reference/websocket/markets), [Kalshi token budgets](https://docs.kalshi.com/getting_started/rate_limits). Filtered short-page exhaustion does not prove an atomic universe snapshot or hidden/unopened listings; live game-ID filter behavior and subscription capacity remain unverified here.

**Next concrete task:** a separately authorized replacement D2 pilot on the repaired candidate, using a new unique attempt directory while retaining the consumed pilot and the same ceilings. Establish live denominators, subscriptions, usable coverage, browser independence and manual Stop before marking D2 complete or starting D3. No replacement pilot is enabled by this report.
