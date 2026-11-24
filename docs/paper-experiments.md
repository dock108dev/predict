# Paper portfolios and backtests

Open **Research → Experiments**. The first saved policy defaults to
college basketball games scheduled for November 23, 2026 in America/New_York.
It is available on the deployed server without activating a trading account or
leaving a browser open. Existing collector-owned first-observation/T−10 captures
and bounded sporting-result follow-ups supply the evidence. No new polling,
orders, account changes or acquisition budget are introduced.

Choose another retained Eastern game date to replay and save it separately. A
replay describes a retrospective paper calculation. The versioned policy and
its hash, source checkpoint IDs and deterministic ticket IDs preserve the
decision basis. Refreshing or repeating a replay over the same inputs reopens
the existing run. A modified policy or changed evidence produces a separate
saved run. Prior results and evidence stay accessible.

## Retrospective raw-response recovery

The November 24 opportunity-recording closeout can supplement the original
November 23 pilot with retained original responses whose dispatch and receipt
were inside the recorded T−10 window. This is a separate definition and saved
run. It never changes a failed task into a successful capture or borrows initial
or later prices. Recovery chooses the last eligible response before computing
EV, without selecting responses by their profitability.

`python -m app.research.recovery --date 2026-11-23` previews admission and counts
without writes. Add `--commit` to append reconstructed evidence, a separate
definition and both portfolios. Repeating identical evidence reopens the saved
run. The reconstruction uses the original response's prices and reference quotes
with an explicit $0-fee replay assumption, rather than today's prices, fee
settings or results. The UI separates original frozen captures from later
reconstructions and exposes receipt and reconstruction clocks. These calculations
do not establish that positive EV was displayed or saved at T−10. All ticket
results remain unresolved in this opportunity-only record; result integration is
deferred. Missing/untracked games and incomplete source markets remain gaps.
An unchanged saved recovery run reopens through its source identities without
decoding the full quote population again. This shortcut requires terminal tasks,
deferred results and unchanged game membership, schedule, checkpoint pointers,
capture states and attempt records; a changed source or definition is replayed.

## Selection and sizing

Only a valid frozen late checkpoint qualifies. The existing collector targets
T−10 with a T−10 through T−9 engineering window. Missed, refused, corrected-baseline
aliases and superseded schedules never borrow an early capture. Early-positive
case retention does not restrict the paper population. Inspect capture coverage
and exclusions before interpreting day totals; untracked games remain unknown.

Use unrounded screening EV ≥ 1/25. Preserve the captured probability policy and
fee mode, including the explicitly labeled zero-fee assumption when selected.
Size at one quarter Kelly against a fixed $10,000 reference bankroll, with no
aggregate budget cap and no intraday compounding. In the simple zero-fee binary
case, commitment = $2,500 × EV / net winning odds. A −110 offer at 4% EV commits
$110; +300 commits $33.33 and +3000 $3.33 after rounding down to cents.

The amount is repriced through the existing calculation owner using the captured
fee inputs. Quantity increments, entry fees, reserves and settlement cashflows
therefore apply at the modeled amount. Recompute Kelly with the sized cashflows,
converge conservatively across rounding boundaries, and reject below-threshold
or unsupported results. Unlimited size at the recorded posted price is an
explicit paper assumption; this is not an execution/depth test.

**Best venue** selects the highest sized EV per exact event, market, period,
side, line and settlement/scoring terms, dropping only delivery and venue
identity. Ties use stable venue/ID ordering. **All venues** retains each qualifying
venue once. Different alternate lines remain separate and correlated. Conflicting
duplicate observations are excluded, not silently chosen. The portfolios are
alternative scenarios; adding their turnover does not measure one bankroll.

## Results and exports

The run leads with coverage and assumption limits. Each alternative shows
turnover, peak overlapping cash commitment, unresolved exposure, and commitments
per venue and game. Expected profit and modeled P/L use the same set of resolved
tickets. Decisive full-game sporting
results can model ticket profit/loss from its sized net receipts. Result knowledge
time controls modeled cash release. Missing results, pushes, cancellations,
unsupported settlement and changed schedules remain unresolved; no venue
settlement is inferred. Resolved-only P/L is labeled separately from outstanding
tickets, and is not an estimate of strategy profitability from a single day.

Open a ticket to see the frozen price, probability, modeled commitment and
sporting result. **Export evidence** retains the exact offer witness, sized
calculation and checkpoint identity for the saved run. The passive legacy report
remains revision bound; its export asks for a fresh read if the projected
evidence changes.

## Latest odds pull

**Data → Odds pulls** opens the newest covering acquisition attempt for the
selected NCAAB game day. Select an individual retained pull to inspect or export
its receipts and original snapshot. Positive, zero, negative and unavailable
observations remain visible. Exact EV requires accepted receipts from the same
pull. A newer failed attempt displays its own failure. Preview commitments apply
the baseline ≥4% rules, and only frozen checkpoints can qualify for a saved
paper replay.

Endpoints are passive GETs: `/api/research/paper?date=2026-11-23` and
`/api/research/paper/latest?date=2026-11-23`. Export adds `export=1&revision=HASH`
to the first endpoint. For a terminal odds pull, add `pull=ID&export=1` to the
second endpoint. Both use repeatable-read, read-only SQL. Workspace mutations
register paper analysis versions and save runs over retained inputs.
