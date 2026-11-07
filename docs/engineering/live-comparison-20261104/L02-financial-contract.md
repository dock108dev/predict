# L02 — native reference and trade-fee calculations

November 4, 2026. Implemented in the sole main checkout, uncommitted. This adds
native Pinnacle calculations to L01's existing ordinary owner and snapshot engine.
No separate financial publisher, collector, checkout, commit or push. Currentness
and storage interruptions remain distinct from mathematical input availability.

## Owner clarification and fee authority

During implementation the owner supplied Kalshi's standard/series schedule and
ProphetX's public-site version 1.3 schedule, and requested estimates that err on
the high side. That authorizes a **separate conservative trade-fee estimate**;
it does not establish direct Kalshi membership or ProphetX's private API terms.
No account fact, fee exemption or expired review was invented. Existing Admin
fee/scenario/funding settings are preserved.

- Kalshi: a fresh public metadata review covers all 18 configured full-game
  series across six leagues and three families. The received MLB multiplier is
  0.5 pregame; the other configured multipliers are 1. Complete series changes
  and the unpaginated complete event-override history are bound into the review.
  Exact source series, event, side, period, league and normal claim must match.
  The existing fee engine computes six-decimal fee ceiling, account-grid balance
  floor and order rounding carry for one taker fill. Direct precision is $0.0001;
  non-direct precision is $0.01. The conservative exchange estimate chooses the
  higher charge across these grids. It is **not an upper bound on unknown FCM or
  intermediary charges**. A verified direct account can enable the exact metric;
  absent account evidence leaves that metric unavailable, with the separate
  conservative estimate available.
- Polymarket US: current official standard single sports taker coefficient
  0.0695, one contract in one fill, half-even cent rounding. Captured product
  type, selected instrument, coefficient, minimum quantity and price increment
  must agree. No combo, table-tennis coefficient or weekly rebate is borrowed.
- Novig: the newly reviewed official table still makes pregame straight trades
  fee-free on app/web and API. Aggregate decimal odds normalize to one USD
  normal claim; there is no invented live/futures/parlay exemption.
- ProphetX: the current public-site page states version 1.3, October 12, 2026,
  two percent of positive net gains per market. The owner's conservative estimate
  assumes one position in that market and rounds commission upward to cents.
  Actual site rounding is unverified. Its fee is deducted from winning proceeds,
  so the maximum modeled decisive loss is the acquisition cost; an upside-only
  fee is not charged again as upfront risk. Private API/account terms remain
  unavailable: official API docs say the assigned commission/maker-taker model
  and rate have no query endpoint. The smallest external input is the applicable
  account/channel fee model, rate/base and rounding. No correspondence was sent.

The November 4 review files are prospective, content-hashed, daily engineering
reviews. They do not fill historical gaps or promise a source will not change.
Known scheduled fee changes shorten applicability and trigger ordinary replacement.
The mockup's flat 2¢/1¢ amounts were not used. Real computed amounts can happen to
round to those values; they come from the formula and exact captured price.

