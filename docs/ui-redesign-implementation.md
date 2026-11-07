# UI01 — implement the approved Predict interface

## Subsequent delivery

The [November 4 live-comparison plan](live-comparison-plan-20261104.md) updated
the design below. The [November 6 delivery record](engineering/live-comparison-20261104/L05-delivery.md)
covers the grouped live list, pinned drawer and their local verification.

## November 3 — integrated engineering verification

The ordinary snapshot product is implemented and integrated in the existing main
checkout. The [final engineering record](completion-20261103.md) documents matching
repairs, named-reference selection, reviewed trade-fee estimates, approved UI
journeys, arithmetic, responsive screenshots and runtime/accounting checks.
The verified capture has 9,324 positions, 1,016 before-fee estimates and 604
trade-fee estimates. Missing source semantics and unspecified owner assumptions
remain explicit; they are not zero or executable-return claims. Owner acceptance
and separately scoped continuous-coverage assurance remain distinct. This section
supersedes the next-action wording in the dated records below.

**Lead — Staff Product Engineer, frontend/UI and full-stack integration.**

You own delivery of the approved Predict UI in the existing repository on main.
Read AGENTS.md and follow its single-working-copy workflow. The owner approved the
November 3 revised design. Complete implementation, integration, local startup and
browser verification in this task.

**Delivery status:** implemented locally; see the [verification record](ui01-delivery-20261103.md).
The owner's subsequent instruction is to complete all engineering in the agreed
product scope before requesting any review. Continue source/accounting recovery,
matching, financial-input work, UI polish and integrated verification in the Desktop
execution plan. The Staff Product Engineer owns the complete outcome; owner feedback
is not a prerequisite. The original UI engineering brief follows.

## Read first

- [Approved design and completion criteria](ui-redesign-20261103.md).
- [Approved interactive preview](design/approved-20261103/preview.html) and
  [editable reference](design/approved-20261103/source.html).
- [Interface design authority](ui-design.md) and [calculation basis](benchmark-ev.md).
- [Runtime contract](data-app-runtime-contract.md) and
  [frontend development workflow](development.md#frontend-sources).
- The Desktop file `prediction_arb_next_steps.md`, plus the current sections of
  `docs/practical-use-requirements.md` and
  `docs/product-completion-20261020-plan.md` for product scope.

Inspect the current routes, snapshot API, source modules and generated assets.
Likely owners include `app/dashboard/multi_game_server.py`,
`app/dashboard/snapshot_api.py`, `app/dashboard/opportunity_static/current/`,
`app/comparison/`, `app/storage/comparison_snapshot.py` and
`scripts/build_stored_frontend.py`. Confirm actual ownership before editing.

## Deliver the approved experience

1. Replace the ordinary landing experience with Opportunities, leading with the
   strongest available results across games. Show game, position, venue, price and
   estimated advantage. Use navy/teal and Manrope from the approved design. Keep
   useful results in the first viewport. Retain all configured leagues, sources,
   market families, native sides, alternate lines and complete pagination.
2. Implement the Markets/game experience and return navigation. Keep the selected
   result, game, market, filters, scroll/focus and odds preference coherent. Search
   by full team names and abbreviations. Preserve different native predicates and
   settlement terms. Existing single-position EV and opposing-position comparisons
   remain accessible with honest metric labels and sorting within their basis.
3. Implement Why from actual engine inputs. Explain offered odds, fair odds,
   reference probability and the $100 example. For the retained Winnipeg example,
   +733 versus estimated fair +621.62 yields 15.43% gross decisive EV, or $15.43
   expected profit per $100 before fees. Use full-precision values and the correct
   explanation for each metric. Keep unavailable inputs and hypothetical assumptions
   explicit. Preserve the user's configured funding and calculation settings.
4. Add one persistent American/Decimal control covering all rendered odds in
   Opportunities, Markets, Why and Admin calculation inspection. Reuse canonical
   conversions, preserve raw originals and keep ranking independent of formatting.
5. Redesign Admin with an actionable overview, source operation, collection
   Stop/resume and pauses, Coverage, usage/budget, quote timing, calculation settings
   and exact inspection. Wire real behavior. Detailed timestamps, IDs, raw records
   and formulas belong here. Preserve an exact link from a selected result to its
   Admin evidence. Distinguish last price change, provider update, confirmation,
   receipt and capture. Ordinary views show concise delayed/saved/unverified status
   when needed, with currentness based on actual quote evidence.
6. Preserve the existing snapshot loop. Refresh captures available local prices;
   Admin assumption changes recalculate captured inputs coherently; later source
   ticks do not mutate a selected result. Keep prior results visible during work
   and report failures clearly. Filtering and inspection do not acquire data.

The approved preview uses a small recorded sample, simulated controls and optional
design tooling. Production must use authentic API results and functional controls.
Resolve routine layout and integration details within the approved direction.
Handle recoverable implementation problems and continue through local delivery.

## Operating authority

Preserve existing work, credentials, settings, data, captured evidence, owner Stop
and source pauses, account/quota/reservation/hold records and unresolved exposure.
Normal build, restart and authorized acquisition are already permitted. Aggregate
limits are 300 credits per 15-minute cycle and 16,800 per operating day, subject to
existing account-window and budget guards, with renewed authorization and no new
cutoff. Check current state before operational decisions. No account resets,
trading, provider correspondence, commit/push, worktrees or isolated successor app.

## Verify and hand off

Use the approved design's completion journeys as acceptance checks. Verify the
actual app at desktop, approximately 600 × 602 and 390px, including first-screen
results, game/back navigation, search, Why arithmetic, global odds formatting,
Admin routes, alternate lines, missing/stale data, empty/zero/negative results,
pagination, refresh/recalculation failures and keyboard/focus behavior. Use
proportionate affected tests and disposable fixtures for unavailable states.
Measure the useful-page timing against the existing two-second target.

Build, integrate and start/restart the local app and necessary data processes.
Complete the remaining agreed product engineering before requesting owner review.
Include screenshots of Opportunities,
game/Why and Admin at desktop and narrow widths. Update the Desktop execution plan
and relevant status docs with what works, what was verified, real limitations and
the next concrete action. Design approval is recorded; owner acceptance of the
running implementation remains open until the owner reviews the finished product.
An implemented UI slice does not make the unfinished product ready for review.
