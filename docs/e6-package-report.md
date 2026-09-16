# E6 — bounded unified synthetic collection

## Scope and status

This report covers one explicitly started synthetic prediction/reference collection session, recovery, durable reopening and an isolated market-watch preview. **Complete for this bounded synthetic collection package.** Full E6 real-feed qualification remains separate. The owner-accepted E5 preview, owner database/services, prior evidence and archived source copies are preserved.

No provider requests, credentials, account/subscription work, outreach, trading, commit, push or publishing are part of this package. The deferred 250 ms gate remains deferred. No further E5 acceptance walkthrough is required or claimed.

## Implementation and boundaries

- `app/collection/session.py`: one Start/Stop owner, independent producer tasks, the existing `CaptureQueue`, one serial database worker and one calculation worker. An independent monotonic deadline bounds collection. Only one calculation runs at a time; skipped calculation intervals do not discard observations.
- `app/collection/synthetic.py`: explicitly injected Kalshi/Polymarket US full snapshots, The Odds API-shaped reference responses and event discovery. Existing event/matching/fee/depth fixture assumptions remain explicitly synthetic. Simulated event time advances at wall-clock speed from two hours before the fixed September 13 fixture kickoff; actual lifecycle timestamps separately identify the September 15 verification.
- `app/collection/storage.py`: explicit connections to existing `Store`, `ReferenceStore`, `FairPriceStore` and `OpportunityStore`. No new migration or change to prior storage/engine interfaces. Every prediction delivery uses the existing receipt/packet path; reference raw receipts, enrichment revisions, rejections and gaps use E2's records and store. E6 arrival/lifecycle/calculation associations use existing immutable coverage events.
- `app/collection/context.py`: separately versioned session-health eligibility at each cutoff. A disconnected/stale/unresolved source makes the session result unavailable. E3/E4 arithmetic is retained as a diagnostic, not rewritten into fabricated market inputs. Saved reopening applies the same context. E3 still selects the latest receipt before eligibility, including invalid arrivals; exceptional mass and net EV remain unknown.
- `app/collection/reopen.py`: file hashes, complete receipt/knowledge cutoffs, captured prediction-book identity, stored E3/E4 dependencies and exact recomputation. Missing or changed evidence fails closed. Prior engineering attempts without recorded session health do not gain retrospective eligibility.
- `app/collection/environment.py`: only freshly created, marked, socket-only PostgreSQL clusters. Every connection verifies database, user, directory, socket, TCP-disabled setting and port before use. No default owner-connection helper is invoked.
- `app/collection/server.py`, `static/`, `scripts/e6-preview`: separate loopback Start/Stop/status/reopen interface using E5's existing stylesheet/panel/detail patterns. It starts idle, retains selection, and does not couple producer lifetime to a browser tab. A process lock prevents simultaneous preview owners; eight sessions per environment and eight active HTTP handlers are permitted, with one saved-replay worker.

The original prediction controller's 60-second cap and receipt ledger remain unchanged. The new owner explicitly replaces their lifecycle role **for this isolated injected path only**, reusing its bounded queue and capture/storage interfaces. The E2 adapter receives finite session-specific bounds rather than retaining its separate 120-second default. Its production HTTP transport remains absent.

## Declared profile and storage policy

| Bound | Final synthetic profile |
|---|---|
| Collection duration | Configurable positive duration, maximum 900 wall-clock seconds; UI choices 30 or 900 seconds |
| Event scope | One fixed synthetic ATL/PIT NFL pregame moneyline; two prediction venues, one reference bookmaker family |
| Prediction snapshots | Every 5 seconds per venue; at most about 360 delivered books over 15 minutes |
| Reference polling | Every 30 seconds; 64 request ceiling, including failed attempts; 3 retries per failure episode, 3-second request/close timeout, 2/4/8-second reference backoff |
| Discovery | Every 30 seconds with finite transient retries; changed start, disappearance, unresolved identity or kickoff stops the session |
| Calculations | Approximately every 30 seconds after prior work finishes; maximum 64; one immutable snapshot/job at a time |
| All ingress records | 1,024 total records, including discovery, reference enrichment/control records and prediction receipts; 16 MiB canonical ingress allowance |
| Queue | Existing item/retained-object accounting, at most 48 queued items and 4 MiB; one additional database item may be in flight |
| Retained reference history | At most 256 records; only two latest prediction books retained; no unbounded per-receipt runtime ledger |
| Primary write envelope | Maximum 64 MiB canonical item/calculation payload; 1 GiB cumulative charged payload per session, checked before writes |
| Database guard | Stop if current database size plus a 128 MiB transaction reserve exceeds 2 GiB. This measures database allocation, not total filesystem/WAL usage. It supplements the logical payload budget; it is not an OS disk quota. |
| Fallback journal | 32 MiB fsynced write-ahead journal; every delivered item is retained before the database queue. A first rejected delivery is retained when it fits the remaining journal allowance. If primary and fallback storage fail, durability is explicitly unknown. |
| Saved reopening | At most 131 manifest entries / 512 MiB per saved package, checked before replay; one replay worker |
| Retention | Preserve evidence; stop at capacity. No automatic history deletion. Explicit environment cleanup stops/removes only the marked disposable cluster after retaining exports/logs. |

