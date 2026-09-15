# Slice 13 — local live dashboard

Current source includes the Slice 13B personal-prototype repairs. The owner is using this alone to prove the product works; strict performance qualification is deferred under the [current follow-up plan](slice-13-follow-up-plan.md). Historical live/browser results below concern the earlier candidate. New live acceptance is not claimed. Slice 14 has not started.

## Use it

Open **http://127.0.0.1:8765/**. The latest code is saved locally. This repair did not restart the owner app or reconnect live feeds.

From any terminal:

```sh
cd /Users/michaelfuscoletti/Desktop/prediction-arb
scripts/dashboard start
```

This single launch command starts/checks the existing socket-only project database, applies existing migrations, and starts the loopback web server. Only one dashboard process can hold the project lock. If already running, open the URL. Dependencies are declared in `pyproject.toml`; for a fresh environment install the project with its `stream` extra.

Choose **Live**, select a duration and markets-per-venue limit, then **Start scan**. Inspect event prices, use Event/Market filters, and open **Inspect** or **Details**. Candidate details include fee assumptions, material outcomes, receipt/source ages and cross-venue skew. **Calculate bounded depth** runs only on request. **Stop** ends the collector and saves coverage. Choose **Historical** to reopen a saved live scan. **Synthetic demo** uses invented prices and rules without venue requests; its saved sessions stay in that mode.

To stop the app, use Ctrl-C in its launch terminal or:

```sh
cd /Users/michaelfuscoletti/Desktop/prediction-arb
scripts/dashboard stop
```

That leaves the database and saved sessions intact. To also stop the dedicated database, after the app exits:

```sh
scripts/project-postgres stop
```

No global login service was installed. Restarting the app never resumes a scan. Do not run migrations/import-and-replay examples concurrently with a scan: database locks can exceed the collector's deliberately short wait bounds, causing a recorded incomplete scan. Stop collection first.

## Scope and safeguards

The aiohttp server binds only `127.0.0.1:8765`. Fixed Host checks, same-origin POST checks, a per-process scan token, JSON/body bounds and a restrictive content policy protect controls. Static assets and session identifiers are allowlisted; endpoints do not accept filesystem paths, hosts, credentials or accounts. Credentials remain in the existing named Keychain entries and are used only by existing server-side signing transports. No trade, balance, fill-history or funding API is used.

The initial configurable universe is pregame NFL: 1–4 markets per venue, default 2. Each scan discovers current events and refreshes selected listings; common canonical events receive subscription priority. Discovery is intentionally truncated (one page: Kalshi 10 events, PMUS 8), with request limits 24/16 and recorded per-venue coverage. Selection is not an exhaustive league search. Metadata refresh occurs at scan start, not periodically during the maximum 60-second run. No historical IDs are hardcoded into live selection. Normalization, event matching, market matching, book reconstruction, fees and top/depth calculations reuse the existing application. Exact rule bindings are re-evaluated; missing or changed evidence remains unknown.

The default scan stops at 60 seconds, 1,000 stream messages or retained receipts, or 128 MiB input. UI durations are 10/30/60 seconds. The capture queue has 48 item slots and a 1 MiB retained-item byte limit. Capacity exhaustion closes acceptance and records rejected or unprocessed work explicitly. Stop closes producers, drains accepted work within the existing budget, waits for depth and view work, then finalizes the saved session.

Capture owns its mutable state and database connection. One separate compute/view worker owns a second connection and receives immutable snapshots containing exact committed receipt identities, original timestamps, evaluation time and matcher/fee state. Intermediate evaluations may be coalesced; accepted observations are retained. Connections are never shared between workers. Old-session, out-of-order or invalidated completions cannot replace the current view. A hard 250 ms view maximum is deferred; the current goal is a dependable personal-use loop, without a claim of fast-arbitrage readiness.

Disconnects invalidate current eligibility immediately. The dashboard uses a conservative **10-second receipt freshness threshold**, not a measured latency guarantee. Source timestamp meaning remains explicit: PMUS last-change time is not receipt latency; Kalshi meaning can remain unknown. Saved data is always ineligible as a current opportunity. Every candidate's own leg timestamps must pass freshness, even if another side has a newer quote.

