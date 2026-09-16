# Historical implementation records

These are the original README slice summaries. Counts and handoff statements
record their original checkpoints, not the current working tree. Run historical
commands from the repository root only within their documented scope.

The numbered slice summaries below retain original evidence and test counts;
they do not set the current next action. Use the
[Desktop tracker](../../prediction_arb_next_steps.md).

The original synthetic example remains available as `python3 -m app.example`.
See the [Slice 1 historical record](slice-1.md),
[Kalshi terms assessment](kalshi-data-use.md), and
[current tracker](../../prediction_arb_next_steps.md).

## Slice 2 — bounded US retail ingestion (complete)

Create a local environment and install REST plus optional stream dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[stream]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m app.polymarket_us_example
```

The default example replays preserved Phase 0 public responses offline. It labels
historical observations and keeps their original capture timestamps. The new tests
are offline; they distinguish replayed live captures from synthetic messages and signing keys. See
[Slice 2](slice-2.md) for authorized public-test controls, secure credential use, protocol
uncertainties, artifact identities, and the live qualification boundary.

The owner-authorized retail key is held in macOS Keychain. Use the bounded
`app.polymarket_us_verify --keychain` command documented in Slice 2 for an explicit
read-only rerun; no credential values belong in source or environment files.

## ProphetX Slice 3

Sandbox API/REST ingestion and authenticated transport recovery are verified. American prices now produce shared probability quotes; quantity sizing and live selection-message delivery remain unqualified. Dedicated sandbox credentials are stored in the project Keychain. See [current handoff](slice-3.md) for the exact evidence, remaining questions and finite verifier.

```sh
.venv/bin/python -m app.prophetx_example
.venv/bin/python -m app.prophetx_verify --help
```

## Kalshi Slice 4

Bounded NFL REST, authenticated snapshots/deltas, timed reconnect/resubscription and
cancellation are qualified. Fractional contracts and dollar prices use Decimal;
fees are modeled separately in Slice 9; settlement comparison is available in Slice 8. Source age, receipt freshness,
state, synchronization and depth are separate. See [Slice 4](slice-4.md) for
precise limits, 110-test verification, captured evidence and Keychain setup.

```sh
.venv/bin/python -m app.kalshi_example
.venv/bin/python -m app.kalshi_verify --help
```

The example is offline and shows historical prices. The verifier requires explicit
live opt-in and a fresh output directory. No orders or trading methods exist.

## Novig Slice 5

Read-only NBX discovery, CASH books, native order reconstruction, quotes, locks,
lifecycle and bounded streaming/recovery are implemented and synthetic-tested.
Live QA/production verification awaits Novig-issued OAuth credentials; the exact
initial WebSocket envelope and ordering/depth guarantees remain unverified.
See [Slice 5](slice-5.md) for access, limits, evidence and the next action.

```sh
.venv/bin/python -m app.novig_example
.venv/bin/python -m app.novig_verify --help
```

## Slice 6 — team and league normalization (complete)

A versioned local registry provides all 32 NFL and 30 MLB teams, explicit aliases,
scoped venue IDs and resolved/ambiguous/unknown/conflicting results with provenance.
Separate event enrichment preserves original observations and participant order.
The offline replay resolves 94 participant occurrences across 47 captured NFL
events; Novig remains synthetic-only and MLB capture coverage remains zero.

```sh
.venv/bin/python -m app.normalization_example
```

151 offline tests and all six examples pass. See [Slice 6](slice-6.md) for
actual coverage, source checks and exact evidence. The historical next action was Slice 13, now complete. Novig credentials and live verification
remain a parallel external dependency.

## Slice 7 — canonical event matching (complete)

Deterministic event groups consume Slice 6 identities and explicit start times.
A versioned atomic local store retains immutable observations, stable canonical
IDs, mapping revisions and reasoned schedule reviews. Ambiguity and conflicting
updates block confirmation; production, sandbox and synthetic scopes stay separate.

```sh
.venv/bin/python -m app.matching_example
```

The 47 captured observations contain 15 production and 32 sandbox native listings.
Production supports 10 canonical events: five Kalshi/Polymarket US pairs and five
singletons. Sandbox has 28 ambiguous listings and four singletons, with no transfer
to production coverage. 176 offline tests and all seven examples pass.
See [Slice 7](slice-7.md) and [evidence](../evidence/slice-7/verification.json).
Event matching establishes sporting identity; market matching and settlement
comparison are implemented separately in Slice 8 below.

## Slice 8 — moneyline market matching (complete)

Fifteen captured native moneyline markets cover all five production event pairs
and form ten cross-venue structural pairs. Same exposure, opposing sporting
outcomes and complementary settlement payoffs are separate outputs. All ten
production pairs remain settlement-UNKNOWN with exact unresolved conditions;
zero currently qualify for settlement-qualified arbitrage evaluation. Independent fee scenarios do not require a matched pair. Synthetic conflicts and
approved-compatibility tests are separate from production evidence.

```sh
.venv/bin/python -m app.moneyline_example
.venv/bin/python -m app.moneyline_example --store /tmp/slice-8-markets.json
```

The matcher requires current Slice 7 parent decisions and preserves scoped native
IDs, source/rule hashes, mapping versions and decision revisions. Changed rules,
parents or active inventory invalidate or re-evaluate dependent qualification.
Duplicate representations retain shared liquidity identifiers without creating
independent opportunities. **213 offline tests and all eight examples pass.**

See [Slice 8](slice-8.md), [offline demonstration](../evidence/slice-8/moneyline-example.json)
and [verification](../evidence/slice-8/verification.json). **Historical handoff: Slice 9 — fee engine (now completed below).**
ProphetX sizing/clock/live-selection limits and Novig credentials/live verification
remain separate dependencies. At the Slice 8 boundary, fees, arbitrage calculation, simulation and dashboard work had not yet been implemented.


## Slice 9 — versioned, outcome-aware fee engine (complete)

Calculate explicit hypothetical acquisition/fill scenarios with Decimal arithmetic,
venue/product schedule selection, order grouping and outcome-dependent charges.
The audit retains inputs, source hashes, schedule versions and a registry snapshot
for offline replay. Unknown charges remain null; account assumptions and deferred
credits remain separate. No actual fill reconciliation is claimed.

```sh
.venv/bin/python -m app.fee_example
.venv/bin/python evidence/slice-9/verify.py
```

**247 offline tests and all nine examples pass.**

See [coverage and API](slice-9.md), [fee examples](../evidence/slice-9/fee-example.json)
and [verification](../evidence/slice-9/verification.json). Kalshi uses explicit scoped
metadata/account rounding; PMUS uses cumulative order charges; ProphetX uses
market net gain; Novig supports documented products with conditional aggregation.
Settlement-UNKNOWN mappings remain unchanged. **Historical handoff: Slice 10 — top-of-book arbitrage detection (completed below).**


## Slice 10 — top-of-book arbitrage detection (complete)

Ask-only cross-venue detection refreshes current matching decisions and separates
pricing diagnostics, conditional outcome cashflows and qualified modeled arbitrage.
Visible equal quantities respect verified units, minimums and increments. Unknown
fees, settlement, clocks, locks and quantities retain their reasons; historical
and synthetic results cannot appear as current production opportunities.

```sh
.venv/bin/python -m app.arbitrage_example
.venv/bin/python evidence/slice-10/verify.py
```

**287 offline tests and all ten examples pass.** Ten production structural pairs
remain settlement-UNKNOWN, yielding 20 candidate leg combinations and zero qualified
production opportunities. The historical replay has one two-ask diagnostic at a
1.0100 sum; no missing books are invented. Twelve synthetic examples demonstrate
positive/zero/negative conditional profits and data/fee/settlement exclusions.

See [API, policies and limits](slice-10.md),
[readable report](../evidence/slice-10/report.md),
[complete example](../evidence/slice-10/detector-example.json) and
[verification](../evidence/slice-10/verification.json).
**Historical handoff: Slice 11 — full-depth arbitrage calculation and sizing (completed below).**


## Slice 11 — full-depth arbitrage calculation and sizing (complete)

Walk all supplied acquisition levels and evaluate equal or unequal quantities on
verified venue grids. Separate objectives select maximum worst-case modeled profit,
maximum ROI and largest cash deployment above explicit profit/ROI thresholds.
Zero allocation remains the no-trade alternative. Cash limits are hypothetical.

```sh
.venv/bin/python -m app.depth_example
.venv/bin/python evidence/slice-11/verify.py
```

**321 offline tests and all eleven examples pass.** Exact small-grid enumeration
and a bounded larger-grid search report their domain, limits and optimality status.
All material outcomes, grouped real fees, exact refunds, conditional fragmentation,
matching exclusions and replay provenance remain explicit. Unknown fees and payouts
stay unknown. Ten production settlement-UNKNOWN pairs still yield zero qualified
current opportunities; missing books are not invented.

See [API, coverage and limits](slice-11.md),
[readable results](../evidence/slice-11/report.md),
[full demonstration](../evidence/slice-11/depth-example.json) and
[verification](../evidence/slice-11/verification.json).
**Historical handoff: Slice 13 — simple live dashboard (now complete).**


## Slice 12 — PostgreSQL historical capture (complete)

Finite historical/synthetic capture now supports a real PostgreSQL database,
exact raw content and Decimal observations, versioned detector/depth audits,
coverage and candidate history, self-contained export and verified restore.
The dedicated local database is stopped after verification; storage is preserved.

```sh
scripts/project-postgres start
.venv/bin/python -m app.storage migrate
.venv/bin/python -m app.storage ingest-default
.venv/bin/python -m app.storage query
.venv/bin/python -m app.storage replay
.venv/bin/python -m app.storage export .local/replay-bundle.json
scripts/project-postgres stop
```

Defaults retain bounded full images and every distinct receipt with shared
content. Saved calculation replay is verified; continuous stream reconstruction,
every exchange event and opportunity survival between discrete samples are not
claimed. Historical production results remain unqualified; conditional diagnostics
and synthetic cases are retained separately. No live credentials were needed.

See [Slice 12 commands, schema, limits and verification](slice-12.md),
[PostgreSQL integration tests](../evidence/slice-12/integration-tests.txt), and
[actual bundle/backup restore results](../evidence/slice-12/restore-verification.json).
**Historical handoff: Slice 13 — simple live dashboard (now complete).**
