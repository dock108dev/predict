# Predict on Hetzner

Predict runs as `web`, `collector`, and `db` in a dedicated Docker Compose project.
The `archive` service exports odds history to a persistent destination with no TTL.
An off-host destination provides protection from loss of the application host.
See [archive deployment and verification](odds-archive-operations.md).
The [public desk](https://predict.dock108.dev/) is open to visitors. Caddy requires
authentication for Admin, the database console, and other operational routes.
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

The image release leaves the host's Caddy config in place. A successful image
deploy does not install new proxy routes. When `deploy/predict.Caddyfile` changes,
copy it from the checkout, validate the full configuration, and reload Caddy.
Keep `predict-auth` in place. From the checkout:

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

After reloading, check the public site without credentials. The favicon request
should redirect to `/view/current/predict-icon.png`. Admin, My Bets and the journal
API should return `401` with a `WWW-Authenticate` header. After signing in with
existing operational credentials, `/my-bets` should display the journal. A bare
`404` for `/my-bets` while the backend serves it indicates a stale proxy route list.

```sh
curl -sS -D - -o /dev/null https://predict.dock108.dev/favicon.ico
curl -sS -D - -o /dev/null https://predict.dock108.dev/admin
curl -sS -D - -o /dev/null https://predict.dock108.dev/my-bets
curl -sS -D - -o /dev/null https://predict.dock108.dev/api/bet-journal
```

## Releases

Start **Deploy Predict dev server** with **Run workflow** in GitHub Actions and
select a branch. For `main`, the equivalent CLI command is
`gh workflow run hetzner.yml --ref main`. Each dispatch builds and smoke-tests
the branch's selected commit, publishes the web, collector, and archive images
to GHCR, and sends their digests to `/srv/predict/release.sh` over SSH. If the
branch advances during the run, dispatch again for the new tip. Select
`publish_only` to run the build, smoke checks, and publication without deploying.
The **Release result** job retains the exact SHA and proxy, Compose,
publication and deployment outcomes in the run summary and its release-result
artifact. Publish-only and disabled deployment appear as intentional skips.

The deploy job requires `HETZNER_DEPLOY_ENABLED=true` and a branch allowed by
the `hetzner` GitHub environment. Set `HETZNER_HOST` and the pinned `HETZNER_KNOWN_HOSTS`
entry as environment variables and `HETZNER_SSH_KEY` as an environment secret.
The key belongs to the restricted `predict-deploy` account. GitHub's job token
authenticates the GHCR pull and is discarded after use.

Install `deploy/compose.yml` and `deploy/release.sh` in `/srv/predict` as root.
Keep this directory and the forced command root-owned. Apply changes to these
two host files over the administrator SSH connection before deploying a release
that needs them. Install both files before the first split-image deploy. The
forced command validates the role and build inputs of each Predict image digest.

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

## Current-row cutover

The current-row release applies forward migrations for per-offer calculations
and coalesced recovery work, then drops generated amount-specific board tables.
The release workflow takes its normal pre-migration database backup. A rollback
must account for these schema changes: an earlier image expecting the dropped
generated tables is not schema-compatible. Preserve subsequent acquisition and
accounting when recovering; do not restore old protected records over new ones.

The Caddy public route list includes `/api/pregame`, `/api/pregame/updates` and
`/api/health`. Install the changed site file with the normal validated Caddy reload
before verifying the new public dashboard. Verify the exact installed image
revision, a normal source receipt through current-row commit, and browser display.

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
