# Slice 2 — Polymarket US read-only ingestion

Updated September 11, 2026. **Slice 2 complete for bounded retail ingestion and advertised-window recovery.** Stop before Slice 3. No account action or external access dependency remains. This is engineering qualification, not continuous-scanner readiness, owner acceptance or trading authorization.

Original bounded [qualification evidence](../evidence/slice-2/qualification-20260911T234447Z/), [artifact manifest](../evidence/slice-2/qualification-20260911T234447Z/manifest.json), and [tests](../evidence/slice-2/qualification-20260911T234447Z/tests.txt). Previous [live verification](../evidence/slice-2/verification-20260911T231849Z/) and all earlier evidence remain unchanged. Historical UNKNOWN-sync judgments below describe the implementation at that time; this qualification supersedes that gate.

## Authorization and access

The owner's authorization supersedes earlier terms-acceptance restrictions: applicable API terms acceptance, existing-account setup, public/authenticated read-only requests, local dependencies, fixes, tests and private market-data evidence are authorized. No repeated confirmation is needed. No trades, deposits, withdrawals, subscriptions, third-party contact, commits, pushes or publication occurred.

The owner completed official portal login. The dedicated credential remains in macOS Keychain, service `prediction-arb.polymarket-us`, entry `retail-api`. Only this explicit project entry is read; no environment file or credential search is used. Ed25519 signing successfully authenticated the retail markets socket. No account/private-data endpoints were requested.

## Protocol decision and source basis

