# Slice 8 — moneyline market matching

Completed September 12, 2026 UTC. `moneyline-matcher-1`,
`moneyline-rules-1`, `settlement-comparator-1`, local store schema 1.
**Next project action: Slice 9 — fee engine. Stop before Slice 9.**

## Result

All five Slice 7 production event pairs have preserved market coverage. Fifteen
native markets form five canonical full-game moneylines and ten cross-venue
structural pairs: two Kalshi team contracts against one Polymarket US market per
event. The ten pairs contain ten same-exposure and ten opposing-sporting-outcome
relationships. These counts describe relationships, not independent liquidity or
trading opportunities.

| Event | Kalshi contracts | PMUS market | Structural pairs | Settlement |
|---|---:|---|---:|---|
| Atlanta / Pittsburgh | 2 | 381956 | 2 | UNKNOWN |
| Baltimore / Indianapolis | 2 | 381955 | 2 | UNKNOWN |
| Buffalo / Houston | 2 | 381962 | 2 | UNKNOWN |
| Chicago / Carolina | 2 | 381953 | 2 | UNKNOWN |
| Cleveland / Jacksonville | 2 | 381957 | 2 | UNKNOWN |

**Zero settlement-qualified pairs; ten UNKNOWN; zero demonstrated production
INCOMPATIBLE pairs.** This is a completed matcher demonstration, not evidence
that arbitrage is impossible. Synthetic exact, refund-versus-fraction,
postponement-conflict, missing-rule and discretionary examples are separate.
ProphetX and Novig are not part of this production market demonstration.

[Offline report](../evidence/slice-8/moneyline-example.json),
[persistent store](../evidence/slice-8/captured-store.json),
[official-source review and unresolved questions](../evidence/slice-8/research/findings.md).
Every excluded captured spread/total has a scoped native reference, reason,
period taxonomy and source hash in the report. No corresponding market capture
is missing from the five-event moneyline demonstration.

## API and integration

```python
from app.moneyline import MoneylineMatcher, observe
from app.matching import Matcher

parents = Matcher.load('current-event-store.json')
matcher = MoneylineMatcher()  # or MoneylineMatcher.load('market-store.json')
# rows = [observe(adapter_market, parent_observation, rule_profile,
#                 native=native_market, context=native_event,
#                 artifact=capture_path), ...]
# matcher.update(parents, rows)
# matcher.save('market-store.json')
# result = matcher.report(parents)
```

`observe()` consumes shared adapter Market observations and existing normalized
parent identities. Native rows must occur in the retained source payload. The
production example uses existing adapter parsers against preserved response
bytes; adapters, shared models and normalization code are unchanged.

`update()` accepts an **authoritative complete active market snapshot**, not a
partial delta. Removing a market explicitly withdraws its dependent current
qualification while retaining evidence. Multiple different observations of one
scoped native market in the same snapshot are conflicting; a caller must supply
its authoritative new snapshot to resolve that ambiguity. This API does not
silently select a latest observation from timestamps or prices.

`report(parents)` requires a current Slice 7 Matcher and re-evaluates against it.
Only current `matched` parents without pending evidence can confirm a market
pair. Candidate, ambiguous, conflicting, unmatched or absent parents block it;
a retained canonical ID is historical linkage. Changed identity or normalization
registry also blocks confirmation. The report's parent snapshot hash records the
exact event-state input; callers remain responsible for providing their current
store, rather than loading a stale file and treating it as live.

The offline example intentionally reloads the preserved Slice 7 store. It is a
historical demonstration, not a collector or a claim about current listings.

```sh
.venv/bin/python -m app.moneyline_example
.venv/bin/python -m app.moneyline_example --store /tmp/slice-8-markets.json
.venv/bin/python evidence/slice-8/verify.py
```

## Identity and exposure policies

Native market keys include evidence kind, environment, venue, event and market
ID. Native side IDs remain scoped by that key. Canonical moneyline IDs derive
from the persisted canonical event ID, moneyline type and full-game period;
source/rule revisions do not rename native IDs or the canonical moneyline.

Kalshi mapping is deliberately limited to KXNFLGAME, binary markets, explicit
Game scope, no conflicting period, and an anchored listing YES-win criterion.
Both participants in that criterion must resolve to the parent event, and its
team must agree with `yes_sub_title`. The documented full-game default supplies
the period. YES means that team's win exposure; NO remains that contract's
negative exposure. Neither ticker suffix nor `no_sub_title` identifies an
opposing team. A different grammar fails closed with its reason.

Polymarket US requires moneyline and exact
`football_team_full_game_winner` taxonomy. Each supplied side uses its explicit
native ID, parent market ID, `long` flag and consistent `teamId`/team object.
Normalization resolves that team in the existing venue/environment registry.
Missing or conflicting identity is rejected. A supplied single side can be mapped;
a missing side is never invented. Unsupported venues, spreads, totals, props and
other/unknown periods are explicitly rejected. Full-game MLB market extraction
is not implemented: no MLB captures were available; the generic rule comparator
still includes extra innings, shortened games and listed-pitcher dimensions.

Outputs distinguish:

- `same_exposure`: the same canonical participant and win/negative predicate.
  This is structural exposure identity; it does not assert equal exceptional payouts.
