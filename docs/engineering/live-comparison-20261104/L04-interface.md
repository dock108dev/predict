# L04 — compact comparison, stable math drawer and crisp styling

You are the Staff Product Engineer responsible for frontend and full-stack
integration of Predict. Work only in the main checkout at
`prediction-arb`. Read AGENTS.md,
`docs/live-comparison-plan-20261104.md`, the queue, current L03 contract and Desktop
next steps. Preserve existing dirty work and protected state; no worktree or
commit/push. This is an implementation prompt to be run when assigned; this
planning handoff itself did not execute it.

Deliver the agreed book-row design. Outcomes rank by best eligible after-trade-fee
EV, all relevant books remain together and the contributing source is apparent.
Show offered odds and both EV columns simultaneously. Keep Kalshi and Polymarket
as prominent as aggregate sources, with exact matched Pinnacle references visible
up front. Preserve missing reasons and every distinct meaningful offer. No native
Long/Short terminology is required to understand the winning condition.

Implement Math & fees as a slide-out panel with source selection and an exact
Admin evidence link. Move detailed formulas, fee assumptions, fair-odds derivation
and clocks there. The list follows new publications automatically; the panel
keeps its selected values until Use latest prices. Show a concise New prices
available notice with old → new odds and EV. Handle identical confirmations,
reference/fee changes, unavailable/removed selections and out-of-order reads.
Preserve focus, scroll and drafts during movement; accessible Close/Escape and
focus return must work even if the original row moves or disappears.

Use `docs/design/live-comparison-20261104/live-ranked-mockup.html` for structure and
interaction only. Mock data, simulated statuses, reference bindings and fees are
not production facts. The owner requested sharper visual quality: use the visual
notes as a proposed starting point, assess actual type/color contrast, restrained
blue actions, positive/negative semantic colors, clear numeric alignment and
reduced chrome. Do not claim the revised palette/font has explicit owner approval.
Finish all known engineering and engineer-led verification before owner acceptance;
do not make owner feedback a prerequisite for fixing known defects.

Keep Opportunities → Markets → Admin, global American/Decimal preference,
configured scope, alternate lines, both-sides comparison and source controls.
Both-sides rows use actual winning conditions and their own scenario-minimum basis.
Rebuild generated assets from authored sources. Verify real desktop, the owner's
roughly 600px panel and 390px, enlarged text, keyboard, focus, reduced motion,
light/dark contrast and populated/empty/pending/error/update states. Measure normal
text contrast at least 4.5:1. Integrate/restart locally and hand L05 the real running
routes and remaining genuine external inputs; update the queue and next steps.


L03 is locally integrated. Read [the delivered API/controller contract](L03-ranking-contract.md)
before implementation. Reuse `SnapshotLive` for exact pin/check/adopt/close/renew;
the provisional panel is functional and the live list advances independently.
Honor explicit `page_changed` continuation refusal and the distinct reviewed-fee
and conservative-estimate ranking bases. Cold useful-page misses and native/storage
currentness remain measured engineering concerns, separate from missing account facts.
