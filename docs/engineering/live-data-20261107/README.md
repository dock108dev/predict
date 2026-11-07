# Live-data engineering — November 7 follow-up

**Current next action: implement E01. Broad observation is finished.** Use targeted
source-to-screen checks to verify each repair; do not start another open-ended
monitoring session or ask for owner acceptance while known engineering remains.

This queue follows the owner's November 7 request to turn the usability findings
into next steps. It supersedes the November 6 “ordinary use / owner acceptance
next” instructions as the active execution order. The November 4
[product contract](../../live-comparison-plan-20261104.md) and November 6
[L05 delivery evidence](../live-comparison-20261104/L05-delivery.md) remain dated
requirements and evidence; earlier checks are not erased or automatically rerun.
The [Desktop next steps](../../../../prediction_arb_next_steps.md) is a concise
entry point to this queue, not a second independently maintained plan.

## Evidence and starting state

The [session report](../../usability/2026-11-07/README.md) covers 13:44–17:00 EST,
with 192 health samples and 76 stage samples. Of 190 successful first-page reads,
123 had no current offers. This is a sampled first page, not all NCAAF coverage.
Connected feeds, an advancing list and HTTP success did not establish current
rows or in-game coverage. The inspected path is pregame-only and says Before fees.

The final post-window recovery was verified at 17:15:40 EST: NCAAF receipt at
17:15:16, both native feeds available, healthy runtime, no quota pause and no
cleanup errors. All original records covering **49 credits / 18 uncertain
attempts** remained unchanged. These are dated facts, not a live status claim.
Use current owning records before an operational action. Both November 7 exact
429 exceptions were approved and consumed; neither grants a future exception.

## Already integrated — preserve, do not redo

| Change | Evidence / remaining limit |
| --- | --- |
| Restored source service and supported same-owner completed-5xx recovery | Live recovery at 15:33 avoided a native restart; holds remained intact. Operator recovery UX remains E03. |
| Exact 15:00 and 17:00 429 exceptions | Each approved independently, one zero-credit observation each, original records preserved. No general retry authority added. |
| Featured-refresh priority over alternate collection | Deferred work at 16:29, 16:44 and 16:59; successful NCAAF receipts at 16:30:15 and 16:45:18. Oldest retained collection receipts get priority next cycle. E02 verifies scheduling under load without treating partial alternate coverage as complete. |
| Raw-image decoding moved off the socket loop | Owned storage, newer-arrival preservation and cancellation checks passed. Reconnects continued; no end-to-end performance win claimed. |
| Bounded websocket close categories | Distinguishes keepalive timeout from transport loss without retaining raw error text. Root cause remains E03. |
| Status-capacity fallback | Trims diagnostic examples while preserving accounting, coverage and controls. Regression checks passed; live pressure fallback was not exercised during the remaining window. |
| Refresh visibility and clearer status wording | List check time, focus-pause indicator, manual list refresh, schedule/next due, alternate progress and partial-price banner verified. Active-collection guidance and stable pagination remain open. |

These are integrated local changes in the existing uncommitted checkout. Focused
unit, disposable PostgreSQL and browser evidence is linked in the session report;
there is no new commit, hosted CI or owner-acceptance claim.

## Execution order

One accountable product/systems lead owns implementation, integration and checks
in this repository on `main`. The workstreams below do not authorize new
worktrees, successor repositories or automatic concurrent agents. A genuine
external dependency in one path does not block independent engineering.

| Order | Workstream | Priority / state | Findings covered |
| --- | --- | --- | --- |
| E01 | Separate acquisition guards from existing-price publication authority | P0 — next implementation | U14, U28 |
| E02 | Measure and repair source-to-screen latency and cycle throughput | P0 — open; preserve integrated scheduling/storage fixes | U08, U12, U16, U23, U24, U25, U29, U30 |
| E03 | Resilient runtime, scoped recovery and truthful operational UI | P0 — open; several narrow fixes integrated | U01, U09, U10, U13, U15, U17, U21, U22, U27, U31 |
| E04 | Resolve the in-game coverage gap and time-window controls | P0 functional gap — open | U02, U07 |
| E05 | Reconcile the active interface with the agreed fee/reference contract | P1 — open; engineering reconciliation precedes acceptance | U05; existing L02/L03 requirements |
| E06 | Stable browsing, consistent market labels and precise inspection | P1 — open; refresh visibility already integrated | U03, U04, U11, U18, U20 |
| E07 | In-app diagnostic session history and change provenance | P1 — open feature work | U06, U19 |

