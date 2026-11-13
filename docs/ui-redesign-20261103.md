# Approved Predict interface — November 3, 2026

The owner-approved [November 12 interface direction](live-comparison-plan-20261104.md#november-12--compare-every-venue-on-the-line)
governs the ranked dashboard, game view and concise financial inspection. The
November 3 design record below remains the dated approval.

## Current planning authority — November 4, 2026

The owner has since selected grouped book rows, after-fee outcome ranking, an automatically updating list and a pinned math drawer. See [November 4 decisions](live-comparison-plan-20261104.md). Keep this approved November 3 record as historical evidence. The requested new visual polish is a proposal, not a retroactive change to this approval.

## Decision and next owner

The owner approved the revised navy/teal, Manrope design after reviewing its
opportunity feed, game view, Admin, Why explanation and global odds switch.
[Implementation is integrated locally](ui01-delivery-20261103.md). Design approval is complete. Acceptance of the running
implementation, financial completeness and live source qualification remain open.

**UI01 lead — Staff Product Engineer, frontend/UI and full-stack integration.**
The lead owns the end-to-end installed outcome, including necessary Python API
work, accurate presentation, local build/restart and browser verification.

The [implementation brief](ui-redesign-implementation.md) records the implemented scope.
The [approved standalone preview](design/approved-20261103/preview.html) preserves
all three screens and their local interactions. The [source fragment](design/approved-20261103/source.html)
is the editable visual reference. Both are repository copies of the approved
revision. The standalone preview may be opened directly or served locally.

These files contain a small recorded-price sample and simulated controls. Use them
for layout, typography, hierarchy and interaction direction. Production uses actual
API data, all configured scope and working controls. External font loading in the
preview is a design convenience; deliver the chosen typeface reliably with the app.
Manrope is the approved default. DM Sans was an optional preview control.

## Product identity and screen hierarchy

The owner's ambition is the “Statcast of prediction dashboards.” Predict has its
own identity, modern visual restraint and useful sports/market analysis depth.
Apple websites informed visual quality; OddsJam, Action Network, DraftKings and
Polymarket informed information needs. This decision adds no new history feeds or
advanced analytical metrics to the current product scope.

- **Opportunities** is the opening screen. Strongest available opportunities lead
  across games. Core fields are game, position, venue, price and estimated advantage.
  Present distinct positions separately and both legs of a two-position result.
- **Markets** is the secondary game-exploration path. Show winner, spread, total,
  alternate lines and venue comparisons, with an estimate and Why where supported.
  Keep exact native sides and settlement distinctions readable.
- **Admin** contains source operation, collection Stop/resume and pauses, Coverage,
  usage/budget, quote timing, calculation settings and precise source inspection.
  Lead with what needs attention and the affected source. Full diagnostic records
  and internal IDs remain available through focused inspection.

Retain compatibility with saved result/game links and useful old route entry points.
Existing EV/opposing-result functionality must remain reachable within the new
navigation. Incomparable metric bases require an explicit view/filter/label and
ranking within that basis. Do not rank a gross EV and a scenario minimum as if they
were the same measure. Preserve positive, zero, negative and unavailable outcomes
and access to unmatched prices. The mockup's five rows are a sample, not the product
universe or a ranked top-five proof.

## Visual and interaction requirements

Use the approved navy header, teal emphasis, lightly tinted surfaces, Manrope
letterforms and clear numerical alignment. Keep restrained color for meaningful
states. Useful opportunity content must appear in the initial viewport, including
at the owner's approximately 600 × 602 window. Avoid oversized setup panels,
repeated explanations, hash fragments and diagnostic prose in ordinary rows.

Use concise filters and search. Search resolves full team names and supported
abbreviations, including Baltimore and Ravens. Carry the selected game, market,
filters, result revision, odds preference and useful scroll/focus context through
navigation and back. Choosing a price or Why must retain its exact selected inputs.

Each actual control must perform its named action. Preview-only behaviors, fixed
rows, canned status and placeholder alternate markets must be replaced by the
existing app's real APIs and complete pagination. Read, filter, sort and inspection
operations do not initiate provider acquisition. Refresh has visible completion or
failure and preserves the prior comparison while working. Assumption changes in
Admin recalculate a consistent captured result and return the user to that result.

## Why an advantage exists

Why expands beside the selected opportunity and is also available in its game.
Lead with offered odds, estimated fair odds, reference basis and expected dollars
per $100. Explain what the displayed percentage means in ordinary language. Make
the $100 win/loss breakdown available as a secondary disclosure. The example is a
normalized explanation, not an overwrite of the user's funding setting.

For the saved Winnipeg −2.5 example, the authentic captured inputs are Novig 8.33,
Pinnacle 6.90 and 1.11, benchmark probability 37/267, and gross return 4121/267 percent.
American presentation gives offered +733, estimated fair +621.62, a 13.86% decisive
benchmark chance and $15.43 expected profit per $100 before fees. Convert for
display from precise inputs. Rounded display values must not become new inputs.

Use each metric's actual meaning. Gross EV, conditional net EV and an opposing
scenario minimum need their appropriate explanation. The $100 example excludes
fees and other settlement outcomes when its gross decisive basis does. Missing
benchmarks/fees/sizing or unknown outcomes stay unknown. An unavailable estimate
should explain its relevant missing input briefly without hiding its price.
The [calculation basis](benchmark-ev.md) remains the financial authority.

## One odds-format preference

American odds are the default. One app-wide American/Decimal control applies to
opportunity prices, market comparisons, offered and fair odds, Why text, source
benchmark prices, and formatted Admin calculation inspection. Persist it across
navigation and reload. Currency, probability, percentage, spread and total values
retain their units. Raw original records preserve their literal units and precision
under an explicitly labeled original-record disclosure.

Reuse the existing canonical conversion and exact-number owners. The toggle
changes presentation only. It must not recalculate probabilities from rounded
American odds, alter ranking or introduce a second financial engine in the client.

## Timing and currentness

The rejected “3h” label measured time since a provider market-update timestamp.
That field did not establish the last price change or latest successful check.
An unchanged price can be current when supported by a fresh confirmation.

Move detailed clocks to Admin and distinguish provider update, source confirmation,
local receipt, last price change, capture and calculation time. If a clock is not
supplied or established, say so. A heartbeat, successful UI read or newer capture
must not imply a fresh quote. The saved Winnipeg example has provider market update
15:46:02 Eastern, receipt 15:46:23 and capture 17:20:04 on November 3; last price
change and latest successful check were not established by that capture.

Ordinary views keep a concise delayed, saved or unverified state when material.
Only show updating/current when existing quote-specific evidence supports it.
Neither a clock relocation nor an approved mockup qualifies the underlying feeds.

## Completion and verification

UI01 is complete when the approved experience runs through normal entry points in
the sole main checkout, using authentic available data with working Admin and
refresh/recalculation controls. Build and restart locally as needed. Existing
account, quota, reservation, hold, Stop and source-pause guards remain authoritative.

Verify these journeys in the actual running app and report observed results.

1. Open Opportunities and see useful results before a setup wall. Check the first
   viewport at desktop, approximately 600 × 602, and 390px, with readable focus,
   keyboard actions, long names, increased text and no horizontal page clipping.
2. Open an opportunity, inspect its game and alternate lines, then return without
   losing selection or filters. Confirm Baltimore and Ravens find the same game.
3. Open Why. Check the Winnipeg example independently if its retained revision is
   available, and a current authentic example. Verify missing-input explanations
   and distinctions between single-position and two-position metrics.
4. Switch American/Decimal and traverse all three destinations, including Why and
   Admin inspection. Confirm numbers, ranking and original-record precision.
5. Inspect Admin Coverage, usage, source status and clocks. Verify control routing
   and protected-state preservation with suitable disposable tests where needed.
   Avoid changing the owner's collection preferences merely to demonstrate a UI.
6. Exercise refresh/recalculation success and failure, stale/saved inputs, empty,
   unavailable, zero and negative results, pagination and late responses. Use
   clearly identified fixtures for states absent from authentic data.

Run proportionate affected tests and the repository's required checks. Preserve the
existing two-second useful-page target and report actual timing. Attach or link
screenshots of the integrated feed, game/Why and Admin at desktop and narrow widths.
Distinguish verified behavior, known defects and remaining source/math limitations.
No new mockup approval is required to begin. Owner acceptance of the implementation
remains a later review of the running product, after all engineering in the agreed
product scope and engineer-led integration checks are complete. Do not request
interim owner reviews to continue known engineering work.
