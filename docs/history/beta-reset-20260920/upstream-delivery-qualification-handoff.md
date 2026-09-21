# Kalshi diagnostic qualification handoff

September 19, 2026. **PASS: one integrated offline timed direct-Stop qualification on the revised candidate. No live readiness or sustained-capacity claim.**

## Current qualification — PASS on revised candidate

[Final report](../evidence/delivery-launcher-preflight-20260919/final-report.md) · [audit](../evidence/delivery-launcher-preflight-20260919/qualification-audit.log) · [measurements](../evidence/delivery-launcher-preflight-20260919/timed-result.json). The owner authorized the telemetry repair and continuation; the original failed preflight remains historical below. Complete executable `8aae112d9af82cf30662eb4030c52998c50ac60783f544b3aec725289da0802f`, source `4bc0a48bcdcd7b62dcf3b09944900e76261a115227bb7b3cd7f9c8e21b7c4dc4`, unchanged spec `e7427b51b8594af05260cb2e17d2d62f1d07503dc18c3d38584d0261b691002a`, attempt `f72e404a-91e6-4fcf-8159-cfe562727346`. The [revised envelope](../evidence/delivery-launcher-preflight-20260919/revised-envelope.json) supersedes only the original candidate binding; all budgets and one-run limits remain unchanged.

105 guarded checks passed, then exactly one timed Start and the documented qualification audit passed. Refresh +120.003s, intake closure +240.028s, Stop latency 18.03ms, cleanup 1.96ms, finalization 4.711s. Collector peak 74.80 MiB; warm growth 0.25 MiB; minimum frozen/diagnostic headroom 79.98%/34.385%. All 18 server HTTP requests and one WS reconcile; 1,446 books replay exactly; no unresolved work. Retained output 8,679,989 bytes; cumulative writes 8,718,246. Independent watchdog armed and exact-candidate short fault checks pass; no full cutoff repeat occurred. Ownership released, service exited and marker remains consumed. All 2,824 original evidence files are unchanged. The earlier preservation-helper memory failure remains recorded; streaming verification passed.

**One next action — engineering:** review the exact passing evidence and prepare a separately bounded live proposal if warranted. No further offline run or user decision is needed for this task. Live execution still needs separate authorization. Offline PASS does not establish live readiness, sustained capacity, D2/full D3, or actual upstream delivery completeness. No beta restart, live access, reset, budget increase, commit, push or publication occurred.

## Historical initial preflight — repaired before the sole Start

The owner authorized exactly the frozen offline attempt. [Preflight report](../evidence/delivery-launcher-preflight-20260919/report.md) and [machine-readable result](../evidence/delivery-launcher-preflight-20260919/preflight-result.json) record exact identity reconciliation and the first failed prerequisite. All 255 executable files, 244 source/test files, runtime/dependencies, Git identity and spec match. Attempt `f72e404a-91e6-4fcf-8159-cfe562727346` remains unused; output/ownership/control socket were absent. No approval activation, serve, Start or timed audit occurred.

The frozen fixture does not retain its origin/Start offset or server-observed request evidence required below. These values remain in worker memory and are not exported or checked by the auditor. Running now cannot meet the documented retention gate. Separately, the closeout preservation helper peaked at 266.77 MiB, exceeding its 256 MiB ceiling; this is not collector RSS. No timed measurements exist. Earlier mock evidence remains unchanged; offline qualification, live readiness and sustained capacity are not established.

**One next action — owner:** authorize bounded fixture telemetry and auditor repair within unchanged joint budgets, followed by refreeze/review before any timed Start. Subsequent preservation hashing must stream files. The proposed envelope and historical evidence below remain unchanged; their earlier ready-for-review language is superseded by this failed prerequisite.

## Original frozen candidate — superseded by authorized telemetry repair

- Complete executable identity: **`724bcda648338cfbd8e83be347437b295dd006c3aeebee5f6e18bee29cf47249`**, [255-file manifest plus runtime/configuration/Git identity](../evidence/delivery-launcher-offline-20260919/executable-candidate-final.json).
- Source/test identity: **`407a0b5a0398647e2c00f6c7fd59fff3789d722849420b549026c77442b1257c`**, [244 files](../evidence/delivery-launcher-offline-20260919/source-candidate-final.json).
- Exact proposed offline spec: **`e7427b51b8594af05260cb2e17d2d62f1d07503dc18c3d38584d0261b691002a`**, [spec](../evidence/delivery-launcher-offline-20260919/proposed-spec.json).
- HEAD remains `edad00dd980cc8535d69a815d1199b82dd0e83cb` plus preserved uncommitted work. No commit/push occurred. All required executable changes are frozen before any proposed timed run.

