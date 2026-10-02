# Native discovery and payload policy v3

This is an offline engineering envelope, not a claim of complete live inventory or provider response maxima. Revision 3 remains consumed. Original 246 aggregate records, 21 native listing associations, complete responses and both truncated bodies remain unchanged. No championship season, effective rules, executable economics or cross-source qualification is inferred.

## Endpoint decision

Official schemas were retrieved as public documentation only, retained under `evidence/native-redesign-20260930/*-events.txt` and `us-markets.txt`.

- [Kalshi events](https://docs.kalshi.com/api-reference/events/get-events): `/trade-api/v2/events`, open status, milestones included, **with_nested_markets=false**, cursor pagination, 200 summaries × 3 pages per generation. Select at most one resolved, supported, future event per each of six sports; retrieve markets separately by returned `event_ticker`, 50 × 3 pages each. The endpoint excludes multivariate events; combos are unsupported. Broad summaries preserve discovery evidence across unsupported series without inventing filter IDs.
- [US events](https://docs.polymarket.us/api-reference/events/get-events): `/v1/events`, active, not closed, ascending startTime, offset pagination, 5 × 30 pages per generation. This schema embeds markets and does not document a summary-only switch. A single event may exceed any chosen envelope; pagination alone cannot solve that. Unknown schedules/championships remain visible and excluded. The supported `/v1/markets` gameId filter supplies separate selected-event metadata, 50 × 3 pages. IDs come from complete responses. No speculative tags, series IDs, undocumented nested suppression, or non-US API.

Both retain NFL/NCAAF/NBA/NCAAB/MLB/NHL scope and all 63 required cells. First future supported event per sport, earliest schedule then native ID, five-minute margin. Traversal exhaustion means only the retained query's stopping rule; page/byte/time exhaustion is incomplete coverage. Unavailable sports are not proven absent. Unsupported native lines, periods, championships and unbound sport identities stay explicit; successful fixture NFL books do not qualify missing live families.

## Payload and resource envelope

| Class | Per-response maximum | Evidence/basis |
|---|---:|---|
| Event discovery | 2 MiB | r3 complete US page 143,614 bytes; two 262,144-byte truncations are only lower bounds. Large nested single-event fixture exceeds old limit and succeeds. Exact 2 MiB succeeds; +1 byte fails. This is a tested ceiling, not estimated full size of either truncation. |
| Market metadata | 1 MiB | Separate selected-event queries, 50 rows/page; exact envelope boundary tested independently. |
| Account budget metadata | 64 KiB | Retained 133/1,431 bytes; exact envelope boundary tested. |
| Book frame | 256 KiB | Existing stream adapters and admission bounds unchanged; metadata limits do not enlarge stream frames. |

Per native source: 8 MiB shared received-body ceiling across HTTP and books; discovery additionally stops at 6 MiB including overflow probes, leaving up to 2 MiB for books (concurrent books may consume that earlier). Requests reserve bytes before read; exact EOF uses a charged one-byte lookahead. Incomplete JSON supplies no catalog objects, including apparently complete prefix objects. HTTP compression is refused before reading; auto-decompression is disabled, so expansion budget is zero. JSON gets a bounded byte scan before decoding: depth 32, 100,000 structural tokens, duplicate keys/nonfinite numbers refused. Invalid complete wire bodies remain inspectable evidence, not admission.

Shared hard limits remain: 256 MiB sampled peak RSS, 4 MiB/48-record queue, 32 MiB compressed AND 32 MiB cumulatively expanded journal / 4,096 rows (stop reserve before 4,032), 128 MiB session output plus 4 KiB control metadata, 1 GiB free disk floor, owned-transport cleanup. The parser token/byte envelope bounds individual allocation; sampled RSS is a stop threshold, not an OS-enforced instantaneous memory reservation. Original raw/base64 evidence and parsed metadata have amplification; the journal/output stop can bind before body totals. Maximum raw body totals are **ceilings, not a promise all fit simultaneously**: two natives × 8 MiB plus aggregate 9.25 MiB = 25.25 MiB; base64 alone could be 33.667 MiB before metadata, exceeding the journal cap. Thus remaining compressed/expanded journal, queue and output capacity is independently checked before durable admission; the global stop remains mandatory. The existing saved decoder bounds each expansion and rejects trailing/truncated compressed data; collection now also reserves against its cumulative 32 MiB expanded ceiling, including terminal headroom. No cap was raised to conceal a failed rehearsal.

## Request/time reconciliation

Three generations maximum. Each HTTP operation has at most two native attempts inside the same lifetime request budget; oversized/compressed/parse/duplicate failures disable that source, without retry. Kalshi account metadata: two operations × two attempts = 4. Kalshi catalogs/details: 3 generations × (3 summary pages + 6 selected events × 3 market pages) × 2 attempts = 126; **130 total**. US: 3 × (30 event pages + 6 × 3 market pages) × 2 = **288**. Aggregate remains 37 requests / 135 credits, no retry or allowance recycling. **455 HTTP + 12 WS = 467 establishments maximum**, nine concurrent maximum. Actual request/byte/time/global capacity may bind earlier.

180 seconds includes startup, paging, parsing, subscriptions and updates. Kalshi pacing follows retained account limits, at least 0.5 seconds/request; US 0.5 seconds/request. Full worst-case retries alone need 65/144 seconds respectively before latency and refresh waits; this is not a feasible promise to exhaust every page in all three generations. Generation starts after prior discovery and 60-second cadence; deadline wins. Many-page fixture and exact-duration rehearsal record observed workload, not exhaustive live coverage. No deadline extension or new credit allowance follows partial traversal.

## Admission and remaining external evidence

Complete contiguous pages can supply evidence even if a later page fails; failed-source books remain disabled. Duplicate cursors/row IDs stop source traversal. Market tickers, not parent event IDs, identify Kalshi market rows. Missing series, schedules, participants, invalid sides and conflicting query identities cannot qualify markets. Complete US championship listing associations retain source IDs/text but never fabricate season, rules, economics or qualified crosswalks.

Actual native availability, supported kickoff/series mappings outside the proven adapter domains, contemporaneous native books and aggregate crosswalks, NCAAB availability, MLB 6/9-inning mappings, championship field/award/season/rules, effective settlement and fee/account/execution facts remain external dependencies. A future run needs separate exact candidate authorization and an unused destination. Startup obtains quota/access/catalog observations. The saved `.env` needs no new key prompt; it was not accessed. Owner/commercial validation remains deferred.
