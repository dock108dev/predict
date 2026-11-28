# Predict on Hetzner

Predict runs as `web`, `collector`, and `db` in a dedicated Docker Compose project.
The `archive` service exports odds history to a persistent destination with no TTL.
An off-host destination provides protection from loss of the application host.
See [archive deployment and verification](odds-archive-operations.md).
The [personal workspace](https://predict.dock108.dev/) requires the owner's
existing login for every page, API, asset and download. Caddy is the only public
application entry point; web stays on loopback and PostgreSQL uses a private Unix
socket. This host is dedicated to Predict.
Install [the site config](../deploy/predict.Caddyfile) on the server and import it
from `/etc/caddy/Caddyfile`. Keep the user name and bcrypt hash in the separate
`/etc/caddy/predict-auth` file readable by Caddy. The `predict` DNS record points
to the Hetzner host. Caddy terminates TLS, checks the public origin, and forwards
to the server's loopback interface. For private access from the Mac, use:

```sh
ssh -N -L 127.0.0.1:8784:127.0.0.1:8784 hetzner
```

Open `http://127.0.0.1:8784/`. Stop the local web process first if it uses that
port. The dashboard checks the local port as part of its browser boundary.

The release installs its managed Compose, proxy and next release-script files
from the verified web image. It validates candidate configuration before changing
the host and preserves the existing owner authentication file, private settings,
provider secrets, database, archive and accounting state. Routine proxy and
Compose changes therefore travel with the tested release.

The separate `/etc/caddy/predict-owner-session.Caddyfile` supplies remembered
owner access. After initial provisioning of `predict-auth`, install
[the provisioner](../deploy/remember-owner.py) as `/srv/predict/remember-owner.py`
and run it once as root before validating the site configuration:

```sh
sudo python3 /srv/predict/remember-owner.py
```

It generates a private random cookie credential, preserving the existing login.
Repeating the command preserves existing sessions. The private snippet is not
part of the managed image bundle and must be preserved across releases/backups.
To revoke remembered cookies deliberately, run with `--rotate`, then validate and
reload Caddy. Password changes require that rotation if old cookies must also be
revoked; the token itself has no server-side expiry. No token belongs in Git,
GitHub settings or the Mac's `.env`.

For initial provisioning or recovery, an administrator installs the restricted
release script and the proxy once. Keep `/etc/caddy/Caddyfile` importing
`/etc/caddy/predict.Caddyfile`, and preserve `/etc/caddy/predict-auth`. For an
emergency proxy-only repair from the checkout:

```sh
scp deploy/predict.Caddyfile hetzner:predict.Caddyfile
ssh hetzner '
  set -eu
  sudo install -o root -g caddy -m 0640 predict.Caddyfile /etc/caddy/predict.Caddyfile
  sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  sudo systemctl reload caddy
  rm predict.Caddyfile
'
```

After reloading, unauthenticated requests to the home page, research, APIs,
assets and favicon must return `401` with a `WWW-Authenticate` header. Foreign
browser origins remain refused. After signing in, normal routes and downloads
work through the same proxy. Authorization and Cookie credentials are stripped before
forwarding to the application.

```sh
curl -sS -D - -o /dev/null https://predict.dock108.dev/favicon.ico
curl -sS -D - -o /dev/null https://predict.dock108.dev/
curl -sS -D - -o /dev/null https://predict.dock108.dev/research
curl -sS -D - -o /dev/null https://predict.dock108.dev/admin
curl -sS -D - -o /dev/null https://predict.dock108.dev/my-bets
curl -sS -D - -o /dev/null https://predict.dock108.dev/api/bet-journal
```

## Releases

Push to `main` to run **CI**. Its single private-beta job performs focused
data/calculation/deployment checks, builds or reuses cached role images, exercises
the private proxy, publishes pinned digests and
deploys through the restricted SSH connection. The runner budget is two minutes;
GitHub queue time is separate. Failed checks stop the release, and main is
rechecked before build and server handoff so an older revision cannot replace
newer work. Full historical regression and user-journey suites are manual-only.

For manual rescue, select **Run workflow** on **CI**, choosing `main`, or use
`gh workflow run ci.yml --ref main`. The same focused checks run first. Optional
`publish_only` verifies and publishes images without changing the server. This
personal setup deploys current main only; it has no feature-branch release funnel.
The run summary records exact SHA, selected validation, cache/build, smoke,
publication and deployment times. An intentional stale/disabled skip is explicit.

Normal releases use the fast image-manifest protocol and refuse unapplied schema
migrations before stopping or reconfiguring services. A full database backup can
exceed the normal two-minute budget. For an authorized schema release, choose
**Run workflow** on **CI**, select `main`, and enable `schema_maintenance`, or run
`gh workflow run ci.yml --ref main -f schema_maintenance=true`. Leave
`publish_only` off. The same focused checks and current-main checks run before
the guarded release. The maintenance run uses GitHub's standard job allowance
while the host retains its pre-migration backup, applies the migration, and
verifies service health. Subsequent pushes use the normal fast path.

The deploy job requires `HETZNER_DEPLOY_ENABLED=true` and a branch allowed by
the `hetzner` GitHub environment. Set `HETZNER_HOST` and the pinned `HETZNER_KNOWN_HOSTS`
entry as environment variables and `HETZNER_SSH_KEY` as an environment secret.
The key belongs to the restricted `predict-deploy` account. GitHub's job token
authenticates the GHCR pull and is discarded after use.

Bootstrap `deploy/compose.yml` and `deploy/release.sh` in `/srv/predict` as root.
Keep this directory and the forced command root-owned. Subsequent managed files
come from the validated web-image bundle. The forced command validates the role
and build inputs of each Predict image digest; it accepts no arbitrary remote
command or destination path.

For the personal Monitor/Live deployment, install and run the committed
`deploy/configure-retention.sh` as root before dispatching the image release.
It creates a persistent host archive and `archive.env` only if no archive
configuration exists, preserving an owner's existing destination. The next
ordinary release applies that configuration to collector and archive. This
initial destination has no off-host backup; provision additional capacity and
an external backup for indefinite growth. Never delete verified history as a
routine disk cleanup. See [Monitor/Live behavior](monitor-live.md).

Web, collector, and archive share Docker layers and have separate image
references. A release preserves a running service's image when its build inputs
match. Dashboard assets and dedicated web entry points roll only web. Collector
worker changes roll only collector. Shared code, dependency locks and migrations
can roll multiple services. PostgreSQL has its own image and volume. Changes to
the host Compose file may require quiescing the collector and archive.

The release script records the active references in `current-images.env` and the
prior references in `previous-images.env`. The first release reads the old
`current-image` file to recover the previous image. A change to `archive.env`
reapplies collector and archive configuration on the next release. You can also
apply it immediately to the affected service with Compose.

After a healthy release records its current and previous references, the managed
cleanup removes only obsolete Predict images. It protects every running or stopped
container image and both release reference sets, refuses cleanup when rollback
identity cannot be resolved, and never forces image removal. A maintenance refusal
is reported separately from release health. No volume, database, archive or backup
is removed by image maintenance.

### Guarded PostgreSQL role cutover

Schedule this maintenance only after the owner explicitly authorizes the hosted
cutover and a disposable PostgreSQL 16 copy at the installed migration level
passes the [role qualification](postgresql-roles.md). Use the validated installed
revision and keep its image digests fixed throughout the role-only change. At
migration 129, keep the Win $25 campaign, original receipts, saved runs, grades,
accounting and spool on their existing mounts. Keep the existing activation
files, Stop and source pauses, and select a window outside protected captures.

Run from `/srv/predict` as root in Bash. Keep the parent maintenance shell open
with file descriptor 9 locked while running the command blocks. Save the exact
running image digests and OCI revisions, the active service list, migration
ledger, Stop/pause choices and account/quota/hold evidence privately. Stage the
two tracked socket-auth files from the qualified checkout in a private operator
directory. Hold `deploy.lock`
through the maintenance, including smoke checks or recovery. The GitHub release
script acquires the same lock, so run the commands below against the installed
images and dispatch any later release after closing this maintenance session.

```bash
umask 077
cd /srv/predict
exec 9>deploy.lock
flock -x 9
[[ ! -e postgres-roles.env && ! -L postgres-roles.env ]]

base=(docker compose --env-file current-images.env)
if [[ -f archive.env ]]; then base+=(--env-file archive.env); fi
profiles=(-f compose.yml --profile collection --profile archive)
legacy=("${base[@]}" "${profiles[@]}")
psql_in_db=("${legacy[@]}" exec -T db psql -X -v ON_ERROR_STOP=1
            -h /run/predict-postgres -p 55432 -U prediction_arb -d prediction_arb)
bootstrap=("${legacy[@]}" run --rm --no-deps -T --user 0:0
           -e PREDICT_DB_ROLE=prediction_arb web python -m app.storage)
recovery=$(mktemp -d "$PWD/.role-recovery.XXXXXXXX")
cp current-images.env "$recovery/"
running=$("${legacy[@]}" ps --status running --services web collector archive)
[[ -n $running ]]
mapfile -t active <<< "$running"
printf '%s\n' "${active[@]}" > "$recovery/active-services"
```

Proceed after every setup command succeeds. Keep the lock in the parent shell
if a maintenance block ends early.

```bash
(
set -euo pipefail
"${legacy[@]}" cp web:/predict/deploy/managed/managed-config.py "$recovery/managed-config.py"
[[ $("${bootstrap[@]}" migration-status) == 0 ]]

"${legacy[@]}" stop "${active[@]}"
"${psql_in_db[@]}" -Atqc 'SELECT version, sha256 FROM public.schema_migration ORDER BY version' \
    > "$recovery/migration-ledger"
"${legacy[@]}" exec -T db pg_dump -h /run/predict-postgres -p 55432 \
    -U prediction_arb -d prediction_arb -Fc -Z1 > "$recovery/database.dump"
"${legacy[@]}" exec -T db pg_restore --list < "$recovery/database.dump" > "$recovery/database.contents"
"${legacy[@]}" exec -T db stat -c '%a:%u:%g %n' /var/lib/postgresql/data/pg_{hba,ident}.conf \
    > "$recovery/socket-auth-modes"
"${legacy[@]}" cp db:/var/lib/postgresql/data/pg_hba.conf "$recovery/pg_hba.conf"
"${legacy[@]}" cp db:/var/lib/postgresql/data/pg_ident.conf "$recovery/pg_ident.conf"
python3 - "$recovery" <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

spool = Path('state/predict-current/experiment-depth-stage.sqlite3')
if spool.exists():
    target = Path(sys.argv[1]) / spool.name
    with closing(sqlite3.connect(f'{spool.resolve().as_uri()}?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as copy:
            source.backup(copy)
            assert copy.execute('PRAGMA quick_check').fetchall() == [('ok',)]
PY
"${bootstrap[@]}" roles-enable
)
```

Use the [provisioning instructions](postgresql-roles.md#authorized-transition)
for the four distinct SCRAM passwords, private files and exact `postgres-roles.env`
contents. While the legacy authentication files are still active, set the role
passwords using `psql`'s interactive `\password` prompt. Keep a trusted database
container console available. Install the qualified HBA and identity map in the
existing data directory, owned by the database container's `postgres` user.
Before reloading, check that both `pg_hba_file_rules` and
`pg_ident_file_mappings` report zero errors. After reloading, verify a fresh
bootstrap connection through `psql_in_db`. Use the following commands once the
private `postgres-roles.env` is in place.

```bash
split=("${base[@]}" --env-file postgres-roles.env "${profiles[@]}")
(
set -euo pipefail
"${split[@]}" config --format json > "$recovery/split-compose.json"
[[ $(python3 -I "$recovery/managed-config.py" database-profile "$recovery/split-compose.json" "$PWD") == split ]]
for service in web collector archive; do
    [[ $service != archive || -f archive.env ]] || continue
    "${split[@]}" run --rm --no-deps -T "$service" python -m app.storage verify-role
done
[[ $("${split[@]}" run --rm --no-deps -T \
    -e PREDICT_DB_ROLE=predict_migrator \
    -e PREDICT_DB_PASSWORD_FILE=/run/predict-migrator \
    --volume "$PWD/postgres-migrator:/run/predict-migrator:ro" \
    web python -m app.storage migration-status) == 0 ]]
"${split[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 180 "${active[@]}"
)
```

Query `session_user`, `current_user` and `rolsuper` using the application's
actual connection in each running service and in the one-off migration
container. Verify the designated `predict_*` login, absence of superuser,
migrator ownership of the application objects and no write privilege for web on
the protected accounting, source evidence or receipt tables. Compare the saved
migration ledger and control settings. Use authenticated Dashboard reads and a
Novig stream reconnect, Data export, and paper campaign read and replay. Verify
an authorized collection command and collector acknowledgment while preserving
Stop and source pauses. If no command is authorized, carry that check forward to
the next permitted command. Check the next normally scheduled collector receipt,
archive acknowledgment and Win $25 replay through their original IDs and clocks.

**Recovery in the same maintenance window.** If the split startup or smoke
checks fail, stop the members of `active` with the split Compose inputs. If
`roles-enable` committed, run `"${bootstrap[@]}" roles-rollback` while the
trusted UID 0 socket login and role-capable image are available. Restore the
saved `pg_hba.conf` and `pg_ident.conf` into the current volume with their original
ownership and modes, reload PostgreSQL, and verify a fresh legacy bootstrap
connection. If the new socket rules broke bootstrap, first restore the auth files
and use `pg_ctl reload` as the database container's OS `postgres` user. Move the
private `postgres-roles.env` into the private recovery directory. Recreate only
the previously active app services and repeat the migration, controls,
protected-data and signed-in health checks.

```bash
"${legacy[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 180 "${active[@]}"
```

Keep the original volumes, current spool and captured backups. Role rollback
changes ownership and grants. Restoring an earlier data snapshot would discard evidence
committed during the window. The release script's image rollback alone leaves
host-managed socket authentication and credentials in place.

### Collector recovery after the Win $25 receipt expansion

Migration 129 raises the Win $25 receipt limit from 512 KiB to 8 MiB. The
previous collector can only drain the legacy SQLite table. It also requires the
exact migration file to start against the upgraded PostgreSQL ledger. Recover
the collector independently of web and archive. Keep the current PostgreSQL
volume and schema so the campaign, saved runs, and receipts committed since the
migration remain available.

From `/srv/predict`, use the installed Compose file and the same optional
`archive.env` and `postgres-roles.env` files as the normal release. In Bash,
initialize these commands under the host release lock. For a successful
rollout, use the collector digests from `current-images.env` and
`previous-images.env`. If rollout failed after migration, use the attempted
candidate digest from that release and the pre-rollout digest from the retained
release record. Image manifests are recorded only after health checks pass.

```bash
exec 9>deploy.lock
flock -x 9
compose=(docker compose --env-file current-images.env)
for file in archive.env postgres-roles.env; do
    if [[ -f $file ]]; then compose+=(--env-file "$file"); fi
done
compose+=(-f compose.yml --profile collection --profile archive)
candidate_collector=$(sed -n 's/^PREDICT_COLLECTOR_IMAGE=//p' current-images.env)
previous_collector=$(sed -n 's/^PREDICT_COLLECTOR_IMAGE=//p' previous-images.env)
[[ $candidate_collector =~ ^ghcr\.io/dock108dev/predict@sha256:[a-f0-9]{64}$ ]]
[[ $previous_collector =~ ^ghcr\.io/dock108dev/predict@sha256:[a-f0-9]{64}$ ]]
```

1. Stop `collector`. Using the installed candidate image, take a consistent
   copy of its exact spool and run the spool initialization below. It moves
   already-accepted larger rows and their associated decision or follow-up out
   of the previous collector's `staged` table in one SQLite transaction.
   Proceed after the command succeeds. Preserve the backup alongside the
   spool.

   ```bash
   "${compose[@]}" stop collector
   PREDICT_COLLECTOR_IMAGE="$candidate_collector" "${compose[@]}" \
       run --rm --no-deps -T collector python - <<'PY'
   from contextlib import closing
   from pathlib import Path
   import sqlite3
   from tempfile import NamedTemporaryFile

   from app.collection.current_storage_policy import require_disk_space
   from app.collection.experiment_depth_stage import DepthStage

   path = Path('/predict/.local/predict-current/experiment-depth-stage.sqlite3')
   if path.exists():
       require_disk_space(path, 3 * path.stat().st_size + 128 * 1024)
       with NamedTemporaryFile(prefix='experiment-depth-before-rollback-',
                              suffix='.sqlite3', dir=path.parent, delete=False) as copy:
           with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(copy.name)) as backup:
               source.backup(backup)
           print('Retained spool copy:', copy.name)
   DepthStage(path).initialize()
   with closing(sqlite3.connect(path)) as spool:
       legacy = spool.execute('SELECT count(*) FROM staged').fetchone()[0]
       parked = spool.execute('SELECT count(*) FROM staged_large').fetchone()[0]
   print('Legacy receipts:', legacy, 'Parked receipts:', parked)
   PY
   ```

2. Copy the byte-identical `129_experiment_depth_receipt_capacity.sql` from
   the installed candidate image to a private host directory. Use a temporary
   Compose override for the collector only. Set `image` to the verified
   previous collector digest and bind the copied file read-only at
   `/predict/app/storage/migrations/129_experiment_depth_receipt_capacity.sql`.
   Keep the normal `./state` mount.

   ```bash
   recovery_dir=$(mktemp -d "$PWD/.collector-recovery.XXXXXXXX")
   override="$recovery_dir/compose.yml"
   receipt_migration="$recovery_dir/129_experiment_depth_receipt_capacity.sql"
   container=$(docker create --network none --entrypoint /bin/true "$candidate_collector")
   docker cp "$container:/predict/app/storage/migrations/129_experiment_depth_receipt_capacity.sql" \
       "$receipt_migration"
   docker rm "$container"
   chmod 0644 "$receipt_migration"
   cat > "$override" <<EOF
   services:
     collector:
       image: $previous_collector
       volumes:
         - type: bind
           source: $receipt_migration
           target: /predict/app/storage/migrations/129_experiment_depth_receipt_capacity.sql
           read_only: true
           bind:
             create_host_path: false
   EOF
   fallback=("${compose[@]}" -f "$override")
   status=$("${fallback[@]}" run --rm --no-deps -T collector python -m app.storage migration-status)
   [[ $status == 0 ]]
   ```

   Start the fallback with `"${fallback[@]}" up -d --no-deps --wait collector`
   after `migration-status` prints `0`, if the collector was running before
   recovery. The previous collector can drain its original-sized entries. The
   parked receipts keep their hashes, clocks, and follow-up links. A write guard
   preserves the parked occurrence if the previous collector tries to recapture it.

3. To return to the candidate, run `"${fallback[@]}" stop collector`. If
   collection should be running, use the main Compose file to recreate the
   candidate with the same state mount.

   ```bash
   PREDICT_COLLECTOR_IMAGE="$candidate_collector" "${compose[@]}" \
       up -d --no-deps --force-recreate --wait collector
   ```

   The candidate drains both tables and resolves already committed entries
   against their original IDs. Review dispositions for the parked receipts.
   Keep the backup as recovery evidence. Reusing it as the active spool would
   discard any intervening staging and disposition changes.

Create a private `postgres-bootstrap` file with a random password for a new
cluster. The database uses a shared Unix socket and a persistent `predict_postgres`
volume. Compose gives both services a 4 GiB SQL storage ceiling. PostgreSQL
reclamation still starts at about 1.2 GiB, leaving room for rewrites under load.
The 1 GiB free-disk floor and logical retention limits still apply. Source
credentials live in `/srv/predict/provider-secrets` as mode 0600
files owned by UID 10001. The collector alone mounts them. Use `kalshi.json`
and `polymarket_us.json` with the fields in
[Credentials](configuration.md#credentials), and put the SportsGameOdds key on
one line in `sportsgameodds`. Set `direct_novig_enabled` to `false` in the server's
source configuration to get Novig prices through SportsGameOdds. The legacy Odds API's existing account records are
retained. Its macOS-bound credential verification needs separate requalification
before selecting that provider on the server.

## Using the personal server from the Mac

Open `https://predict.dock108.dev` and sign in with the existing owner credentials.
The proxy remembers a successful login in that browser for up to one year,
including browser restarts and normal server deployments. Clearing site cookies,
an expired cookie or a separate private-browsing session requires another login.
Hosted use requires no local `.env` change, running local app, SSH tunnel or
provider API key. Collection, research checkpoints and exports run on the server
without the browser open.

The existing GitHub deployment settings are already configured:
`HETZNER_DEPLOY_ENABLED` is a repository variable; `HETZNER_HOST` and
`HETZNER_KNOWN_HOSTS` are `hetzner` environment variables;
`HETZNER_SSH_KEY` is that environment's restricted-key secret. Provider API keys
stay in `/srv/predict/provider-secrets`, mounted only into collector. Do not put
provider keys or a personal access token in GitHub for this deployment.

The Mac's private `.env` is for optional local acquisition, not hosted operation.
Leave it private and out of Git. While this server owns acquisition, keep
`.local/predict-remote-collection-owner` present: it prevents accidentally starting
a second local collector. Read-only [snapshot development](local-ui-development.md)
continues to work with the existing `hetzner` SSH alias and PostgreSQL tools.
Do not remove the marker to resolve a local startup error; acquisition ownership
requires transferring the latest state and accounting deliberately.

The one-time server cleanup keeps older migration backups and the retired
application's data in a private off-host archive on the Mac. These copies and the
live odds archive are different records. Preserve the off-host archive; it is not
temporary build output. A long-term automated off-host destination remains a
separate storage choice.

## Current-row cutover

The current-row release applies forward migrations for per-offer calculations
and coalesced recovery work, then drops generated amount-specific board tables.
The release workflow takes its normal pre-migration database backup. A rollback
must account for these schema changes: an earlier image expecting the dropped
generated tables is not schema-compatible. Preserve subsequent acquisition and
accounting when recovering; do not restore old protected records over new ones.

The private Caddy proxy authenticates every route, including `/api/pregame`,
`/api/pregame/updates` and `/api/health`. Internal service health uses loopback
without exposing a public health bypass. Verify the exact installed image
revision, a normal source receipt through current-row commit, and authenticated
browser display.

## Collection ownership and recovery

Restore a logical PostgreSQL backup into the new database while collection is
disabled. Copy the current source configuration and the separate accounting
state with both collectors quiescent. Preserve `.local/predict-odds`, the account
and window files, any alternate authority file, and the native attempt records.
Check the restored `data_runtime` Stop and pause state and compare the ledger
checksums before enabling collection. Keep `/srv/predict/state` private and
writable by UID 10001. Keep `.local/predict-remote-collection-owner` on the Mac
once the server owns collection. To move ownership back, quiesce the server and
transfer the **latest** database and ledgers before removing that marker.

Create `/srv/predict/collection-enabled` once the server owns collection. The
release script then starts the collector as a persistent Compose service. It
collects and calculates affected-game current rows with no browser running, subject
to existing schedules and budget guards. Collector health uses bounded owner
heartbeat/dispatch/failure checks and distinguishes deliberate Stop or disabled
collection. Web health calls `/api/health`, which checks current SQL read availability
without importing or invoking financial arithmetic. Neither health check proves
a real offer reached the browser. See [current pregame](current-pregame.md).
Check the collector logs for startup, dispatch or publication errors.
Admin Stop and source pauses stay in PostgreSQL and survive service or host
restarts. The release script checks the
applied migration digests, backs up PostgreSQL before forward migrations, and
restores the previous image after a failed health check when the schema is
unchanged. For a failed release that did migrate, inspect the retained backup
and the current data before choosing a recovery. Keep any subsequent provider
accounting intact. Back up PostgreSQL and the accounting files off the server.

## Observing a live slate

The collector records each appearance of an exact cross-venue pair with
positive modeled after-fee return at the desk's default $100 stake before fees.
The record captures the first qualifying publication's two prices, selections,
source clocks, total funding, lowest modeled net payout and profit, and the
states modeled. It also records when the captured depth does not support the
allocation. The completed-game model alone does not qualify full arbitrage.
A pair opens another entry if a later
publication drops it and it subsequently qualifies again. Closed entries are
retained for up to 30 days, with a limit of 10,000. From `/srv/predict`, read
the latest entries with an administrator connection.

```sh
docker compose --env-file ./current-images.env exec -T db \
  psql -h /run/predict-postgres -p 55432 -U prediction_arb -d prediction_arb -x \
  -c 'SELECT appeared_at, disappeared_at, pair_id, generation, facts FROM arb_appearance ORDER BY appeared_at DESC, id DESC LIMIT 25'
```

Run the coverage sampler in `web` and save its JSON lines outside the container.
For example, from `/srv/predict`:

```sh
docker compose --env-file ./current-images.env exec -T web \
  python scripts/live_coverage_census.py --phase live --samples 240 > live-coverage.jsonl
docker compose --env-file ./current-images.env exec -T web \
  python scripts/pipeline_storage_report.py /tmp/storage.json
docker compose --env-file ./current-images.env cp web:/tmp/storage.json ./storage.json
```

Take storage and account snapshots before and after the window. Compare the
fresh source, matched, and published counts by sport and market against the
scheduled games. Record worker outages, stale quote gaps, accounting deltas,
database growth and resource pressure alongside coverage.
