# Predict UI design

Use the [design requirements](ui-design-requirements.md) and `app/dashboard/opportunity_static/glass.css` when changing the interface.

## Layout and behavior

The dashboard opens All opportunities, with supported EV percentages first in their existing groups and raw price comparisons kept distinct from net-return calculations. Arbitrage, EV estimates and Saved-page research remain separate views. Search, league and market filters stay visible; saved scans, sizing and scan settings share one secondary disclosure. The compact header and controls bring the existing cards earlier on the page. Game names and market scope have separate text hierarchy.

Keep saved/demo context, source state, fee uncertainty and blockers visible. Put coverage, original inputs and calculation evidence in named disclosures. Unknown and zero metrics use neutral text; negative and unavailable results remain explicit.

Refresh preserves open disclosures and keyboard focus by record/control identity using row IDs, `data-detail-key` and `data-focus-key`. Missing controls and a different saved scan do not inherit focus. Restoring focus must not scroll the page.

Active templates are `dashboard.html` and `index.html` under `app/dashboard/opportunity_static/`; their renderers include `dashboard.js`, `board.js`, `presentation.js` and `resolution.js`. `coverage.html` and `coverage.js` provide the auxiliary coverage inspector.

## Visual checks

Check the affected screens at supported sizes, including keyboard focus, long content, disabled actions and error recovery. Existing review records are in [UI verification](ui-verification.md).

## Labels and feedback

Keep the card arrangement and identity-based refresh behavior. Display
labels translate internal market/period values; saved connection states say “At
saved time.” Routine source setup is inside “Sources and market coverage”; failure,
unavailable and resynchronization states and supplied reasons stay visible outside.
Prices, quantities, receipt/source age, settlement uncertainty and EV limitations
remain beside each result. Source records and calculations are unchanged.

Invalid-input feedback points to filters or saved-scan settings, while connection
failures keep the Refresh recovery message. Matched synthetic screenshots and validation are in
[UI verification](ui-verification.md#september-28-presentation-cleanup).
