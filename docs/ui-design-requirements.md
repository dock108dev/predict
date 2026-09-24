# Predict UI design requirements


## Direction

Use a light iOS Liquid Glass-inspired appearance: cool white surfaces, restrained translucency, subtle blue/lavender ambient background, soft depth, rounded controls, and native system typography. Do not recreate the former beige, forest-green, yellow-tinted dashboard theme.

## Foundations

- Use `app/dashboard/opportunity_static/glass.css` for tokens and components. Default action accent is blue (#0969df); primary text is deep slate (#182338), secondary text #54647b.
- Use the platform system font stack. Favor natural sentence case; reserve small uppercase labels for occasional context. Avoid oversized headings and widely spaced labels throughout the interface.
- Use an 8-ish pixel spacing rhythm (8, 12, 16, 20, 24, 32). Keep related controls close and groups visibly distinct.
- Panels generally use 22–26px radii; controls 12–14px; status pills fully rounded. Avoid applying pills to every piece of information.
- Glass is a surface treatment, not decoration to stack endlessly. Use subtle borders, a white top highlight, restrained shadows, and approximately 24px backdrop blur. Keep text and dense data on sufficiently opaque surfaces.
- Blue communicates action/selection. Green is reserved for meaningful success/positive values; amber for caution; red for error/destructive states. Pair color with text or icons. Preserve negative, zero, unknown, stale, and unavailable states accurately.

## Layout and common patterns

Use dashboard summaries for overview, list/table layouts for comparison, grouped forms for editing, sidebar settings for preferences, and detail views for records. Put secondary diagnostics in disclosures; retain necessary provenance and limits. Give each view a clear title and primary next action. Import/setup/debug controls should not displace the main product heading.

Use compact tables on desktop, deliberate horizontal scrolling or readable record cards on phones. Long names, timestamps, and values must wrap or remain accessible. Avoid clipped selects, overlapping controls, and page-level horizontal scrolling. Keep useful data near the first viewport; do not sacrifice usability for giant empty hero sections.

## Interaction and accessibility

- Use native buttons, links, labels, inputs, and dialog semantics. Provide visible keyboard focus and accessible names. Aim for at least 44px primary touch targets.
- Refreshing data must preserve open disclosures and keyboard focus by record/control identity, including when rows reorder or their links change. Capture focus immediately before replacing markup. Do not steal focus moved during a request, focus a different record when one disappears, or scroll merely to restore focus.
- Body text should meet 4.5:1 contrast; large text and meaningful component boundaries should meet applicable 3:1 contrast requirements. Check actual composited colors because transparency changes contrast.
- Honor reduced motion and reduced transparency; provide opaque fallback surfaces when blur is unsupported. Do not animate large backgrounds or use glass effects that impair reading.
- Distinguish loading, empty, error, disabled, selected, and successful states in words. Do not make a control look active when unavailable.
- A light theme is included. Do not claim dark-mode support without implementing and checking it.
- Demo interactions are local-only. Real apps must retain their existing behavior, confirmation rules, persistence, math, data boundaries, and source labels.

## Maintaining the interface

Keep design guidance consistent with the implementation. Check affected screens and interactions at supported sizes; record any remaining limitations. Preserve data contracts, calculations, permissions, persistence and game rules.

For Predict, the active HTML templates are `dashboard.html` (Compare games) and
`index.html` (Game details) under `app/dashboard/opportunity_static/`. Keep their
IDs, accessible labels and display-only focus keys consistent with their renderers.
The three views are Arbitrage, What-if EV and Saved-page research. Keep saved/demo
context, current blockers and material assumptions visible; put original inputs
and diagnostics in named disclosures. Preserve negative, zero and unavailable
values and the existing calculation, source and persistence contracts.
