# L01 — ordinary publication and integration record

November 4, 2026. Implemented and integrated in the sole `main` checkout;
uncommitted. The app at `http://127.0.0.1:8783/` now follows ordinary publication
automatically. An explicit historical result URL remains immutable. This closes
the manual-head disconnect; it does not certify complete current source coverage,
native financial support, the L03 ranking rules, or the L04 drawer.

## Ownership and acquisition

`CurrentService` and its existing serialized ingress, native workers and aggregate
scheduler remain the acquisition owners. Native startup restores catalogs and
synchronizes books before admitting current evidence. The aggregate scheduler
restores retained data, checks the account window, reservations, quota, inventory
and next due time, then admits the initial eligible batch. Empty/stale retained
data does not waive a future reserved cycle, source pause, backoff or account hold.
Its configured scope remains NFL, NCAAF, NBA, NCAAB, MLB and NHL; winner, spread and
total; Novig, ProphetX and Pinnacle. Native Kalshi and Polymarket US stream under
the same existing source owners. No page request dispatches provider work.

`OrdinaryOwner` replaces the old `LatestBoardOwner` observation/estimate loops in
the data process. It reuses the existing matching-component partition,
`comparison_snapshot.capture/calculate`, auxiliary worker lifecycle, cancellation,
resource limits and snapshot serialization lock. There is one ordinary worker,
not a second collector or alternate financial formula engine. Scanner and Coverage
retain their existing ownership; Coverage uses its reserved optional thread so
its long census cannot hold the ordinary worker's auxiliary turn.

The old replaceable board/grid/inventory working caches are retired once, under
their publication locks. This reclaimed 196,763,648 physical bytes in the observed
installation. Source rows, raw acquisition retention, manual saved results,
reviews, separately leased original packets and all protected accounting records
are preserved. Existing legacy latest-board routes are no longer the ordinary
comparison contract; L03 must use the routes below.

## Publication identity and replacement

The singleton `comparison_live_head` holds monotonically increasing `generation`,
an immutable root `result_id` and publication facts. The root is an atomic union
of disjoint matching components, each with its exact immutable member result and
captured inputs. A component can have an older capture than another component;
no source row combines one capture's price with another capture's reference or
math. `row.evidence_result_id` identifies its exact member. Root `captured_at` is
assembly time; `row.captured_at`, original source/receipt clocks and member details
are the evidence clocks. Neither root time nor generation grants freshness.

Latest desired work is derived from current offer, contract and event revisions,
the current-row epoch, settings revision, engine/model/policy content hashes and
authority expiry. Missing components and then oldest visits define fair rotation. Each batch
reserves the first slot for that rotation, followed by one recently confirmed
complete component per native source when available. This prevents a full-slate
rotation from expiring every hot native frame without starving API/reference work.
Only one latest component pointer is retained. There is no update-event backlog.
A bounded batch first seals source-only members and a root, then attempts optional
finance and seals another root. Finance exceptions leave source prices readable
and independent components continue; later turns retry the failed component.
Superseded dependencies are withdrawn immediately on reads, even before their
replacement calculation has finished.

Policy identity includes existing engine/observation bindings, snapshot math,
ordinary publication code and the reviewed fee documents. L02 must bind any new
reference/fee authority into this identity and `current_authority`; it must not
introduce a separately scheduled financial publisher.

Automatic compressed inputs/results have a 128 MiB logical cap in addition to
the existing physical SQL cap and rewrite runway. Automatic roots have a
10-second handoff grace starting when superseded (not when assembled), then unreferenced roots/members are pruned. Current
components, the current root and selected evidence remain protected. Automatic
encoding uses gzip level 3; historical decoding also supports the existing LZMA
and gzip formats. At most 32 explicit selection tokens live for two hours each.
Capacity exhaustion refuses additional retention/publication, preserving evidence
and source collection; it never discards protected selections to claim progress.
No automatic provider-body archive is added. Normal VACUUM reuses expired snapshot
and hot acquisition pages every 15 seconds; expensive compaction checks retain
their 60-second cadence so they cannot monopolize the publication lock; existing controlled maintenance/restart handles the
remaining physical guard pressure.

## L05 storage representation amendment

