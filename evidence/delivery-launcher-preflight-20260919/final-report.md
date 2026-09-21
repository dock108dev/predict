# PASS — integrated offline direct-Stop qualification

September 19, 2026 local time. The owner authorized bounded repair and continuation after the preserved preflight failure. Exactly one major attempt ran; it is consumed. No replacement, reset, live feed, real credential lookup, external DNS/connection, beta restart, budget increase, commit, push or publication occurred.

- Executable candidate: `8aae112d9af82cf30662eb4030c52998c50ac60783f544b3aec725289da0802f` ([manifest](revised-candidate.json)).
- Source identity: `4bc0a48bcdcd7b62dcf3b09944900e76261a115227bb7b3cd7f9c8e21b7c4dc4`.
- Unchanged spec: `e7427b51b8594af05260cb2e17d2d62f1d07503dc18c3d38584d0261b691002a`.
- Attempt: `f72e404a-91e6-4fcf-8159-cfe562727346`.
- [Revised envelope](revised-envelope.json), [repair and authorization](repair-and-run.md), [approval](../delivery-launcher-offline-20260919/offline-approval.json), [qualification audit](qualification-audit.log), [measured result](timed-result.json), [retained attempt](../delivery-launcher-offline-20260919/proposed-timed-direct/launcher-result.json).

## Observed gates

| Gate | Result |
|---|---|
| Candidate/runtime/spec | Exact revised manifest verified before Start and after audit; 105 guarded checks passed |
| Fixture origin | Start +0.448133 seconds; retained independently from Start |
| Refresh | First refresh request +120.003164s; selection completed +120.531609s |
| Scheduled direct Stop | Sent +240.009759s; intake closed +240.027793s; latency 18.03ms |
| Cleanup/finalization | Cleanup 1.96ms; finalization through report 4.710615s; outer completion +244.827935s |
| Independent protection | Watchdog armed before collection; scheduled-Stop notification observed; no cutoff/failure fired. Revised-candidate short process tests passed blocked-loop/control/finalizer, liveness and TERM/KILL gates. No second 300-second cutoff experiment |
| Server/request accounting | 18 successful HTTP requests: 4 initial, 2 refresh, 12 references; one WS. Server path/query/order/time equals client ledger; no server HTTP after closure |
| Reference slots | 12 attempted, +120 skipped for refresh priority, +255/+270/+285 not reached; all 16 reconciled |
| Replay/drain | 1,447 raw frames /298,295 body bytes; 1,446 qualifying books equal at every stage; 13,123 received=accepted=durable=drained; zero rejected/pending/unresolved/durable-not-queued |
| Collector memory | 78,430,208 bytes (74.80 MiB) through report; warm matched one-market RSS growth 0.25 MiB |
| State/queue | Live state 14,845 bytes; replay traced state 52,516 bytes; queue peak 1 object/5,360 bytes |
| Helpers | Launcher 64.91 MiB; watchdog 62.41 MiB; worker includes in-process fixture. Audit 63.89 MiB/7.382s; combined run CPU 37.573s |
| Output/writes | 8,679,989 retained bytes including marker; 8,718,246 cumulative application writes; helper 103,397 bytes, included once |
| Headroom | Minimum frozen headroom 79.98%; minimum diagnostic headroom 34.385%; all required margins pass |
| Ownership | Service exited, control socket removed, ownership flock available, original marker retained consumed |

The read-only documented audit exited 0 and independently replayed the full new history. Original-input math checks and original retained replay passed. The fixture telemetry is bounded to 32 KiB/98 observations and counts within existing helper/output/write reservations. All 2,824 preexisting evidence files remain unchanged; [preservation result](preservation-result.json). Total two-pass preservation input was 3,749,352,388 bytes, below 4 GiB. Streaming preservation peak was 24.73 MiB. The initial preflight failure and 266.77 MiB whole-file preservation-helper failure are retained; the repaired qualification does not erase or relabel them.

## Limits and next action

PASS applies only to this revised executable and one-market offline workload. The earlier candidate `724bcda6…` remains mock-verified only. The collector receipt excludes its own creation and the later fixture telemetry write from its memory/timing boundary; helper bytes are included in outer accounting. Process-lifetime worker RSS through final exit is not claimed. The direct run did not reach the +300 cutoff; independent protection is established by the armed integration and exact-candidate short fault tests, not a new timed cutoff measurement.

No live readiness, owner acceptance, uninterrupted delivery, temporally ordered missed exchange changes or sustained/all-market capacity claim follows. Live Keychain/TLS/account/depth20/eligibility and current production idle checks remain unverified; US completeness, Short depth, D2/full D3 and both separate device-identity findings remain unresolved.

One next action: engineering review of this exact passing evidence and preparation of a separately bounded live proposal if warranted. Any live attempt still requires separate explicit authorization. No decision is needed to complete the authorized offline task.
