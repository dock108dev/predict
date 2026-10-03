# Predict user-facing design direction

October 2, 2026. **Replacement design required; current UI rejected.** The [audit](usability-audit-20261002.md) and [major sprint plan](usability-sprint-plan.md) govern current work. This document specifies the target, not implemented behavior or owner acceptance. The [previous design](history/usability-reset-20261002/ui-design.md) is historical.

## Main board

Use a familiar sports odds-board structure: games grouped together, exact market/period/line selections, outcomes in compact rows and venue prices in aligned columns. Kalshi, Polymarket US, Novig and ProphetX remain intended columns; show their actual availability. Keep opposing outcomes and signed spread/total lines unmistakable. Do not compare different lines as the same selection.

Each supported price cell shows **American odds and cents together**. Distinguish actual native contract cents from aggregate cents equivalents with a concise marker. Retain native precision and conversion basis in Details. Better gross quotes may receive a restrained cue; missing fees/rules/depth prevent stronger return or profit claims.

Primary controls are sport/league, market, period, venue and game search. Default to relevant common markets and periods; do not present every unrelated sport period at once. Preserve working filters and stable keyboard focus through updates. No normal-user scan controls, duration, saved-scan selector, imports, raw JSON, source budgets or history tools.

Data flows automatically when the configured app runs. Show concise connecting, unavailable, delayed, stale and partial-source states. A slower Novig/ProphetX observation remains labeled with its age; a live browser connection does not make that quote current. Never silently fill an unavailable live board with saved/test observations.

## Details

Present selected game, outcome, exact line/period and coherent selected price revision first. Then present original prices, source and receipt times, rules/settlement differences, supported calculations and short unavailable reasons. More detailed acquisition diagnostics belong to admin.

Open Details freezes the selected revision in a bounded temporary lease. New prices must not silently rewrite that review. Offer an understandable newer-price indication; expiry/restart has an honest selection-expired state. New permanent history, exports and exact saved-cutoff bookmarks are deferred.

Raw price difference, conditional arbitrage return, supported EV and manual What-if remain distinct. Missing inputs withhold only dependent calculations; zero and negative supported results remain visible and accurately labeled.

## Admin and visual quality

Separate owner/admin operation, quota, source health, metrics and sanitized issue evidence from the price board. Admin retains operational stop/pause and recovery controls. This separation does not establish hosted authentication.

Design the board and Details together for desktop and narrow screens, long names, unavailable venues, mixed update cadence and live changes. Use restrained spacing, typography and contrast. Readability and stable comparison alignment take precedence over decorative glass effects or preserving the rejected cards. Prior local browser checks remain evidence for their old candidate, not acceptance of the new product.

## Implementation and review

The ordinary router/assets are the integration point. Existing normalized matching, exact quote arithmetic, stable update/focus behavior and security checks should be reused where suitable. Automatic collection and ephemeral latest-state projection need their own explicit runtime contract; removing controls or journal writes alone is insufficient.

U0 produces a realistic complete design and data contract; U1–U5 implement it; U6 qualifies the replacement with live source evidence and owner feedback. [Requirements](ui-design-requirements.md) define review criteria. No application implementation or fresh provider qualification occurred in the audit/documentation pass.
