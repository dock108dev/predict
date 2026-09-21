# Predict — five-minute supervised segmented policy

September 16, 2026. **Five-minute offline qualification complete; thirty-minute qualification deferred.** See the [consolidated report](data-coverage-supervised-5m-qualification-report.md). Both busy wall-clock lifecycle cases and all 59 selected checks pass; collector peaks were 113.05/109.81 MiB against the unchanged 192 MiB target. Frozen limits below remain unchanged. Profile `predict-supervised-segmented-5m-v1` is still selected only through the isolated fixture path; production selection, legacy limits and consumed-attempt protection are unchanged. US completeness remains unknown, D2 live validation/full D3 incomplete. [Later-authorized live proposal](data-coverage-supervised-5m-live-handoff.md) · [measurement basis](data-coverage-sustained-capacity-measurements.md) · [frozen budgets](../evidence/supervised-5m-20260916/frozen-budgets.md).

## Objective

One supervised owner Start, idle startup/no autoresume, up to **300 seconds including discovery**, representative **64 Kalshi/32 US markets**, initial discovery plus one scheduled refresh at **120 seconds**, direct active Stop at **240 seconds**, and an independent **300-second deadline** check. Preserve original observations, identities, clocks and exact incremental native/book/packet replay. US full completeness remains unknown. No venue access or live collection is authorized by this profile implementation.

The retained short capture contained only 23.180 seconds of frames within 50.904 seconds of collection. At twice that active mix, the five-minute arithmetic is **45,114 logical rows / 15,039 frames / 92.96 MiB encoded / 329.41 MiB expanded**, before refresh and churn. Real expanded rows average 5.30 times the earlier tiny mock. These estimates set test objectives, not a live-duration guarantee. A full stable two-generation traversal is about **68 Kalshi / 78 US REST attempts**.

## Frozen limits

All cumulative allowances survive rotation. MiB/GiB are powers of two. Logical ingress counts every admitted observation, including health and metadata. Physical records include headers, seals and the terminal. Encoded ingress excludes journal envelopes; physical journal bytes include them. Expanded serialization, retained Python objects and RSS are different measures.

| Resource | Segment / instantaneous ceiling | Whole-session ceiling |
|---|---|---|
| Logical / physical rows | 1,024 logical threshold, effective 1,023; underlying 4,096 physical writer guard and 64-record structural reserve | 65,536 logical; 65,793 physical = logical + 2×128 + one terminal |
| Encoded / expanded | 4 MiB physical encoded / 8 MiB physical expanded per segment, 64 KiB structural reserve; ingress row ≤1 MiB each | 160 MiB encoded ingress / 512 MiB expanded ingress; 176 MiB physical journals / 520 MiB physical expanded |
| Segments / manifest | Small segments; terminal ≤32 KiB; manifest ≤256 KiB | 128 segments including open/interrupted segment |
| Ingress rate | Rolling second: 1,024 rows, 256 frames, 8 MiB encoded / 32 MiB expanded | No sampling or capacity credit after rotation |
| Frames / bodies | Wire frame/REST response ≤1 MiB; WebSocket queue one message/socket | 24,000 frames aggregate, 20,000/group lifetime; 64 MiB body allowance/venue including pending reservations |
| Discovery | ≤64 attempts/venue/traversal; existing ≤2 requests/second/venue, additionally respecting verified account pacing; at most two tries/request, 5-second HTTP timeout | 128 attempts/venue; exactly initial + one refresh at 120 seconds; retries consume allowance |
| Coverage / connections | 100 selected/venue, groups ≤20 Kalshi/100 US, six simultaneous sockets; catalog ≤128 events/256 markets/venue | 12 distinct groups, 24 connection attempts, two/group; 256 unique requested market IDs/venue |
| Queue | 48 objects / 4 MiB retained Python objects | Peak, drain and durable-not-queued accounting retained |
| Memory | 256 MiB hard RSS; stop intake at 224 MiB; live/replay retained working state each ≤64 MiB | Native frame/response history is journal-backed; diagnostics ≤128 entries/list and 1 MiB live aggregate; snapshot ring 60 |
| Exact identities | Sort at most 4,096 UUIDs in RAM per chunk, exact merge comparison | At most 16 chunks / 1 MiB spool for 65,536 UUIDs; no whole-run identity set |
| Disk | Preserve 1 GiB free floor plus remaining output reservation | 224 MiB output: 176 journals + 16 routine metadata/spool + 32 protected finalization; 256 MiB write ceiling with 32 MiB finalization reserve |
| Finalization | Feeds close before replay; streaming sequential verification | 300-second finalization deadline, separate from collection; qualification target ≤240 seconds |

