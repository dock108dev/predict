# D2 journal efficiency — offline repair, live-incomplete

September 16, 2026. A lossless per-record encoding reduces the actual saved workload's serialized ingress by **72.36%**, without dropping or combining observations. **It does not establish readiness for another 90-second live validation:** the unchanged 2,048-record ceiling is now the measured constraint. No live handoff is prepared.

## Measurement and cause

Original session: `3b9cf13c-0696-4fcb-b643-bdd545d9bbd3`, journal chain `abb0baea87f750515618b50d3de13fc298431e8239f7d541da98f0836bf1d592`. The 50.904-second live run admitted 1,914 rows / 16,770,735 serialized bytes before a byte rejection. The terminal row is outside ingress but inside journal accounting.

| Record type | Records | Original payload bytes | Encoded payload bytes |
|---|---:|---:|---:|
| Session start | 1 | 1,862 | 1,259 |
| Discovery HTTP | 74 | 1,139,597 | 521,542 |
| Account budget | 1 | 1,594 | 779 |
| Coverage inventory | 1 | 286,951 | 27,585 |
| Selected market | 96 | 2,128,673 | 349,604 |
| Health | 580 | 490,683 | 331,508 |
| Native frame | 581 | 1,344,716 | 764,742 |
| Book and quote packets | 575 | 11,371,300 | 2,634,748 |
| Terminal | 1 | 665 | 554 |

[Component measurement](../evidence/d2-coverage/journal-efficiency-20260916/measurement.json) breaks every type down by field; [nested components](../evidence/d2-coverage/journal-efficiency-20260916/nested-components.json) identify repeated values. Book objects account for 5,718,479 field bytes and quote packets for 5,428,964. Selected-market objects account for 2,100,289. Across rows, native `json_text` contributes 3,963,462 value bytes, including 1,533,518 identical repeats; packet `raw_b64` contributes 4,283,492, including 2,141,746 identical repeats. These nested categories overlap and must not be added together.

No complete book or packet-list value was identical across observations. Native frames, receipt/source timestamps, IDs, sequence/order, state transitions and calculation inputs remain necessary evidence. Some raw bodies appear again in metadata, reconstructed books and two side packets; normalized structures and JSON keys repeat too. Health rows include repeated connected notifications, but all original identities/timestamps are retained. Expansion is not all waste: independent reconstruction and exact packet comparison remain useful. This repair compresses repeated byte patterns rather than deciding which observations to discard.

## Smallest implemented change

D2 writes `d2-zlib-row-1` envelopes within the existing fsynced hash-chain journal. Each carries the compressed canonical JSON row and declared expanded length. Each observation still has its own journal envelope, original ingress identity, ordering and durable acknowledgement. There are no cross-record references, batches, external dictionaries, sidecar payloads or omitted fields. The chain authenticates the encoded representation; decoding restores the identical original row before existing replay/calculation code sees it.

Serialized ingress counts the entire encoded envelope, including base64 and version/length metadata; journal accounting additionally counts chain wrappers. The 2,048-ingress-record and 4,096-journal-record bounds remain unchanged. The queue still holds/accountably measures expanded objects. All fsync, failure accounting and terminal reserves remain. Replay memory reservation uses the larger of journal bytes and expanded bytes, so compression does not evade its memory check. Readers enforce a 32 MiB cumulative expanded payload bound and reject missing/corrupt/truncated/unknown encodings clearly. Runs exceeding this conservative replay bound remain unverified, rather than claiming successful finalization.

Legacy plain rows remain readable, with their original chain verification. The recovery reader also decodes the explicit new representation before validation; no historical file/index was migrated. General non-D2 writers retain their old representation.

## Before/after and offline checks

The exact original admitted workload was passed through both writers, fsyncing every row. Reopened row lists compare equal, including every timestamp, native body, identity and calculation input. Native replay verifies **400 Kalshi + 175 US books and all corresponding quote packets exactly**. Saved-math regressions pass unchanged.

| Measurement | Original writer | Repaired D2 writer |
|---|---:|---:|
| Serialized ingress bytes | 16,770,735 | 4,635,301 |
| Ingress records | 1,914 | 1,914 |
| Journal bytes, including terminal | 17,083,545 | 4,948,000 |
| Journal records | 1,915 | 1,915 |
| Expanded payload bytes | 16,771,400 | 16,771,400 |
| Local replay wall / CPU seconds | 0.805 / 0.780 | 1.007 / 0.979 |
| Process peak RSS bytes | 185,909,248 | 186,400,768 |
| Synchronous queue peak | 1 row / 758,515 bytes | 1 row / 758,515 bytes |

These resource measurements include materializing the saved capture; they are not live throughput predictions. A clearly labeled repeated-row pressure fixture can admit only **134 additional rows** before the record cap, at **4,955,774 bytes**. It does not generate or claim additional real history, and does not infer an exact future stop time.

A separate **quiet synthetic localhost fixture** exercised actual discovery, subscriptions, scheduled refresh at 60 seconds and direct collector Stop requested at **90.019 seconds**. It finalized at **90.062 seconds** with generation 2, 276 accepted/durable ingress records, 285,519 ingress bytes, 331,220 journal bytes, zero rejected/unresolved/pending writes, and exact replay of 32 fixture books. Peak RSS 83,099,648 bytes; queue 9 rows / 199,650 bytes. It uses 24 synthetic Kalshi/eight synthetic US markets and no sustained update load. Its success establishes lifecycle behavior only, not capacity for the observed live workload.

Focused checks cover row equivalence, old-format/interrupted reads, malformed payloads, byte and logical record rejection, retained terminal capacity, durability failures, queue/resource stops, generation coherence and native/saved-math replay. The full suite ran 94 checks: 92 passed and two legacy-index checks failed. The regression result and the two legacy-index limitations are recorded in [final checks](../evidence/d2-coverage/journal-efficiency-20260916/final-checks.log). Two recovery-surface checks encounter preexisting physical-device identity drift: the indexes record device `16777234`, while these unchanged files now reside on `16777233`. Hash, inode, length, times and all other verified prefix fields match. The identity protection was not weakened and originals were not rewritten. [Drift evidence](../evidence/d2-coverage/journal-efficiency-20260916/legacy-recovery-device-drift.json).

## Identity, boundaries and next task

Candidate source-map SHA-256: `f9c30390d1b91bdf70bbf860772c06a5d95fa2f1e08f7f1dbbefd5fcbedeb072`. All **1861 preexisting evidence files** match their pre-repair hashes.

[Verification and source identity](../evidence/d2-coverage/journal-efficiency-20260916/verification.json) records every candidate hash, previous-source differences and read-only original-evidence comparison. Derived files, scripts and fixture journals are confined to `evidence/d2-coverage/journal-efficiency-20260916/`. The beta was not restarted; no credential access, venue request, pilot, attempt reset, background collector, database change, segmentation, retention/outcomes, trading, commit, push or publishing occurred.

**D2 remains live-incomplete.** Prior usable subscriptions remain historical evidence; repaired refresh and active manual Stop still lack live validation. Existing bounds do not support claiming this workload can reach 90 seconds. Next concrete task is an offline design/test of record-count efficiency with explicit logical-observation versus physical-record accounting, preserving every admitted observation and transition. Do not silently redefine the 2,048-record ceiling, batch around it, or issue another live handoff before that policy and measured capacity are resolved.
