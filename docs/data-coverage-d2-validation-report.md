# D2 repaired-candidate validation — partial; D2 incomplete

September 16, 2026. The single authorized attempt demonstrated US embedded subscriptions, then stopped at the unchanged serialized-ingress ceiling after **50.904 seconds**. It ended before the first scheduled refresh and direct Stop deadline. **No second attempt ran.**

## Identity and preflight

Session: `3b9cf13c-0696-4fcb-b643-bdd545d9bbd3`.
Candidate source-map SHA-256: `d42c27b914996c4f05376aaf3a1982998677e34211545550d95c345ec7bf0481`.
All **181 source hashes** matched the [offline verification](../evidence/d2-coverage/offline-repair-20260916/verification.json), before and after; no code differences or affected checks to rerun. Reused the recorded 75-test suite and final 20 affected checks. No application code was changed.

Beta idle/cleanup, absence of venue sockets and shared lock availability were confirmed before restart. A first launcher invocation resolved the virtual-environment interpreter symlink incorrectly and exited with a missing dependency **before Start**. The launcher path was corrected; the new beta was then verified idle, Start available and no previous session loaded. The earlier provisional idle sample was from the exiting old process and is not the loaded-candidate proof; `loaded-idle-verified.json` is authoritative. No credentials or venue requests occurred during this setup.

The new attempt uses the existing owner mechanism and shared lock symlink. Consumed attempts remain intact. An independent local control recorded a monotonic clock before the sole Start and prepared the specified Stop request for 90 seconds.

## Actual coverage

| Measure | Kalshi | Polymarket US |
|---|---:|---:|
| Independently retained events | 32 | 32 |
| Retained markets | 64 | 32 embedded |
| Eligible / selected / requested | 64 / 64 / 64 | 32 / 32 / 32 |
| Ever acknowledged / receiving / usable | 64 / 64 / 64 | 32 / 32 / 32 |
| Peak simultaneous usable | 64 | 32 |
| Usable after finalization | 0 | 0 |
| REST attempted / received / durable | 35 / 35 / 35 | 39 / 39 / 39 |
| Connection attempts | 4 | 1 |

Event traversals exhausted their filtered open/active queries. Kalshi market queries exhausted for all 32 retained events. US separate market queries again returned empty lists for all 32 game IDs; embedded listings stayed visible and every event correctly reported `contradictory_listings`. **US market completeness remains unestablished: 32 is a known observed inventory, not the full venue denominator.** All 32 sufficiently evidenced listings progressed through subscription stages. US acknowledgement means a valid current-request market image, not a separate acknowledgement frame. Kalshi used explicit channel acknowledgements.

No retained market was excluded by type, state, identity or kickoff margin. All observed eligible market IDs were selected; hidden/unopened or otherwise filtered-out counts remain unknown. US has 32 supported Long and 32 unsupported Short sides; Short purchase depth remains unavailable. Event matching does not prove contract/settlement equivalence.

## Generation, timing and Stop

Start request: **17:02:43.666221 UTC**, monotonic `44653.828327541`; HTTP 200 response **17:02:43.771650 UTC**. Journal began **17:02:43.770970 UTC**. Initial generation 1 completed at **17:03:11.005909 UTC**; both producers applied generation 1. Status kept its denominator, plan and applied generation distinct, with increasing age. Final report age was 24.164 seconds. No second generation or partial refresh occurred: the cap stopped collection before the 60-second refresh. Coherent *refresh* publication on this candidate therefore remains live-unverified; offline interrupted-traversal evidence is retained.

Terminal journal receipt: **17:03:34.582383 UTC**. Start-to-feed-cleanup duration: **50.903776 seconds**. Independent control observed fully inactive status at **17:03:36.311047 UTC**, 52.644 seconds after its Start clock, and canceled its pending Stop action.

**Manual Stop unverified. Stop request and response timestamps: none.** The early `session_ingress_cap` stop occurred before 90 seconds; no post-hoc Stop was presented as a successful active-collector test. No run was extended, and no transition/disconnect was forced.

## Resources, replay and finalization

Serialized ingress: **16,770,735 / 16,777,216 bytes**. Of 1,915 received ingress records, **1,914 were accepted and durably acknowledged; one was rejected**, zero unresolved, zero queue pending. All HTTP responses were retained; the rejection occurred later in streaming. Upstream lost-update totals remain unknown.

Journal: **1,915 records including terminal / 17,083,545 bytes**; finalized session directory **18,210,632 bytes**. Queue peak **14 records / 550,599 bytes**. Sampled collection RSS peak **131,710,976 bytes**; post-finalization high-water **188,104,704 bytes**, below 256 MiB. Native bytes charged: Kalshi **713,147**, US **909,762**. Five total sockets/attempts, zero added spend; no resource ceiling changed.

Exact replay passed for **400 Kalshi + 175 US books and quote packets**, with no reported native replay sequence gaps. Native frames retained: 405 Kalshi, 176 US. Receipt intervals among repeated recent book observations: Kalshi median **0.019797 s**, maximum **21.877292 s**; US median **1.588887 s**, maximum **20.423013 s**. These describe this capture, not delivery guarantees. All 64 initial Kalshi snapshots lacked source timestamps; US recorded 32 first and 143 advancing source times. Native observations, timestamps, health and calculation inputs remain in the journal.

Both feeds are disconnected, cleanup has no errors, collector and finalizer are inactive, journal terminal acknowledgement and manifest hashes validate, shared lock is released and usable books are zero. Only the beta's loopback listener remains. The beta is quiescent (`state=stopped`, `active=false`, Start disabled by the consumed attempt), with no autoresume. No additional restart was needed.

## Evidence, carry-forward and next task

[Attempt audit](../evidence/d2-coverage/validation-20260916T170132Z-2cbe6460/audit.json) · [control timestamps](../evidence/d2-coverage/validation-20260916T170132Z-2cbe6460/control.jsonl) · [pilot manifest](../evidence/d2-coverage/validation-20260916T170132Z-2cbe6460/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3/manifest.json). Journal chain: `abb0baea87f750515618b50d3de13fc298431e8239f7d541da98f0836bf1d592`. All **1,838 preexisting evidence files** match their preflight hashes.

Prior Kalshi coverage and browser independence remain attached to session `97dbc1e0-36c7-49c8-a19b-f4856278e21c`, source-map identity `528162c35fee86d31a473d38c091fc73346f802e1026a12759164d0c30e3069b`, and its [replacement report](data-coverage-d2-replacement-report.md). Browser closure was not repeated or attributed to this candidate.

**D2 remains incomplete:** repaired US subscriptions now have live evidence, but repaired refresh publication and active manual Stop do not. Next concrete task: use this saved journal offline to identify and test a minimal reduction in redundant serialized payloads while preserving native inputs, exact replay/math and every existing ceiling. Do not implement D3 or run another pilot automatically; any later finite validation requires separate authorization. No database, new feeds, paid access, scheduling, trading, commit, push or publishing occurred.
