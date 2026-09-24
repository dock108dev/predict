# Predict UI design

Updated September 23, 2026. Shared Glass UI Starter 01; presentation and keyboard-focus behavior.

## For future contributors

Start with [local design requirements](ui-design-requirements.md) and the checked-in
implementation below. The historical shared gallery and guide were recorded at
`/Users/michaelfuscoletti/Desktop/UI Templates/index.html` and `README.md` in that
folder. Those files are unavailable in the current workspace; the portable local
requirements remain the contributor baseline.

Use light cool glass, slate text, blue actions, restrained depth, rounded controls, and system typography as the default. Do not reintroduce the generic beige/green/yellow template. Preserve explicit semantic success, caution, error, unavailable, and unknown states. Readability and the task's layout outrank decoration.

The shared folder is a design reference, not a runtime dependency. Project assets are checked in locally and can run without the Desktop folder. If you receive this repository alone, this local requirements copy and the implementation describe the baseline. Request the source template folder when you need the full gallery. Template revisions are adopted deliberately, never silently synchronized.

## This project's adaptation

Dashboard and saved-game details use the shared glass treatment. The retained-reference importer moved to the footer so the product heading leads. Unknown and zero detail metrics use neutral text rather than a positive-result color. Stored IDs, math, scan behavior, saved history, and source meaning are unchanged; display labels use familiar words. Historical diagnostic/collection viewers remain historical tools.

The September 23 cleanup groups view selection, quantity and search; reduces header
and panel spacing; puts net profit early in comparison rows; and shows the selected
pair first in game details. Game names and market scope have separate text hierarchy.
Display labels translate known period/status values without changing stored values.
Source state, saved/demo context, fee uncertainty and result blockers remain visible;
coverage, original inputs and calculation evidence use named disclosures. Primary
controls remain at least 44px high and wrap under magnification.

Dashboard refresh preserves focus on the same row link, disclosure summary or
source reference, along with open details. Row IDs, `data-detail-key` and
`data-focus-key` identify controls without depending on position or a changing
cutoff URL. Missing controls and a different saved scan do not inherit old focus;
restoring focus does not scroll the page. Search and other unchanged controls keep
their focus. Both ordinary comparisons and saved-page research use this behavior.

Implementation: `app/dashboard/opportunity_static/glass.css`, `dashboard.html`,
`index.html`, `dashboard.js`, `board.js`, `presentation.js` and `resolution.js`.
The adjacent `coverage.html` and `coverage.js` serve the auxiliary `/coverage`
inspector; they are not the ordinary game-list or game-detail templates. The older
`static/`, `e5_static/` and other diagnostic viewers retain their documented roles.

## Review and status

See [UI verification](ui-verification.md). Source changes and technical/visual checks do not establish owner acceptance, a new release, live-data qualification, or acceptance of an older frozen candidate. Existing project-specific gates remain separate.
