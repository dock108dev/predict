# Usability and performance sprint — November 18, 2026

## Scope and evidence boundaries

This sprint addresses the nine findings in the owner's five-person simulated
study, plus measured read performance and a final read-only liquidity assessment.
The study did not establish executable live arbitrage. The working copy remains
on `main`. Existing Novig/ProphetX percentage-format edits and their tests are
preserved and integrated. No local collector starts during snapshot development.

Before implementation, a public Opportunities response was retained privately:
HTTP 200, 495,028 bytes, 5.747 seconds, 71 rows (61 Novig, 10 ProphetX).
The documented `scripts/dev-snapshot pull` then completed a consistent private
server dump and restored the separate read-only cluster. Dumps and raw response
evidence remain outside Git under `.local/` or `/tmp/`; no account ledger,
credential, Stop choice, source pause or unresolved exposure is replaced.

The owner's 100 ms feedback, 200 ms selected-comparison shell and two-second
ordinary-results targets are proposed engineering budgets, not release gates.
Evidence needed is comparable request timing, actual browser behavior, exact
source clocks and recovery under authored failures. Stop a check when it proves
the changed behavior; no new fixed-duration observation window is imposed.
GitHub's existing source, browser, portable, SQL and image/deployment checks
remain separate required repository workflows.

## Findings and implementation

| Study finding | Change and verification |
| --- | --- |
| Arbitrage stays loading | Versioned cancellation, request deadlines and explicit loading/loaded/empty/partial/failed states. Server work is bounded separately from the browser. |
| False “no other sportsbooks” before response | The selected quote appears immediately with “Comparison is incomplete.” Absence is stated only after a successful complete read. Failed reads retain prices with unverified status. |
| Old and mixed-age positive comparisons | Each venue exposes original quote and reference age beside prices/EV; unknown clocks stay unknown. Historical and mixed-age evidence is highlighted. Recalculation and refresh never replace source clocks. |
| Repeated Kalshi fee labels | Acquisition fee is explicitly included in upfront cash; additional settlement charges and outcome total fees are separate. A $6.35 acquisition fee with no settlement charge remains $6.35 total in each outcome. |
| Mobile close control moves | Fixed dialog shells keep headings/close controls outside independently scrolling content. Touch gestures scroll content without background leakage. |
| Parent results jump after nested dialogs | Preserve page and parent-content scroll, filters and trigger focus; restore after native dialog close handling. |
| Shopper has to find the comparison route | Main-line picks on Browse game cards now open exact comparison directly; All game lines remains available. |
| Practice hidden when live board is blocked | Practice is in main navigation and loading/error/empty recovery paths, explicitly labeled synthetic. |
| Dollar payout explanation buried | Comparison begins with stake/purchase → committed cash → total winning receipt → net profit, followed by fees and conditional EV explanation. |

The original `$6.35 / $6.35 / $6.35` labels were not evidence of three charges.
The stored cashflow has `entry_usd`, separate `settlement_fee_usd`, and
`total_fee_usd` inclusive of acquisition. The shared `pregame-evidence.js` reads
these existing fields instead of changing financial arithmetic.

One normal local browser example is Philadelphia Eagles +199: $100 stake,
$100 committed, $299 winning receipt and $199 profit. Its original quote and
reference ages remain visible. This real stored-price example proves presentation,
not currently fillable size. A separately labeled Practice pair demonstrates both
legs, fees, funding and the lowest modeled completed-game payout.

Missing-reference prices remain inspectable through Browse/game/comparison with
null EV and the stored refusal reason. They are not zero-EV estimates and cannot
be saved as complete EV journal entries.

## Technical principles

Request identity governs publication: a response may update the page only while
its version still matches the active filter/request. Aborting transport alone is
insufficient, because an obsolete response can race with cancellation. Likewise,
a browser deadline alone does not stop background server arithmetic; SQL and
Python work need their own bounds.

