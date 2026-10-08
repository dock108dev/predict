# Admin API: predict-admin-1

`GET /api/admin/status` and compatible `GET /api/admin/current` project local
source, quota and issue state. Reading them does not dispatch provider requests,
consume credits or trigger recovery. `/admin` is a separate operator surface,
not hosted authentication.

`POST /api/admin/current` uses the shared same-origin JSON boundary and service
ownership rules for pause, Stop, guarded recovery and explicit aggregate refresh.
Refresh chooses its own sport scope without changing automatic scope or scheduled
due times; it uses the same ledger and affordability checks. Recovery preserves
spend, reservations, consumed attempts, uncertain charges and due times.
Native-only configuration stays aggregate-disabled during recovery.

## Issues and resource bounds

Issues use provider/category/code plus exact scope/attempt/affected venues for
deduplication. First occurrence is preserved; last time/count advance. Different
attempts or affected venues remain distinct. Retention is bounded by configured
record and byte limits (defaults: 200 records and 1 MiB).

Persistence uses private temporary files, fsync and atomic replacement. Failure
blocks safe recovery rather than inventing clean state. Returned advice is
regenerated from the local safe vocabulary; credentials and raw provider payloads
are excluded. Historical issues retain their recorded provenance and cannot
become a current observation.

Current operation shares the [current state contract](predict-current-1.md).
See [configuration](../configuration.md), [security](../security.md) and
[failure recovery](../error-handling.md) for supported controls and limits.
