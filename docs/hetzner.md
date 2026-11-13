# Predict on Hetzner

Predict runs as `web`, `collector`, and `db` in a dedicated Docker Compose project.
The dashboard listens on the server's loopback interface. From the Mac, use:

```sh
ssh -N -L 127.0.0.1:8784:127.0.0.1:8784 hetzner
```

Open `http://127.0.0.1:8784/`. Stop the local web process first if it uses that
port. The dashboard checks the local port as part of its browser boundary.

## Releases

The **Deploy Predict dev server** workflow runs when an in-repository PR to
`main` opens or changes, or when dispatched manually from `main`. It builds and
smoke-tests the locked Linux image, publishes it to GHCR, and sends its digest to
`/srv/predict/release.sh` over SSH. The separate CI workflow runs the broader
regressions. The deploy job requires the repository variable
`HETZNER_DEPLOY_ENABLED=true` and the `hetzner` GitHub environment with branch
rules for `main` and `refs/pull/*/merge`. Set `HETZNER_HOST` and the pinned `HETZNER_KNOWN_HOSTS`
entry as environment variables and `HETZNER_SSH_KEY` as an environment secret.
The key belongs to the restricted `predict-deploy` account. GitHub's job token
authenticates the GHCR pull and is discarded after use.

Install `deploy/compose.yml` and `deploy/release.sh` in `/srv/predict` as root.
Keep this directory and the forced command root-owned. Apply changes to these
two host files over the administrator SSH connection before deploying a release
that needs them. The forced command accepts only a Predict image digest and does
not offer an interactive shell or any port forwarding.

Create a private `postgres-bootstrap` file with a random password for a new
cluster. The database uses a shared Unix socket and a persistent `predict_postgres`
volume. Source credentials live in `/srv/predict/provider-secrets` as mode 0600
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
release script then manages both services. Admin Stop and source pauses stay in
PostgreSQL and survive service or host restarts. The release script checks the
applied migration digests, backs up PostgreSQL before forward migrations, and
restores the previous image after a failed health check when the schema is
unchanged. For a failed release that did migrate, inspect the retained backup
and the current data before choosing a recovery. Keep any subsequent provider
accounting intact. Back up PostgreSQL and the accounting files off the server.

## Observing a live slate

Run the coverage sampler in `web` and save its JSON lines outside the container.
For example, from `/srv/predict` with `PREDICT_IMAGE` set to `current-image`'s
contents:

```sh
docker compose --env-file /dev/null exec -T web \
  python scripts/live_coverage_census.py --phase live --samples 240 > live-coverage.jsonl
docker compose --env-file /dev/null exec -T web \
  python scripts/pipeline_storage_report.py > storage.json
```

Take storage and account snapshots before and after the window. Compare the
fresh source, matched, and published counts by sport and market against the
scheduled games. Record worker outages, stale quote gaps, accounting deltas,
database growth and resource pressure alongside coverage.
