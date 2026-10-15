# Current-state API: predict-current-1

This is the validated current-state interface used by compatibility readers and
explicit injected providers. The ordinary SQL-backed browser uses the separate
[current-board API](../comparison-board-api-contract.md). Shared admission retains
original native observations and rejects silent synthetic or retained substitution.

## Routes and context

| Route | Meaning |
| --- | --- |
| `GET /api/current` | Coherent capture; unique optional `league` and `search` (up to 200 characters) scope only the read |
| `GET /api/current/changes` | Latest revision delta; runtime/revision reset returns a full capture |
| `GET /api/current/updates` | Coalesced post-commit revision notices |
| `GET /api/comparison`, `/api/arbs` | Current-state financial and opposing-leg results; no acquisition |
| `GET /api/current/details` | Exact selected quote/group and optional pair evidence |
| `POST /api/selections`, `GET /api/selections/{token}` | Create and inspect a temporary immutable calculation lease |
| `POST /api/selections/{token}/release`, `/api/selections/{token}/what-if` | Release or explicitly evaluate manual assumptions on that lease |

Details binds `runtime_id`, `state_revision` and `quote_id`. Optional quote/pair
revision, opposing quote and request generation strengthen exact selection. Crossed
selection/revisions return 409; changed runtime or closed/expired context returns
410. Current Details follows coherent revisions without acquiring a lease. Manual
What-if uses a lease; restart/recovery invalidates it rather than substituting data.

`ceiling` and `buffer` select a read-only effective financial policy. Amount must
be positive and at most $100,000; buffer is a 0–1 rate. Comparison separates the
evaluated policy from the configured default and echoes request generation.
Optional comparison runtime/revision must appear together. Overrides never save
settings, source observations or acquisition authority.

## Identity, clocks and notices

`current_contract.serialize` and `validate_snapshot` own semantic validation.
Runtime identity and increasing revisions order updates; conflicting same-revision
content or regressions reject. Source IDs, original price units, orientation,
period, cardinality and economic contracts remain exact. Titles are not identity.

Receipt time, source time, calculation time and connection health are distinct.
Age removes eligibility without rewriting observations. Unknown clocks, fees,
payouts, depth or probability withhold dependent results. A change cursor describes
the latest bounded delta, not a historical backlog; merge only against its stated
base revision. Eight notice streams each retain one pending notice with a bounded
slow-write deadline. HEAD does not subscribe. Heartbeats do not refresh prices.

## Versioned representation

The [schema](predict-current-1.schema.json) describes structure; semantic validation
remains authoritative. The [snapshot](examples/predict-current-1.snapshot.json) is
synthetic, [unavailable example](examples/predict-current-1.unavailable.json) shows
missing data, and [state fragments](examples/predict-current-1.states.json) are not
a complete snapshot.

Supported additive shapes include display-group and `predict-occurrence-1` match
metadata, native contracts, interned `comparison-current-dependencies-2` templates
and selected `comparison_details`. Display identity never merges payout identity.
Expanded profile hashes remain exact references. Compact result shells and filter
indexes avoid repeatedly embedding each full graph; Details expands the pinned graph.

Policy metadata is versioned. `predict-estimate-policy-2` preserves ceiling
semantics; v3 identifies requested funding and benchmark selection. Saved payloads
without additive fields reproduce through their declared legacy path. Do not
assume every snapshot carries the newest fields or reinterpret older arithmetic.
See [financial interfaces](../requested-trade-financial-contract.md).

Funded single results retain allocation, deployed/unused capital, support, net
and buffered values, scope and dependency revisions. `model_available` differs
from ranking eligibility. Supported-size evaluations have an independently
calculated result or explicit refusal. Funded pairs bind both groups/quotes and
revisions, joint states, objectives and bounded-search limitations. V1
[single](predict-funded-single-1.schema.json) and [pair](predict-funded-pair-1.schema.json)
schemas remain supported; v2 result formats preserve explicit requested-funding
metrics. Optional display fields never qualify fees, actual fills or calibrated priors.

## Transport and cancellation

Complete responses keep captured revision/as-of boundaries. Large bodies write in
64 KiB blocks with backpressure. Cooperative policy calculations use one active
and one latest pending job. The versioned [delivery object](comparison-delivery-1.schema.json)
separates validation time, captured calculation time and runtime/revision. A reader's
request generation is not part of reusable financial bytes.

Disconnect, settings changes, supersession, actual temporal boundaries and Stop
release readers and revoke old publication. Selected Details expands only its
chosen context; temporary overrides retain the same finance owners. See
[runtime bounds](../estimated-runtime.md), [security](../security.md),
[Admin API](predict-admin-1.md) and [synthetic preview](../development.md#synthetic-preview).
