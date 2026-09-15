# Owner try preparation — September 15, 2026 UTC

**OWNER TRY READY — User starts a bounded scan, inspects updates, manually stops, and reopens the saved session.**

Dashboard: http://127.0.0.1:8765/ — open in the app, Live selected, Ready to scan, 60-second maximum, up to two markets per venue. Start is enabled; Stop is disabled. The agent did not click either control or operate the owner review.

## Exact candidate and reconciliation

All 103 application/test/fixture files match the retained [13C candidate](../13c/candidate.json), SHA-256 `66af90a9384e2d01304d18e6183c07c4e34b34f96f57deb7c4b99592f2207fcc`. No intervening application changes or extra source files were found. Relative to 13B, the six changed files and four additions are exactly those recorded by 13C. No applicable AGENTS.md was found in the repository or its ancestor directories.

[Prepared candidate](prepared-candidate.json), SHA-256 `1579e314fb09dc38198d1160cbfb8bc23375acfc90819cbadc770d65ce10f582`, additionally identifies the lifecycle scripts and project metadata. The only executable preparation change is `scripts/dashboard start-existing`: check that the existing PostgreSQL process is running and launch the app without setup or migrations. README documents this procedure. Application code is unchanged. The parent repository still has the project untracked; no commit identity is claimed.

## Verification and evidence reuse

The exact-source [13B verification](../13b-cadence-repair/verification.json) and [13C verification](../13c/verification.json) are reused: 365 offline/42 storage checks for 13B, followed by 26 focused offline/8 disposable PostgreSQL checks and JavaScript syntax/DOM checks for 13C. The retained isolated browser evidence covers synthetic Start → updated observations → inspect → manual Stop → saved reopening, truthful gap/error lifecycle interpretation, and saved ineligibility. These behaviors are unchanged; no new synthetic run, full suite or performance matrix was warranted.

New [lifecycle checks](lifecycle-checks.json) passed app-only dispatch, refusal to launch when PostgreSQL is not running, and shell syntax. A disposable temporary harness used command stand-ins and was removed; it did not use a database. No new disposable PostgreSQL cluster was necessary.

## Restart and initial interface

Immediately before restart, old PID 43541 reported stopped synthetic collection, queue zero, no depth work and stopped venues. Its previously retained synthetic session was not replayed or changed. The supported stop command exited cleanly; `start-existing` launched PID 30583 against the existing running database. [Restart evidence](restart.json) confirms the served HTML, JavaScript and CSS hashes exactly match 13C. This interface has no explicit release-number badge; candidate identity is established by exact source and served-asset hashes plus the fresh process, not an invented UI version label.

[Initial interface](initial-interface.png) and [accessibility state](initial-interface.txt) show Live, Ready to scan, enabled Start, disabled Stop, no observations and zero current opportunities. [Browser warnings/errors](browser-errors.json) are empty. The backend reports `idle`, no session, no messages, no queue and no depth activity. [Network snapshot](app-network-snapshot.txt) shows only loopback listener/browser connections; source inspection confirms producers and credentials are reached only after Start. No automatic collection or venue request occurred.

## Owner data and preservation

Before/after read-only repeatable-read fingerprints match across all 11 public tables, including schema migrations: 28 sessions, 459 receipts and 90 coverage events. All 833 pre-existing evidence/PLAN files match their before hashes. No migration, repair, replay, insert, update or deletion was performed on the owner database.

[Read-only legacy status](read-only-legacy-status.json) confirms both original live sessions now return Saved with capture gaps in picker and details, each with 32 unprocessed observations and unknown rejected/message counts. Their actual retained receipt counts are 22 and 40 respectively. Both have zero current opportunities and all saved quotes remain ineligible as current. This is read-only engineering inspection, separate from owner review.

## Limits and stop boundary

[Verification summary](verification.json). Local synthetic evidence does not establish live reliability, owner acceptance, continuous capture, fee/settlement/sizing completeness, known source times or profitable fills. Unknown values stay unknown; zero qualified opportunities remains valid. ProphetX remains partial and Novig unavailable within this two-venue scan. Strict 250 ms qualification remains deferred with prior failures preserved. No substitute timing gate, redesign, profit sorting, always-on collection, Slice 14, credentials access, venue requests, live scan, owner review, orders, commit, push, publication or automation occurred.

Preparation is complete. The next action belongs to the owner; do not start collection or further development automatically.