The actual snapshot browser exposed a failure absent from initial fixtures:
the server's Content Security Policy rejected restoring saved styles through
`body.setAttribute('style', ...)`. A second dialog close could leave background
scroll locked. Restoring individual CSSOM properties preserves the prior styles
under that policy. The regression fixtures now carry the real CSP. Native close
events are asynchronous, so restoration checks wait for the app's unlock state
rather than treating trigger focus alone as completion.

The first hosted Linux browser run exposed a second touch difference: tapping a
button need not make it `document.activeElement`. Saving active focus could
therefore save the game-close button instead of the tapped quote. Dialog openers
now pass `event.currentTarget`, and restoration searches the saved parent for a
replacement with the same focus identity if a late response replaced the node.
The regression reproduces absent native focus and both before/after-close response
orderings without weakening its original focus or scroll assertions.

The 15-minute historical-input caution follows the existing
`CURRENT_DESK_MAX_AGE_SECONDS` display convention. It does not remove retained
pregame prices or establish execution authority. Sporting eligibility remains
server-owned, and source timestamps remain evidence rather than refresh clocks.

## Verification and delivery

See [performance and backend evidence](usability-performance-20261118.md) and the
[liquidity assessment](liquidity.md). Focused backend checks
passed 23 unit tests and 29 PostgreSQL tests plus two subtests. The package build
and isolated installation passed; frontend composition/drift, Ruff and maintained
documentation references passed. Focused browser checks cover deadlines,
out-of-order replies, failed refreshes, exact-line absence, null EV, retained
DOM identity, repeated/nested dialogs and touch gestures.

The broad local browser run initially passed 65 tests and failed two first-use
checks: their old helper opened More before selecting the newly promoted Practice
link, leaving the dropdown over the navigation link. That failure is retained
with the final corrected-path result in the local report directory.
The two corrected desktop/mobile first-use cases passed in 10.28 seconds; combined
with the prior 65 passing cases, all 67 browser cases have passing local evidence.
The direct navigation expectation now follows the owner's explicit discoverability
scope, while More retains a secondary Practice examples link. The three-minute
broad run did not need repeating for that navigation-only correction.

Post-change actual-data browser observations: Opportunities first/repeated
903/241 ms; Browse first route/repeated 837/411 ms; selected comparison shell
15.6 ms; completion after shell 84 ms; all 78 game lines 158 ms; search feedback
0.3 ms and results 384 ms including debounce; market/league filters 79/57 ms;
refresh/return 84/69 ms. Browse reused shared assets. Arbitrage browser visits
took 81/43 ms against warm server calculations; these do not replace the measured
2,235 ms cold calculation cost. Raw timings and screenshots remain under
`.local/usability-sprint/`.

The final owner handoff records the pushed SHA, hosted CI, deployment workflow,
installed commit and deployed browser/API results separately; local evidence is
not substituted for any of them.

Initial deployed commit `adead29` did pass image smoke tests and all five normal
deployed persona paths, but its cold live-Arbitrage requests returned explicit
503 timeouts. That prevented completion. Profiling isolated the eight-second
failure to SQL eligibility, before any pairing arithmetic: pending reference jobs
caused repeated payload decompression. The equivalent indexed reference-ID join
reduced that statement to 474 ms in the same deployed read snapshot. Positive-bet
group filtering and paging game identities before JSON aggregation also reduce
unneeded work while preserving full eligible results. The follow-up source checks
pass 30 SQL tests plus two subtests and 23 unit tests. Installed final-SHA behavior
and the new Linux hosted run remain separate evidence in the final handoff.

Mobile evidence uses Chromium touch emulation and dispatched touch gestures,
with focused keyboard input. Physical iOS/Android software-keyboard resizing
cannot be established by that environment and will be reported separately.

Review decision: Browse must hide prices without complete EV | prior test expectation superseded by owner sprint scope; blocks desired browsing | updated assertions to require null EV and actual reason while retaining the positive-opportunity rule.
