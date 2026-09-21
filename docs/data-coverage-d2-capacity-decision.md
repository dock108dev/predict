# D2 capacity decision — move minimum D3 history work forward

September 16, 2026. **Recommend D3a: bounded journal segments and incremental replay before sustained D2 validation.** Keep D2 incomplete and its existing live limits intact. Do not spend another iteration making a finite, whole-session pilot resemble a daily collector. This assessment changed no production implementation, limits or original evidence and ran no live collection.

## What 2,048 actually protects

`TransportSession.emit` counts one admitted ingress row per call, including control, metadata, health and derived-book rows—not one market, quote, network message or transaction. It rejects the next row when `delivered >= 2048` or encoded ingress would exceed 16 MiB. Receipt/rejection accounting occurs before admission; accepted work is journaled and fsynced before durable count/delivered increase and queue insertion. A subsequent queue failure leaves the durable row retained. Draining the queue does not restore the session's record allowance.

Thus 2,048 is a **finite session-work/exposure guard**: it bounds write/fsync count, downstream row processing and retained history size indirectly. There is no measured derivation making 2,048 a venue-supported capacity or a sufficient standalone RAM bound. The independent queue bounds are 48 expanded objects / 4 MiB, with expanded-object accounting; they limit pending work rather than accumulated history. One book row includes its two side packets, but remains one logical ingress row.

Today each logical ingress row maps to one physical hash-chain line in both encodings. Compression changes bytes, not observations or counts. Batching multiple observations into one line cannot manufacture logical headroom. The terminal line bypasses ingress and consumes the separate **4,096 physical journal records / 32 MiB** limit. D2 reserves 64 records / 64 KiB for shutdown, stopping ordinary work at 4,032 journal records or the reserved byte boundary. These are different protections, not an extra 2,048 usable ingress slots.

Replay materializes the whole journal. Readers allow at most 4,096 rows and 32 MiB cumulative expanded payload; finalization first requires `RSS + 6 × max(journal bytes, expanded bytes) < 256 MiB`. The multiplier is conservative reservation, not a measured object-size formula. It can refuse replay even when compressed bytes and physical count fit. `CaptureQueue`, journal fsync, logical allowance and replay memory therefore cannot substitute for one another. See `transport_session.py:181`, `continuous.py:519`, `coverage_owner.py:109`, `bounds.py:33` and `journal_encoding.py`.

## Actual workload and information content

Source: session `3b9cf13c-0696-4fcb-b643-bdd545d9bbd3`, original chain `abb0baea87f750515618b50d3de13fc298431e8239f7d541da98f0836bf1d592`. It ran 50.904 seconds and reached 64 Kalshi/32 US usable markets. US completeness remains unknown. No duration below is inferred from synthetic repetition.

- **581 native frames:** four Kalshi acknowledgements, 64 snapshots, 337 deltas and 176 US market-data images. Retain every admitted frame, including messages without a retained derived book; do not equate frames with quote updates or silently discard repeats.
- **580 health rows:** ten per-stream changes (five awaiting-snapshot, five connected) and **570 repeated same-state notifications**, comparing group/state/market IDs/gap reason. The repeated state is derivable; its historical ingress identity, observation timestamp, position and context are not identical and must survive any lossless historical representation. Terminal disconnected state is recorded separately. Counts here do not imply unrecorded disconnects or gap transitions.
- **575 book/packet rows:** all distinct full values. Existing native replay reconstructs 400 Kalshi + 175 US books and packets exactly. It uses native frames, selected-market metadata, stream/request context **and the saved book receipt time**; it does not infer that time from the frame. Freshness/invalidation events, derivation version, original row identity/time/order and expected-output hashes would also need explicit retention if full derived values became reconstruction recipes. Exact reconstruction is demonstrated for this capture, not every future protocol version or clock event.

Suppressing duplicate health *notifications before creating future observations* may be a valid explicit producer-policy change. Replacing full derived rows with compact recipes may save more bytes. Neither permits deleting original rows or pretending their logical identities never counted. The following omissions are **optimistic analytical lower bounds, not implemented encodings or admitted capacity**:

| Saved-workload view | Logical ingress rows | Physical lines including terminal | Encoded ingress bytes | Expanded ingress bytes |
|---|---:|---:|---:|---:|
| Actual lossless encoding | 1,914 | 1,915 | 4,635,301 | 16,770,735 |
| Omit 570 repeated health rows, hypothetically | 1,344 | 1,345 | 4,309,601 | 16,288,153 |
| Also omit 575 derived book rows, hypothetically | 769 | 770 | 1,674,853 | 4,916,853 |

The lower bounds exclude required reconstruction/identity metadata, so they are not lossless results. A lossless recipe retaining one logical identity per row still has 1,914 observations. Native evidence and control inputs alone continue growing indefinitely.

Actual encoded journal bytes including wrappers/terminal: **4,948,000**; expanded payload including terminal: **16,771,400**. Python retained size of the decoded row list measured **53,058,673 bytes** (excluding interpreter, replay engines and other live state). Prior measured writer/reopen process peak was **186,400,768 bytes**; compression did not make RAM usage 4.64 MB.