These are joint limits. Hitting any one stops intake rather than granting another segment or silently discarding observations. Structural reserves remain inside per-segment bounds. Finalization output is unavailable to ordinary collection. Initial free-space check and subsequent remaining-reservation checks do not promise protection from other processes filling disk. Retain incomplete prefixes on storage/publication failure; no automatic evidence deletion, overwrite, autoresume or new attempt.

The native engines retain only current dependency state in this mode. Original wire observations are journaled before native parsing. Bounded diagnostic samples are non-authoritative; full input frames remain available for replay. Retired groups release engines and previous-book dependencies only after a durable departure; observations requiring a retired group fail closed. Catalog pages reset each generation; byte guards and resident measurements apply in addition to cardinality limits. Unchanged subscriptions survive refresh without reconnect. Partial discovery never replaces a complete generation or proves US completeness.

Output accounting includes manifests and pending copies, locks, reports and exact-identity spool. Track manifest replacement write traffic separately from retained bytes. On Stop/resource exhaustion: close intake immediately, preserve the first reason, cancel/join feeds and discovery, drain admitted queue work, account for cleanup rejection/unresolved writes, seal/publish only where safe and replay within remaining bounds. A resource Stop or incomplete replay cannot pass the requested active-Stop/deadline objective.

## Qualification and stop rule

Fresh process and exclusive new output for every gate; loopback-only network and blocked credentials. Preserve all original evidence. Major lifecycle cases are bounded to 660 seconds wall / 600 CPU seconds, 224 MiB collector output + 8 MiB harness output each. Focused suites are bounded to 180 seconds; all new task artifacts ≤1 GiB. No real disk exhaustion. Budgets were recorded before implementation and cannot be expanded after failure.

1. Exact original 1,914 ingress observations + terminal, **575 native books / 1,150 packets**, including metadata/stream boundary rotation, and unchanged saved calculations.
2. Representative retained-shape fixtures for all 96 markets, actual clocks, both feeds active, rotations, real scheduled refresh at 120 seconds and direct Stop at 240 seconds. Measure ≥50.13 frames/active second and encoded/expanded flowing payload volume against twice the retained active mix. A quiet timer or tiny-payload run does not pass.
3. Independent 300-second deadline case, same busy traffic and refresh. Report catalog published/applied generations, subscription/usable counts, exact sequence digest/replay, received/accepted/durable/rejected accounting and task/feed closure.
4. Reuse applicable existing rotation/storage/queue/recovery tests; add changed policy, identity, rate, row and cumulative budget boundaries. Measure state across rotations, bounded native histories and diagnostic samples. At matched cardinality after warmup, state growth ≤8 MiB.
5. Headroom: ≥25% spare logical/frame/encoded/expanded/output budgets; RSS ≤192 MiB; live/replay state ≤48 MiB each; queue ≤24 objects/2 MiB; feed/task closure and queue drain ≤5 seconds; finalization ≤240 seconds. Intake closes synchronously when Stop is requested. Record actual latency and elapsed finalization.

**Stop at a required failure**, preserve evidence and name the concrete blocker. Do not enlarge limits or start an optimization loop. A pass permits preparation of one separately authorized five-minute live-validation handoff, not a live run. Five minutes establishes neither thirty-minute nor daily capacity. D2 live validation and full D3 remain incomplete.

Preserve separate environmental findings: `ReadOnlySurface.test_catalog_reopen_no_activation_and_identity_error` failure and `test_offline_guarded_reopening` error, tied to original device 16777234/current 16777233. Never rewrite original indexes or weaken identity checks. The earlier combined-process RSS failure is distinct from these two recovery findings.
