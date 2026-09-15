# Slice 13 follow-up — a working personal prototype

Updated September 15, 2026 UTC. This plan reflects the owner's revised direction: **this is for the owner alone, and the immediate goal is to prove that the live-stream product works.** Favor a stable, understandable working loop over strict speed guarantees and exhaustive performance qualification.

## What matters now

The owner should be able to start a bounded scan, see prices update, inspect a result, stop, and reopen what was saved. Preserve accepted observations, keep resource use finite, and make failures and stale/disconnected data honest. Missing fees, quantities or settlement facts remain unknown. Zero qualified opportunities is a valid result.

A hard 250 ms maximum is **no longer an acceptance gate for this personal prototype**. The earlier measurements and failures remain intact; the old gate did not pass. This is an explicit change of scope, not a claim that the old requirement was met. Do not introduce a new strict millisecond target in its place or slow the application artificially to match an example cadence.

Use focused checks for changed behavior and a practical start → updates → Stop → saved reopening check. Re-run broader checks when a regression or material change warrants them. Do not repeat the full timing matrix, every example, drain-stress experiments or detailed profiling on each small change.

## Current backend

13A reproduced capture loss. The 13B backend now preserves accepted observations within its bounded workload and drains safely on Stop. Capture and view work have separate owners: immutable receipt-bound snapshots go to one compute/view worker with its own database connection, while capture keeps its connection and mutable state. There is at most one refresh chain and one pending evaluation signal. Stale or previous-session completions cannot replace the current view.

The existing finite scan, queue, receipt and storage limits remain. So do immediate loss of current eligibility on Stop/disconnect, exact timestamps and receipt bindings, transaction rollback, first-stop reason, and waiting for actual work to settle. Personal use does not justify silent data loss or a misleading clean stop.

Current evidence and exact identity are linked in the [Desktop tracker](/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md) and [continuation report](../evidence/slice-13-follow-up/13b-cadence-repair/README.md). Local synthetic/storage checks are separate from a new production-feed run and owner acceptance.

## Practical work and current completion

| Step | Purpose | Enough for this prototype |
|---|---|---|
| 13B — backend stability | Capture, useful updates, bounded Stop and saved reopening | Focused controller/storage tests and the actual local synthetic loop pass; known losses remain explicit. No strict cadence qualification. |
| 13C — truthful status | Make saved-session labels agree with known capture gaps | One simple shared lifecycle/coverage interpretation, including the two legacy complete-with-backlog sessions. Avoid a broader dashboard redesign. |
| 13D — practical regression check | Catch a broken user flow | Check the changed behavior and inspect the usable interface. Expand testing only when evidence warrants it. |
| 13E — supervised owner proof | Find out whether this is useful with real feeds | A separately authorized short live Start → inspect → Stop → Historical try, with honest limitations and owner feedback. No automatic or always-on collection. |

13B and 13C are complete within the revised personal-prototype scope. September 15 preparation completes the focused 13D check by reconciling the unchanged 13C source and reusing valid isolated synthetic/storage/interface evidence, verifying the app-only lifecycle option, restarting the stopped app without migrations, and inspecting the initial stopped interface. See the [preparation report](../evidence/slice-13-follow-up/owner-try-preparation-20260915/README.md) for exact candidate identity, preservation and results.

**OWNER TRY READY — User starts a bounded scan, inspects updates, manually stops, and reopens the saved session.** The dashboard is open at http://127.0.0.1:8765/, idle with collection stopped. 13E remains owner-operated and has not occurred on this candidate. Subsequent owner feedback should drive what gets fixed next.

The original review found two sessions with 32 unprocessed queued observations each: `ed06c7d1-ae22-4ed8-8b90-bec4e22e2917` and `c93f79fe-d2c0-4c33-bf97-7ba5fe61a17f`. They must not look like clean captures merely because their stored lifecycle says complete. Preserve their records and explain the gaps; do not rewrite their historical evidence.

## Deferred until the prototype proves useful

- Strict 250 ms or other subsecond maximum guarantees, repeated timing matrices and detailed stage profiling.
- Sustained-load, prolonged soak, extreme burst and broad resource-envelope qualification beyond the initial bounded use.
- Exhaustive example/memory/performance reruns for every iteration.
- Always-on collection, autostart, periodic discovery, broader venue coverage and production-scale operation.
- Profit ranking, execution, fill assumptions and trading.

Revisit performance when the owner's actual use reveals a sluggish screen, missed usefulness, data loss or a desired use case that requires faster decisions. Define that requirement from the observed need. Preserve the existing failure evidence as a baseline instead of treating it as a current blocker.

The September 15 user instruction separately authorized local preparation and a controlled stopped-app restart. That work is complete; owner database inspection was read-only and no migration or data modification occurred. No venue credential access, venue requests or live scan occurred. This document grants no automatic collection or owner-review authority. `PLAN.md` and historical evidence are preserved. Slice 14 remains separate.