Money values cross the API as Decimal strings and are displayed unchanged; browser arithmetic is confined to age/control presentation. Live fee diagnostics may use an explicitly hypothetical one-contract calculation. Unknown sizing, fees and material outcomes are not converted to zero. Profit/ROI remain unknown when required outcomes are unknown. Depth uses at most 64 allocations per candidate within the small configured universe, only on demand; the selected candidate's saved result exposes grid/search/optimality limits. Missing live grids produce **No sized result**; zero allocation is only the no-trade alternative. Related candidates share liquidity and are never summed as independent capacity.

Raw/normalized observations, matcher/fee inputs, calculations, curated views and coverage use existing Slice 12 storage APIs. The prior schema/migrations and economic engines are unchanged. Adapter observations include repeated/invalidation images, so their count differs from exchange stream messages. Raw preservation is not proof of every wire frame or complete event recovery. History shows at most the first 100 samples and true first/last bounds across all retained samples. Neither those bounds nor time between samples establishes opportunity survival. No retention deletion is automatic.

ProphetX remains partial (sandbox/unsized); Novig live access remains unavailable. They are visible and do not block Kalshi/PMUS. Existing settlement, fee applicability, unit/minimum/increment, lock, actual-fill and continuous reliability limitations remain unresolved.

## Historical verification and observed results

See `evidence/slice-13/verification.json` and individual logs. The final verifier passed JavaScript syntax, **340 offline tests**, **32 real PostgreSQL integration tests**, and **all twelve existing examples**. Dashboard tests cover double-start, quiet discovery/stream deadlines, queue overflow, cancellation, slow workers, stop/journal behavior, origin/Host controls, Decimal serialization, mode isolation, stale/disconnected eligibility, exact saved replay and history bounds. PostgreSQL tests include an actual terminated writer connection and incomplete-session behavior in disposable databases.

Final actual live session: **ecb8e401-cb51-46fb-8542-0347ea0c5950**, started **2026-09-13T00:00:17.441470+00:00** (see saved state for exact timestamp), stopped at its 60-second deadline. Both existing named Keychain credentials worked. Current discovery selected four markets, with Atlanta/Pittsburgh shared across venues and a Baltimore/Indianapolis PMUS market. **22 stream messages, 64 retained observations, four related comparisons, two conditional calculations, zero qualified opportunities.** Shutdown recorded zero queued unprocessed observations. All **34 saved calculation audits**, including on-demand live depth, replayed exactly. This is bounded technical evidence, not continuous feed qualification or owner acceptance.

Earlier verification runs remain retained: a development queue-limit gap, a completed 60-second run, an owner-stopped live run, and synthetic runs including an incomplete run during database verification. The queue was increased from 8 to 32 and canonical event selection corrected before the final run. Browser checks caught and fixed a JavaScript label syntax error. A later clean synthetic run verified changing positive/nonpositive conditional prices, depth, discrete history, stop and saved browsing. No synthetic result was promoted into Live.

Browser evidence covers initial controls, real updates, useful zero-opportunity tables, market/candidate details, depth and unavailable results, disabled Start/Stop states, saved sessions, event/search filters, empty filter recovery and a safe database error. Desktop viewport was 1360×980; narrow viewport was 390×844. Narrow tables scroll horizontally within their panels; details fit the screen, and page width remains 390 pixels. Use the viewport screenshots as the visual reference; full-page browser stitching can duplicate scrolling table content.

Artifact identities are in `evidence/slice-13/manifest.json`; preservation checks compare 590 prior implementation/test/evidence files and PLAN.md against their pre-work hashes. Credentials are excluded from hashing and evidence. No prior evidence, original plan, core economic implementation or historical session was deleted. No commits, pushes, publishing, trades, funds, purchases or contacts occurred.

**Next action:** follow the [current personal-prototype tracker](/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md). The next small implementation is truthful saved-status/coverage presentation in 13C; strict performance qualification is deferred. No live verification was started in this repair.