### E01 — publication authority during ordinary collection

At 15:46, fresh NCAAF observations became unavailable because a normal in-flight
request was reported as `ambiguous_dispatch_unresolved`. The ledger correctly
blocks another dispatch, but `ordinary_publication.authority` also applies that
reason to existing aggregate prices. This couples a normal acquisition to a
screen-wide withdrawal. A failure in one league also obscures which earlier
league receipts completed successfully.

Trace `current_quota.snapshot` / `pending_reason`, the owning runtime's active
request evidence, `ordinary_publication.authority`, reference authority and the
ordinary read projection. Introduce a separately justified read/publication
state for a known owned in-flight request. Keep genuine uncertainty, Stop,
source pauses, stale ownership, failed transport and invalid source evidence
protective. Do not simply ignore `blocking_reason`, clear a hold, relabel an old
receipt or globally allow all retained prices.

Done when focused fixtures distinguish active transport from completed failure,
ownership loss and unresolved exposure; valid already-admitted price evidence
survives a normal refresh, genuine revocation still withdraws it, and one normal
scheduled cycle is traced through the visible list. Show per-league last success
and affected scope without claiming unchanged old evidence is newly collected.

### E02 — delivery latency and throughput

Add bounded timestamps/durations for receipt, normalization, database admission,
first capture, later recapture, publication and browser display. Record accounting,
reservation, admission and storage durations between requests. Aggregate
`projected_at=received_at` is not a commit timestamp. Retained-receipt age is not
first-delivery latency. Label process-peak RSS separately from current residency.

The completed 15:45 cycle took 995.40s: 235.93s dispatch-to-receipt and 759.47s
between requests. This locates work to measure; it does not identify a single
bottleneck. Use those measurements to repair encoding, queue drain, publication
rotation, accounting or storage contention as supported. Preserve FIFO/fairness,
exact book/receipt ownership, bounded retention and cancellation behavior.

Keep the 900-second schedule and handoff fix. Verify unfinished alternate work
continues fairly and is clearly partial; do not cancel an in-flight paid request
or increase the credit budget to catch up. Examine source age versus cadence and
publish observed freshness gaps. Do not extend expiry to make a stale row pass.
Retain the previous 2.454s startup Markets miss against the existing two-second
target as a specific performance regression, not a new arbitrary release gate.

Done when measured stage timings explain the repaired path, fresh inputs reach
the intended rows under representative existing scope, stale/quiet-source cases
remain honest, and scheduled handoff plus deferred-work progress are exercised.
Report remaining delays by stage and population; no blanket fresh-coverage claim.

### E03 — runtime and operations

Make an absent or failed data owner distinguishable from a healthy app, slow
restoration, network resync and stale rows. Expose restoration stage, safe close
category, per-league collection status and last successful receipt. Finish
active-collection availability and next-action wording: some cards still say
budget delayed or repeat an old offering instruction while collecting.

Reproduce the status-size failure using bounded fixtures and a relevant loaded
case; verify trimming diagnostic examples cannot alter accounting, coverage,
Stop/pauses or source authority. Preserve the hard capacity and memory guards.
Investigate reconnects with the existing close categories and stage timings;
reducing one decode workload did not establish their cause.

Separate presentation identity from acquisition/control identity so a harmless UI
edit need not invalidate accounting recovery. Keep exact ownership, acquisition
code/config, credential/account/window and immutable-attempt attestation. Build
a guarded recovery workflow that shows the exact incident, original exposure,
permitted action, single-use outcome and next eligible slot. Ordinary supported
recovery should not require editing code or restarting independent native feeds.
A future 429 policy expansion remains a concrete separate decision; do not treat
consumed one-time grants as reusable or reinterpret balance evidence as charges.

Done when outage, restoration, active refresh, failure, bounded status pressure
and recovery are understandable in the app and verified without losing protected
state. User Stop and source pauses must survive restarts and attempted recovery.

### E04 — in-game scope and time window

This is an unmet requested capability, not a label-only fix. Establish a dated
source-by-source matrix for authoritative game state, supported in-game books,
suspension/resumption, source clocks and available terms. Trace discovery's
started-game exclusion and publication's scheduled-kickoff withdrawal. Implement
the supported lifecycle path with explicit scheduled/live/suspended/final/unknown
states, preserving exact occurrence, period, line and settlement identity.