Ordinary roots may now store an ordered manifest of immutable compact member
fragments instead of repeating all list rows. Migration 060 binds each fragment
to its member with a cascading foreign key; existing root membership and selected
leases own retention. The read owner resolves the entire manifest coherently and
returns the same HTTP row/drawer contract. Legacy roots remain readable. Missing
or crossed fragment identities fail closed; no delta chain is followed. Fragment
bytes count against the existing ordinary retention cap. Exact complete selected
inputs/results remain immutable in their original member.

For a new root, the existing single-root lazy reader cache may reuse unchanged
immutable member slices. The reader still verifies every requested member's
presence in the same MVCC frame and decodes new members; a missing cached member
fails closed. Current authority and expiry are evaluated again. No historical
cache or additional cache allowance is introduced. A `cold_decode` timing means
a root-cache miss and may include reused members; it is not an all-content-cold
measurement.

Exact unchanged line groups may reuse validated materialization inside the capture
owner, bound to complete normalized evidence and governing policy/settings/epoch/
control dependencies. Clock eligibility is reassessed without renewing source time;
changed inputs use full validation and optional finance uses the original complete
calculation owner. See the latest [L05 evidence and limits](L05-delivery.md).

## L03 HTTP contract

All reads use a coherent database view and perform presentation/validity checks,
not acquisition or financial calculation. Mutation requests retain the app's
existing same-origin protection. `provider_requests` is always zero here.

| Route | Contract |
| --- | --- |
| `GET /api/comparison-current` | Latest root with existing view/filter/sort/pagination parameters. `group=outcome` supplies the preliminary grouped presentation. Returns `id`, `generation`, opaque `cursor`, `publication`, `assumptions`, counts and rows. No head returns an initializing response. |
| `GET /api/comparison-current/updates?after=CURSOR` | Small notification: `changed`, new `cursor`, `generation`, `result_id`, stored publication facts and `poll_after_ms=2000`. Facts are a committed-work hint, not current readiness; fetch the current read for authoritative validity. |
| `GET /api/comparison-current/selection?id=ROW_ID` | Exact source-row or pair lookup in the current projection. Returns `ready`, `unavailable` or `removed`, row or null, result identity, assumptions, publication and cursor. Never substitutes a different outcome. A ready price can still have unavailable finance: inspect numeric fields and reasons. |
| `POST /api/comparison-current/lease` | Body `{result_id, lease_id?}`. Creates or renews one exact immutable-result token; returns `lease_id`, `result_id`, `lease_seconds=7200`. Renew the same token, do not allocate a token per poll. |
| `GET /api/comparison-snapshot/details?result_id=ROOT&id=ROW&lease_id=TOKEN` | Reads/renews that selected evidence. Returns exact full member row, originals, references, assumptions, clocks and diagnostics, plus root `result_id`, `evidence_result_id` and member `snapshot_id`. |
| `DELETE /api/comparison-current/lease?lease_id=TOKEN` | Releases that token when selection closes. |
| `POST /api/comparison-current/settings` | Body `{expected: PRIOR_SETTINGS_REVISION, assumptions: SETTINGS}`. Compare-and-swap settings; returns pending. The data owner recalculates. Reads withdraw old finance immediately. |
| `GET /api/comparison-snapshot?result_id=ROOT` | Explicit immutable historical result. Existing legacy read retention remains supported; use releasable tokens for the new drawer. |

The current endpoint always follows latest; it does not pin pagination by a
`result_id` query. Each response is coherent, but a later page can have a later
generation. L03 should cancel/reject stale request responses, reset/reconcile
pagination after a new generation and retain stable source/outcome identities.
The opaque cursor includes dependency/control/policy/settings changes and expiry
boundaries, so it can change without a new root generation. It excludes heartbeat
and read timestamps. Poll at two seconds, at most one outstanding request per
viewer; pause hidden-page polling and re-read after reconnect. After an overdue
boundary the cursor advances in two-second buckets until replacement, ensuring
later expiries still withdraw while the worker is delayed. No notification log or
server-held stream accumulates per client.

Opening inspection should lease the displayed root immediately and obtain its
exact details. Continue ordinary list polling independently. Compare selected
`price_revision` and `economic_revision` against the exact `/selection` row;
unchanged confirmation clocks do not alter those identities. `economic_revision`
is null while finance is pending. A material price/reference/fee/settings/policy
change permits an explicit coherent adoption; lease the new root before releasing
the old token. Do not silently copy latest probability or fees into old details.
Missing/expired/unavailable selections keep their retained original evidence and
show that state. A raced-out root/expired token is an explicit refusal, not a
request to silently select a newer result.