- `opposing_sporting_outcomes`: two different participants' positive win outcomes.
- `opposite_predicates`: one team's win and negative exposure.
- `complementary_payoffs`: YES only when known modeled terminal fractions sum to
  one in every modeled case and settlement qualifies. NO names a counterexample;
  UNKNOWN retains missing, refund-dependent or discretionary cases.

Scenario comparisons show each normal winner, tie, outside-window postponement,
cancellation, abandonment, pregame forfeit, shortened game and discretionary
review. Fractional NO settlement uses one minus the positive contract fraction.
Refunds remain cost-dependent symbols; unknown/discretionary payouts stay symbols.
No price, fee, sizing or ROI calculation is performed.

Each native instrument's sides share a liquidity key. Related markets retain a
venue-event liquidity family. The matcher creates no same-venue opportunity,
no synthetic side and no summed liquidity claim. Later evaluation must deduplicate
these identifiers and respect venue collateral/netting behavior.

## Settlement policies and evidence

The rule comparator is separate from structural matching. Profiles retain exact
listing text, general terms, source URLs, original capture hashes and times,
listing update metadata, nullable effective dates, assessment actor, profile
version and content hash. The exact reviewed listing-text hashes are pinned in
`app/fixtures/moneyline_rule_assessments.json`. This file is an explicit technical
assessment, not an owner decision. It contains no production pair approval.

The current Kalshi PDF is byte-identical to the preserved Phase 0 terms. Its
full-game overtime default can supplement the listings. Current PMUS broad
sports guidance is retained for context; listing-specific exceptions take
priority. General-source assessments are pinned to source and extracted-text
hashes. New listing text starts unknown; stale profiles cannot qualify a changed
listing. No semantic equivalence is inferred by text similarity.

Material dimensions are overtime/extra innings, ties, postponement, resumption,
cancellation, abandonment, forfeits, shortened games, listed pitchers, settlement
sources, deadlines, fair-value discretion, venue changes and result corrections.
NFL listed-pitcher conditions are explicitly not applicable. Unknown fields have
reasons; absent fields never compare as known equal. Scenario payout evidence is
also required. EXACT is equivalence across this version's modeled material
conditions, not a claim that every imaginable terminal condition is modeled.

- EXACT: supported equal semantic values and modeled payout policies throughout.
- COMPATIBLE: equal semantic values include an explicitly assessed equivalence.
  It qualifies only after `approve_compatible()` records an actual actor, reason,
  source, aware review time, exact profile hashes and comparator version.
- UNKNOWN: missing material conditions or unresolved independent discretion.
- INCOMPATIBLE: a specific known condition/payout conflict, retained alongside
  any other unknowns. Approval cannot override unknowns or known conflicts.

The approval API records its caller's actor verbatim; it does not authenticate
reviewers or infer owner acceptance. Synthetic approvals are labeled test actors.
A profile/comparator change invalidates prior review binding. Even qualified
settlement does not qualify a pair for later fee/arb work without confirmed
structure and at least one proven complementary leg.

## Persistence, verification and limits

The store reuses Slice 7's atomic single-writer JSON writer (temporary file,
file/directory fsync and replacement). It retains immutable market observations,
current references, source-backed parent snapshots, reviews, numbered decision
revisions and before/after qualification. Repeating identical input is idempotent,
including reversed input order. Market deletion/parent changes explicitly
withdraw or re-evaluate prior decisions without deleting their history.

Parent snapshots keep normalization details, source hashes, artifact locations,
event mappings and revisions. Full original response bodies remain in preserved
capture/event-store artifacts, avoiding another copy of the 14 MB PMUS catalog
for each side. The market store retains each selected native row and exact source
body hash. Preserve those referenced capture artifacts with the store.

Load validates schema/matcher versions, content checksum, observation/profile
hashes, scoped IDs, rule bindings, current references, parent evidence hashes,
revision chains and review bindings. This is corruption detection, not signed
provenance or actor authentication. No concurrent writer locking or schema
migration is claimed.

**213 offline tests pass (176 existing and 37 new); all eight examples exit 0.**
The verification record contains the complete suite and example logs. Tests cover captured production cases offline,
YES/NO versus long/short, side reversal, missing/conflicting IDs, unsupported
markets/periods, current parent gates, synthetic fractional/refund/discretionary
cases, unknowns/conflicts, approvals and revisions, stable IDs, duplicate
representations, scope isolation, withdrawal, restart, idempotency and failed
atomic replacement.

[Verification](../evidence/slice-8/verification.json),
[artifact manifest](../evidence/slice-8/manifest.json),
[preservation check](../evidence/slice-8/preservation.json).
PLAN.md, credentials, pre-existing implementation/tests and all historical
evidence remain unchanged. README and the Desktop tracker are updated.
Only three bounded public rule/schema downloads were performed; no new market
capture, account access, venue contact, trades, money movement, purchases,
commits, pushes or publishing occurred.

**Next: Slice 9 — fee engine.** Pair-specific settlement uncertainty travels with
these mappings; ProphetX sizing/clock/live-selection limits and Novig credentials/
live verification remain separate dependencies. No fee engine, arbitrage
calculator, execution simulator or dashboard was implemented.