These limits comfortably cover the declared synthetic cadence: roughly 360 prediction receipts, 30 reference receipts plus their revisions, 30 discoveries and bounded gap/stop records. They are not live cadence or source-to-target latency qualification. JSON/record overhead, duplicate dependency exports and database allocation are separately measured. The write-ahead journal introduces explicit local-disk backpressure; no claim is made about responsiveness during an OS-level hung filesystem operation.

A delivered record and a raw observation are different counts. Reference revisions, gaps and discovery responses contribute to the all-ingress count. The report separately records prediction receipts, reference receipts and gap/control records. Identical raw arrivals are not deduplicated. The first capacity-rejected delivery remains distinguishable from PostgreSQL-persisted input.

## Shutdown, interruption and recovery

Disconnect detection clears current eligibility immediately. Recovery requires a new validated full snapshot; it links observed failure and recovery records without inventing outage onset or unseen intermediate updates. Rejected reference snapshots invalidate previous eligible snapshots. Discovery never silently changes the event or continues incompatible pregame calculations.

Manual Stop closes/cancels and awaits producers, drains accepted persistence work, awaits the active calculation/write, retains lifecycle/export evidence and joins workers before the API reports completion. The UI remains stopping during export. Queued records after an unrecoverable primary failure stay explicitly journal-only, not falsely counted as PostgreSQL completion.

A killed process leaves an unfinished database session. On the next explicit preview launch, the owner marks it interrupted, records detection time and available persisted/journal counts, exports its saved history and stays idle. Exact crash time remains null; `ended_at` reflects reconciliation, not a claimed crash instant. A torn journal tail is reported as incomplete. No automatic collection/resumption or journal import occurs.

## Verification and exact candidate

Unchanged Git HEAD: `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`. E6 implementation digest: `9a098e61b662c8dccb2bb2bdf633c7b568e34c75fda5e1ae05185bb4e4cc4573`. Full retained implementation digest: `325d291b427c1679f44ce5e07f319b41511970b02ae4ffcafc720959ff681dfe`. [Exact file manifest](../evidence/e6/candidate-implementation.json). Digests hash sorted compact JSON file-to-SHA-256 maps.

The final sustained run records its own [loaded file identity](../evidence/e6/final-candidate-15m/runtime-implementation.json). Collection, transport, persistence, calculation-context and replay code match the final candidate. Only the independent preview server gained the subsequently tested eight-session/request cap checks; final browser and five API checks use that server. The final sustained results are recorded below. Earlier failed/diagnostic attempts remain in `evidence/e6/`; they are not substituted for the final-candidate sustained check.

Focused checks cover manual Stop, browser independence, actual process kill/restart, quota, entitlement, queue pressure, slow storage/calculation, logical capacity, stale inputs, reference repeats, prediction resynchronization, schedule changes/disappearance/identity/kickoff and saved health context. Existing E1–E5 evidence is reused; focused regressions cover the relevant unchanged reference, pricing, opportunity, E5 preview, controller/refresh and saved-status behavior.

The initial malformed rejection fixture also removed event identity; the collector correctly stopped. A second fault script placed invalid odds immediately after three failed retries; it also correctly stopped. Both attempts and their cleanup remain preserved. The final script separates invalid-odds and transport-outage checks. An intermediate run predates the saved-health overlay and is diagnostic only. The final candidate has its own complete 15-minute run and exact runtime file manifest.

## Final results — September 15, 2026

Session **`bc5c5a97-36ae-460d-bf4d-8598617bc80f`**. [Measured summary](../evidence/e6/sustained-summary.json), [95 resource samples](../evidence/e6/final-candidate-15m/resource-samples.json), [exact replay verification](../evidence/e6/final-candidate-15m/replay-verification.json).