The minimal installed controller now polls and replaces the ordinary list,
rejects older responses, preserves scroll/focus and suppresses identical-economic
confirmation notices. Its existing inline inspection still pauses that displayed
list while selected. The backend supports independent advancement; the complete
independent list plus stable drawer, explicit adoption interaction and focus
behavior belong to L03/L04. After-fee default ranking also remains L03 work.

## Readiness and withdrawal

Use nested `publication.state`, not the legacy top-level `state` (which says
whether a response can render), and not `/updates`' stored assembly-state hint.

| State | Meaning |
| --- | --- |
| initializing | No ordinary head or no admitted rows yet. Collection may still be synchronizing. |
| partial | Some source prices/evaluations are pending, expired, replaced, unsupported or unavailable. Valid prices remain readable; unavailable finance is null. |
| ready | The assembled rows pass current authority and the component finance pass completed. This does not establish the denominator of all provider offerings or imply every row has a supported numeric EV. |
| held | An explicit global Stop/source pause or accounting hold affects the scope. Unaffected prices can still be current. |
| failed | The data owner's liveness/authority is unavailable. Retained prices remain inspectable and dependent current finance is withdrawn. |

`publication.finance` separately reports pending/ready/failed calculation work;
optional-finance failure produces partial source availability, not blank prices.
`current_prices` and `retained_prices` count source-price rows, not outcomes or
provider coverage. `coverage_complete` deliberately remains false: no complete
offering denominator has been proved by this slice.

Freshness uses `source_clock.assess` against exact captured source evidence.
Native quotes retain their existing 30-second policy; ordinary aggregate prices
use the existing 900-second default; exact benchmark witnesses retain
`current_benchmark.MAXIMUM_AGE` (1,800 seconds). A validated content-bound native
book confirmation can date an unchanged book. A receipt alone, read, heartbeat,
recalculation, root assembly or metadata change cannot renew it. Unknown/future
clocks and invalid confirmation seals fail closed. Kickoff ends pregame authority.

Material offer/contract/event revision changes withdraw that quote and dependent
finance. Offer authority compares exact price/source/state/policy facts while
excluding receipt/confirmation timestamps and the raw payload hash. A fourth,
full receipt revision still schedules new captures. Thus a newer identical
confirmation cannot withdraw a still-valid captured proof, and cannot extend that
proof's expiry. This distinction is covered by a pre-replacement read fixture.
A reference-only change withdraws dependent probability/EV while the execution
price stays visible/current if independently valid. Settings/model/policy changes
withdraw affected finance until exact recomputation. Fee review expiry withdraws
after-fee values but preserves independently supported gross values. Stop/pause,
resynchronization and source failure withdraw affected authority; a dead owner is
recognized at the existing eight-second heartbeat bound. Reconnect uses original
evidence clocks until genuine synchronized evidence arrives. Every retained row
has `price_current` and `current_reasons`; stale values cannot set a current score.

## Verification and observed limits

Disposable PostgreSQL 16 fixtures verify immutable replacement, unchanged
confirmation, reference-only invalidation, optional-finance failure/retry,
Stop/source pause/reconnect, expiry/policy changes, exact selection/details,
settings CAS invalidation, lease release and pruning, and legacy cache retirement
without losing sources or selected evidence. The final ordinary suite passes all
11 tests, including fair/native scheduling, preservation of the latest two
manual captures during automatic churn and selectable-head grace after replacement. The companion snapshot/storage suites
pass their 18 tests; the final immutable-read change also passed the combined
16-test ordinary/snapshot run before the additional manual-retention fixture. Focused portable tests passed
112 tests plus 14 subtests. Frontend composition, pure view rendering and asset
drift checks passed. Local wheel build passed. Hosted CI was not run; no commit or
push occurred. Owner acceptance and L05 qualification are not claimed.

Real observations are in ignored `test-results/l01/runtime/`; SQL reports are in
`test-results/l01/sql-final-batched/` (27 tests), `sql-mvcc-final/` (16 tests after the read fix) and `sql-manual-retention-final/` (10 ordinary tests after the retention fix) and
`sql-handoff-grace-final/` (11 ordinary tests after the displayed-head grace fix).