Sources: [Kalshi schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf),
[Kalshi rounding](https://docs.kalshi.com/getting_started/fee_rounding),
[Polymarket US](https://docs.polymarket.us/fees),
[Novig](https://support.novig.com/en/articles/16195057-fees-on-novig),
[ProphetX public site](https://www.prophetx.co/lobby/t-c/trading-fees),
[ProphetX account/API distinction](https://docs.prophetx.co/docs/fees).

## Exact reference binding

The old retained-native path was restricted to NCAAB. The repaired path covers
NFL, NCAAF, NBA, NCAAB, MLB and NHL winner/spread/total, including alternate lines.
Pinnacle witnesses remain reference-only. Existing aggregate probabilities remain
on their existing exact owner; native probabilities come from their own matched
Pinnacle pair, not a neighboring venue's calculated EV.

Finance reuses the ordinary occurrence resolver, including its source membership,
participant roles, typed IDs, context and conflict checks. This preserves the
ordinary mutually unique metadata association when providers list different start
minutes; for example, the retained Bulls–Knicks native start is 00:30 UTC while
its aggregate start is 00:40 UTC. Both original times remain inspectable. This is
an estimated ordinary occurrence association, not a new strict settlement proof.
Missing-context cases retain the existing exact-schedule/unique-role path. Wrong
occurrences, conflicting roles/context, ambiguous repeated games, wrong periods
and unsupported scoring remain unbound.

Each pair requires one receipt/route, two distinct source outcomes, matching book
clocks, valid original decimal odds, matching signed threshold and full scoring
scope (overtime, extra innings and shootout treatment). The latest complete pair
is selected without splicing frames; conflicting equally recent frames fail.
A source-only price still publishes when optional finance cannot complete.

The financial domain is explicitly **decisive win/loss**, excluding equality,
ties, pushes and exceptional settlement. This permits conditional gross EV even
when full-state equality settlement is unknown. It does not change the grouping
identity or the user's full-state scenario. Kalshi NO/not-win keeps its own
predicate, including equality where stated; it is never renamed opposing-team win.
Polymarket's named Short interpretation is retained from its source binding.
Native bid complements keep both `native_value` and `transformation`; no additional
complement is applied to an already normalized acquisition cost.

## L03/L04 field contract

Consume `/api/comparison-current`, `/selection` and the L01 lease/details routes.
The current root is compact; full source and fee graphs remain in its immutable
member. `evidence_result_id`, `price_revision` and `economic_revision` are unchanged
between that displayed row and its exact member. A new calculation/review/authority
change gets a coherent economic identity. No current read computes finance.

| Field | Meaning |
| --- | --- |
| `original`, `source`, `times` | Captured normalized acquisition, retained native transformation, exact source identity and clocks. |
| `snapshot_benchmark` | Native matched pair IDs/prices, selected index and literal selected predicate; never a currentness grant by itself. |
| `reference_calculation` | Ordered exact pair with named selections, original prices, clocks, selected ID/index, proportional no-vig probability, fair decimal/American odds, overround and conditional scope. Full occurrence/equality evidence in selected details. |
| `probability`, `gross_return_percent`, `gross_profit_per_claim` | Decisive probability and before-fee arithmetic; unavailable fees do not erase these. |
| `conditional_trade_benchmark`, `conditional_return_percent` | Reviewed supported trade-fee scenario, fee/risk amounts, quantity, rounding/formula, applicability and review interval. Actual fill/depth is not claimed. Kalshi membership and ProphetX account gaps stay typed missing inputs here. |
| `conservative_trade_benchmark`, `conservative_return_percent` | Separate owner-authorized conservative exchange/public-site estimate. Carries fee payment timing, expected fee, win/loss profits, total risk, assumptions and source evidence. `account_verified=false`, `ranking_eligible=false` for verified-fee ranking. |
| `metric_status` | Independent `reference_probability`, `before_fee_ev`, `after_trade_fee_ev`, `conservative_trade_fee_ev`, `assumed_net_ev`, each with `available`, `unavailable` or `withdrawn` and typed reasons. |
| `current_authority` | Original quote/reference dependencies and deadlines, fee review/content identity, conservative review deadline and kickoff. |
| `price_current`, `current_reasons` | Present source/authority validity, separate from mathematical input support. |
| `math`, `net_return_percent` | Existing explicitly configured full/assumed/buffered scenario; never an alias for trade-fee EV. |

Common supported comparison basis is
`decisive_taker_one_usd_claim_one_fill_total_risk_v1`: one USD normal claim, one
modeled acquisition fill, decisive expected profit divided by maximum modeled
loss including upfront trade fees. For the ProphetX conservative commission
scenario, the fee comes out of winning proceeds; loss/risk remains acquisition.
Quantities are normalized hypothetical scenarios, not execution qualification.

For verified after-fee ranking use numeric `conditional_return_percent` only.
Do not silently substitute `gross_return_percent` or the separate conservative
estimate. The explicit `metric=conservative_return_percent` read is available for
an estimate view; L03/L04 must label that basis and keep unknowns distinct. The
owner's estimate clarification is recorded above so downstream work can display
useful estimated native fees without claiming account verification.

Reference replacement/expiry withdraws probability and dependent financial fields
while independently current source prices remain visible. Fee expiry withdraws
only the dependent trade-fee metric, preserving supported gross. Conservative
expiry has its own deadline. Policy/account/evidence changes invalidate the
component through the existing ordinary content identity. Selected details keep
the exact historical arithmetic and clocks; retention does not confer currentness.

An optional `.local/trade-fee-account-facts.json` supports evidenced direct Kalshi
membership without changing Admin assumptions. It is absent in this installation.
The strict schema is `trade-fee-account-facts-1`, with `kalshi.membership=direct`,
`channel=direct_api`, `effective_from`, `review_before` and a content-hashed local
`evidence.path`/`evidence.sha256`. Missing, changed, expired or non-direct facts
fail closed. Public-schedule estimates never write this account record.

## Engineering checks and runtime evidence

Retained regression inputs preserve actual Jaguars–Ravens and Bulls–Knicks source
rows and exact Pinnacle witnesses. Their independent rational oracles verify each
side from original decimal prices, no-vig weights, native complements, fees,
rounding and total risk. Fixtures also exercise all six leagues/three families,
wrong occurrence/line/scoring, missing account facts, conflicting selected fee
coefficients, verified direct rounding, reference replacement and fee expiry.
These fixtures are retained evidence plus explicitly disposable mutations, not
claims of fresh production odds.

The new financial disclosure initially pushed ordinary root encoding over the
existing 1 GiB worker peak guard. Current roots now retain compact exact financial
fields and point to full immutable member evidence. The fast encoder feeds C JSON
chunks into gzip without constructing whole-root string and byte copies at once.
The worker limit, bounded leases and source-only-first publication are unchanged.
Recent post-fix turns use 654–733 MB instead of reaching that guard. This does not certify sustained native
latency or remove L01's storage-maintenance concern.

Verification on Python 3.14.5 / PostgreSQL 16.15:

- 103 focused portable tests plus 6 subtests passed before the final streaming
  encoder change. The final affected unit suite passed 74 tests plus 9 subtests,
  including the canonical JSON/Unicode round-trip test. Native transformation and
  occurrence checks separately passed 49 tests plus 10 subtests.
- All 18 ordinary-publication/snapshot SQL checks passed again with the final
  encoder against a disposable PostgreSQL 16 cluster. Eleven storage-maintenance
  checks passed in the earlier companion run. No owner database was used as a
  test database.
- Twelve authentic ordinary HTTP selections were independently checked: both
  native venues, winner/spread/total, Jaguars–Ravens and NBA examples. Current
  roots were leased, immutable member details read, latest selection queried and
  leases released. Pair probabilities, native complements, gross EV, fee rounding,
  total risk and exact revision identities were recomputed independently from the
  original source prices. Evidence is under `test-results/l02/live/`, especially
  `arithmetic-verification.json` and the twelve `*-retained.json` records.

Illustrative exact values from those immutable production members (not a claim
that these prices remain current):

| Native example | Pinnacle pair | Selected probability | Cost | Fee/risk | After-fee return |
| --- | --- | --- | --- | --- | --- |
| Jaguars–Ravens Kalshi winner | 4.85 / 1.20 | 97/121 | 0.82 | Conservative exchange fee 0.02 / risk 0.84 | -11600/2541 percent |
| Jaguars–Ravens Polymarket US winner | 4.85 / 1.20 | 97/121 | 0.8175 | Reviewed one-fill fee 0.01 / risk 0.8275 | -125100/40051 percent |
| NBA Polymarket US spread | 1.92 / 1.99 | 192/391 | 0.49 | Reviewed one-fill fee 0.02 / risk 0.51 | -24700/6647 percent |
| NBA Polymarket US total | 2.08 / 1.81 | 181/389 | 0.44 | Reviewed one-fill fee 0.02 / risk 0.46 | 10300/8947 percent |

The first live monitor caught fresh NBA Kalshi winner and spread calculations.
The complete twelve-case selection pass also observed withdrawn current values
with valid retained arithmetic: source expiry, replaced inputs/policy and native
reconnect/resync were explicit reasons. These are not missing reference or fee
facts. This is evidence of ordinary publication/read integration, **not sustained
fresh coverage**. L01's 30-second native freshness policy is unchanged. The later
monitor, final runtime measurements and build results are noted below.

At 23:06 UTC, accounting was used 1,764 / remaining 98,236, reserved 31, no blocker.
The normal 23:00 six-league cycle charged 15 credits. The 31-credit unresolved
exposure was preserved; no manual settlement, forgiveness, guard change or
unsupported recovery was attempted. Source pauses and owner Stop choices remain
untouched.

Known independent financial engineering is implemented. The genuine external
facts still needed for verified account-specific fees are Kalshi membership/channel
(and intermediary charges if applicable), and ProphetX's applicable account/channel
model, rate/base and rounding. The owner's public schedules support explicit
conservative scenarios, not those missing account facts. Continue L03 ranking and
L04 presentation using the field contract above; L05 owns sustained currentness
and storage-interruption qualification. None is deferred to owner review.


Final local integration: the wheel rebuilt successfully and the app restarted
successfully after the final encoder change; ordinary data subprocesses execute
the current checkout. Documentation, lint, canonical frontend build checks and
whitespace checks passed. No commit/push or hosted CI.

Generation 716 retained 18,219 rows with 2,900 gross calculations, 1,840 reviewed
trade-fee calculations and 1,060 conservative estimates; 240 components were
represented and one had pending finance. Native supported counts were NBA Kalshi
208 / Polymarket US 256, NFL Kalshi 4 / Polymarket US 24, and NHL Kalshi 48.
These counts change with real inventory and exact available lines. The final
current read at generation 718 had 1,042 current prices, 408 current gross, 210
reviewed trade-fee and 198 conservative calculations across the board; its sampled
NBA Polymarket page had no fresh numeric EV. Ordinary workers measured 591–741 MB
and roughly 14–16 seconds per turn in this short final sample. The board remains
truthfully partial. See `test-results/l02/root-final.json`, `current-read-final.json`,
`status-final.json` and `live-observation-final.log`.


The final registered financial suite (including the new L02 regressions) passed
**115 tests and 12 subtests**. CI test classification and generated frontend drift
checks passed; the existing L01 SQL module is now explicitly classified in its
already configured PostgreSQL lane. A final automatic maintenance interruption
at 23:11:28 UTC recovered without intervention: generation 725 published at
23:12:02, 29 components calculated, 712 MB peak. Data was healthy and active at
23:12:07. Accounting confirmed **31 held credits across 12 unresolved attempts**,
used 1,764 / remaining 98,236, no blocker. This recurrence reinforces the open
storage-interruption qualification concern; it is not an account-fee dependency.
