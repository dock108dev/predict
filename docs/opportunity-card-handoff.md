> **October 2 product reset:** the owner rejected the UI and stopped the saved-data walkthrough. [Audit](usability-audit-20261002.md), [major usability sprint plan](usability-sprint-plan.md) and [current acceptance](beta-coverage-acceptance.md) govern new work. Historical scan/history/card-layout requirements and owner-review next actions below are superseded; existing technical behavior and candidate evidence retain their own boundaries. Necessary new live attempts are authorized within the plan and shared 500/month Odds API allowance.

# Opportunity-card local candidate — September 26, 2026

Engineering package complete locally. **Real-source qualification OPEN; beta NOT READY FOR SIGNOFF; owner acceptance NOT OBSERVED.** This supersedes the presentation package's earlier “specified, not implemented” status, not the retained source gates.

## Open the exact preview

From `/Users/michaelfuscoletti/Desktop/prediction-arb`:

```sh
.venv/bin/python -m tests.opportunity_card_preview .local/opportunity-card-preview
```

Open [Predict simulation](http://127.0.0.1:8797/). The current process is left available, idle. Do not start a second copy while that port is occupied. Ctrl-C stops a foreground preview server; ordinary **Stop** stops and saves only its bounded simulation session. The launcher serves ordinary `create_app`, uses isolated `.local/opportunity-card-preview/sessions`, and binds fixture feeds to loopback. First launch prepares one saved simulation; later launches read it. Page loads and Refresh only read local data. Start explicitly begins a bounded loopback simulation, never a provider request. No recurring job is installed.

For the retained reviewed starting scan, choose the September 26 9:24 PM simulation under **Size, scan settings and saved sessions**, or use the [fixed saved selection](http://127.0.0.1:8797/?view=feed&capture=a0469fa2-b2b3-4f78-9aae-c4cb26d9c9d3). Simulation source timestamps deliberately remain unknown where the fixture supplies none; warnings are not production readiness claims. The fixture does not pretend to qualify Novig or ProphetX.

## Delivered behavior

Ordinary Predict opens a card feed using existing shared calculations and durable history. Sourced model EV%, manual What-if EV%, bookmaker-derived estimates, unavailable EV and arbitrage return have separate groups. Supported EV percentages sort descending within each group using exact Decimal values and stable IDs; unknowns have reasons and no numeric rank. Refresh no longer pins an outdated ranking. No stake setup is required; the default is an evaluation size, not a proposed trade.

Game, competition, period, market and venue filters remain visible. Size, fee assumptions, saved sessions and scan settings are secondary. Start/Stop and status remain visible. Cards and game Details disclose original prices/depth, evaluated size, full fee audits/rounding, payout states, probability provenance, cutoff/timestamps and net dollars. EV% divides expected net profit by entry cash including applicable entry costs. Conditional assumptions remain explicit; no implied probability or arbitrage-return substitution. Exact fractional probabilities, including a synthetic break-even 0.515, can be saved as manual scenarios.

Details links bind session, hash, cutoff, requested size, fee scenario, selected leg/candidate, reference ID and manual probability/basis when present. Source records remain immutable; manual What-if preferences are local browser inputs, distinct from imported saved models. Historical, current and simulation labels remain separate. Missing material cost scenarios suppress percentages while original purchase prices stay visible. Disconnected loading clears prior cards and disables Start until status is recovered.

## Candidate and verification

HEAD: `ad4191be6ab91b09075fc57d048b0f113da5f667`. HEAD alone is not this candidate. [Candidate identity](../evidence/opportunity-card-20260926/candidate.json), [source manifest](../evidence/opportunity-card-20260926/source-manifest.json), and retained working-tree patch identify the changed source, including prior uncommitted documentation. No commit, push or publication occurred.

[Verification directory](../evidence/opportunity-card-20260926/) contains per-module logs, the initial combined-process failure, browser snapshots/screenshots, original-input arithmetic and frozen-reopening checks. Tests run in separate fresh processes because the first combined run crossed the existing offline RSS cap; limits were not raised. New test setup corrections (missing synthetic terms, omitted Origin, and changing lifecycle metadata) are retained separately; calculation inputs were not changed to force agreement.

- **132 focused Python tests and five JavaScript suites pass.** Focused shared math/fees, dashboard/security, projection, reference, lifecycle/Stop/recovery and new feed checks pass. No completed B5 slice or accepted thirty-minute B6 workload was rerun.
- Five independent checks calculate from original prices, quantity and the fixture fee formulas: model **16.50% / 15.94%**, bookmaker **−2.91% / −3.38%**, and conditional arbitrage **−11.65%**. [Exact arithmetic](../evidence/opportunity-card-20260926/independent-math.json). These are synthetic cent-balance scenarios, not current exchange fee qualification.
- All ten original cards reopen with identical percentages, leg inputs and cutoff after a second session. [Reopening evidence](../evidence/opportunity-card-20260926/saved-reopening.json). Fresh-process recovery preserves that saved package. A browser-created manual 0.515 scenario also displays **0.00%** separately.
- Ordinary browser verification covers automatic cards, separate groups, filters/empty recovery, secondary controls, Details, manual zero, unknown fees, Start/Stop/finalization, saved selection, disclosure preservation, disconnected recovery, paused-book stale warnings and recovery, and desktop/390px layout. Width check: document 390px, viewport 390px. Keyboard focus preservation is covered by the existing identity-based regression.
- The retained reviewed simulation is copied under the evidence directory’s `sessions/` folder. No-model-input tests show unavailable EV alongside purchase comparisons and supported conditional arbitrage through the same HTTP/shared calculation path. Positive, negative, zero, missing and empty cases are covered. Thirteen review7 manifest files still match their retained hashes.

## Remaining real-source workstream

The [per-venue readiness ledger](market-data-gaps.md#all-four-venue-readiness) remains authoritative across all six sports and required full-game, selected period and championship families.

| Venue | Missing evidence | Next actor and completion condition |
|---|---|---|
| Kalshi | Effective contract amendment, fee/rounding/settlement-charge scope; native state and measured clocks for later runs | Owner may authorize unsent inquiry; exchange supplies authoritative terms; engineering reconciles and later qualifies useful comparable real coverage with exact reopening |
| Polymarket US | Historical contract/modification coverage and mandatory charge or exemption; future native economics/state/time | Owner may authorize unsent inquiry; exchange clarifies; engineering establishes supported purchase/settlement math and useful actual participation |
| Novig | Provisioning unconfirmed; issued NBX environment/contract, periods/IDs, depth, fees/settlement and clocks | Owner reports changed nonsecret status/docs; provider provisions; engineering maps actual supported NBX observations into ordinary matched cards and saved history |
| ProphetX | Provisioning unconfirmed; actual production API/tournament scope, quantity/value ownership and units, purchasable depth, fees/rules/timestamps | Owner reports changed nonsecret status/docs; provider provisions/clarifies; engineering reconciles exact API then qualifies useful production participation |

No credentials or account inspection occurred. Kalshi/US drafts remain unsent. A changed-status question for Novig/ProphetX was asked during implementation; no reply is assumed. Optional models and bookmaker lines, including Pinnacle, are not gates. KenPom and NHL analytics remain deferred; MoneyPuck acquisition remains dropped. Consumed attempts and retained evidence are unchanged.

Prerequisites do not yet support a concrete real-source qualification run. No new run or approval is requested. Once supported, engineering prepares the candidate-bound endpoint/coverage/cadence/duration/resource/freshness/Stop proposal with a fresh attempt identity; owner decides that separate scope.

## Short formative owner review

Begin with one neutral task: **“Choose a card you would want to inspect and tell me what it means to you.”** Wait for the owner to operate and respond. Then, one task at a time, ask them to narrow the feed, inspect Details, and return to a saved scan. Record their wording and any confusion without coaching a verdict. This simulation review cannot close source or beta gates. No owner review of this candidate has yet been observed.