- Startup synchronized native books (Kalshi initial 6,705 images; Polymarket US
  also resumed book receipts). Initial recovery encountered the existing SQL
  guard and 28 uncertain credits in 11 attempts; supported independent balance
  recovery preserved every hold and admitted the next scheduler slot.
- The 21:45 UTC / 4:45 PM Eastern scheduled cycle returned all six primary league
  requests with the three families and three aggregate sources. Five requests
  charged 3 credits each; MLB was empty and charged 0. The 15-credit cycle left
  used 1,701 / remaining 98,299 and the same 28 uncertain credits. Empty response
  is not evidence of complete MLB market availability.
- Healthy-owner reuse is recorded in `reuse-before.json` / `reuse-after.json`:
  data PID 30578 and runtime `56967481-3414-4914-9546-78ec6ec616f3` unchanged,
  attempts 12,708 and balance/holds unchanged after idempotent data start, app-only
  restart and filtered reads. No duplicate collector or paid browser dispatch.
- An early material API NBA sample reached its member result 206.031 seconds
  after receipt during startup/backlog. This is a member timing, not a measured
  browser paint or whole-root timing (`material-changes.json`).
- Root-visible native changes were measured separately. The 21:59–22:00 sample
  (`root-material-changes.json`) contains 28 Kalshi changes at 17.114–139.120
  seconds receipt-to-root (median 42.971), and 91 Polymarket US changes at
  18.695–175.668 seconds (median 122.354). These include ingress and component
  scheduling delays. They do not demonstrate 30-second currentness throughout
  the universe. Late rows are retained/withdrawn; the UI truthfully remains
  partial. Earlier smaller Kalshi samples reached the root in 8.08–38.56 seconds.
- Six browser replacements at 21:58–21:59 UTC painted 2.244–4.248 seconds after
  root publication, with no page errors. Exclude the initial preexisting root
  from replacement-delay statistics. The observed board had 994 current and
  17,170 retained prices; heartbeat health was not used as coverage evidence.
- At 22:00 UTC the NFL response succeeded for 3 credits, then NCAAF returned HTTP
  502 without quota headers. The guard stopped the rest of that cycle and added
  3 held credits. Supported independent balance observation subsequently succeeded
  with remaining 98,296, used 1,704 and **31 held credits in 12 unresolved attempts**;
  all exposure remains reserved. Next permitted scheduled slot was 22:15 UTC.
  This is an external intermittent provider/receipt failure, not permission to
  erase a charge, force replay the cycle or bypass the guard.
- Storage improvements include retiring obsolete output caches, batching root
  composition, timely ordinary vacuum, and the faster automatic encoder. On the
  same 90,261,011-byte root, compression measured 1.416 seconds with LZMA and
  0.275 seconds with gzip level 3, increasing packed size from 9,656,904 to
  13,146,057 bytes under the unchanged cap. Before the final integration restart,
  the data owner ran about nine minutes without an automatic storage restart;
  SQL usage at 22:02 UTC was 1,712,210,723 bytes. This is not a sustained-hours
  qualification. Normal shutdowns exceeded the launcher's initial wait (the final drain took
  several minutes while owned catalog/normalization work finished); they completed without force-killing an owner or clearing reservations.

The subsequent reconnect sample (`root-changes-final.json`) was slower: 43 Kalshi
material changes measured 20.577–287.239 seconds (median 155.949), and 58
Polymarket US changes 161.884–356.213 seconds (median 222.489). At 22:09 UTC a read
had zero current / 17,891 retained prices while the owner remained healthy. This
motivated the final oldest-waiter plus recent-native scheduling change; do not
interpret compression improvement or owner health as a source-currentness result.
The 22:07 browser run (`paint-timing.json`) saw seven replacements in 2.024–9.293
seconds, no page errors, and a partial list; its first paint was a preexisting
root and is excluded. `scheduled-api-root.json` independently verifies 12 NFL
prices (six Novig, six ProphetX) from the successful 22:00 response in an ordinary
root. That is existence evidence, not a first-publication latency measurement.