Starting source matched all237 hashes of `63f5510b768065130bbb6b645dc6b8fc8bb5afb4ee2623d07a63a41a075d654c`. The preceding review, detailed final-delta analysis and implementation contract are retained verbatim in [the prior handoff](../evidence/delivery-launcher-offline-20260919/qualification-handoff-before.md). Its missing-launcher next action is superseded by this completed implementation. Earlier provisional manifests in the new directory are preserved; only `executable-candidate-final.json` and `source-candidate-final.json` are current.

[Preservation verification](../evidence/delivery-launcher-offline-20260919/preservation-final.json) confirms all2,739 prior evidence files and the original tracked diff are unchanged; only the authorized diagnostic modules, new launcher/tests and current handoff/report/tracker were changed or added.

## Implemented binding and remaining verification

The dedicated `app.collection.delivery_live` command has idle serving/status, explicit Start, idempotent Stop, and no reset. Serving, Start and worker entry verify the supplied complete manifest/spec. Start requires a separate approval bound to mode, exact candidate, spec and UUID. The worker's emitted session spec must also match before discovery is scheduled. Neither serving nor status loads credentials or starts transport.

Real mode is fixed to `/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/d2-coverage/collector.lock`; alternate production roots are rejected. Start acquires the flock and writes/fsyncs an exclusive marker binding candidate/spec/output/approval before the armed worker loads credentials. Parent and worker share the owned lock description. Failed Start, crash, changed output and duplicate/concurrent Start cannot restore the allowance. Offline mode uses separate disposable roots and rejects the production root.

The worker loads only `keychain:prediction-arb.kalshi.production/market-data`, then injects the Kalshi credential into the native transport. It does not use `venue_access.load_credentials()` or the two-venue validator. Native destinations stay `https://external-api.kalshi.com` and `wss://external-api-ws.kalshi.com/trade-api/ws/v2`. GET surface is limited to `/trade-api/v2/account/limits`, `/trade-api/v2/account/endpoint_costs`, bounded KXNFLGAME/open/milestones `/trade-api/v2/events`, bounded `/trade-api/v2/markets` for discovered eligible event tickers, and the URL-quoted selected ticker's `/orderbook?depth=20`. No proxies/redirects, hidden GET retries, reference retries or replacement WS attempts. Explicit discovery retries remain charged and bounded; 429/access failures end the attempt.

The new independent watchdog is armed before credential/discovery work and uses explicit Start clocks. Scheduled +240 Stop goes through the same handler as owner Stop; +300 intake cutoff remains independent of blocked worker/control loops, with closure+300 finalization cutoff and TERM/one-second/KILL escalation. Failed initialization and supervisor loss fail closed. Intake closure alone does not extend the deadline while transport cleanup remains blocked. Helpers/marker/early failures are reserved inside existing budgets; outer accounting preserves the collector receipt's original measurement boundary. Real observations retain real provenance; fixtures remain synthetic and real histories reject synthetic authority.

**104 distinct checks pass**, including33 launcher checks and the existing49 diagnostic,17 regression, one retained and four saved-math checks. Actual short process checks establish the new supervisor binding, blocked-loop termination, escalation, finalizer/control/supervisor-loss behavior. The whole final launcher suite was29.975 seconds; all suites were within their180-second/256 MiB bounds, with retained exactness within60 seconds. No full-suite, live-access or real-duration qualification claim follows.

## Requirements to evidence

| Requirement | Covered by final offline evidence | Remaining gap / closure |
|---|---|---|
| Approved executable/spec identity | Complete manifest; serve/Start/worker rechecks; explicit generated-spec equality; mismatch negatives | Reverify exact files/runtime/spec at the proposed timed Start and audit |
| Kalshi-only credentials and destinations | Exactly permitted fake lookup after marker; zero US access; sanitized failures; native host/path/query/signature and redirect/proxy checks | Actual Keychain, authenticated TLS/access/account/depth20 contract remain later-live unknowns |
| Shared ownership/one shot | Lock conflict, duplicate/concurrent/failed Start, crash, changed output, marker reuse; production-root guard | Future real preflight must verify stopped beta/other collectors and exclusive owner; do not restart beta |
| Stop and post-Stop receive guard | Same control handler, real Unix controls, pending HTTP cancellation, retained ready-receive rejection without parsing/coverage/freshness mutation | One integrated real-duration +240 direct Stop with closure/drain timings |
| Independent supervisor | Short actual blocked-process TERM/KILL, control EOF, stalled control/finalizer, parent death/watchdog loss; exact deadline boundary checks | No five-minute measurement of this new watchdog; short checks establish the binding, not sustained resources |
| No implicit retry; exact accounting | Fresh and reused disconnected connections each one server request; charged discovery retry and fatal reference; append-only helper writes | Integrated final-candidate request/body/slot and joint write/output audit |
| Reference identity and provenance | Begin/end path/query/depth/ID/lineage negatives, quoted ticker, correct observation/synthetic parsing and authority rejection | Recheck generated comparisons in integrated replay; REST exchange-time uncertainty remains unresolved |
| Replay and original math |575-book exactness, four saved-math checks; old direct-analysis deterministic fields unchanged | New complete history replay, independent memory assessment and full qualification audit |
| Resource/finalization bounds | Existing boundary checks; short lifecycle receipt, helper/marker accounting; unchanged PROFILE/CAP | One final-candidate timed workload must demonstrate frozen headroom, cleanup and finalization targets |