The current [official US retail market guide](https://docs.polymarket.us/api-reference/websocket/markets) calls the subscription “Full order book and market stats” and says quantities are totals at each price. Its depth section limits the image to top levels. This supports **standalone replacement of the advertised window**, not accumulation of incremental deltas or unlimited exchange depth.

The official Python SDK at exact commit `aa38c1620b2898d953ba65b6a36687ddec3dd3bb` corroborates this: [MarketData type](https://github.com/Polymarket/polymarket-us-python/blob/aa38c1620b2898d953ba65b6a36687ddec3dd3bb/polymarket_us/websocket/types.py) identifies a full order book; [subscription/handler](https://github.com/Polymarket/polymarket-us-python/blob/aa38c1620b2898d953ba65b6a36687ddec3dd3bb/polymarket_us/websocket/markets.py) forwards the image without delta reconstruction. The SDK payload fields are optional, so a missing side cannot be assumed empty. Exact retrieved pages, code, retrieval metadata and SHA-256 hashes are in [research](../evidence/slice-2/qualification-20260911T234447Z/research/sources.json). The overview's conflicting snake_case example is not used to override the observed camelCase market guide. No international or institutional guarantee is imported.

**Interpretation, explicitly distinguished from a literal protocol promise:** a supplied full-window image replaces previous levels. Omission means absence from this advertised window, not proof an exchange-wide order was canceled. An explicit empty array contains no levels. Zero total quantity contains no usable liquidity and is excluded while preserving raw input; it is not applied as a delta operation. Neither empty sides nor zero quantities occurred naturally in this bounded capture; those cases are tested synthetically. Missing/null arrays remain unknown. The docs do not promise a numeric depth ceiling, historical event continuity or source-clock freshness.

## Precise book qualification

`BookSync.SYNCHRONIZED` means the local advertised window equals the latest structurally valid image accepted for this market on the current subscription/connection generation. Both long-side arrays must be explicitly present. It does not mean every intermediate event was received, all exchange liquidity is visible, or the source timestamp is recent.

- Each complete frame atomically replaces both long ladders. Omitted prices disappear, quantities replace previous totals, and explicit empty sides clear previous levels. No side is inherited from an older frame.
- Missing/null sides produce UNKNOWN qualification. Malformed/ambiguous frames invalidate the previous image; the transport reconnects. Disconnect and shutdown also invalidate it.
- A new subscription starts unqualified. Its first valid full image restores that market's qualification independently. Old request IDs and old connection generations cannot restore or overwrite current state.
- `receipt_freshness` is separate: RECENT on accepted data, STALE after the local timer, UNKNOWN by default. Quiet periods preserve image correctness while freshness expires; heartbeat/socket health cannot refresh market data. Recent receipt does not establish recent exchange time.
- Stream ladders retain PARTIAL depth; REST depth remains UNKNOWN. Native short-side ladders remain unavailable, not manufactured from complements. Status remains a separate field; an OPEN image is not a trading recommendation.

Decimal prices/quantities, native identities, immutable raw JSON, original timestamp spelling and explicit unknowns are preserved. Python datetime carries microseconds; raw `transactTime` retains nanoseconds. BBO sample time is not substituted for an absent book timestamp.

## New bounded live evidence and replay

The declared ceiling was three markets, ten minutes, 1,000 frames and 20 MB; the actual capture used **46.01 seconds, 42 frames, 187,214 bytes, two connections, four public discovery/detail requests**, then stopped early. It selected pregame September 13 NFL moneylines: Ravens–Colts (`381955`), Falcons–Steelers (`381956`), Bears–Panthers (`381953`). All three delivered initial images on both connections. The first connection was deliberately closed after 20 seconds; the second used a new subscription UUID. See [capture summary](../evidence/slice-2/qualification-20260911T234447Z/live/capture-summary.json) and lifecycle evidence.

The wire showed natural total-quantity changes. In frame 042, Ravens–Colts bid `0.5000` disappeared without a zero-quantity tombstone; the other supplied levels remained. This corroborates replacement semantics. It does not establish why that price left the window. Initial and post-reconnect frames had the same full-image envelope. Previous captures additionally show an initial reconnect image identical to the prior image, including its timestamp: reconnect is not proof of a newer source image. No separate acknowledgment, heartbeat, sequence or delta marker appeared in these short sessions. All observed states were OPEN.

The live process loaded the prior conservative parser before the qualification edit. Therefore its saved UNKNOWN classifications are historical capture-time results, not outputs of the revised parser. **Offline replay through the revised adapter** checks all 42 unmodified frames against every supplied nonzero price/quantity, confirms removal at frame 042, and checks all three markets' first images after each subscription generation. [Replay result](../evidence/slice-2/qualification-20260911T234447Z/window-replay.json). No second live session was needed to repeat the same wire behavior.

## Actual public results

The prepared smoke ran successfully under the new authorization: **five HTTP 200
responses**, saved with receipt/source provenance in [public-smoke](../evidence/slice-2/verification-20260911T231849Z/public-smoke/).

- Event `74902`, market `381955`, slug `aec-nfl-bal-ind-2026-09-13`:
  Baltimore Ravens–Indianapolis Colts, scheduled September 13 at 17:00 UTC.
- Long side `763424` (Ravens); short side `763425` (Colts).
- REST book: **26 bids, 27 offers**; top long bid `0.6050 × 145489.5600`
  contracts, offer `0.6100 × 64690.8500`. BBO agreed at that observation.
- Rule description retrieved. State OPEN. Raw exchange timestamp
  `2026-09-11T23:06:03.697243528Z`; receipt `2026-09-11T23:19:00.463148+00:00`.
  The roughly 13-minute difference is observed data age, not transport latency.

A focused [supplemental REST check](../evidence/slice-2/verification-20260911T231849Z/supplemental-rest/)
verified filtered market pagination: one matching market, followed by an empty page.
The pregame `/settlement` endpoint returned **404**, retained as unavailable rather
than invented settlement data. The first supplemental harness failed to persist its
responses on that exception; the [initial-attempt record](../evidence/slice-2/verification-20260911T231849Z/supplemental-first-attempt.json)
records this limitation. Failure preservation was repaired and the bounded check repeated.

The two stream/REST comparisons and a two-request cache check bring this session's
public request budget to **at most 15 attempts**, with **12 response bodies preserved**
(the first supplemental attempt had a three-request cap and no saved bodies).
There were no broad scans or continuous polling.

## Authenticated streaming and recovery evidence

[Session 1](../evidence/slice-2/verification-20260911T231849Z/authenticated-01/result.json):
about 25 seconds, **12 market frames**, two authenticated connections, one market.
Initial subscription at 23:25:11 UTC; deliberate local disconnect at 23:25:21;
reconnection/resubscription at 23:25:23; cancellation and close at 23:25:36.
New request IDs were used and echoed in the corresponding data frames. All four
exercise flags are true: disconnect requested/completed, cancellation requested/propagated.

All received messages used `requestId`, string `subscriptionType`, and `marketData`
with `marketSlug`, `bids`, `offers`, `state`, `stats`, `transactTime`. No separate
subscription acknowledgment, sequence field, delta marker or application heartbeat
was observed in these short sessions. Data delivery confirms the subscription worked;
absence of a separate acknowledgment or heartbeat here is not a universal guarantee.
All observed state values were OPEN; no live halt transition occurred.

Each frame supplied 26 bids/27 offers with fractional sizes. The **first frame after
resubscription exactly repeated the last pre-disconnect `marketData` object**, including
its exchange timestamp; subsequent frames advanced. The adapter accepted each as a
standalone UNKNOWN-sync observation and never merged a presumed delta.

[Session 2](../evidence/slice-2/verification-20260911T231849Z/authenticated-02/result.json):
about 14 seconds, **5 frames**, two connections, deliberate close after five seconds,
resubscription and cancellation verified again. Two fresh REST requests were made
specifically to [compare the first image on each connection](../evidence/slice-2/verification-20260911T231849Z/authenticated-02/rest-comparison.json).
REST still reported 23:06:03 while the stream had reached 23:27–23:28, with different
ladder quantities. They were different-time observations, not valid same-time matches.

The [cache check](../evidence/slice-2/verification-20260911T231849Z/rest-freshness/provenance.json)
returned `CF-Cache-Status: HIT`, `Age: 12`, and `Cache-Control: public, max-age=30`.
A request with `Cache-Control: no-cache` returned the same cache metadata and old
book. These headers document caching but do not explain the entire 22-minute
exchange-time discrepancy; an upstream/source discrepancy remains possible.
No cache-bypass query guessing or continued probing was performed. REST must not be
used as authoritative proof of stream resynchronization in this condition.


## Fixes and validation

**45 tests pass**, including all 16 original Slice 1 tests, both historical capture replays and the new 42-frame replay. Both offline examples pass. Synthetic tests cover omitted levels, replacement quantities, zero quantity, empty/missing sides, malformed atomic invalidation, recovery after a new subscription, old-generation/request rejection, freshness/depth independence, quiet connections, reconnection bounds and cancellation. These cases establish implementation behavior; they do not claim naturally observed empty books, zero rows or halts.

The adapter now qualifies current full-window images, guards subscription generations, rejects duplicate prices, and separates receipt freshness from book reconstruction. The finite capture utility retains sanitized market-only evidence. Earlier fixes for HTTP error/cache provenance, pending receive survival and idempotent cleanup remain covered.

## Focused hardening pass — September 11, 2026

**49 tests pass; bounded ingestion qualification remains complete.** No new market-data capture, account setup, dependency installation or order action was needed. Current [hardening evidence](../evidence/slice-2/hardening-20260912T001008Z/), [tests](../evidence/slice-2/hardening-20260912T001008Z/tests.txt) and [artifact identities](../evidence/slice-2/hardening-20260912T001008Z/manifest.json) supersede implementation identities only; all prior evidence stays historical and unchanged.

**Actual gap fixed — source-clock visibility:** receipt freshness was already separate from exchange time, but consumers had to discover repeated/regressing source time themselves. `OrderBook.source_time_progress` now reports MISSING, FIRST, ADVANCED, REPEATED or REGRESSED against the market's greatest previously accepted source timestamp. UNKNOWN is the default for adapters without this tracking. The stream retains this reference across reconnects and missing/regressing frames; a new stream instance starts a new reference. Comparisons preserve fractional seconds beyond microseconds and normalize timezone offsets. ADVANCED means only greater than that reference; FIRST does not establish recency.

`RawPayload.source_age_at_receipt` exposes signed receipt-minus-source time, or None for missing time. `receipt_age(as_of)` evaluates receipt age at the caller's chosen time. These datetime intervals have microsecond resolution; original nanoseconds remain in raw JSON and source ordering. Negative age exposes clock disagreement. No universal age cutoff, transport-latency estimate, eligibility decision or quiet-image rejection was added. A source timestamp may represent last change. Repeated/regressing images remain observations with explicit uncertainty, even when their current-window reconstruction is SYNCHRONIZED. Downstream code must apply its own explicit source-age/progression policy alongside receipt freshness and market state.

**Existing protections verified:** exchange and receipt timestamps remain independent of socket lifecycle events and transport ping/pong. Receipt timers neither disconnect quiet sockets nor change source timestamps. No REST-to-stream fallback exists, and REST snapshots stay UNKNOWN-sync/UNKNOWN-depth; the captured old REST sample still exposes more than twelve minutes of source age at receipt. Stream ladders stay PARTIAL; unavailable short ladders and missing BBO quantities remain explicit. Window omission is not proof of exchange-wide cancellation. Examples now explicitly label observed levels as having unknown total exchange depth and executable capacity. No unlimited-depth investigation was needed.

**Status mappings verified, no speculative mapping added:** the [official retail market states](https://docs.polymarket.us/api-reference/websocket/markets) and [retail book schema](https://docs.polymarket.us/api-reference/markets/get-market-book) were rechecked and saved with hashes in this evidence directory. OPEN maps to ACTIVE; PREOPEN to PREOPEN; SUSPENDED/HALTED to SUSPENDED; EXPIRED/TERMINATED to CLOSED. The retail schema does not enumerate a literal CLOSED state. Unrecognized values, absent status and MATCH_AND_CLOSE_AUCTION remain UNKNOWN; institutional instrument enums are not imported. Original state spelling is retained in raw JSON. These mappings already existed.

Four focused new tests cover (1) the actual repeated reconnect image, (2) missing/regressing/sub-microsecond timestamps across reconnect, (3) signed old/future source age without image rejection, and (4) OPEN → SUSPENDED → OPEN plus halted/expired/terminated/unknown states and a status-only reopen. The latter retains ACTIVE state but UNKNOWN book qualification with unavailable ladders; reopening alone cannot revive an earlier book. A synchronized full image may separately be SUSPENDED, CLOSED or UNKNOWN. Earlier depth, omission, cancellation, malformed-image and quiet-market tests were reused rather than duplicated. The existing REST replay assertion now checks its exposed source age. Both offline examples pass.

**Venue constraints remain:** no live halt transition was observed or required; REST cache/source disagreement remains unresolved; top-window depth is not total liquidity; a recent receipt is not a newly changed source. Downstream eligibility must consider these independent facts. They do not reopen completed bounded ingestion/recovery qualification. README's stale partial-status wording was corrected.

**Next concrete action:** Begin ProphetX Slice 3 by verifying sandbox API enablement and the authentication path in its official integration guide, recording the exact available entitlement before the first bounded catalog request. No Slice 3 implementation began in this pass.

## Focused review follow-up — September 11, 2026

**50 tests and both offline examples pass. Slice 2 remains complete for bounded ingestion and advertised-window recovery.** Current [review evidence](../evidence/slice-2/review-20260912T002420Z/), [test results](../evidence/slice-2/review-20260912T002420Z/tests.txt) and [artifact identities](../evidence/slice-2/review-20260912T002420Z/manifest.json) supersede implementation identities only. The prior 49-test hardening record and all capture evidence remain unchanged.

**Additional actual gap fixed:** the source-time helper added whole epoch seconds to a Decimal fraction using the caller's arithmetic precision. At precision 3, distinct nanosecond timestamps collapsed to the same value; a precision change across reconnect could also misclassify a repeated source image as advanced or regressed. It now compares an exact pair of integer UTC seconds and a Decimal fraction constructed directly from source text, with no rounded addition. One new synthetic regression checks a repeated timezone-equivalent image, nanosecond regression/advance and the next whole second across reconnect after the caller lowers precision. This extends, rather than repeats, existing reconnect/source-clock tests. No change to age policy, accepted images, wire data or market-state mappings was needed.

**Protections already present and reverified:** exchange time, local receipt and socket lifecycle remain independent; source age is signed and is not transport latency. Missing/repeated/regressing source time remains visible, and old quiet-market images remain observations. Cached REST is never a streaming reference or fallback. Streaming ladders retain PARTIAL depth, REST depth stays UNKNOWN, and omitted prices indicate absence only from the current advertised window. Examples do not claim total exchange liquidity or maximum executable capacity. Existing OPEN → SUSPENDED → OPEN and unknown-status tests retain state independently from synchronization, and a status-only reopen leaves the book UNKNOWN with no inherited ladders. No duplicate depth/status tests were added.

The [official US market states and depth guide](https://docs.polymarket.us/api-reference/websocket/markets) and [REST book schema](https://docs.polymarket.us/api-reference/markets/get-market-book) were rechecked during this review; the existing mappings remain consistent with those sources. OPEN is ACTIVE; SUSPENDED/HALTED are SUSPENDED; EXPIRED/TERMINATED are CLOSED; unrecognized or missing states stay UNKNOWN. Reopening does not itself supply a current image or establish source recency.

**Remaining venue constraints and downstream implications:** receipt recency cannot establish source recency; a last-change timestamp may be old in a quiet market. Downstream eligibility needs an explicit source/receipt policy without treating age as latency. Advertised depth cannot establish full exchange liquidity or executable capacity; REST cache/source disagreement prevents same-time corroboration; no live halt or continuous-scanner reliability was established. These limitations do not reopen completed bounded ingestion qualification. No new market-data capture, account/credential access, unlimited-depth investigation or later engine work occurred. PLAN.md and every preexisting evidence file were verified unchanged by hash; no commit, push or publication occurred.

**Next concrete action for ProphetX Slice 3:** verify sandbox API enablement and the official integration guide's authentication path, recording the available read-only entitlement before the first bounded catalog request. Slice 3 has not started.

## Remaining limitations and handoff

Stale REST is not used for same-time corroboration. Its cache/source discrepancy remains unresolved, and consumers must use its actual source timestamps. Unlimited depth, a fixed depth ceiling, gap-free event history, live halt transitions, continuous reliability, trading fees and cross-venue settlement compatibility are not established. None is silently represented by SYNCHRONIZED. This completes the bounded Slice 2 ingestion/recovery scope; later scanner qualification must retain these independent restrictions.

PLAN.md and historical evidence are preserved by hash verification. Credentials are absent from project artifacts and the Desktop tracker. No Slice 3 work began. **Next concrete step:** Begin ProphetX Slice 3 by verifying sandbox API enablement and the authentication path in its official integration guide, recording the exact available entitlement before the first bounded catalog request.

Offline verification:

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python -m app.example
.venv/bin/python -m app.polymarket_us_example
```
