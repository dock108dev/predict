# First engineering prompt — D1 coverage inventory

Implement D1 of `/Users/michaelfuscoletti/Desktop/prediction-arb/docs/data-coverage-plan.md` in `/Users/michaelfuscoletti/Desktop/prediction-arb`.

Read the current Desktop tracker, the D1 plan, applicable repository instructions and the current architecture/SSOT. Preserve existing work and evidence. This is an implementation task: deliver working offline coverage inventory tooling, not another proposal.

Start with the existing Kalshi and Polymarket US NFL pregame full-game winner scope. Build a per-venue event/market catalog before cross-venue intersection or scan selection. Include unmatched events, unresolved identities and unsupported purchase sides. Reuse native adapters and normalization/matching. Keep discovery completeness and pagination/truncation explicit; the six-game scan limit must not define the inventory.

Deliver a reproducible local command and saved coverage report showing each venue's discovered/in-scope events and markets, matching status, supported sides, exclusions and collection status where known. Counts must reconcile and distinguish events from markets and sides. Retain native identifiers, schedules, provenance and retrieval times. Use retained raw data where available and isolated fixtures for absent cases. Label old, partial and synthetic inputs honestly; report unavailable current coverage instead of inventing counts.

Check current official public documentation and existing adapter evidence for relevant discovery/subscription limits. Public documentation research is permitted; no authenticated requests, credential reads or fresh venue market-data collection. Document any difference between documented and observed support.

Add focused checks for pagination/truncation, duplicate handling, unmatched events, unknown identities, unsupported sides and count reconciliation. Keep original calculation inputs and saved evidence unchanged. Do not add broad infrastructure qualification.

Write a concise D1 report with exact input/code identity, changed files, command usage, actual coverage findings, tests and remaining gaps. Recommend concrete D2 discovery/subscription/resource bounds and one D3 persistence path based on existing code. Update the tracker and plan with actual D1 status and the next bounded D2 task; do not claim current full live coverage from offline evidence.

Authorized scope: local code, fixtures/tests, reports and documentation plus official public documentation research. Do not restart the beta, migrate a database, enable background collection, access credentials, collect new market data, trade, commit, push or publish. Stop after D1 and report what is ready for D2.
