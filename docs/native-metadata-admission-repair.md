# Native metadata admission and delivery repair

September 30, 2026. Offline engineering only. Authority: `../prediction_arb_next_steps.md` and `evidence/native-nyi-tor-live-assessment-20260930-v1/`. Attempt `5c26ecaf-d41b-4589-a590-d2423e2aa62d` stays consumed. No new acquisition package, provider request, real credential resolution, restart or spending.

## Versioned field policy

`native-reviewed-target-v2` requires each conditional source review to contain `native-semantic-review-v1`. The review validator checks the contract against its retained source objects. The reusable comparison route applies the same contract. Historical records without this explicit policy retain their full-hash gates and interpretations. New session reviews bind their actual raw event/market hashes, original template raw hashes, source receipts, selection time and session ID. Listing observations never create books.

The exhaustive retained-field classifications and actual review contracts are in `evidence/native-metadata-repair-20260930-v1/field-policy.json`.

| Class | Policy and retained justification |
| --- | --- |
| Identity and material terms | Participant/team/side IDs and roles, outcomes, rules/description, market family/period/strike, schedule and expiration, payout/notional/collateral, tick/quantity/fees, settlement sources, rescheduling and other retained fields remain exact. The retained native review binds these attributes to its normal-winner correspondence; no price observation supplies replacement terms. Unknown fields are review-sensitive opaque terms, including timestamps with no justified narrower meaning. |
| Current eligibility | Kalshi selected market must have `status=active`. US requires explicit active, open, unarchived, unhidden event/market, event period `NS`, supported native market status and EP3 status. Absent US live/ended flags retain the reviewed schema's explicit unspecified treatment and cannot establish a source clock; newly present fields require review. Five-minute schedule margin, resolved normalized scope and market/event correspondence remain independent gates. |
| Mutable observations | Kalshi listing bid/ask/last/previous prices, bid/ask quantities, liquidity, volume and open interest. Actual complete NYI–TOR receipt changed the captured volume/interest/size fields and TOR prices while preserving rules/outcomes. US retained listing schema and documented response distinguish outcomePrices, bestBid/AskQuote, side price/quote values, volume/liquidity/interest from participant/role/currency/terms. These can vary only with retained field presence/type and valid finite nonnegative values. Currency and nested unknown quote attributes stay exact. |
| Packaging | Event `markets` arrays package separately reviewed selected contracts. Each selected market must be present and supported; unrelated embedded contracts cannot replace it. Missing/malformed selection is explicit. No partial JSON supplies an event or selected market. |

Added/removed fields, missing eligibility, invalid observations, unknown changed fields, conflicting duplicates and changed material terms fail closed with explicit reasons. Ordinary observed Kalshi price/volume changes pass without a whole-object identity match. Full raw hashes remain immutable provenance, not the sole semantic admission gate.

## US request and bounded payload rationale

The consumed attempt sent `/v1/events` with `id=['127804']`, NHL scope, hidden/player-prop exclusions, `limit=1`, `offset=0`. The actual transport supplies the list as repeated query values through aiohttp. HTTP 200 and 524,288 retained / 524,289 charged bytes establish overflow only. The incomplete prefix proves neither filter effectiveness nor target availability/absence.

Retained complete r3 events response is 143,614 bytes for two events with embedded markets; the following response overflowed 256 KiB. This proves embedded metadata can be delivered in complete list responses, not that the NYI–TOR exact filter or any current size bound worked. Complete NYI–TOR selected US objects retained in the original reviews establish the expected embedded schema, not delivery under a new request. See `retained-us-delivery.json` and the preserved review source receipt provenance.

