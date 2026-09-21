# Isolated ordinary-product browser verification

Observed September 21, 2026 through the Codex in-app browser at localhost:8795. No venue access; fixture-only preview and output. The existing beta was not used.

- Explicit Start with 60-second fixture duration; current ordinary dashboard displayed six comparison pairs across Kalshi, Polymarket US and Novig. ProphetX visibly unselected.
- Novig native-shaped .55 bid and 300 payout cents supplied the opposite purchase ask .450 and 3 contracts. Missing opposite liquidity remained unavailable. Net results stayed unavailable with concrete synchronization, timing, fee and listing-rule reasons.
- Clicked Stop around 26 seconds; displayed observations frozen, then feeds stopped. Saved scan reopened six pairs at its retained cutoff.
- Narrow layout inspected visually and DOM overflow checked during the initial run; no horizontal overflow observed. Screenshot viewed inline; no screenshot artifact is claimed.
- Final implementation reopened this retained scan without Start. UI displayed synthetic saved, Idle / feeds stopped, synthetic production-shape Kalshi/US, synthetic QA-shape Novig stopped, dated REST snapshot and ProphetX unselected. Prices .450 and size 3 remained visible with unavailable net results.
- Verification tab closed and isolated preview stopped after review.

Run: `26d86fba-9261-4abf-8519-67131d2ef11c`. The retained package is [here](browser/sessions/26d86fba-9261-4abf-8519-67131d2ef11c/report.json). This verifies fixture product behavior, not native access, owner acceptance or production qualification.