Expose local-time/timezone range controls and supported game-state filters. Keep
unsupported sources and unknown game state explicit. Do not remove kickoff
withdrawal alone and call retained pregame observations live. Work on available
sources and UI independently of a genuinely unavailable provider capability.

Done when supported pregame-to-live, suspension, reconnect and final transitions
have trustworthy source evidence and safe withdrawal behavior, and the requested
noon–17:00 Eastern selection means what the interface says. Record specific
unsupported paths or missing source facts rather than marking in-game coverage
complete because a websocket is connected.

### E05 — active-route fee/reference correctness

The November 4 contract calls for disclosed before/after-fee values, reviewed
fee eligibility and exact Pinnacle-backed native calculations. November 6 recorded
proof on a specific workflow; November 7's inspected desk says Before fees and
has different navigation. Trace the actually served route/assets, read API,
metric selection, fee model and ranking before deciding whether this is a route
regression, missing integration or only inaccurate documentation.

Repair supported calculations/display/ranking under the existing financial
contract; do not settle for renaming documentation if an agreed feature is
missing. Verify source/product/account applicability, effective interval, rounding,
quantity and risk denominator. Missing fees remain unknown, never zero. Preserve
separate reviewed and conservative estimates, exact reference identity and pinned
inspection. Carry verified prior arithmetic forward only when its inputs and
path still apply. Name any smallest genuinely missing external fee fact while
continuing independent engineering.

Done when the active route's displayed basis, eligible ordering, evidence drawer
and docs agree, with independent arithmetic for supported cases and explicit
unknown/expiry behavior. This is correctness work, not proof of executable profit.

### E06 — navigation and inspection

Fix pagination under changing whole-board dependencies: three Next clicks returned
to page one. Define stable membership/order for browsing while revalidating the
current authority of displayed evidence. Make a necessary reset explicit and
retain filters, scroll, keyboard focus and the coherent selected inspection.
Do not drop cursor checks without replacing their consistency protection.

Distinguish games, outcomes and offers in counts. Resolve title/market mismatches
against source and canonical facts. Show precise source/receipt/capture clocks
and elapsed age on demand. Keep already-integrated automatic-refresh visibility;
verify later-page behavior after pagination is repaired. Preserve explicit Use
latest prices adoption and coherent updates of dependent fields.

Done when a user can browse later pages during ingestion without silent resets,
duplicates or omissions, inspect a stable selection, return focus after close,
and understand labels/counts/ages. Check relevant desktop/mobile and keyboard
paths rather than treating API success as UI verification.

### E07 — diagnostic history and repeatable user guide

Move the external session log into a bounded inspect/export workflow: observation
time, filters, source/collection state, source clocks, admitted/published changes,
withdrawals, reconnects and gaps. Distinguish unchanged-source confirmation from
material change, receipt order from display order, and first/last observation
from continuously established duration. Price-direction/change-history is a
requested feature, not a result already measured by this session.

Keep exported data within established retention and secret-redaction boundaries.
Do not retain unbounded provider bodies or claim opportunity lifetimes from sparse
samples. Update the [how-to](../../usability/2026-11-07/how-to.md) from the actual
implemented flow as each feature replaces an external tracking burden.

Done when a user can reproduce a dated diagnostic session and export its facts
without keeping the current side spreadsheet/notes, with explicit gaps and clock
semantics. No actionable opportunity/duration validation is claimed by this queue.

## Working and completion rules

Follow [AGENTS.md](../../../AGENTS.md): one checkout/main; preserve dirty work,
credentials, settings, user data, holds, actual Stop and pauses. Existing ordinary
acquisition remains authorized within 300 credits per 15-minute cycle and 16,800
per operating day, subject to account/quota/ownership guards. Routine builds,
restarts and integration are part of implementation. No additional collection
or recovery authority is created by this document.

For each repair, record the concrete symptom, code/result change, relevant tests,
installed verification and remaining limits in its workstream. Use disposable
fixtures/SQL for faults and focused live checks for claims that require real data.
A bounded observation answers a named verification question; it is not another
activity phase or a substitute for implementing a known repair. Keep local checks,
commit/push, hosted CI and owner acceptance distinct. No arbitrary receipt quota,
fixed soak duration, new diagnostic-attempt limit or mandatory owner-review gate.

Every U01–U31 entry is mapped above. The [finding register](../../usability/2026-11-07/backlog.md)
retains the original evidence and status; this queue owns the next execution order.
