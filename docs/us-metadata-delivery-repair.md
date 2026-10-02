# Polymarket US complete metadata delivery boundary

September 30, 2026. Offline engineering. Authority: the current `../prediction_arb_next_steps.md`, the NYI–TOR v3 actual assessment, and this task's explicit instruction allowing a separately bounded offline design. No provider request, real credential access, new acquisition package, reset, retry of a consumed attempt or spending is authorized or performed.

## What exceeded the consumed ceiling

The consumed **HTTP entity body** exceeded 512 KiB. The list and direct-event receipts each retained 524,288 bytes and charged an additional unretained overflow byte. Both prefixes begin with the expected JSON envelope; their embedded markets include many props, totals and spreads. They end inside strings. Completion of those actual deliveries cannot fit the consumed ceiling. Neither prefix supplies current identity, eligibility, availability, terms or executable economics.

The old reader did not retain response headers or the actual request/response URL. Its code disabled redirects, proxies and decompression and requested identity encoding. Reaching the body overflow means its absent-or-identity encoding check passed. Content-Length, Content-Type, transfer framing, unseen suffix validity and final size remain unknown. No historical headers were manufactured.

A complete earlier response for the same event was 15,229 bytes with one moneyline market and a different documented filter combination. The failed list and singular direct response expanded into many more embedded contracts. This supports a packaging/budget mismatch without proving which individual filter caused the difference or promising a smaller future response. The separate complete comparison receipts are 143,614-byte MLB futures and 52,916-byte NFL data.

Exact trace, retained-byte comparisons, original hashes and documented route analysis: [forensics](../evidence/us-metadata-delivery-repair-20260930-v1/forensics.md). Eight preserved source files match the exact consumed v3 implementation; five original hash-chain journals were independently verified.

## Supported route and admission

The retained official Events schema supports `GET https://gateway.polymarket.us/v1/events/{id}` with a singular `event` and embedded markets. The exact selected route remains `/v1/events/127804`, with no parameters, pruning, pagination or fallback. It supplies the independent event schedule, participants and current state required by the existing event/market semantic review. No documented direct-event switch removes unrelated embedded markets. The documented exact-market route `/v1/market/id/{id}` supplies a Market but cannot alone replace that current Event review. Its response size is also unobserved.

The entire response must pass HTTP framing, encoding, UTF-8, JSON, envelope and resource validation before entering metadata review. The existing `native-semantic-review-v1` then independently requires selected event/market identity, exact material and unknown terms, eligible current state and valid mutable observations. Full raw hashes and original receipt provenance remain saved. A protocol-valid envelope can still fail semantic review. Incomplete bodies, rejected complete bodies and unsupported terms create no supported identity or source book selection.

There is no incremental JSON admission. A structural scan bounds expansion before whole-document decoding; it cannot produce records. No retained prefix is extended, reconstructed or interpreted as a complete response.

## Explicit finite engineering contract

`native_transport` must exactly select `native-http-v2` in a newly bound reviewed-target-v2 specification. Absence retains the legacy reader and its 512 KiB event ceiling. Adding the contract changes the specification hash; implementation changes also invalidate every old approval's candidate hash. No new specification/attempt/package for acquisition is prepared here.

| Resource | Finite bound and meaning |
|---|---|
| HTTP plaintext ingress | 4 MiB per admitted response, measured before header/transfer-frame removal. This includes response headers and chunk framing, excludes TLS ciphertext and TCP/IP. One violating callback is separately bounded at 256 KiB, counted and charged before rejection. |
| Transfer-decoded entity / UTF-8 input | 2 MiB each per admitted response; one overflow lookahead byte is read/charged without being retained. Content compression and other character encodings are refused, so admitted entity and decoded-input sizes are equal. |
| Discovery totals | 6 MiB plaintext and 6 MiB decoded input per source, with reservation/refund of actual observed ingress and the existing shared 8 MiB HTTP/stream source budget. |
| JSON expansion | Depth 32, 100,000 structural tokens, 16 MiB pre-decode allocation charge (`4 * input_bytes + 256 * structural_tokens`) and 16 MiB measured parsed-object allocation. The precharge is an accounting estimate; sampled RSS remains an independent limit. |
| Source catalog | 2 MiB retained Python allocation before semantic admission. An oversized source is terminal with `native_source_inventory_cap`; no subset of its contract fields is admitted. Complete original bytes remain durable and excluded entries retain page references. |
| Shared queue | Existing 4 MiB / 48 records; a source catalog also has to fit the complete normalized inventory/publication gate. |
| Journal / ingress | Existing 32 MiB encoded journal, 32 MiB expanded journal, 32 MiB ingress and 4,096 journal records, including reserved stop/finalization headroom. |
| Storage / memory / time | Existing 128 MiB output, 1 GiB free-disk floor and 256 MiB sampled RSS limits; existing total session deadline and finite HTTP timeout. Reopening has its own memory reservation. |

