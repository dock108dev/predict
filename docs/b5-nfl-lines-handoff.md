# B5 NFL full-game spread/total — bounded engineering handoff

**COMPLETE — offline and isolated synthetic acceptance, September 21, 2026 local time.** Actual venue/model qualification and full B4/B5 remain open. **Beta NOT READY FOR SIGNOFF.**

Candidate HEAD `c7204c98fc78cde2f314a3227c03c7d6d70fbe2a`; uncommitted app/test/script SHA-256 `d13452e4e3e1d06b275f1342dab7c4d1c12b6aa05bf225dc072557952e5968ac`, 320 files. [Exact identity](../evidence/b5-nfl-lines-20260921/implementation-identity.json) · [acceptance report](../evidence/b5-nfl-lines-20260921/final-report.md). All 317 shared score-line acceptance files matched before editing; prior winner and basketball saved calculations reproduce exactly. Existing uncommitted work is preserved; no commit or publication occurred.

## Supported product semantics

Ordinary Predict accepts explicitly retained NFL full-game integer/half-point spread or combined-total reviews, for the **2026 season, regular season and postseason only**. It reuses existing NFL registry aliases and requires two distinct resolved participants, explicit home/away bindings, a reviewed shared game ID, timezone-aware current/original starts, season/stage and consistent reschedule status. Repeated opponents are not an identity. Conflicting game IDs, starts, seasons or stages remain visible and cannot pair. Legacy NFL winner behavior is unchanged.

The existing score review preserves source/native event and market IDs, original body hash, retained event/descriptor/terms/fee paths, signed line, unit, subject, native outcome IDs/labels and explicit operators. Only `KXNFLSPREAD`/`KXNFLTOTAL` are supported Kalshi line series. Away handicaps invert into home-minus-away margin together with their comparators. Totals use combined nonnegative integer points. Different thresholds do not match. Regulation-only, halves, quarters, team totals, exact-count/range contracts, futures, quarter stakes and in-play remain unsupported.

Normal scope requires all regulation and applicable overtime, four 15-minute quarters, explicit stage-specific 2026 overtime format and a source review that evaluates tied final scores by their actual score predicate. Missing or conflicting tie/OT/completion meaning is unsupported. A regular-season tie has margin zero: it does not imply a blanket refund or $.50 payout. A normally completed postseason game cannot end tied; the zero-margin equality partition is removed only with the explicit postseason binding. Other thresholds retain their existing score intervals. This extends the shared partition interface, not a separate NFL calculator.

Native `gt/ge/lt/le`, equality `predicate/stake_refund/unknown` and refund-fee semantics remain independent. Binary complements can win at equality; a supported push returns **actual consumed purchase stake**, retaining entry fees. Returned/unknown refund fees are unavailable when equality is reachable. Fees, depth, source isolation and conditional net dollars use the existing engines. Unknown size, source fee basis or settlement charge leaves dollars unavailable. Cent/direct precision and no event override remain explicit what-if assumptions. No venue borrows another venue’s economics.

Source terms separately retain completion, shortened game, abandonment, suspension, cancellation, postponement, void, forfeit, venue change, corrections and settlement fee. Exception payouts/probabilities remain unknown and excluded from normal completed-game calculations: no all-outcome guarantee or unconditional EV. Missing analytics does not block supported price comparisons or conditional Arb.

The existing B4 reference importer accepts explicit `score_distribution` receipts bound to the complete NFL market identity, original source event, participant and reachable partition probabilities. Integer boundaries require equality mass; half-point/manual outcome inputs stay labeled what-if. Moneyline probabilities, scores, margins, ratings/rankings and season probabilities cannot substitute. Receipt/publication/start clocks prevent future leakage. Ordinary Details, filters, health, immutable links, Stop and saved reopening share the existing product paths.

## Official contracts versus fixture evidence

Reviewed public documents and retained hashes: [audit](../evidence/b5-nfl-lines-20260921/retained-native-audit.json).

- [Kalshi FOOTBALLSPREAD](https://assets.kalshi.com/contract_terms/FOOTBALLSPREAD.pdf) defines signed point differential, comparison operators, period alternatives and OT inclusion. A tie is differential zero; positive winning-margin predicates are false. It separately describes 55-minute/official-final completion, 48-hour rescheduling/resumption, venue changes, forfeits and discretionary fair-price payouts.
- [Kalshi FOOTBALLTOTALS](https://assets.kalshi.com/contract_terms/FOOTBALLTOTALS.pdf) distinguishes combined and team totals, periods, and strict over/under thresholds. Its completion/exception wording is not identical to the spread contract. The downloaded text contains visible duplicated/malformed wording in its interruption clause; no cleanup or universal payout inference is applied.
- [NFL 2026 rulebook, Rule 16](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf) allows a regular-season tie after one maximum 10-minute overtime and continues postseason 15-minute periods until a winner. These sporting rules establish score reachability only; they do not establish venue payout terms.

The retained phase-0 catalog independently identifies both full-game Kalshi series and `quadratic_with_maker_fees`, multiplier 1. Catalog evidence does **not** establish an actual selected listing’s sign/operator/outcome binding, fee applicability or purchasable depth. Existing adapters still retain unsupported native metadata; no title parser, new discovery collection or unverified automatic line mapping was added.

The fixtures supply deliberately labeled hypothetical NFL review annotations and copied quote shapes. They test inverted native IDs and source-specific economic interfaces, not actual NFL venue contracts or model forecasts. PMUS tie/line rules and Short purchase availability are not inferred from its moneyline fields. Novig remains unsupported in the fixture catalog; ProphetX is not configured. No fabricated fixture qualifies these sources.

## Remaining owners and next slice

- **B3:** actual per-venue NFL line listings, participant/orientation/period binding, source rules, event fee applicability, quantities and purchasable sides. Novig/ProphetX requests remain pending; ProphetX selected. No new requests or credentials used.
- **B4:** actual exact-line forecast distributions, provenance and independence. No model acquisition. KenPom deferred; MoneyPuck dropped and NHL analytics missing/deferred. Completed Pinnacle allowance remains consumed with no additional requests/credits.
- **B5:** other seasons, partial games, team totals, exact-count/range predicates, unsupported refund economics and other sports’ line mappings. Broader B4/B5 and actual joint-source qualification remain open.
- **Next independent engineering:** bounded **NCAAF full-game spread/total mapping**, preserving its own subdivision/school/site and college overtime rules while reusing this shared engine.