## Prior timed runs remain historical

The direct timed run belongs to `3601a26697b27172d924552f883b0d7800d027e41ef848182174da196d5ee89f`: intake closed240.046677s, Stop latency10.94ms, subsequent cleanup2.74ms,1,447 reconciled books,18 REST attempts,67MiB collector peak. It predates the ready-receive guard, implicit-retry suppression and reference-path analyzer checks. Its observations remain valid for that revision only.

The forced-cutoff run belongs to `2bb98f5bef358ced807ff1048af46b8d7debc9327e74cf75066149875720eb75`: termination300.019916s, exit-15, ownership released and marker preserved. It includes the receive guard but predates final retry/path changes. Its incomplete suffix, lifetime RSS and cumulative writes remain unknown. It neither proves successful direct Stop nor qualifies this new launcher/watchdog. [Original final audit](../evidence/upstream-diagnostic-offline-20260919/run-audit-final.json).

Historical attempts `261c39b2-8362-4f31-ae55-e8f9037f77ae` and `ed437dd3-c78a-4a1c-a68a-86e3b7ec21cc` stay consumed. No old run is relabelled. The stronger new parent-liveness/initialization binding is covered by new short process checks, not inferred from old timed evidence. Nominal deadline and TERM/KILL limits are unchanged. No automatic full cutoff repeat is proposed. A future change to those semantics, failed binding check, or unresolved termination gap requires a revised scope before adding any run.

## Populated offline envelope — proposal only

[Machine-readable envelope and exact commands](../evidence/delivery-launcher-offline-20260919/qualification-envelope.json). **One newly reviewed major direct-Stop attempt; no spare/replacement run.** Its purpose is final integrated elapsed-time scheduling, +120 refresh, +240 private-control Stop, complete cleanup/finalization and joint resource headroom. Short mocks cannot establish those real-duration properties. A second full cutoff run is not automatically warranted by the final analyzer/retry changes or the now-demonstrated process binding.

Proposed UUID: **`f72e404a-91e6-4fcf-8159-cfe562727346`**.

Proposed output: `/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/delivery-launcher-offline-20260919/proposed-timed-direct`.

Proposed offline ownership root: `/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/delivery-launcher-offline-20260919/proposed-timed-ownership`.

Neither directory nor a consumed marker has been created. [Approval template](../evidence/delivery-launcher-offline-20260919/approval-template-final.json) has `approved:false`; it cannot authorize Start. After separate review, an explicit matching approval would be retained as `offline-approval.json`. No live approval is requested.

| Envelope item | Exact scope |
|---|---|
| Prerequisites | Final candidate/spec hashes above;104 checks passed; exact runtime/dependencies and source reverified; new exclusive output/UUID; separate offline approval. Any changed source/test/spec/fixture/auditor/runtime must be refrozen and reviewed before Start. |
| Workload | `tests.delivery_launcher_fixture.Runtime` → `tests.delivery_fixture.Server(busy=True)`: one `KXNFLGAME-FIXTURE-DET` market, kickoff fixture-creation+2 hours; actual paced loopback HTTP/WS;4 initial REST attempts including2 account lookups,2 refresh attempts at+120; acknowledgment/snapshot then8 snapshots per active second, alternating quantities, quiet fixture interval[55,110). Preserve fixture-origin/Start offset rather than inventing alignment. No real secrets or external DNS/connections. |
| References | Slots+60,+75,…,+285; refresh priority at+120; no overlap/catch-up; at most16 references/96 total attempts,40/40 discovery and44/52 generation ceilings. +240 can race Stop, but no request starts after intake closure. Do not demand an old run's exact slot counts when valid scheduling differs. |
| Duration | One Start; scheduled direct Stop+240; independent intake cutoff+300; finalization≤300 seconds from closure, qualification target≤240; whole run≤660 wall/600 CPU seconds. Each short process check≤30 seconds; focused suites≤180 seconds/256 MiB RSS; retained exactness≤60 seconds/64 MiB output. |
| Frozen limits | Every value in [frozen budgets](../evidence/supervised-5m-20260916/frozen-budgets.md), PROFILE and CAP is unchanged. RSS intake stop224 MiB/hard256; preflight below192; free disk≥1 GiB plus conservative224 MiB output reservation. Existing catalog, body, row, rolling-rate, segment, queue/state, diagnostic ring, identity spool and manifest caps apply jointly. |
| Diagnostic limits |4,096 frames;256 KiB/body; primary8 MiB/HTTP24 MiB with pending reservations;20,000 logical/20,257 physical rows; ingress64 MiB encoded/192 expanded; journals72 MiB/200 expanded;128 segments. Output120 MiB=72 journal+16 routine+32 finalization; routine includes8 MiB collector metadata/spool and8 MiB helper/control/marker. Writes160 MiB=128 before finalization+32 reserved. No extra harness allowance outside the joint caps. |
| Qualification margins | RSS≤192 MiB; live/replay state≤48 MiB; queue≤24 objects/2 MiB; matched-cardinality post-warmup RSS growth≤8 MiB;≥25% spare against frozen logical/frame/encoded/expanded/output ceilings. Report diagnostic headroom separately. Helpers separately measured, each≤256 MiB. Workload must exceed2× retained one-market62-frame/18,360-byte basis; no all-market or sustained-capacity inference. |
| Retention | All new task artifacts≤1 GiB; preservation hashing≤4 GiB input. Preserve failed and partial results. Record unknown interrupted cumulative writes/lifetime memory honestly. Receipt creation remains outside its own timing/RSS boundary and counted once in bytes. |

