# Fee coverage validation checklist

## Current fee work

The running SGO configuration is tracked in [repository Next Steps](../NEXT_STEPS.md).
The November 11 [fee and desk census](sgo-paid-observation-20261111.md#fee-verification-deadline-and-live-page-coverage-november-11-10431044-pm-eastern)
showed active Polymarket US standard sports and eligible Novig pregame
reviews and an expired local Kalshi review. The follow-up separates standing
terms and their scheduled rechecks. The installed [overnight verification](sgo-paid-observation-20261111.md#overnight-coverage-and-usability-integration-november-1112-eastern)
covers fee-only rows, captured-product publication and a current exact
two-leg payoff. F09 measures numeric fee coverage independently from EV and
two-leg coverage on the same unfiltered cohort.

The November 12 corrected two-hour window measured 11,905 of 11,905
fee-covered native offer observations and 11,905 of 12,169 across all
sources (97.83%). All 264 uncovered observations were SGO-attributed
Kalshi or Novig offers with unverified native contracts. The same running
desk published a current two-leg payoff with fees on both legs and 46
pregame indicative EV prices. The audit found no qualified native or
in-game EV. [Final window](sgo-paid-observation-20261111.md#two-hour-installed-verification-november-12-eastern)

November 10, 2026 · existing `main` checkout · manual retail straight trades

The November 10 evidence below describes the earlier integrated candidate
and its separate live validation pass. Keep normal collection and
the recorded controls and quota limits. Use disposable data for induced faults,
synthetic arbs and any cases the live slate cannot supply.

## Engineering evidence at the pause

The disposable PostgreSQL run exercised signed-format Novig catalog and
WebSocket input, normal SQL ingress, fee-only publication, the exact
same-phase Pinnacle path under the declared NCAAB overtime scenario, and
frozen detail after disconnect. The Kalshi renderer passed a packaged PDF
extraction and a simulated official-origin 429. The focused run passed
160 tests and six subtests. Two client suites passed.

Both installed processes restarted and matched the current candidate.
The installed Novig worker reported the production read key unavailable.
Kalshi still requires a qualified HTTPS route, with the current manual
review expiring at 11:24:42 p.m. Eastern on November 10. Source controls
and all 19 unresolved holds totaling 52 credits matched before and after
integration. The evening validation observer was paused before it started.
[Focused run](../.local/final-fee-engineering-20261110/focused-tests.log) ·
[Installed smoke check](../.local/final-fee-engineering-20261110/installed-smoke.json)

## F03 · Novig signed in-game feed

- Provision a production read-only Novig key through the existing local
  credential reference. Confirm Admin shows the signed worker is connected and
  reports its subscription count and roster limits. The producer starts before
  scheduled events and uses a bounded roster of up to four events and 12 markets,
  with a maximum 30-minute connection window. Record which markets were sampled.
- Watch one subscribed market through pregame, a signed `GOLIVE`, and a
  nonce-bound post-reset book. Reconcile the signed event, participants, exact
  market type, line, side and opposite resting order. Independently calculate
  the taker fee on 100 one-cent contracts. Confirm a qualifying fee is visible
  on the ordinary desk and pinned drawer when the EV reference is unavailable. Also verify
  the existing aggregate pregame $0 fee on an eligible straight offer.
- Verify an exact, current same-phase sportsbook pair under the active
  [best-payout basis](benchmark-ev.md) and compatible scoring and settlement
  evidence before checking conditional after-fee EV. For the decisive-only
  calculation, reconcile the selected book's no-vig probability, acquisition
  price and fill fee. Record missing same-phase reference and missing
  settlement evidence separately if they prevent a live EV witness.
- Use a disposable source stream to exercise empty post-reset books, stale or
  unsolicited images, insufficient first-order size, replacement, delays,
  gaps, disconnect, reconnect and Stop. Check that the current offer withdraws,
  that an unsigned catalog or initial live snapshot does not restore it, and
  that the next qualified image after a newly observed reset can restore it.
  Freeze a qualifying offer and compare its pinned price, fee and reference
  after the ordinary row changes or disappears. Capture actual browser evidence
  for the ordinary and frozen drawers.

## F08A · Kalshi fee renewal

- Observe the scheduled [official checks](f08a-kalshi-rendered-renewal.md).
  Match all 18 configured series, complete change listings and the rounding
  document. For a full-document check, match the direct rendering or the
  request-bound renderer receipt and PDF digest. For scoped API verification,
  retain the direct HTTP result and match Admin's scope to a current pinned offer.
- Exercise failed retrieval and changed or incomplete terms with disposable
  data. Confirm a failed recheck preserves established terms, a changed source
  requires review, an actual cutover withdraws dependent results, and frozen
  offers retain their original terms. Record the measured coverage impact.

## F09 · Representative 99% coverage

- Read the unfiltered desk-wide census after distinct scheduled batches across
  pregame and an active in-game window. Keep generation, Eastern read time,
  source receipts, source publication status and fee review clocks. Export
  coverage by venue, league, market family, period and phase. Keep exact
  sportsbook reference, after-fee EV, retained unavailable and unpublished working prices
  separate. Show empty cohorts without a coverage percentage.
- Reconcile ordinary desk, pinned detail, Coverage export and Admin on desktop
  and mobile. Keep fresh and retained screenshots distinct. Check fee-only,
  reviewed versus conservative EV, stale evidence and coherent latest-price
  adoption. Reconcile a current sized arb if available and otherwise use the
  two existing disposable arb cases with both stake and fee cashflows.
- Report which populations met 99%, which were below it and how many offers
  would close each gap. Call out the documented Polymarket US price boundary,
  missing in-game or MLB offers, and Kalshi's current verification scope.
  Check both runtimes and confirm original holds, quota limits and source
  controls at the end.

[Prior F09 observations and arithmetic](f09-coverage-20261110.md) ·
[Root tracker](../NEXT_STEPS.md)
