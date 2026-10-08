# Current state API: predict-current-1

The ordinary board consumes validated current snapshots and bounded revision
notices. Shared source admission supplies verified normalized identities; the
serializer derives stable event/group/outcome/instrument IDs, displays and
calculations from original inputs. Saved and synthetic data cannot silently
replace ordinary source observations.

## Routes

- `GET /api/current`: latest coherent validated snapshot.
- `GET /api/current/updates`: small coalesced post-commit revision notices.
- `GET /api/arbs`: opposing-leg results from current state.
- `POST /api/selections`: temporary immutable calculation lease.
- `GET /api/selections/{token}`: inspect a live lease.
- `POST /api/selections/{token}/release`: release a lease.
- `POST /api/selections/{token}/what-if`: explicit manual probability/cost/quantity calculation.

Live Details follows current quote revisions and does not acquire a lease.
Manual What-if binds its calculation to a temporary lease. Expiry, restart and
recovery invalidate leases; stale selections fail rather than substitute data.

## State and identity

`current_contract.serialize` admits normalized inputs; `validate_snapshot`
reproduces derived values. Runtime identity and increasing state revisions define
update ordering. Duplicate/regressing revisions cannot replace committed state;
conflicting same-revision content is rejected. Native instruments retain exact
source IDs and original values. Time, orientation, period, result policy and
cardinality are validated before comparison; labels alone do not prove equivalence.

Quote receipt time, source time and provider connection health stay separate.
Monotonic aging can remove eligibility without changing original observations.
Unknown source clocks, fees, payout terms, depth or probability withhold dependent
results. Signed gross Arb percentages and manual dollar What-if have distinct
input requirements. Original units and rational conversion basis remain available.

Notices include runtime and revision identities. There are at most eight streams,
one pending notice per stream and a bounded slow-write deadline. HEAD does not
subscribe. Restart resets runtime and leases. Browser notices and heartbeats do
not establish provider freshness or dispatch a paid refresh.

## Schema and examples

The [JSON schema](predict-current-1.schema.json) describes structural fields;
semantic validation remains authoritative in `app/dashboard/current_contract.py`.
The [snapshot example](examples/predict-current-1.snapshot.json) is synthetic.
The [unavailable example](examples/predict-current-1.unavailable.json) illustrates
missing data, and [state fragments](examples/predict-current-1.states.json) are
illustrative fragments rather than a complete snapshot.

The [synthetic development server](../development.md#synthetic-preview) injects
its test provider through production interfaces. It cannot be selected by the
ordinary launcher. See [architecture](../architecture.md) for module ownership
and [Admin contract](predict-admin-1.md) for source controls.
