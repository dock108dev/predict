# Predict UI design

Use the [design requirements](ui-design-requirements.md) and `app/dashboard/opportunity_static/glass.css` when changing the interface.

## Layout and behavior

The dashboard groups view selection, quantity and search, puts net profit early in comparison rows, and shows the selected pair first in game details. Game names and market scope have separate text hierarchy. The views are Arbitrage, What-if EV and Saved-page research.

Keep saved/demo context, source state, fee uncertainty and blockers visible. Put coverage, original inputs and calculation evidence in named disclosures. Unknown and zero metrics use neutral text; negative and unavailable results remain explicit.

Refresh preserves open disclosures and keyboard focus by record/control identity using row IDs, `data-detail-key` and `data-focus-key`. Missing controls and a different saved scan do not inherit focus. Restoring focus must not scroll the page.

Active templates are `dashboard.html` and `index.html` under `app/dashboard/opportunity_static/`; their renderers include `dashboard.js`, `board.js`, `presentation.js` and `resolution.js`. `coverage.html` and `coverage.js` provide the auxiliary coverage inspector.

## Visual checks

Check the affected screens at supported sizes, including keyboard focus, long content, disabled actions and error recovery. Existing review records are in [UI verification](ui-verification.md).
