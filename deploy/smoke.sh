#!/usr/bin/env bash
set -euo pipefail

# Stage only the Compose manifest and a disabled source policy. The disposable
# test has its own PostgreSQL volume and no credentials or production state.
scratch=$(mktemp -d)
project="predict-smoke-$$"
cp deploy/compose.yml "$scratch/compose.yml"
mkdir -p "$scratch"/{state,socket,provider-secrets,archive}
cp config/current.example.json "$scratch/state/predict-current-config.json"
openssl rand -hex 32 > "$scratch/postgres-bootstrap"
chmod 0777 "$scratch/state" "$scratch/socket"
chmod 0644 "$scratch/state/predict-current-config.json"
export PREDICT_ODDS_ARCHIVE_MOUNT="$scratch/archive" PREDICT_ODDS_ARCHIVE_ID=predict-smoke
printf '%s\n' "$PREDICT_ODDS_ARCHIVE_ID" > "$scratch/archive/.predict-archive-id"
chmod 0755 "$scratch/archive"
chmod 0644 "$scratch/archive/.predict-archive-id"

compose() {
    docker compose --env-file /dev/null -f "$scratch/compose.yml" -p "$project" --profile collection --profile archive "$@"
}

cleanup() {
    status=$?
    if (( status != 0 )); then compose logs --tail 50 >&2 || true; fi
    compose down --volumes >&2 || true
    docker image rm "$project:web-update" >/dev/null 2>&1 || true
    # UID 10001 owns the worker-created state directories on the Linux runner.
    sudo rm -rf -- "$scratch"
}
trap cleanup EXIT

compose up -d --wait db
compose run --rm --no-deps -T web python -m app.storage migrate
# The data service must start and report readiness before the first web process.
compose up -d --no-deps --wait --wait-timeout 180 collector
compose up -d --no-deps --wait --wait-timeout 180 archive
before=$(compose exec -T collector python -c '
from app.collection.runtime_status import RuntimeState

runtime = RuntimeState().read()
assert runtime["healthy"] and runtime["service_state"] == "running" and not runtime["active"]
print(runtime["runtime_id"])
')
compose up -d --no-deps --wait --wait-timeout 180 web
first=$(curl -fsS http://127.0.0.1:8784/api/admin/status | jq -er 'select(.dispatch_enabled == false and .data_runtime.healthy) | .runtime_id')
[[ "$before" == "$first" ]]
[[ $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8784/) == 302 ]]
curl -fsS http://127.0.0.1:8784/research > "$scratch/research.html"
grep -q '/view/current/research.js' "$scratch/research.html"
curl -fsS http://127.0.0.1:8784/api/research/catalog > "$scratch/research-catalog.json"
jq -e '.schema == "predict-research-catalog-1" and .provider_requests == 0 and .scheduled_calculations == 0' "$scratch/research-catalog.json" >/dev/null
catalog_token=$(jq -er '.token' "$scratch/research-catalog.json")
curl -fsS -X DELETE -H 'Origin: http://127.0.0.1:8784' -H 'Content-Type: application/json' "http://127.0.0.1:8784/api/research/read?token=$catalog_token" >/dev/null
data_containers=$(compose ps --status running --quiet db collector archive | sort)
[[ $(wc -l <<< "$data_containers") -eq 3 ]]
web_container=$(compose ps --status running --quiet web)
docker build -t "$project:web-update" - <<DOCKERFILE
FROM ${PREDICT_WEB_IMAGE:-${PREDICT_IMAGE:?Set the tested web image}}
LABEL dev.dock108.predict.smoke-update=true
DOCKERFILE
PREDICT_WEB_IMAGE="$project:web-update" compose up -d --no-deps --wait web
[[ $(compose ps --status running --quiet web) != "$web_container" ]]
[[ $(compose ps --status running --quiet db collector archive | sort) == "$data_containers" ]]
after=$(curl -fsS http://127.0.0.1:8784/api/admin/status | jq -er '.runtime_id')
[[ "$before" == "$after" ]]
[[ $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: unrelated.invalid' http://127.0.0.1:8784/) == 403 ]]
