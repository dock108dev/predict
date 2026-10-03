# Predict usability and live-data audit

October 2, 2026, America/New_York. **Current presentation rejected by the owner. The guided walkthrough is stopped.** This audit and the [usability sprint plan](usability-sprint-plan.md) replace the saved-workflow walkthrough as the next engineering work. Application implementation is unchanged in this pass.

## Reviewed identity and evidence

The reviewed checkout is `/Users/michaelfuscoletti/Desktop/prediction-arb`, HEAD `f3c2a299af22bd2c1c408e0f2a7265786663002b`. Canonical application SHA256 is **`893a457d928a32de3514c8a5761bba8f015774587c4c4b13db3fdc2dce74ae83`**, calculated using `native_approval.implementation()` and its compact sorted-JSON digest over 649 `.py/.js/.html/.css/.json` files. Initial walkthrough preparation also recorded an all-file tree digest `dab2734548bb90162fe5eae823baf10eadeac764e20bb4da382a3186e36bfaab` over 655 files; that is a different manifest, not the canonical approval hash.

The October 1 beta candidate `2b3b9330…` and its checks remain historical and distinct. No old qualification, owner acceptance, production readiness or source uptime transfers to this checkout.

Preparation used the ordinary launcher. The verified September 26 process was idle, inactive, had no current session and reported completed cleanup before restart. The newly launched process at `http://127.0.0.1:8784` is idle with live Start disabled. Saved data and existing watch storage were preserved.

Session `offline-v1-repair-713fd0fa-20261001` visibly opened as Historical observations: four games, 18 price comparisons, zero return calculations. The owner selected NFL. A subsequent UI observation confirmed NFL selected and one game/six comparisons, including full-game and first-half rows. The owner reported the filter worked. These prices are historical and establish no current opportunity.

