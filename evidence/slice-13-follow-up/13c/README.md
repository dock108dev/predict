# Slice 13C — saved-session status corrected

Completed September 14, 2026 UTC. Focused implementation and isolated verification complete; owner use and live verification remain separate.

The picker, saved-session summary and market/comparison details now use the same read-only lifecycle/coverage interpretation. Stored `complete` is preserved independently of capture completeness. Both legacy IDs display **Saved with capture gaps**, with 32 unprocessed and unknown rejected/message counts. Failed, interrupted and unfinished records retain their distinct lifecycle; missing evidence does not become a clean capture or invented terminal outcome. A normal bounded ending and `continuous_coverage=false` alone do not prove lost observations.

The summary reads every saved coverage event even when the evidence list displays only 100. Recorded counts are snapshots (maximum known values, never summed across duplicate events). Retained observations are counted from that session's receipt rows. New terminal accounting saves its own stream-message count; older absent counts remain unknown. Saved origin says “Captured from a live feed”; current status says “Saved observations—not live.” Existing eligibility and mode separation remain intact. The 13B capture/compute/drain behavior is unchanged; its sole controller change adds the message count to existing terminal accounting.

## Verification

- [26 focused offline/dashboard tests](offline.log), including clean bounded shutdown, actual retained legacy evidence, failure/interruption, unfinished records and missing coverage.
- [8 disposable PostgreSQL tests](storage.log), including summary agreement between picker and details, gap evidence beyond the 100-event display limit, session-specific receipt/message counts, real Controller Start → updates → Stop → reopening and saved ineligibility.
- JavaScript syntax and [focused DOM assertions](ui-unit.log): a saved session with 7 messages stays at 7 while another active synthetic session has 999; missing saved messages stay unknown.
- Isolated browser at port 8873: both legacy picker entries and summaries inspected; synthetic retained observations increased from 10 to 22, manual Stop settled, reopening showed 22 receipts / 0 stream messages / 0 unprocessed / 0 rejected and “Stopped by owner.” Saved comparison details agree. No browser console errors. [Saved readback](isolated-saved-results.json).
- Screenshots: [legacy picker](legacy-picker.png), [legacy summary](legacy-status.png), [second legacy](legacy-second.png), [synthetic updates](synthetic-updates.png), [reopened](synthetic-reopened.png), [details](synthetic-details.png).

The legacy UI fixtures contain status evidence only, not reconstructed owner receipt rows; their zero receipt count in screenshots is a disposable fixture count, not an assertion about the owner's saved observations. The first fixture derives from retained owner-review JSON; the second derives only the recorded ID, time, lifecycle, stop reason and backlog from the Desktop tracker's historical review. No missing legacy counters were inferred. The earlier clean deadline fixture comes from retained Slice 13 evidence. Original owner evidence was not edited.

[Exact candidate](candidate.json) SHA-256: `66af90a9384e2d01304d18e6183c07c4e34b34f96f57deb7c4b99592f2207fcc`. It lists all application/test files and exact changed/added paths. [Verification](verification.json) and [before identities](before.json) confirm all **816** pre-existing evidence/PLAN artifacts are unchanged. The source tree is untracked in the parent repository; no commit identity is claimed.

[Isolated harness](isolated_check.py) patches all storage connectors to a disposable socket-only PostgreSQL cluster, changes only the test server's port/Host allowlist in memory, and rejects Live starts. Tests never used the owner connector. The isolated server was stopped and its cluster removed. No credentials, venue requests, owner database access, owner app restart, live feeds, trading, publication, commit or push occurred. PLAN.md and the revised plan remain unchanged. Existing aiohttp AppKey warning is informational.

## Remaining limits and next action

Unknown legacy counts cannot be recovered from missing evidence. A bounded successful save is not continuous-feed coverage or proof of profitability. Strict cadence/performance matrices, redesign, profit sorting, always-on capture and further slices remain deferred.

Next practical action: a separately authorized short owner try of this candidate's Start → inspect → Stop → saved reopening flow, including the saved status explanation. The owner app has not been restarted to load this candidate. Stop here; subsequent owner feedback should guide further work.
