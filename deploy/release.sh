#!/usr/bin/env bash
# Invoked by the restricted SSH key. Read one tested image reference on stdin.
set -euo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
cd /srv/predict
unset DOCKER_HOST DOCKER_CONTEXT COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES

IFS= read -r -t 10 image
[[ $image =~ ^ghcr\.io/dock108dev/predict@sha256:[a-f0-9]{64}$ ]]
IFS= read -r -t 10 registry_user
[[ $registry_user =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]
IFS= read -r -t 10 registry_token
exec 9>deploy.lock
flock -x 9

compose() {
    PREDICT_IMAGE="$image" docker compose --env-file /dev/null --profile collection "$@"
}

registry_config=$(mktemp -d)
trap 'rm -rf "$registry_config"' EXIT
printf '%s' "$registry_token" | docker --config "$registry_config" login ghcr.io -u "$registry_user" --password-stdin >/dev/null
unset registry_token
docker --config "$registry_config" pull "$image"
rm -rf "$registry_config"
compose up -d --wait db

# Refuse an image with a missing or altered applied migration before touching
# running services. Emit only the number of valid forward migrations needed.
pending=$(compose run --rm --no-deps -T web python -c '
from hashlib import sha256
from pathlib import Path
from app.storage.store import connect

files = {p.name: sha256(p.read_bytes()).hexdigest()
         for p in Path("app/storage/migrations").glob("*.sql")}
with connect() as db:
    exists = db.execute("SELECT to_regclass(%s) AS ledger", ("public.schema_migration",)).fetchone()["ledger"]
    rows = db.execute("SELECT version, sha256 FROM schema_migration").fetchall() if exists else []
if not files or any(files.get(row["version"]) != row["sha256"] for row in rows):
    raise SystemExit("Applied migrations do not match the release")
print(len(files) - len(rows))
')
[[ $pending =~ ^[0-9]+$ ]]

previous=''
if [[ -f current-image ]]; then
    read -r previous < current-image
fi
if (( pending > 0 )); then
    compose stop web collector
    backup=$(mktemp backups/before-migration.XXXXXXXX.dump)
    if ! compose exec -T db pg_dump -h /run/predict-postgres -U prediction_arb -p 55432 -Fc -d prediction_arb > "$backup"; then
        rm -f "$backup"
        # No migration ran. Restore the previously installed services.
        compose start web
        if [[ -f collection-enabled ]]; then compose start collector; fi
        exit 1
    fi
    if ! compose run --rm --no-deps -T web python -m app.storage migrate; then
        # The migration transaction rolls back as a unit.
        compose start web
        if [[ -f collection-enabled ]]; then compose start collector; fi
        exit 1
    fi
fi

services=(web)
if [[ -f collection-enabled ]]; then services+=(collector); fi
if ! compose up -d --no-deps --wait --wait-timeout 180 "${services[@]}"; then
    if (( pending == 0 )) && [[ -n $previous ]]; then
        echo 'Health check failed. Restoring the previous image with current data.' >&2
        image=$previous
        compose up -d --no-deps --wait --wait-timeout 180 "${services[@]}"
    else
        echo 'Health check failed. Inspect the services and the retained database backup.' >&2
    fi
    exit 1
fi

printf '%s\n' "$image" > current-image.tmp
mv current-image.tmp current-image
if [[ -n $previous && $previous != "$image" ]]; then
    printf '%s\n' "$previous" > previous-image
fi