Future commands, **only after separate offline approval**, from `/Users/michaelfuscoletti/Desktop/prediction-arb`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m app.collection.delivery_live serve --spec evidence/delivery-launcher-offline-20260919/proposed-spec.json --candidate evidence/delivery-launcher-offline-20260919/executable-candidate-final.json --approval evidence/delivery-launcher-offline-20260919/offline-approval.json
```

The service remains idle. In a separate control invocation, explicit Start would be:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m app.collection.delivery_live start --spec evidence/delivery-launcher-offline-20260919/proposed-spec.json
```

Use the same command with `status` or `stop` for private controls. Scheduled Stop is issued by the launcher at+240. After completion, the read-only full qualification audit is:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m tests.delivery_launcher_audit evidence/delivery-launcher-offline-20260919/proposed-timed-direct --qualification
```

The envelope JSON contains absolute commands. A future audit result must be retained in a new bounded artifact; never overwrite an old report. Do not redirect unbounded console output into an unaccounted sidecar.

Stop at the first failed prerequisite, test, resource/account/identity/eligibility/reference/sequence/retention/control gate. A forced cutoff in the major direct run is a direct-Stop qualification failure. No threshold increase, extension, marker reset, second market, reconnect, replacement output or automatic new attempt. Preserve failure evidence, make a bounded repair, refreeze and return for scope review before another attempt.

Retain exact manifests/spec/runtime/approval/marker, control and clock events, selected identity/exclusions, raw bytes/hashes and stage lineage, server-observed requests, request/slot/body ledgers, segments/terminal hashes, replay/identity results, resource samples, cleanup state, receipt and outer accounting. Require received=accepted+rejected, accepted=durable=drained, zero pending/unresolved/durable-not-queued; reconcile control/qualifying/shutdown-rejected frames separately. Reference attempts=success+failure+cancelled; all16 slots=attempted+skipped+not-reached. No post-Stop primary admission or new HTTP request. Preserve original-input math and evidence.

## Conditional live handoff remains later

Only after successful exact-candidate timed qualification and engineering review may a later proposal bind an actual real-mode spec/candidate, approval, new UUID/output, operator, production lock and credential reference. Current real credentials, native TLS/access, account-cost usability, depth20 response contract and deterministic market eligibility remain unverified. Verify these only through counted startup/reference requests inside an independently authorized live attempt, never an extra probe. Verify current beta/collector idle state before that attempt; do not restart beta. No live authorization is requested now.

The later scope remains one deterministic Kalshi NFL pregame full-game winner market, kickoff later than Start+600 seconds, kickoff/ticker sort, one WS attempt/subscription, no reconnect/replacement, startup by+60, safety refresh+120, at most16 references/96 total REST attempts, direct Stop+240 and independent intake cutoff+300, all frozen limits and diagnostic subcaps, and offline finalization≤300 seconds. No US, paid feed, trading or ranking integration.

Ordinary REST cannot prove uninterrupted delivery or a temporally ordered missed exchange change. Conclusions remain sampled returned-state consistency/disagreement and demonstrated local processing boundaries; no positive finding is required. US completeness, unsupported Short depth, sustained capacity, D2/full D3 and both separate device-identity findings stay unresolved.

**Who acts next:** engineering reviews the revised candidate’s passing offline evidence and prepares a separately bounded live proposal if warranted. No additional execution is authorized.
