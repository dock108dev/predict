# Predict UI design

Updated September 21, 2026. Shared Glass UI Starter 01; presentation-only adoption.

## For future contributors

Start with [local design requirements](ui-design-requirements.md) and the checked-in
implementation below. The historical shared gallery and guide were recorded at
`/Users/michaelfuscoletti/Desktop/UI Templates/index.html` and `README.md` in that
folder. Those files are unavailable in the current workspace; the portable local
requirements remain the contributor baseline.

Use light cool glass, slate text, blue actions, restrained depth, rounded controls, and system typography as the default. Do not reintroduce the generic beige/green/yellow template. Preserve explicit semantic success, caution, error, unavailable, and unknown states. Readability and the task's layout outrank decoration.

The shared folder is a design reference, not a runtime dependency. Project assets are checked in locally and can run without the Desktop folder. If you receive this repository alone, this local requirements copy and the implementation describe the baseline. Request the source template folder when you need the full gallery. Template revisions are adopted deliberately, never silently synchronized.

## This project's adaptation

Dashboard and saved-game details use the shared glass treatment. The retained-reference importer moved to the footer so the product heading leads. Unknown and zero detail metrics use neutral text rather than a positive-result color. IDs, math, scan controls, saved history, and data-source labels are unchanged. Historical diagnostic/collection viewers remain historical tools.

Implementation: app/dashboard/opportunity_static/glass.css; dashboard.html; index.html; board.js (metric color classification only).

## Review and status

See [UI adoption verification](ui-verification.md). Source changes and technical/visual checks do not establish owner acceptance, a new release, live-data qualification, or acceptance of an older frozen candidate. Existing project-specific gates remain separate.
