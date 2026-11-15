#!/usr/bin/env bash
# Invoked by the restricted SSH key. Accept only tested Predict image digests.
set -euo pipefail
umask 077

roles=(web collector archive)
keys=(PREDICT_WEB_IMAGE PREDICT_COLLECTOR_IMAGE PREDICT_ARCHIVE_IMAGE)
digest_pattern='^ghcr\.io/dock108dev/predict@sha256:[a-f0-9]{64}$'
inputs_pattern='^[a-f0-9]{64}$'

compose() {
    PREDICT_WEB_IMAGE="${images[0]}" PREDICT_COLLECTOR_IMAGE="${images[1]}" PREDICT_ARCHIVE_IMAGE="${images[2]}" \
        docker compose --env-file "$compose_env" --profile collection --profile archive "$@"
}

image_label() {
    docker image inspect --format '{{index .Config.Labels "dev.dock108.predict.role"}} {{index .Config.Labels "dev.dock108.predict.inputs"}}' "$1"
}

read_installed() {
    local index line image
    if [[ -f current-images.env ]]; then
        for index in 0 1 2; do
            IFS= read -r line || return 1
            [[ $line == "${keys[$index]}="* ]] || return 1
            image=${line#*=}
            [[ $image =~ $digest_pattern ]] || return 1
            previous[$index]=$image
        done < current-images.env
    elif [[ -f current-image ]]; then
        IFS= read -r image < current-image
        [[ $image =~ $digest_pattern ]] || return 1
        previous=("$image" "$image" "$image")
    fi
}

write_images() {
    local file=$1 index
    shift
    for index in 0 1 2; do
        printf '%s=%s\n' "${keys[$index]}" "$1"
        shift
    done > "$file.tmp"
    mv "$file.tmp" "$file"
}

migration_count() {
    compose run --rm --no-deps -T web python -c '
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
'
}

needs_rollout() {
    local index=$1
    if (( host_changed || pending > 0 || (index != 0 && archive_changed) )) \
        || [[ ${images[$index]} != "${previous[$index]}" ]]; then
        return 0
    fi
    local running
    running=$(compose ps --status running --quiet "${roles[$index]}") || return 0
    [[ -z $running ]]
}

rollback() (
    [[ -n ${previous[0]} ]] || return 1
    images=("${previous[@]}")
    local previous_pending
    previous_pending=$(migration_count) || return 1
    [[ $previous_pending == 0 ]] || return 1
    compose up -d --no-deps --wait --wait-timeout 180 "$@"
)

release() {
    local header registry_user registry_token index extra label pending backup
    local host_changed=0 archive_was_running='' collector_was_running='' registry_config
    local archive_settings archive_changed=0 archive_failed=0
    local services=() previous=('' '' '') images=() inputs=('' '' '') db_flags=(--wait)
    local compose_env=/dev/null
    [[ ! -f archive.env ]] || compose_env=archive.env

    IFS= read -r -t 10 header
    IFS= read -r -t 10 registry_user
    [[ $registry_user =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]
    IFS= read -r -t 10 registry_token
    if [[ $header == predict-images-v1 ]]; then
        for index in 0 1 2; do
            read -r -t 10 "images[$index]" "inputs[$index]" extra
            [[ ${images[$index]} =~ $digest_pattern && ${inputs[$index]} =~ $inputs_pattern && -z $extra ]]
        done
    else
        # Allow existing jobs to finish during the host-script upgrade.
        [[ $header =~ $digest_pattern ]]
        images=("$header" "$header" "$header")
    fi

    read_installed
    archive_settings=$(sha256sum < "$compose_env")
    if [[ -f applied-archive-env && $archive_settings != $(<applied-archive-env) ]]; then
        archive_changed=1
    fi
    registry_config=$(mktemp -d)
    trap "rm -rf -- $(printf '%q' "$registry_config")" EXIT
    printf '%s' "$registry_token" | docker --config "$registry_config" login ghcr.io -u "$registry_user" --password-stdin >/dev/null
    unset registry_token
    for index in 0 1 2; do
        label="${roles[$index]} ${inputs[$index]}"
        if [[ -n ${inputs[$index]} && -n ${previous[$index]} && $(image_label "${previous[$index]}" 2>/dev/null) == "$label" ]]; then
            images[$index]=${previous[$index]}
        else
            docker --config "$registry_config" pull "${images[$index]}"
            if [[ -n ${inputs[$index]} && $(image_label "${images[$index]}") != "$label" ]]; then
                echo "Image role or inputs do not match ${roles[$index]}." >&2
                return 1
            fi
        fi
    done
    rm -rf -- "$registry_config"
    trap - EXIT

    if [[ -n ${previous[0]} ]] && ! cmp -s compose.yml applied-compose.yml; then
        # Host Compose changes can replace PostgreSQL. Quiesce its writers first.
        host_changed=1
        collector_was_running=$(compose ps --status running --quiet collector)
        archive_was_running=$(compose ps --status running --quiet archive)
        [[ -z $collector_was_running ]] || compose stop collector
        [[ -z $archive_was_running ]] || compose stop archive
    elif [[ -n ${previous[0]} ]]; then
        db_flags+=(--no-recreate)
    fi
    if ! compose up -d "${db_flags[@]}" db || ! pending=$(migration_count) || [[ ! $pending =~ ^[0-9]+$ ]]; then
        [[ -z $collector_was_running ]] || compose start collector
        [[ -z $archive_was_running ]] || compose start archive
        return 1
    fi

    if (( pending > 0 )); then
        archive_was_running=${archive_was_running:-$(compose ps --status running --quiet archive)}
        compose stop web collector
        [[ -z $archive_was_running ]] || compose stop archive
        backup=$(mktemp backups/before-migration.XXXXXXXX.dump)
        if ! compose exec -T db pg_dump -h /run/predict-postgres -U prediction_arb -p 55432 -Fc -d prediction_arb > "$backup"; then
            rm -f -- "$backup"
            resume_previous
            return 1
        fi
        if ! compose run --rm --no-deps -T web python -m app.storage migrate; then
            resume_previous
            return 1
        fi
    fi

    if needs_rollout 0; then services+=(web); fi
    if [[ -f collection-enabled ]] && needs_rollout 1; then services+=(collector); fi
    if [[ ${#services[@]} -gt 0 ]] && ! compose up -d --no-deps --wait --wait-timeout 180 "${services[@]}"; then
        if (( pending == 0 )) && rollback "${services[@]}"; then
            echo 'Health check failed. Restored the previous images for the affected services.' >&2
            [[ -z $archive_was_running ]] || compose start archive
        else
            echo 'Release failed. Inspect the services and any retained migration backup.' >&2
        fi
        return 1
    fi

    if [[ -f archive.env ]] && needs_rollout 2 && ! compose up -d --no-deps archive; then
        archive_failed=1
        echo 'Odds archive did not start. Check the off-host mount and staging status.' >&2
        if (( pending == 0 )) && [[ -n ${previous[2]} ]] && rollback archive; then
            images[2]=${previous[2]}
        fi
    fi

    if [[ -n ${previous[0]} && ${images[*]} != "${previous[*]}" ]]; then
        write_images previous-images.env "${previous[@]}"
    fi
    write_images current-images.env "${images[@]}"
    cp compose.yml applied-compose.yml
    if (( ! archive_failed )); then
        printf '%s\n' "$archive_settings" > applied-archive-env.tmp
        mv applied-archive-env.tmp applied-archive-env
    fi
}

resume_previous() {
    # A failed backup or migration leaves the previous schema in place.
    compose start web
    if [[ -f collection-enabled ]]; then compose start collector; fi
    [[ -z $archive_was_running ]] || compose start archive
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    export PATH=/usr/sbin:/usr/bin:/sbin:/bin
    cd /srv/predict
    unset DOCKER_HOST DOCKER_CONTEXT COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES
    exec 9>deploy.lock
    flock -x 9
    release
fi
