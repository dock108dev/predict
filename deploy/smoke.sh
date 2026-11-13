#!/usr/bin/env bash
set -euo pipefail

# Stage only the Compose manifest and a disabled source policy. The disposable
# test has its own PostgreSQL volume and no credentials or production state.
scratch=$(mktemp -d)
project="predict-smoke-$$"
cp deploy/compose.yml "$scratch/compose.yml"
mkdir -p "$scratch"/{state,socket,provider-secrets}
cp config/current.example.json "$scratch/state/predict-current-config.json"
openssl rand -hex 32 > "$scratch/postgres-bootstrap"
chmod 0777 "$scratch/state" "$scratch/socket"
chmod 0644 "$scratch/state/predict-current-config.json"

compose() {
    docker compose --env-file /dev/null -f "$scratch/compose.yml" -p "$project" --profile collection "$@"
}

cleanup() {
    status=$?
    if (( status != 0 )); then compose logs --tail 50 >&2 || true; fi
    compose down --volumes >&2 || true
    # UID 10001 owns the worker-created state directories on the Linux runner.
    sudo rm -rf -- "$scratch"
}
trap cleanup EXIT

compose up -d --wait db
compose run --rm --no-deps -T web python -m app.storage migrate
compose up -d --no-deps --wait --wait-timeout 180 web collector
before=$(curl -fsS http://127.0.0.1:8784/api/admin/status | jq -er 'select(.dispatch_enabled == false and .data_runtime.healthy) | .runtime_id')
compose up -d --force-recreate --no-deps --wait web
after=$(curl -fsS http://127.0.0.1:8784/api/admin/status | jq -er '.runtime_id')
[[ "$before" == "$after" ]]
[[ $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: unrelated.invalid' http://127.0.0.1:8784/) == 403 ]]
