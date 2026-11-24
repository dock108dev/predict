# Paper portfolios and backtests

Open **Experiments → Paper portfolios**. The first saved policy defaults to
college basketball games scheduled for November 23, 2026 in America/New_York.
It is available on the deployed server without activating a trading account or
leaving a browser open. Existing collector-owned first-observation/T−10 captures
and bounded sporting-result follow-ups supply the evidence. No new polling,
orders, account changes or acquisition budget are introduced.

The same date control replays other days as retained evidence accumulates.
This is a retrospective paper replay, not a claim that a simulated order was
submitted when the source capture occurred. The versioned policy and its hash,
source checkpoint IDs and deterministic ticket IDs preserve the decision basis.
Refreshes do not accumulate tickets. Existing immutable evidence is the ledger;
the read-only API does not need a second mutable trading journal.

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

Report turnover, peak overlapping cash commitment, outstanding commitment,
expected entry profit and commitments per venue/game. Decisive full-game sporting
results can model ticket profit/loss from its sized net receipts. Result knowledge
time controls modeled cash release. Missing results, pushes, cancellations,
unsupported settlement and changed schedules remain unresolved; no venue
settlement is inferred. Resolved-only P/L is labeled separately from outstanding
tickets, and is not an estimate of strategy profitability from a single day.

**Export evidence** downloads a revision-bound JSON report containing the policy,
exact selected offer witnesses, sized calculations, clocks, source checkpoint
identities, game dispositions and outcome evidence. If source results or portfolio
evidence changed since rendering, refresh before exporting. The normal page omits
the bulky original offer witnesses; calculations stay on the server.

## Latest odds pull

**Latest odds pull** first selects the newest covering acquisition attempt for
the selected NCAAB game day. It shows only that attempt, with positive EV by
default and an optional ≥4% display filter. Source/calculation witnesses must
belong to accepted receipts from that same pull. A newer incomplete or failed
attempt cannot inherit an older positive. This view is a changing preview, not
the frozen T−10 entry list. Preview commitments apply the same ≥4% policy.

Endpoints are passive GETs: `/api/research/paper?date=2026-11-23` and
`/api/research/paper/latest?date=2026-11-23`. Export adds `export=1&revision=HASH`
to the first endpoint. Both use repeatable-read, read-only SQL and submit zero
provider requests and zero orders. Future policies should receive new versions
and retain their own probability, fee, cutoff and settlement assumptions.
