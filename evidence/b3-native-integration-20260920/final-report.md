# B3 engineering handoff — IN PROGRESS

September 21, 2026. **B3 NOT COMPLETE. Beta NOT READY FOR SIGNOFF.** No new authenticated venue access or external market collection. No commits, pushes, provider messages, trading or publication.

## Exact implementation

B2's 24 recorded implementation hashes matched the starting working tree with zero mismatches. [Starting identity](baseline.json) and [current implementation identity](implementation-identity.json) distinguish existing uncommitted B2 work from these B3 edits. Retained earlier evidence was not rewritten.

The existing collector now accepts explicit four-source states and integrated Novig/native REST plus provisional unselected ProphetX producers. Normal product rows, source health, unsupported catalog listings, original values, dated updates, shared history and Stop are wired through B2. US Short and Novig complementary purchase quantities are opt-in and independently checked. Unknown fees, settlement, clocks and usable size remain unavailable. See the [implementation and per-venue matrix](../../docs/b3-native-integration.md).

## Verification

| Evidence | Result and boundary |
|---|---|
| [CI](verified-ci.txt) | 46 existing tests + 18 B2/B3/projection tests PASS; both UI checks PASS; compilation and JavaScript syntax PASS. Includes existing 18-Arb/96-EV reconciliation. |
| [Native and lifecycle](verified-native-lifecycle.txt) | 124 tests PASS: Novig, ProphetX, retained sandbox replay, US, coverage, continuous and segmented B2 lifecycle/history. |
| [Final cleanup regression](verified-final-cleanup.txt) | 18 B3/B2/projection tests PASS; final source shutdown reporting fix explicitly checks Novig disconnected, adapter closed, unchanged saved cutoff and late observation rejection. |
| [Browser observations](browser-verification.md) | Ordinary current / Stop / saved flow, six synthetic pairs, unselected fourth source, honest unavailable economics; final implementation also reopened retained scan idle. |
| [Retained browser replay](browser/sessions/26d86fba-9261-4abf-8519-67131d2ef11c/replay.json) | 25 Kalshi + 25 US native fixture books and 3 Novig REST books reconstructed exactly. No production inference. |
| Native arithmetic | Published Novig 45,000 payout cents at .36 -> 450 opposite contracts at .64 ($288); fractional US Short from retained production Long bids; historical ProphetX +146 / -164 unsized prices remain dated sandbox observations. |

The browser capture predates the final shutdown-report label repair and scope validation corrections. Its retained report still records Novig's last connected state; it is not rewritten or relabeled as final-candidate collection. Final saved UI explicitly displays stopped, and the final focused test verifies final-candidate shutdown reporting. The production proposal must bind a newly frozen implementation before any real attempt.

Earlier failing local test logs remain retained: fixture bookkeeping, replay receipt formatting, deterministic source ordering and native league-conflict handling were corrected. Their failures are not promoted to successful qualification. Final passing logs above supersede only their engineering checks.

## Remaining gates and next actor

- **Owner:** select ProphetX or another fourth venue; confirm Novig provisioning, issued environment/access documentation and local credential reference only. No secrets in chat.
- **Engineering:** native listing-period/rule association remains unverified for real Novig. Determine production tournament identity for the selected fourth source from issued access. ProphetX quantity/value ownership remains unknown; unsized prices are displayable but not sized opportunities.
- **Engineering then owner:** finalize the one [bounded qualification proposal](../../docs/b3-native-qualification-proposal.md), freeze exact spec/candidate/output/window and obtain the requested single approval before any authenticated access. The current proposal is not approved or executable authorization.
- **Real B3 exit:** all four production sources, useful ordinary overlap, correct native interpretation, supported dated updates, Stop/cleanup and exact reopening. No such B3 session has occurred.

Independent next work available: native listing-period/rule association from official contracts and retained data, focused additional sport-scope cases, and native REST replay across segmented packages. Current B3 native REST explicitly supports the shared flat journal; B2 segmented behavior remains supported and regression-tested. B4 owns model/Pinnacle acquisition; B5 owns broader sport/period/futures matching and economics.
