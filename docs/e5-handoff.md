# E5 handoff — one synthetic NFL market-watch walkthrough

September 15, 2026. **Prepared only. E5 implementation is not authorized by the E4 request.** Read the Desktop tracker, roadmap, E3 report/contracts and [E4 report](e4-report.md)/[service contract](e4-contracts.md). Recheck their exact candidate manifests and preserve all existing uncommitted work, historical evidence and archived sources.

## One concrete next action

After separate authorization, build **one local synthetic event market-watch screen consuming the saved E4 audit exports** for ATL/PIT. Show the E3 estimate, reference receipts, Kalshi/Polymarket US books, separate Arb/Mispricing results and saved reopening. Use existing dashboard components and the documented E1 Scroll Down reuse findings; keep the framework and source copies intact.

### Concrete data and interaction

- Load `evidence/e4/durable/e3-unavailable-ev.json`, `invented-positive.json`, `invented-negative.json`, `invented-missing-mass.json`, `unknown-quantity.json`, `unknown-fees.json` and `stale-book.json` through validated E4 restore/replay.
- Start with the saved E3 result: **52.5% conditional on a normal team-winner result**. Explain that unconditional target value and net expected profit are unavailable because exceptional mass is unknown. Show the saved source receipt, age, exclusions and one-family limitation.
- Label the complete-model cases **Invented scenario**. Their 0.635 target value and modeled +1.265/−0.535 USD are test assumptions and arithmetic, not a calibrated replacement for E3.
- Show prediction book prices and quantities, actual consumed levels, total dollars, dollars per contract, required capital and return denominator. Keep fee applicability, rounding/refund details, exceptional state cashflows and exact source/version identities in expandable details.
- Use separate Arb and Mispricing tabs or filters. Use E4's declared ranking groups; do not combine expected and worst-case numbers. Keep unknown rows visible with reasons. Show shared-liquidity alternatives without an aggregate profit total.
- Preserve stable row selection when switching through the saved receipt timeline. A stale/disconnected book must visibly make the result unavailable. Provide a saved-session reopening action with exact identity and replay status.
- Keep Synthetic, Historical and Live modes clearly distinct. This walkthrough uses Synthetic only. Do not generate apparent reference movement between unobserved intervals or present fixture receipt times as bookmaker price-change times.

### Completion evidence for that separately authorized package

One operable local walkthrough: open event → inspect E3 unknown expected value → select a labeled invented positive/negative scenario → inspect fees/depth/outcomes → switch to stale/unknown inputs → reopen the saved audit. Verify visible labels, units, separate sorting, stable selection and exact replay. Record visual and repeatability evidence separately from owner feedback. Owner acceptance requires the owner's actual review.

Use the existing file exports for UI development. Any durable test must use a separately authorized fresh identity-checked disposable cluster, never the owner connection helper. Do not load or mutate the existing owner service without explicit scope.

## Stop boundary

E4 establishes synthetic service engineering and durable replay only. Neither provider is live-qualified; calibration, empirical exceptional probabilities, continuous collection, fill feasibility, profitability and owner acceptance remain unresolved. Keep the 250 ms gate deferred.

This handoff does not authorize provider requests, credentials, account access, signup/subscription, outreach, owner-database migrations, owner-service changes, sustained collection, lead/lag, maker modeling, orders, commits, push or publishing. Stop after the separately authorized E5 package; E6 remains a distinct scope.
