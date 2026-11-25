# Owner amendment: target $10 profit on each winning paper ticket

The owner requests replacing Kelly sizing for a new version of the November
23–29, 2026 men’s D1 paper experiment with **Win $10** sizing. Calculate a Kelly
comparison using the same retained evidence. The consolidated assignment at
`docs/engineering/workbench-win10-beta-20261124.md` sets release acceptance.

This amendment accompanies the Workbench beta implementation. Its presentation
requirements remain: no branding, flat trade list, complete information and
evidence. Use the selected sizing policy for each new calculation.

## Definition and math

For positive net win odds b per dollar risked, ideal stake = 10 / b. With
American odds A > 0, b = A/100; with A < 0, b = 100/abs(A). Under the recorded
zero-fee binary model, win profit is $10, returned cash is stake + $10, and loss
is minus the stake. It equalizes winning profit; it does not equalize loss risk
or eliminate outcome variance/correlated exposure.

Examples before rounding: −110 stakes $11; +300 stakes $10/3; +500 stakes $2;
+1000 stakes $1; +3000 stakes $1/3. Distinguish profit from total returned cash.

Use exact rational/decimal arithmetic and the existing frozen odds, cashflow and
fee inputs. Production repricing must respect the declared quantity/price grids
and rounding. Expose target win profit, actual modeled win profit and any target
delta. Do not silently promise an exact $10 when legal increments make that
unattainable; make the rounding convention explicit in the versioned policy.
If an idealized exact-fractional-stake model is offered, name that assumption
separately from a venue-grid-constrained replay. The preview below is the former.
Do not infer actual fees, depth, fills or settlement evidence.

## Implementation requirements for the lead

- Add a versioned sizing mode to existing experiment creation/revision: Kelly or
  Win fixed profit, with target $10. Expose the mode and amount in the UI, daily/
  weekly reports, trade inspector and exports. It must not require SQL/CLI setup.
- Create the fixed-profit revision linked to the existing November 23–29 campaign;
  retain both Best venue and All venues, T−10 scope, >=4% unrounded EV, reference
  method, EV buckets, freshness/provenance comparisons and existing coverage gaps.
- Reprice at the resulting stake using original inputs, recheck net sized EV,
  then select the best qualifying venue. Do not merely edit displayed stakes or
  reuse the old stake-dependent fee receipt, profit/return, grading or result ID.
- Keep the Kelly-only creation flow usable. New identity includes sizing mode,
  target and rounding policy.
- Replay retained days and schedule remaining dates with existing publication/
  grading workers. Both versions reuse retained acquisitions; the new sizing mode
  must not duplicate paid odds pulls or submit real orders. Yield to T−10 work.
- Keep bankroll reference and Kelly multiplier specific to Kelly; fixed-profit
  labels must not imply Kelly is still controlling the new stake. Preserve any
  existing source/account/storage guards and explicit Stop choices.
- Verify positive/negative odds, repeating-decimal stakes, fee/quantity rounding,
  unmet target handling, EV requalification, best-venue reselection, automatic
  grading/corrections and UI daily/weekly/inspector/export parity.

## November 23 idealized preview, not a saved production run

Read-only replay of the current retained selected tickets and grades, using
exact fractional stakes, the same tickets and zero fees. It does not rerun the
full grid-constrained candidate qualification or best-venue reselection, so the
production version must publish its own verified results.

| Portfolio | Tickets | Staked | Modeled P/L | ROI |
| --- | ---: | ---: | ---: | ---: |
| Best venue | 76 | $264.51 | +$14.56 | +5.50% |
| All venues | 114 | $338.11 | −$20.87 | −6.17% |

+500-or-longer stake falls to $39.40 (14.89% of daily stakes) in Best and $76.13
(22.52%) in All; these tickets still all lose. Earlier Kelly allocations were
23.88% and 32.74%. This is a retrospective sizing sensitivity check after seeing
the results; it does not establish future profitability or remove variance.

The original Kelly run is
`5100a1a827c4e76236489281f67f92e411ce2f8b61495cb9f5e823635b881ea3`.
No application code or production experiment was changed when recording this
amendment. Workbench source files were already being edited by the lead and
were left intact. Implementation/deployment of the new sizing mode is pending.
