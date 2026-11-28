# PostgreSQL roles

Predict uses a dedicated PostgreSQL 16 cluster on a Unix socket. The legacy
profile stays available during migration and on the single-user development
socket. Activate the split profile during authorized database maintenance.

| Login | Service access |
| --- | --- |
| `prediction_arb` | Cluster bootstrap, login provisioning, backup and operations requiring a database administrator. The split socket admits this login only through the database container’s OS identities. |
| `predict_migrator` | Owns the Predict database, application schemas, relations and routines. Applies packaged migrations and grants in one transaction. Runs guarded physical compaction. |
| `predict_web` | Reads product and retained evidence, including the read-only Database inspector. Inserts control requests, saves research and campaigns, leases selected evidence, applies fee settings and performs the retained replay/grade worker writes. |
| `predict_collector` | Admits source and accounting evidence, publishes and expires current/cohort observations, writes capture and sporting-result evidence, stages archive material and acknowledges runtime commands. |
| `predict_archive` | Reads the archive staging and batch metadata. Assigns batch membership and acknowledges verified files by deleting staged rows and updating delivery counters. |

The versioned grant inventory lives in
[`app/storage/database_roles.py`](../app/storage/database_roles.py).
Web fee Settings can invalidate working calculations and enqueue recomputation.
The collector inserts grading input notifications through the result triggers.
The collector cannot edit saved paper campaigns or acknowledge archive delivery.
The archive cannot edit staged payloads or inspect research. All three runtime
logins lack schema creation, ownership, DDL and membership in the migrator.
The database and its protected data remain in the existing Compose volume.

## Authorized transition

1. Follow the [guarded server procedure](hetzner.md#guarded-postgresql-role-cutover).
   First install the role-capable revision and apply any pending schema
   migrations through maintenance in the legacy profile. Qualify role behavior
   against a disposable copy at that migration level before changing hosted
   authentication. Record migration hashes, backup and active service state.
2. As trusted cluster bootstrap on the existing network-isolated socket, run
   `python -m app.storage roles-enable` from the new image before enabling
   peer/SCRAM. This command requires a current schema and changes ownership
   and grants without writing application rows or migration hashes.
3. Prepare four distinct high-entropy credentials. Use `psql` as the bootstrap
   identity, set `password_encryption` to `scram-sha-256` and use its
   `\password` prompt for each dedicated login. Store only one password per
   file under `/srv/predict`. Use mode 0400, UID 10001, with no symlinks. The
   migration file is `postgres-migrator`; its only mount is the one-off
   maintenance invocation.
4. Stage these two files from this revision separately from the image release.
   Install the tracked [socket HBA](../deploy/postgres-split-hba.conf) and
   [peer identity map](../deploy/postgres-split-ident.conf) into the existing
   database container’s data directory. Preserve ownership by the database
   container’s OS `postgres` user. Check `pg_hba_file_rules` and
   `pg_ident_file_mappings` for errors, then reload PostgreSQL. Confirm the
   trusted database-container bootstrap login still works. From an application
   container identity verify bootstrap connection is denied and the dedicated
   credential authenticates only its own login.
5. Create a separate private, root-owned `postgres-roles.env` for the role
   names and file paths. Keep any existing `archive.env` and its activation
   state. Each credential file is mounted read-only by its intended service.

   ```dotenv
   PREDICT_WEB_DB_ROLE=predict_web
   PREDICT_WEB_DB_SECRET=/srv/predict/postgres-web
   PREDICT_COLLECTOR_DB_ROLE=predict_collector
   PREDICT_COLLECTOR_DB_SECRET=/srv/predict/postgres-collector
   PREDICT_ARCHIVE_DB_ROLE=predict_archive
   PREDICT_ARCHIVE_DB_SECRET=/srv/predict/postgres-archive
   ```

6. Apply the split profile to the existing images in the authorized maintenance
   window. Exercise signed-in Dashboard reads and Novig stream reconnect, Data
   exports, Experiments save and replay, applicable grading, collection control
   and acknowledgment, and archive status. Use disposable tests for direct denied
   writes and for any owner state changes outside the authorized hosted smoke.
   Compare migration, quota, hold, Stop and pause records to the protected
   snapshot. The same checks distinguish service health from functional access.

The release checks active socket authentication from each enabled service
before rolling the changed role configuration. An absent `archive.env`
continues to leave the archive service disabled.

The normal focused release still refuses pending migrations. The full maintenance
path checks the ledger via the web reader, backs up through cluster bootstrap,
and applies pending SQL and grants through the one-off migration login. Newly
introduced write paths need corresponding grants and disposable PostgreSQL tests.

## Storage maintenance

PostgreSQL 16 limits explicit VACUUM to owners and administrators. The migration
login receives the specific `pgstattuple(regclass)` privilege when the extension
is installed. Runtime logins receive no extension permission. The
collector continues ordinary row retention and the database’s built-in
autovacuum. Under storage pressure its maintenance status reports
`vacuum_requires_migration_role`. A qualified operator can run the same
guarded physical compaction with the migration credential from `/srv/predict`:

```sh
docker compose --env-file current-images.env --env-file postgres-roles.env \
  --profile collection --profile archive run --rm --no-deps -T \
  -e PREDICT_DB_ROLE=predict_migrator \
  -e PREDICT_DB_PASSWORD_FILE=/run/predict-migrator \
  --volume /srv/predict/postgres-migrator:/run/predict-migrator:ro \
  web python -m app.storage maintain
```

Check measured storage headroom and maintenance deferrals during cutover.
The existing disk and SQL guards can pause writes until sufficient storage is
reclaimed. Decide who will act on pressure before enabling the split profile.

## Rollback

Keep the backup, trusted bootstrap session and original authentication/layout
until the restricted services pass their checks. If the role cutover fails,
quiesce the affected services and use the trusted bootstrap identity to run
`python -m app.storage roles-rollback` while the revised tool is still available.
The maintenance operator can start the revised one-off container as UID 0
with `PREDICT_DB_ROLE=prediction_arb` to use the trusted bootstrap peer mapping.
The normal application containers run as UID 10001. The
[server recovery procedure](hetzner.md#guarded-postgresql-role-cutover) restores
the original HBA, identity map and host role environment, then recreates the
previously active app containers on the same mounted state. The role rollback
changes ownership and ACLs in a transaction and keeps all committed rows.
Applied schema migrations still follow the existing schema recovery policy and
backup.
