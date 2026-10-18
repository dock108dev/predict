# Current comparison coverage — local investigation

October 17, 2026. Read-only local engineering evidence. The owner reports that
Odds and Details are useful and understandable for inspecting observed prices;
this investigation addresses the reported current-comparison limitation.

## Result

There are three independent constraints: old aggregate inputs, an unattached
reviewed Kalshi scoring scope, and conservative global publication invalidation.
Recent native observations exist. Neither source age nor publication state alone
explains the absence of compatible Kalshi comparisons.

The smallest supported next repair is to attach the already reviewed overtime
scope to the exact HOU–JAC Jacksonville YES market, with unchanged-term/evidence
checks. Its matching Polymarket US Short observation exists locally. Publication
validity remains an independent requirement for a current comparison label.

## Scope and method

Eight repeatable-read, read-only PostgreSQL snapshots were captured from
11:33:08.403 to 11:33:23.070 EDT (15:33 UTC). Each detached frame was aged through
the existing Odds presentation functions. First/last frames also retain current
rows without depth. This investigation caused zero HTTP/provider requests, database
writes, refreshes or runtime controls. Ordinary background collection continued
independently. No application, model, source configuration or policy was changed.

Evidence is in `test-results/current-comparison-coverage-20261017/`:

- `investigate.py`, `samples.json`, `summary.json`: method and eight samples.
- `sql-0.json`, `sql-7.json`: coherent first/last SQL frames and aged Odds boards.
- `game-guard-analysis.json`: existing per-game guard recomputed purely from
  retained frames, without a database connection or financial evaluation.
- `selected-scope-analysis.json`: exact reviewed terms and retained PDF hash check.
- `manifest.json`: evidence identities and scope.

These are SQL/presentation diagnostics, not new HTTP/browser qualification, a
load test, continuous availability measurement, hosted CI or owner signoff.

## Source age

Every sample contained 27 games and 102 observations. All 58 numeric differences
were last-known; 44 observations had no comparison. Each numeric difference
included at least one Novig/ProphetX input.

At 11:33:23.070 EDT:

| Venue | Observations | Pass source-only freshness | Display pending | Display last-known | Numeric differences |
| --- | ---: | ---: | ---: | ---: | ---: |
| Kalshi | 16 | 12 | 12 | 4 | 0 |
| Polymarket US | 6 | 6 | 6 | 0 | 6, all last-known |
| Novig | 54 | 0 | 0 | 54 | 26, all last-known |
| ProphetX | 26 | 0 | 0 | 26 | 26, all last-known |

The 80 aggregate observations were about 48.4 hours old and also carried existing
unavailable/uncertain-transport reasons. Four Kalshi observations exceeded their
30-second source-age limit. Twelve Kalshi and all six US observations passed
source-only freshness; pending publication is a separate reason they were not
labeled current. Keep the aggregate holds and existing age limits unchanged.

Twenty-eight Novig observations had no compatible other-venue observation. These
missing peers are distinct from the 16 Kalshi scope refusals.

## Matching and scoring scope

All 16 Kalshi observations were occurrence-matched but had overtime `unknown`.
The generic message “Occurrence identity or scoring scope is unresolved” hides
which field failed. For the inspected JAC YES row, the first structural blocker
is the scoring scope, not an unmatched game or an optional financial input.

`app/comparison/combined_native.py` reads `native_scope_binding.overtime`, defaulting
to `unknown`; the current KXNFLGAME discovery binding has no overtime value.
`app/dashboard/current_normalized.py` carries it into scope identity, and
`gross_comparison` in `app/dashboard/comparison_board.py` refuses unknown scope.

There are six same-selection native candidates across CAR–PHI, BAL–CLE and
HOU–JAC if only the scoring-scope mismatch is set aside for diagnosis. All six
candidate pairs met source-age limits at the final snapshot; their source-clock
separations ranged from 1.375027 to 17.041442 seconds. These are candidates,
not newly admitted comparisons.

The exact narrow repair example is:

| Field | Kalshi | Polymarket US |
| --- | --- | --- |
| Native event | KXNFLGAME-26OCT18HOUJAC | 141502 |
| Native market/outcome | KXNFLGAME-26OCT18HOUJAC-JAC / yes | 1198902 / 2397287 |
| Native side | YES | Short |
| Normalized selection | NFL:JAX / win | NFL:JAX / win |
| Price in USD per contract | 0.5700 | 0.5675 |
| Original source clock (UTC) | 15:32:55.289 | 15:33:12.330442 |
| Age at final read | 27.781203 seconds | 10.739761 seconds |