The 22:15 UTC / 5:15 PM Eastern cycle subsequently confirmed all six primary
league responses for 15 credits: five charged 3, MLB charged 0. After associated
free inventory calls completed, used was 1,719, remaining 98,281, and the original
31 held credits / 12 uncertain attempts were unchanged; no accounting blocker,
next cycle 22:30 UTC. Temporary in-flight reservations are not additional lost
charges. A live worker profile found 16.82 of 25.96 seconds spent assembling the
two roots, including hundreds of individual SQL round trips. Root member reads
and inserts are now batched. Frequent space reuse is separated from expensive
compaction checks. Temporary profiling instrumentation was removed.

At 22:30 UTC the next six-league primary cycle also completed for 15 credits,
leaving used 1,734 / remaining 98,266 and the same 31-credit historical hold.
The final post-integration monitor (`integrated-monitor.jsonl`) observed advancing
roots and 276–724 current source prices before that new batch invalidated older
inputs; rows withdrew during replacement rather than combining old finance with
new prices. The resulting state remains partial. The final code includes the
manual-retention and MVCC read fixes. These observations supersede the earlier
zero-current reconnect frames as the current functional publication evidence;
they do not establish a stable freshness percentage or complete native coverage.

The final browser run at 22:31–22:32 UTC (`paint-closeout.json`,
`ordinary-closeout.png`) observed eight automatic replacements with
publication-to-paint delays 2.427–5.136 seconds and no page errors. Initial paint
of an already published root is excluded. The final screen showed 657 current
and 17,410 retained prices. Both processes run from this checkout. Data PID 68417 initially had runtime
`ca35c65b-b2b3-49eb-a11f-720662265982`; app PID 68466 serves the browser. A later
ordinary storage interval re-executed the data process with the same PID and
runtime `6ee1ec66-a9dc-41aa-8fda-88aded4cd762`. These are dated observations, not
instructions to stop a future process with a reused PID.

The final warm-feed sample (`root-changes-warm-final.json`) observed **20 Kalshi
material price changes**, receipt-to-root **8.517–84.477 seconds, median 20.250**.
Affected scope: NBA winner/spread/total, NCAAB winner and NCAAF winner. This sample
does not establish a Polymarket or all-market latency bound, and its tail still
exceeds the native 30-second policy. The final selected-evidence HTTP check caught
and fixed grace starting at creation instead of supersession; fixture coverage
now verifies a long-lived head remains leasable after replacement.

At 22:36 UTC the measured SQL footprint reached 2,062,787,363 bytes, below the
2 GiB hard guard but above the orderly maintenance threshold. The existing
controlled interval withdrew acquisition and re-executed after compaction;
by 22:37 the new owner was healthy and SQL use was about 1,786,995,491 bytes.
The reader reported failed/withdrawn authority during the gap and then resumed
publication. This is an observed operational interruption, not evidence of
uninterrupted freshness. The full-scope retention/ingress load still needs sustained
L05 qualification; do not conceal this behind a heartbeat or relabel it an
external provider blocker. No holds were cleared or account limits increased.
`exact-selection-final.json` records successful live current ProphetX
lease → exact member inspection → release after the grace fix.

Latest read at 22:38 UTC: runtime `6ee1ec66-a9dc-41aa-8fda-88aded4cd762`
healthy, ordinary generation 498 advancing, SQL 1,797,636,899 bytes, **404 current /
18,174 retained prices**, state partial. Kalshi was streaming; Polymarket US had
not yet reconnected after that maintenance interval. Aggregate waited for the
22:45 scheduled slot with no accounting blocker, 31 held credits and 12 historical
uncertain attempts. `final-status.json` and `final-current.json` contain this dated
read. The earlier native/aggregate timing samples remain scoped observations,
not a claim that every source was current at closeout.

## Remaining slices and dependencies

L02 owns complete exact native Pinnacle bindings and reviewed native fee inputs;
no example fee or missing probability was fabricated here. L03 owns complete
filtered-universe grouping, after-fee ranking and independent selected-evidence
adoption against this contract. L04 owns the stable drawer and interface polish.
L05 must qualify sustained whole-product operation, including native ingress and
publication latency under full catalog load. The observed long native tail and
partial source coverage are explicit limitations, not a green full-coverage gate.
Existing Scanner capacity deferral and Coverage optional-memory failure are also
visible in runtime diagnostics; ordinary publication proceeds independently and
does not use those background census results as its source-readiness denominator.
Intermittent provider 502/absent-quota responses can hold aggregate acquisition
again; recover only through the existing supported account observation procedure.
