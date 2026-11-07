# November 4 design references

The owner selected compact book rows, Pinnacle visible, after-fee outcome ranking,
a live list and stable Math & fees panel with explicit latest-price adoption.
See the [product plan](../../live-comparison-plan-20261104.md) for exact decisions.

`live-ranked-mockup.html` is the current editable inline-preview fragment;
`outcome-study.html` retains the earlier component study. Both contain historical
or illustrative values. Simulated feed status, matched references and native
fee assumptions do not certify the running product.

## Visual refinement proposal

The updated mockup uses a neutral cool canvas, white comparison surfaces, navy
primary text, a darker secondary text color and restrained blue actions. Positive
EV uses deep green and negative EV restrained red, each with a signed number.
The rank-contributing row has a small edge marker and a very light tint instead
of applying teal to every interactive and numeric element. Amber identifies a
material new-price notice. Typography uses a system body stack, clearer 12px
secondary labels and tabular 15px values, with fewer heavy weights and sharper
rules. Maintain the existing bundled Manrope option for headings during actual
visual review; no font download is required to render the mockup.

Proposed light tokens: canvas #f4f6f9, surface #ffffff, primary text #182d43,
secondary text #4d6075, action #2255b5, positive #08654a, negative #a54237,
notice text #765012 on #fff6e3. The fragment includes dark equivalents. These exact
tokens and the body-font change are proposals, not recorded owner approvals.
Normal text should meet at least 4.5:1 contrast against its actual surface; colors
are semantic and never the only state signal. Verify hover/focus/disabled and
light/dark combinations in the app, not just this design sample.

Scope of this turn: planning files and mockup polish only. Earlier app prototype
changes remain preserved. No new app implementation, deployment or trading occurs.

## Preview checks in this planning turn

Reviewed at 1024px and 390px. The narrow list had matching content/scroll width
(358px inside the preview wrapper), with all four sources and numeric columns
visible. Mockup scripts passed syntax/element-reference checks. Proposed light
token contrast: primary 14.04:1, secondary 6.47:1, action 6.92:1, positive on rank
tint 6.38:1, negative 6.11:1 and notice 6.68:1. Dark primary/secondary text on the
proposed surface measured 13.90:1 and 8.85:1. These are token/preview checks, not
qualification of every app state, live source, fee model or final owner acceptance.