Source-clock separation is 17.041442 seconds. Both displayed pending because of
publication identity mismatch. Preserve the explicit JAX win mapping for US Short
and the separate Kalshi `not_win` predicates; opposing named selections are not
interchangeable price peers.

The retained selected review at
`test-results/sc07-execution/source/selected-series-fee-and-ot-resolution.json`
supports overtime included for this exact JAC YES market. Current retained
`original_terms` exactly matches its reviewed text, canonical SHA256
`b0137b5db2fb2ec32870890ba5b2bbf7926748c59ed83bf51407b62985a5f8bd`.
The successful current-series response points to FOOTBALLGAMEWIN; the retained
PDF SHA256 is `57b57e1ad96466e413e9274c0d2598225997e35d71262eb63c4ae13858b81d38`.
The review explicitly says production scope was not automatically changed.
Runtime attachment is the missing engineering step; new provider input is not
needed for this selected fact.

Do not make overtime included a global default, reuse expired annotations,
rewrite original terms, or widen this selected review to every market.

## Comparator choice is another coverage constraint

The established comparison chooses the lowest-price compatible other-venue
observation before considering freshness. Its exact arithmetic and deterministic
tie behavior were not changed or bypassed here.

For the saved JAC pair, both native prices are below the aggregate comparison
price `1 / 1.75`, approximately 0.571429 USD. With a valid selected scope attachment,
either direction would select the other native observation at these saved prices.
That conditional price-order conclusion does not grant publication authority.

Houston differs: retained aggregate odds 2.3 imply approximately 0.434783 USD,
below US Long 0.4350 and Kalshi HOU YES 0.4400. Attaching Houston scope alone would
still select a historical peer. Do not promise universal current comparisons,
silently change comparator selection, or relabel an old quote as current.

## Publication reconciliation

All eight sampled reads differed from the global input marker/runtime identity.
Publication nevertheless advanced twice during the 14.67-second sample, and the
same runtime remained healthy/active. Capture/as-of age ranged from 3.10 to 26.15
seconds. This is time since captured publication input, not measured commit-to-
publication latency. The evidence does not show a permanently stopped publisher
or quantify rejected publication attempts.

`app/storage/latest_board.py` hashes current identities across the whole stored
universe. A mismatch adds `current_dependencies_changed`; runtime revision mismatch
adds `runtime_authority_changed`. Both are applied to every observation and both
comparison inputs. Pure heartbeat time is excluded from the material runtime
fingerprint, but source-status changes accompanying book arrivals can change it.

A separate frozen guard analysis found 23 of 27 published game guards equal to
current SQL at each endpoint. Those games had no pending source-current
observations. The three recent native games had changed full-game dependencies,
even though six US observations individually matched current SQL source values,
clocks and book revisions. Therefore the sample establishes conservative global
fanout in code, but does not prove that per-game guards alone would make these
18 native observations current. Counts of unchanged published guards between
samples are not proof of equivalence to current SQL.

Before any publication repair, reproduce changed-game-A/unchanged-game-B behavior
in a disposable database, and preserve epoch, Stop, source health, configuration,
identity and time-boundary checks. Never remove the global guard without an exact
replacement proof. Current comparison labels require both source eligibility and
valid published dependencies.

## Next bounded engineering handoff

Implement a selected, evidence-bound JAC YES scoring attachment and a precise
scope-unavailable explanation, then validate the ordinary JAC comparison using
normal background collection. Check both native inputs, exact arithmetic, ages
and honest publication state. Preserve all other market scope and comparator
behavior. If it remains pending, retain the exact changed dependencies before
proposing a publication repair. A disposable A/B reproduction can establish that
separate boundary without changing ordinary runtime policy.

A short Details takeaway remains a secondary presentation improvement. It must
summarize only captured inputs, preserve units/sign and disclose the comparator's
age/state; it must not imply currentness. No takeaway or coverage repair was
implemented in this investigation.

## Preservation and validation

No application/runtime restart or database mutation was performed. Protected
records, holds and source settings were not acted on; this is not a newly repeated
protected-state regression suite. No new broad test result is claimed. Existing
local delivery, financial unknowns and hosted-CI limitations retain their prior
scope. Documentation/link/whitespace checks are recorded separately in the manifest.
