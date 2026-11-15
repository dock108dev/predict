# Predict on Hetzner

Predict runs as `web`, `collector`, and `db` in a dedicated Docker Compose project.
The optional `archive` service exports odds history to an off-host mount.
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

The image release leaves the host's Caddy config in place. When
`deploy/predict.Caddyfile` changes, replace the imported site file on the host,
validate the full configuration, and reload Caddy. Keep `predict-auth` in place.

```sh
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
```

After reloading, check the public site without credentials. The favicon request
should redirect to `/view/current/predict-icon.png`. Admin should return
`401` with a `WWW-Authenticate` header.

```sh
curl -sS -D - -o /dev/null https://predict.dock108.dev/favicon.ico
curl -sS -D - -o /dev/null https://predict.dock108.dev/admin
```

## Releases

The **Deploy Predict dev server** workflow builds and smoke-tests the exact
commit that passed **CI** for a push to `main`. It checks that the commit is
still at the tip of `main` before publishing the web, collector, and archive
digests together in the GHCR `:latest` release record. A manual run from
`main` reads that record and sends the published digests to
`/srv/predict/release.sh` over SSH. The first successful automatic main build
creates the record. To publish it on demand, run the workflow from `main` with
`publish_only` selected. This runs the same image build and Compose smoke checks.
In-repository PRs build and deploy their own tested digests.
The deploy job requires the repository variable
`HETZNER_DEPLOY_ENABLED=true` and the `hetzner` GitHub environment with branch
rules for `main` and `refs/pull/*/merge`. Set `HETZNER_HOST` and the pinned `HETZNER_KNOWN_HOSTS`
entry as environment variables and `HETZNER_SSH_KEY` as an environment secret.
The key belongs to the restricted `predict-deploy` account. GitHub's job token
authenticates the GHCR pull and is discarded after use.

Install `deploy/compose.yml` and `deploy/release.sh` in `/srv/predict` as root.
Keep this directory and the forced command root-owned. Apply changes to these
two host files over the administrator SSH connection before deploying a release
that needs them. Install both files before the first split-image deploy. The
forced command validates the role and build inputs of each Predict image digest.

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
collects and publishes with no web process or browser running, subject to the
configured source schedules and budget guards. An enabled collector passes its
health check when it can dispatch and has published or verified unchanged results
within the last three minutes. A deliberate global Stop can pass the heartbeat
check. The web check reads the same public odds endpoint used by the browser.
Check the collector logs for startup, dispatch or publication errors.
Admin Stop and source pauses stay in PostgreSQL and survive service or host
restarts. The release script checks the
applied migration digests, backs up PostgreSQL before forward migrations, and
restores the previous image after a failed health check when the schema is
unchanged. For a failed release that did migrate, inspect the retained backup
and the current data before choosing a recovery. Keep any subsequent provider
accounting intact. Back up PostgreSQL and the accounting files off the server.

## Observing a live slate

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