| Check | Observed result |
|---|---|
| Wall-clock collection | **900.011642 seconds** between first delivered record and Stop initiation, September 15, 15:15:18–15:30:18 EDT. Monotonic deadline: 900 seconds. |
| Full shutdown/export | **944.877950 seconds** from session start through producer/worker shutdown and saved export. Completion was withheld during the approximately 45-second drain/export interval. Separate offline replay then ran before database cleanup. |
| Delivered versus persisted | **459 / 459** ingress records; **0 journal-only**, **0 pending** at completion. |
| Actual observations | **360 prediction receipts**, **30 reference receipts**; changing prices, repeated odds, invalid latest snapshots and non-opportunity changes retained. |
| Calculations and replay | **27** persisted E3/E4 calculation pairs; **27 exact replays**, all with their recorded session-health context. |
| Reference gaps/control | **9 records**: 3 transient transport failures, 2 rejected snapshots, 3 observed recoveries, 1 cancellation at session Stop. These are not nine separate outages. |
| Controlled transport outage | Detected at simulated elapsed approximately 300 seconds; retries at approximately 302 and 306; fresh-snapshot recovery at approximately 314. The injected interruption lasted 8 seconds; observed recovery took approximately 14 seconds after detection. Actual outage onset and unseen source changes are not inferred from these sampled observations. |
| Queue/ledger high water | **5 queued items**, **163,027 retained queue bytes** (159.2 KiB), **70 reference records**. Two latest prediction books and one calculation job; six producer/consumer/calculation tasks. |
| Process memory | Peak sampled collector process RSS **472,104,960 bytes** (450.2 MiB), including collection/export. This is the Python process, not a total PostgreSQL/system-memory measurement. |
| Storage | **5,722,675 ingress bytes**; **5,736,088 journal bytes**; **376,777,697 charged canonical payload bytes**; **37,684,003 measured database bytes**; **245,125,964 saved export bytes**. Database allocation, canonical payload charges and export bytes are different measures. |
| Focused E6 tests | **21 passed** for collection/durability/health and **5 passed** for isolated preview/API bounds. [Collection log](../evidence/e6/final-focused-tests.log), [API log](../evidence/e6/server-tests.log). |
| Regressions | **117 passed**, plus the unchanged E5 interface-state suite and E6 JavaScript syntax check. [Regression log](../evidence/e6/regressions.log), [E5 interface-state log](../evidence/e6/e5-ui-regression.log). |
| Actual browser | Start → changing books/reference and conditional economics → Stop (clears current economics and awaits export) → saved reopen. Closing/reopening the tab preserved the running session and selected Polymarket US venue. Final manual check completed with **16/16 records** and one replayable calculation. [Browser ledger](../evidence/e6/browser-verification.json), [viewport](../evidence/e6/browser-saved-viewport.png), [saved DOM](../evidence/e6/browser-final-saved.txt). |
| Actual process interruption | Exact isolated preview PID was killed; relaunch marked its session interrupted with **10 prediction / 1 reference receipts** and null crash time, exported evidence and remained idle. [Injection](../evidence/e6/process-interruption.json), [restart](../evidence/e6/process-restart.json). |
| Actual storage failure | Closed PostgreSQL connection: **13 deliveries, 7 primary-persisted, 6 journal-only**. Explicit fallback failure remained; reconnect reconstructed an interrupted primary session without inventing crash time or silently importing the journal. [Evidence](../evidence/e6/primary-storage-failure/verification.json). |
| Preservation | All **1,196 preexisting project files** match entry hashes. SDA and Scroll Down retain clean original revisions. [Preservation](../evidence/e6/preservation.json), [source copies](../evidence/e6/archived-source-preservation.json). |
| Cleanup | Final verifier and browser preview services stopped; their marked PostgreSQL directories removed after exports/identity logs. Short focused test clusters also stopped/removed. [Final cluster cleanup](../evidence/e6/final-candidate-15m/cleanup/cleanup.json), [preview cleanup](../evidence/e6/preview-20260915-145944/cleanup/cleanup.json). |

Synthetic conditional reference probabilities changed with delivered odds; unconditional target value and net expected profit stayed unknown. Positive/negative Arb arithmetic remains conditional on the preexisting invented fee, quantity and settlement fixture, not attainable or qualified live profit. No new real pairing, lineage, settlement or probability-mass evidence was manufactured.

The final browser showed saved-cutoff books rather than mixing them with the latest session books. Source-health context is retained independently from E3/E4 diagnostic arithmetic. Console warnings/errors were absent in the retained browser check. Earlier full-page screenshot stitching is not used as layout evidence; the linked viewport and DOM are the relevant final records. The API test log retains aiohttp configuration-key recommendations; these are not test failures.

**Engineering completion only:** this does not qualify production transports, actual account entitlements, real-event identity, live timing, settlement, unattended operation or profitability. E5's existing basic owner acceptance remains separate and unchanged.

## Reproduce locally

From any directory:

```sh
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/e6-preview start --port 8786
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/e6-preview status
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/e6-preview stop
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/e6-preview cleanup
```

`start` initializes/reopens only the isolated disposable environment and prints the actual loopback URL. It leaves collection idle. Use **Start synthetic session** in the page. **Stop and save** awaits actual shutdown; choose the saved session and **Reopen saved history** to validate/replay it. A changed port is a different browser-storage origin. `stop` retains the database for explicit process-restart checks; `cleanup` retains exports and database identity/shutdown logs under the printed evidence directory, then removes the marked cluster. It never controls the accepted E5 preview.

Repeat a fresh 15-minute verification using an unused evidence directory:

```sh
cd /Users/michaelfuscoletti/Desktop/prediction-arb
.venv/bin/python -m app.collection.verify --seconds 900 --output evidence/e6/new-explicit-run
.venv/bin/python -m unittest tests.test_e6_collection -v
node --check app/collection/static/watch.js
```

The verifier refuses an existing output directory and stops/removes its newly created cluster in cleanup. No account or provider connection is needed. Short focused tests use their own fresh disposable clusters.

## Next handoff and stop boundary

Only this bounded synthetic package can be marked complete. Full E6 real-feed qualification remains unstarted. The single next proposed step is the [bounded real-feed transport handoff](e6-real-feed-handoff.md), with explicit transport, entitlement, event, duration/cadence and cost decisions. **Do not launch it.**