The new path uses the narrower documented [Get Event By ID](https://docs.polymarket.us/api-reference/events/get-event-by-id): **one GET `/v1/events/127804`, no query parameters, pages, retries or fallback**. Its documented response is a singular `event` with embedded `markets`. The [list endpoint](https://docs.polymarket.us/api-reference/events/get-events) documents filters including market types, but does not establish an observed successful exact filter or a response-size guarantee. No embedded-market pruning parameter is assumed for the direct endpoint. Local checks independently require the exact returned event ID and selected market `1061481`.

The collector, catalog, adapter extraction and native replay now understand the singular envelope while retaining the original path and body/hash. Catalog-only pagination descriptors are derived internally for the single object; they are not wire parameters. An event with several raw team entries requires unanimous supported league evidence and the existing embedded selected-side identity binding; it does not infer a league from the URL or an ID.

The cap stays **512 KiB + one charged overflow byte**; it was not increased. Depth 32 / 100,000 structural-token checks occur before decoding; duplicates, nonfinite values, malformed JSON and compression fail. Encoded raw receipt is at most about 700 KiB before journal overhead; the shared queue is 4 MiB/48 records, normalized inventory is checked against queue retained-object size, journal encoded/expanded limits are 32 MiB, ingress 32 MiB, output 128 MiB and sampled RSS 256 MiB. All apply together. Parsing objects, raw/base64 strings, normalized metadata and replay coexist; structural and inventory checks plus measured RSS complement the byte bound. A constructed complete 512 KiB direct envelope tests delivery, selected identity, paired books, queue/journal costs and reopening; one byte over remains evidence only. This finite engineering bound is not a provider maximum. A live direct envelope may still overflow or fail identity.

Reasons retained in ordinary health, source catalog exclusions and saved journal include `native_response_byte_cap`, `native_incomplete_json`, `native_malformed_data`, absent selected event/market in a complete response, unsupported selected identity, changed material/unknown terms and unsupported eligibility. Wire completeness is separate from usable metadata. Historical incomplete receipts remain unchanged.

## Runtime and verification

A finite native session stops with `all_selected_sources_terminal_no_permitted_work` when every enabled selected source is terminal and no aggregate/reference work exists. Disabled venues are excluded from that count. Healthy independent source work continues. Exhausted native stream workers become terminal instead of waiting for the global deadline. The normal Stop path cancels/joins workers, closes clients/sockets, drains acknowledged records and seals/replays the journal.

Verification uses the actual existing launcher copied into labeled offline control directories, rebound solely for intercepted HTTP, synthetic sockets and fake credentials. These directories are test artifacts, not unused acquisition packages or real approvals. External socket connections are denied. The original package/attempt/approval are untouched. Captured Kalshi response objects are tested unchanged; US direct envelopes, padding, fault responses and books are explicitly constructed controls.

The exact launcher exercises semantic admission, two paired NHL raw cards, one shared US market/side depth identity, Details/download, sizing with unavailable net result, watches/history/download, stale book exclusion, ordinary Stop, isolated metadata failures, terminal metadata/stream completion and exact fresh-process saved digest. Separate product regressions cover all 63 synthetic scope cells, shared math/size routes, original/v2/v3 historical digests, settlement/fee exclusions and reference isolation. Logs retain preliminary harness/replay failures and repairs. A combined broad regression process exceeded its existing RSS ceiling; suites were rerun in fresh processes without changing any limit.

Results, measured resources, exact repair identity and preservation audit: `evidence/native-metadata-repair-20260930-v1/`.

## Remaining live uncertainties

No direct event-by-ID response, current US availability, embedded selected-market completeness, current Kalshi terms/state, or paired native stream delivery has been observed under this repaired candidate. Current books, updates/recovery, provider sizes/filters and real source clocks remain unqualified. Any future collection requires new source review/current window and a fresh separately authorized unused sealed acquisition; the consumed attempt cannot be reset. No such acquisition is prepared here.

Settlement compatibility/amendments/exceptional payouts, fees/precision/mandatory charges, fair probabilities, execution/clocks and broader coverage remain unresolved. Economics and owner/commercial validation remain unqualified; beta NOT READY FOR SIGNOFF.