## Pressure and choices

Explicit arithmetic repetitions of the original admitted rows—not additional market history—give:

| Copies | Logical ingress / physical lines with one terminal | Encoded ingress | Expanded ingress | Six-times replay reservation, before RSS |
|---|---:|---:|---:|---:|
| 1 | 1,914 / 1,915 | 4,635,301 | 16,770,735 | 100,624,410 |
| 2 | 3,828 / 3,829 | 9,270,602 | 33,541,470 | 201,248,820 |
| 4 | 7,656 / 7,657 | 18,541,204 | 67,082,940 | 402,497,640 |

The existing writer pressure check reaches 2,048 logical rows after 134 additional repeated rows at only 4,955,774 encoded bytes. There is no honest 90-second active-market prediction. With a hypothetical 4,096 logical allowance, two copies fit the encoded-byte and physical-record limits, but adding the observed collection RSS of 131,710,976 to the replay reservation exceeds 256 MiB. Two copies nearly exhaust the expanded-reader limit too. Four copies violate multiple bounds. No such policy change was applied.

| Path | Benefit and effort | Decision |
|---|---|---|
| Minimal lossless representation under existing logical limits | Low/moderate effort; reduces bytes, preserves 1,914 identities. Health/derived recipes require clock/version/dependency handling. | Useful optional optimization, insufficient sustained capacity; not the next slice. |
| Explicit finite capacity-policy increase | Small counter edit but substantial requalification: replay memory, expanded reader, fsync/queue pressure, output/disk and terminal handling must all agree. Measured 2× pressure already challenges RSS. | Reject as the primary delivery direction; only an explicitly bounded future test policy, never a silent live change. |
| Minimum D3 segments + incremental replay | Moderate work in existing journal/owner; bounds retained replay working set while preserving every observation and cumulative accounting. Requires deliberate rotation/crash semantics and disk policy. | **Recommended D3a**, ahead of sustained D2. No new database or collector framework. |

Segmentation alone must **not reset** the existing D2 lifetime allowance. Keep legacy D2 mode unchanged; introduce a separately named, initially offline-only segmented mode with explicit run-wide accounting/policy. Daily use ultimately also requires explicit handling of the pilot's 100 REST-attempt totals, per-group 600-message and connection budgets, disk growth and supervised session lifetime. These remain unchanged now. Exhausting finite caps after a rotation is not continuous operation.

## Recovery findings

An isolated copy was reverse-patched to the pre-encoding candidate and verified against **all 181 original source hashes**, identity `d42c27b914996c4f05376aaf3a1982998677e34211545550d95c345ec7bf0481`. Both `ReadOnlySurface` tests fail identically there and on the current candidate: one failure and one error. Original recovery indexes bind device `16777234`; the unchanged files are now on `16777233`. Other source signature fields/content hashes and verified prefix fields match. This is environmental identity drift, not an encoding regression; no identity protection or index was changed. **The prior full suite remains 92/94, not passing.**

Fresh isolated fixtures on device `16777233` pass both old and new encoding recovery: 42 identical logical rows, interrupted-prefix inspection, new index/reopen, exact replay of six native books plus two health-derived books/16 packets, preservation of the injected rejected-frame gap, torn-tail exclusion and rejection after the indexed source changes. The same synthetic input was used for both formats. This demonstrates format recovery on current filesystem identity without legitimizing or rewriting old indexes.

## Next slice and completion criteria

Implement **D3a bounded segmented journal and incremental exact replay, offline only**, using the [next implementation prompt](data-coverage-d3a-prompt.md). D3 outcomes, settlements, backfill, retention deletion and dashboard expansion stay deferred.

Acceptance requires: explicit per-segment and cumulative logical/physical/encoded/expanded accounting; crash-safe manifests and rotation; fail-closed missing/reordered/corrupt segments; no counter reset granting legacy D2 more capacity; original journal compatibility; all 575 original books/packets and saved calculations exact across boundaries; bounded-memory replay measured across multiple segments; injected partial-write/rotation/Stop recovery and empty final queues; preservation of original evidence and identity checks. Pressure must test busy saved observations, not just a quiet timer fixture.

Keep the remaining **D2 control checks** distinct: coherent first refresh and active manual Stop are still live-unverified on the repaired candidate. The quiet localhost 90-second check is offline lifecycle evidence only. A later separately authorized finite control pilot may use an explicitly declared smaller inventory or approved policy, with its coverage limitation reported; it need not pretend to qualify daily throughput. No new pilot is requested or authorized here.

[Assessment evidence](../evidence/d2-coverage/record-capacity-decision-20260916/workload-analysis.json) · [pre-encoding identity](../evidence/d2-coverage/record-capacity-decision-20260916/preencoding-identity.json) · [fresh recovery](../evidence/d2-coverage/record-capacity-decision-20260916/fresh-recovery.json). Scripts and both legacy-test logs are retained alongside these files. Production source identity and original evidence preservation are recorded in `verification.json` in that directory.