This envelope is justified as a finite fourfold entity increase beyond the observed lower bound and is tested at its exact boundaries. It is **not** a measured maximum or a guarantee that the unseen provider response fits. Earlier unrelated CFB delivery exceeded two MiB. Every resource gate applies together; body size alone does not authorize admission.

The revised production transport uses aiohttp's actual HTTP reader with an explicitly verified protocol hook to count plaintext before parsing. Header count/line/field limits, a single forced-close connection, disabled cookies/proxies/retries/redirects/decompression and identity encoding bound the supporting transport state. A fixed 256 KiB `BufferedProtocol` buffer bounds both TCP intake and TLS decryption. The actual buffered read path and aiohttp private-hook capability are checked before dispatch and on the connection; unsupported runtimes fail closed. The copied TLS path can join several reads, so its per-read size was explicitly rejected as a callback proof. Request/response provenance and duplicate-preserving safe header values are retained, with secret-bearing fields redacted and credential echoes suppressed. HTTP plaintext is hashed without persisting its raw header stream.

Peer close and full message framing must be validated within the original HTTP timeout. Explicit declared-length surplus, chunk framing surplus, truncation, conflicting lengths, unsupported encoding, bad JSON/envelopes and timeouts retain distinct reasons. A server that ignores `Connection: close` can fail this policy; future provider compatibility remains unobserved.

## Offline verification and remaining live question

The [final report](../evidence/us-metadata-delivery-repair-20260930-v1/README.md) and [machine verification](../evidence/us-metadata-delivery-repair-20260930-v1/verification.json) bind the final source. Forty actual HTTP/TLS boundary controls and 28 ordinary-session controls passed; four TLS controls cover exact entity/plaintext boundaries, overflow and delayed surplus. Eighty-two focused regression test methods passed, including the 63-cell product loop. Peak RSS was 230,522,880 bytes, queue eight records / 2,810,277 bytes, encoded journal 5,199,934 bytes, expanded journal 6,171,528 bytes and session storage 5,554,579 bytes. All-terminal cleanup took 0.814 seconds. All 28 controls reopened exactly in fresh processes with drained accounting. Ordinary Start/Stop, production HTTP reading, semantic selection, fsynced persistence, native reconstruction, saved source health/catalog and exact fresh-process reopening are exercised through actual numeric loopback servers. External connections and real credential resolution are denied. Complete US responses are constructed controls from already reviewed complete objects, never failed prefixes.

The Kalshi regression reuses the latest consumed 11,768-byte metadata, two snapshots and 52 deltas. The local acknowledgement request ID is rebound to the local subscription; original snapshot/delta bytes and source times remain retained. No Kalshi data is recollected. No synthetic US metadata becomes a provider book, and no paired provider card or contemporaneous comparison is established.

All original files, attempts, seals, historical interpretations and all 63 scope cells remain preserved. Economics, settlement/fee/execution/arbitrage/EV qualification and owner/commercial acceptance remain unavailable. The initial sandbox refusal, verifier memory-reservation failure after accumulated controls, and discovered framing/semantic-reason faults are retained separately; final verification is bound to the repaired source and fresh-process controls.

The smallest live question is whether one newly authorized direct US event response closes and delivers a complete supported envelope within these separately sealed finite bounds, then passes the independent current identity/terms/eligibility review. Any later US/Kalshi observations require a fresh approved session; historical Kalshi books cannot stand in for simultaneous new counterparts. No acquisition package or approval request follows this engineering task.