The audit inspected the landing/detail templates, comparison renderer, refresh/focus behavior, router, source owner, projection/persistence boundary, source-session policy and current operation/product/acceptance docs. Public reference inspection covered [Action Network's NFL board](https://www.actionnetwork.com/nfl/odds). [OddsJam's odds-screen address](https://oddsjam.com/odds-screen) redirected to the public OpticOdds product page; no authenticated OddsJam experience was inspected. Provider budget facts were checked against [The Odds API's official V4 documentation](https://the-odds-api.com/liveapi/guides/v4/).

No provider collection, credential resolution, purchase, trade, outreach, recurring automation, application edit or application test suite execution occurred in this audit. The page was read; the owner operated the NFL filter. Documentation checks do not constitute runtime qualification.

## Owner words

These are owner feedback/instructions, separate from engineering conclusions:

> There is still wayyyyyyy too much data on the page. the formatting is kinda stinky. its not for users thats for sure. the cards are impossible to figure out. I mean this is kinda bad....

> i mean look at odds sites. actionnetwork. oddsjams. etc... theres tons of examples out there from a sportsbook persepective that look good and work. we are just doing the same but with prediciton engines

Asked about American odds or prediction-market cents:

> we should have both

After selecting NFL:

> the filter works the page is still horrible

> we should stop the walkthrough and work on the major UI prod ready user ready not debugging design. and also data presentation. we shouldnt have start scan stop scan etc... the data should just flow and we dont need any historical data saved (for now) so we dont have to do anything crazy on data storage the scans were ok for testing but it should just be as close to real time as possible on the page. well have admin metircs and data for me but idk this thing as is is a fail

> and by work on i mean first lets audit and then get the docs and next steps in desktop updated to be (a) huge usability sprint(s)

> I am apprving all attempts to get the live data in full  as needed. if some is stuck record it and let me know what site the issues are and we will work on it.

> remember odds api is only 500 tokens a month right now so be cool with novig and prophetx for now in terms up like hourly update sor something to keep it lw. i assume kalshi and polymarket will be good though

## Findings and engineering interpretation

| Finding | Current evidence | Consequence and planned change |
| --- | --- | --- |
| U-01: Discovery/interpretation blocked | Owner screenshot and feedback; comparison panels repeat odds, implied percentages, unknown quantity, source/receipt ages, market state, links and long caveats | Treat as a major product usability failure. Replace the presentation hierarchy with a compact odds board; a CSS-only cleanup is insufficient. |
| U-02: Main workflow is a test-session console | `opportunity_static/dashboard.html` leads with Start scan, Stop, Refresh, saved scan, calculation settings, watch/history and import/setup tools | Ordinary users should open the board and see flowing prices. Put engineering operation and metrics in a separate admin surface. |
| U-03: Price units do not match owner preference | `opportunity_static/comparisons.js:displayedPrice` renders aggregate decimal odds plus four-decimal implied percentages; native prices use dollar strings | Display both American odds and cents compactly. Preserve original values, units and transformation basis. Label aggregate cents as equivalents, not actual executable contract prices. |
| U-04: Repeated pair cards fragment the game | NFL winner, total and first-half comparisons are distinct large rows; raw-gap ranking separates related outcomes | Group by exact event/period/market/line, outcomes in rows, venues in columns. Keep different lines and periods visibly separate. Better quoted price is distinct from best net return or EV. |
| U-05: Diagnostic language competes with prices | “Explicit acquisition cycle cap reached,” receipt/source seconds, “Market Unknown,” 751 references, and raw JSON are on or adjacent to primary results | Keep concise availability/age/material-rule signals on the board. Move transport details, counters, JSON and acquisition reasons to admin/evidence views. |
| U-06: Default selection prefers archive data | `multi_game_server.dashboard_payload` selects the active session or the last dataset; `datasets` includes retained captures and history paths | The future default board must select the running current-price view. No automatic fallback to saved/test prices when live data is absent. Use an honest connecting/unavailable state. |
| U-07: Automatic browser updates are only part of the loop | Browser already subscribes to `/api/updates` and polls active sessions at 1.5 seconds; server checks revisions every 25 ms and emits active notices at most about once a second | Reuse stable update/focus behavior. SSE is not proof of fresh provider data. A service-owned collector lifecycle and actual per-source acquisition are still needed. |
| U-08: Existing owner is deliberately finite | `CoverageOwner.start` admits up to 180 seconds in ordinary mode and consumes candidate-bound qualification authority; source settings cap refresh at 300 seconds | Hiding Start/Stop will not deliver continuous operation or hourly aggregate refresh. Add a distinct runtime policy; retain old finite qualification contracts unchanged. |
| U-09: Projection depends on durable acknowledgments | `SessionProjection` validates contiguous durable cursor; `CoverageOwner.current_snapshot` rebuilds from journal on projection error; finalization verifies/export manifests | No-history runtime needs an explicit bounded latest-state/projection boundary. Preserve exact identity/order and coherent Details without writing every observation forever. Do not simply disable file writes underneath the current owner. |
| U-10: Archive accumulation is unbounded across attempts | Each completed capture is saved; operation docs say no pruning; historical readers remain active dependencies | New ordinary operation should retain current state in memory plus small bounded operational configuration/budget records. Archive/replay remains a testing tool. Preserve existing records; do not migrate/delete them as UI work. |
| U-11: Aggregate cost is amplified by event polling | `source_session.cycle/event` discovers and requests selected events individually; `BOOKS` includes two comparison sources and three references | For common full-game markets, evaluate a shared per-sport response, not a paid request per event/venue/tab. Keep references optional and never comparison legs. Special markets have a separate small budget. |
| U-12: Budget is per session, not a monthly operating plan | Source-session budget/preflight exists, but no ordinary persistent 500/month aggregate operating allowance is wired | Add a small durable quota ledger, provider-header reconciliation, reservations and cross-process/tab deduplication before recurring paid polling. |
| U-13: Documented workflow is now superseded | Product/UI/acceptance docs still require visible saved selectors, manual Start/Stop and history reopening | Replace active requirements with the owner's current ordinary-user workflow. Preserve old results as dated engineering evidence. |

NFL filtering is a working component, not approval of layout, calculations or the app. The first task (choose a useful comparison and explain its prices) was not completed. Details, saved watches, history/download and exact bookmarks were not owner-reviewed. No acceptable-limitations decision or beta acceptance was given. The owner explicitly called the present product a fail.

## Live-data and cost disposition

The owner has now authorized the necessary live-data attempts and retries. Bind that instruction to fresh current-candidate attempt records; do not repeatedly ask for approval already granted, reactivate spent approvals, or use a sealed package as the new authority. The immediate task is documentation, so new collection was not necessary in this pass.

| Site/source | Intended current role | Audit disposition |
| --- | --- | --- |
| Kalshi | Faster native listings/books | Implemented native route exists. Current access, full supported overlap and sustained cadence were not freshly tested. Owner expects this to work; that remains an assumption until measured. |
| Polymarket US | Faster native listings/books | Same evidence boundary as Kalshi; retain US identity/orientation and exact source state. Do not substitute the international Polymarket API. |
| The Odds API → Novig | Slower budgeted comparison quotes | Shares the owner-reported 500/month allowance with ProphetX and any optional references. Current remaining quota/reset and present offerings were not checked. |
| The Odds API → ProphetX | Slower budgeted comparison quotes | Same shared response/quota; not a second 500-credit allocation. Direct native provisioning is not a prerequisite for this route. |

No newly tested site failure is being reported. Availability, authentication, quota and endpoint problems discovered during later attempts must be recorded individually, with the affected site, sanitized evidence, practical impact and smallest owner/engineering action.

Cost guidance: the provider bills usage credits, which is how this plan interprets the owner's “tokens.” Official docs charge selected markets and region-equivalents; up to ten named bookmakers count as one region-equivalent. A three-market, one-sport sport-wide refresh can therefore cost three credits for both comparison venues together. Hourly for 30 days is 2,160 credits; six such sports is 12,960. One three-market refresh every six hours is 372 credits over 31 days, before extras. These are conservative planning calculations, not current quota readings. Current per-event requests multiply costs; cheap operation requires addressing that path.

## Disposition

**Audit complete; usability sprint series planned, implementation pending.** Start with a complete sportsbook-style user-facing design and data-presentation contract, then implement the board, automatic native flow, budgeted aggregate flow, lightweight storage boundary and separate admin observability. Retain honest missing/stale/different-settlement states. [Sprint dependencies, acceptance and stop rules](usability-sprint-plan.md) govern the next work. “Production/user ready” is the target, not an achieved claim or authorization for remote deployment.

Documentation verification: `git diff --check` passes. Active local links in the audit, sprint plan, design, design requirements, acceptance, roadmap, coverage plan and Desktop handoff resolve. All eleven pre-reset documentation snapshots match their recorded hashes. Recomputing the canonical application manifest in the existing project environment confirms all 649 source files retain the reviewed digest above. Application tests and provider qualification were not run for this documentation-only change. The walkthrough record retains owner rejection, incomplete/unreviewed workflows and no acceptance.

Handoff cleanup on October 2: the active Desktop next-steps file now contains only current scope, U0–U6 status, standing source authority/quota, baseline identity and genuine remaining verification. The full prior tracker is preserved in a [separate historical archive](../../prediction_arb_history_20261002.md); old current/next-action headings are absent from the active file. Historical bodies were also removed from active roadmap/delivery documents into their existing pre-reset snapshots. The latest recorded local CI portability repair is completed, not current backlog; only its hosted Linux/locked-install verification remains unverified. The baseline record was read, not rerun.

Follow-on U0 execution: the [local synthetic preview, contracts, screenshots and coverage record](../evidence/u0-design-20261002/README.md) are now complete. The audit above remains a record of its original documentation-only pass. Current next action is U1/U2 under the updated sprint plan and Desktop tracker; U0 engineering checks do not supply owner acceptance or live-source qualification.
