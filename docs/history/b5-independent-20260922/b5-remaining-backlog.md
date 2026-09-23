# B5 remaining backlog — September 22, 2026

**Current engineering:** bounded full-game winner and spread/total paths exist across all six sports; pregame H1 winner/spread/total paths exist for NFL, NCAAF, NBA and men's D1 NCAAB. Bounded NFL, NBA, NCAAF and men’s D1 NCAAB result/settlement linkage is also complete; latest [NCAAB handoff](b5-ncaab-resolution-handoff.md) records 606 Python checks/two JS suites and exact saved reopening. Latest [college H1 handoff](b5-ncaab-first-half-handoff.md) is four schools/2026–2027 only. Fixtures and retained replay do not establish complete sport/venue/model coverage. **Full B4/B5 open; beta NOT READY FOR SIGNOFF.**

| Remaining work | Owning item and next action | Dependency / completion evidence |
|---|---|---|
| Sporting result / venue settlement linkage | Bounded NFL/NBA/NCAAF/NCAAB engineering COMPLETE; implement bounded MLB full-game linkage below next | No initial owner decision or collection needed for offline engineering; actual result and payout data remain a separate qualification |
| Actual native qualification across supported families/periods | B3/B5: selected source IDs, period/completion/tie terms, outcomes, fee applicability/overrides and executable quantity/depth | Missing native observations stay visible. Novig/ProphetX requests pending. Any new authenticated collection needs separate authorization; no requests/credits in this slice |
| Actual model and Pinnacle coverage | B4: correctly bound game/line/H1 distributions with equality mass, timestamps and independence | KenPom deferred, MoneyPuck dropped/NHL analytics deferred. Existing NFL Pinnacle h2h sample does not qualify H1, lines or other sports. No new acquisition selected |
| Broader college team/season coverage | B5 registry: independently review additional memberships/aliases/competition/site bindings | NCAAF six-school 2026 and men D1 NCAAB four-school 2026–2027 bounds remain. Roster expansion requires review and adversarial ambiguous-name tests, not a census inferred from fixtures |
| Fractional/shared winner and three-way portfolios | B5 payout engineering: a separately bounded extension after actual payout structures are defined | Current binary/DNB engines do not express fractional tie allocations or require buying a third tie leg; do not silently convert into refunds |
| Exceptional and refund economics | B5/B3: source-specific shortened/suspended/postponed/forfeit/void/fair-price/fee-return payout reviews | Current normal-completion conditional results are valid; all-outcome guarantees/EV remain unavailable where payout/probability/fees are unknown |
| Futures and pending resolution | B5 definition + engineering | Owner categories/horizons remain undefined. Preserve as beta work; do not substitute season probabilities for game forecasts or silently select a futures family |
| MLB/NHL partial-period equivalents | B5 scope definition | Undecided; do not select first-five/innings or hockey periods automatically. Keep separate from completed basketball/football H1 requirements |
| Practical saved-session operation and storage bounds | B5, then B6 integration | Existing bounded Stop/history tests pass; sustained jointly reviewed session/resource scope and real six-source integration remain unqualified |
| H2 offered at halftime, quarters, live/in-play | Later scoped work | H2-at-halftime and live/in-play are stretch; none implemented or promoted by this handoff |

## One recommended next slice

**Bounded MLB full-game winner/run-line/total sporting-result and venue-settlement linkage.** Reuse existing reviewed MLB identity and payout descriptors plus shared result records, import/journal/history/as-of/Details paths. Preserve doubleheader game numbers, repeated matchups, original/current starts and reschedules, native outcome orientation, listed-pitcher/action distinctions, extra-inning inclusion and explicit full-game completion. Names alone cannot bind a result.

Keep sporting scores separate from each venue’s decision. Require explicit inning/score/completion meaning without reconstructing absent totals or treating a sporting final as proof of settlement. Unknown shortened, suspended, postponed, abandoned, void/refund and fee-return terms stay unsupported. Keep corrections append-only and pregame calculations/cutoff links unchanged.

Acceptance should cover identity, completion/extra-inning ambiguity, expected versus observed payouts, independent winner/run-line/total cashflows, conflicting/corrected evidence, clock/as-of exclusion, source isolation, Stop and exact ordinary saved reopening, plus original 18-Arb/96-EV and existing NFL/NBA/NCAAF/NCAAB resolution regressions. Use labeled fixtures and retained evidence. No new collection, models, credentials, spending or actual account settlement is implied.

No MLB first-five/inning scope or NHL period equivalent is selected. Actual native data qualification, broader B4/B5, futures and unsupported exceptional economics remain separate. **Beta NOT READY FOR SIGNOFF.**
