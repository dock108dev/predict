#!/usr/bin/env bash
# Invoked by the restricted SSH key. Accept only tested Predict image digests.
set -euo pipefail
umask 077

roles=(web collector archive)
keys=(PREDICT_WEB_IMAGE PREDICT_COLLECTOR_IMAGE PREDICT_ARCHIVE_IMAGE)
digest_pattern='^ghcr\.io/dock108dev/predict@sha256:[a-f0-9]{64}$'
inputs_pattern='^[a-f0-9]{64}$'
CADDY_DIRECTORY=/etc/caddy

compose() {
    PREDICT_WEB_IMAGE="${images[0]}" PREDICT_COLLECTOR_IMAGE="${images[1]}" PREDICT_ARCHIVE_IMAGE="${images[2]}" \
        docker compose --env-file "$compose_env" --env-file "$roles_env" --project-directory "$release_root" \
        -f "$compose_file" --profile collection --profile archive "$@"
}

prepare_managed() {
    local container name failed=0
    container=$(docker create --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges --entrypoint /bin/true "${images[0]}") || return 1
    for name in compose.yml predict.Caddyfile release.sh managed-config.py image-cleanup.py; do
        docker cp "$container:/predict/deploy/managed/$name" "$staging/$name" || failed=1
    done
    docker rm "$container" >/dev/null || return 1
    (( failed == 0 )) || return 1
    python3 -I "$staging/managed-config.py" bundle "$staging" || return 1
    bash -n "$staging/release.sh" || return 1
    compose config --format json > "$staging/previous-compose.json" || return 1
    compose_file="$staging/compose.yml" compose config --format json > "$staging/candidate-compose.json" || return 1
    python3 -I "$staging/managed-config.py" validate-compose "$staging/candidate-compose.json" \
        "$staging/previous-compose.json" "$release_root" || return 1
    python3 -I "$staging/managed-config.py" stage-caddy "$CADDY_DIRECTORY/Caddyfile" \
        "$staging/predict.Caddyfile" "$staging/Caddyfile" || return 1
    caddy validate --config "$staging/Caddyfile" --adapter caddyfile || return 1
}

install_managed() {
    python3 -I "$staging/managed-config.py" install "$staging" "$release_root" "$CADDY_DIRECTORY"
}

cleanup_images() {
    python3 -I "$staging/image-cleanup.py" --root "$release_root" --apply
}

verify_health() {
    local service container health
    for service in "$@"; do
        unhealthy_service=$service
        container=$(compose ps --all --quiet "$service") || return 1
        if [[ -z $container || $container == *$'\n'* ]]; then
            unhealthy_service=$service
            return 1
        fi
        health=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container") || return 1
        if [[ $health != 'running healthy' ]]; then
            unhealthy_service=$service
            return 1
        fi
    done
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
    rows = db.execute("SELECT version, sha256 FROM public.schema_migration ORDER BY version").fetchall() if exists else []
if not files or list(sorted(files))[:len(rows)] != [row["version"] for row in rows] or any(
    files[row["version"]] != row["sha256"] for row in rows
):
    raise SystemExit("Applied migrations do not match the release")
print(len(files) - len(rows))
'
}

migrate_database() {
    if (( split_roles )); then
        local secret="$release_root/postgres-migrator"
        if [[ ! -f $secret || -L $secret ]] || [[ $(stat -c '%a:%u' "$secret") != '400:10001' ]]; then
            echo 'A private migration credential must be prepared before schema maintenance.' >&2
            return 1
        fi
        compose run --rm --no-deps -T \
            -e PREDICT_DB_ROLE=predict_migrator -e PREDICT_DB_PASSWORD= \
            -e PREDICT_DB_PASSWORD_FILE=/run/predict-migrator \
            --volume "$secret:/run/predict-migrator:ro" web python -m app.storage migrate
    else
        compose run --rm --no-deps -T web python -m app.storage migrate
    fi
}

verify_socket_roles() {
    local role
    for role in "${roles[@]}"; do
        [[ $role != archive || -f archive.env ]] || continue
        compose run --rm --no-deps -T "$role" python -m app.storage verify-role || return 1
    done
}

needs_rollout() {
    local index=$1
    if (( host_changed || pending > 0 || (roles_changed || (index != 0 && archive_changed)) )) \
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
    compose_file="$release_root/compose.yml"
    local previous_pending
    previous_pending=$(migration_count) || return 1
    [[ $previous_pending == 0 ]] || return 1
    compose up -d --no-deps --wait --wait-timeout 180 "$@"
)

failed_release() {
    local reason=$1 role requested
    shift
    local restore=()
    # A role can be affected by both its image and host configuration. Restart it
    # once while keeping unrelated services out of a selective rollback.
    for role in db web collector archive; do
        for requested in "$@"; do
            if [[ $role == "$requested" ]]; then restore+=("$role"); break; fi
        done
    done
    echo "$reason" >&2
    if (( pending == 0 && ${#restore[@]} > 0 )) && rollback "${restore[@]}"; then
        echo 'Restored the previous images and host Compose for the affected services.' >&2
    else
        echo 'Inspect the affected services and any retained migration backup before recovery.' >&2
    fi
    return 1
}

release() {
    local header registry_user registry_token index extra label pending backup
    local host_changed=0 archive_was_running='' collector_was_running='' registry_config staging
    local archive_settings archive_changed=0 archive_rollout=0 unhealthy_service='unknown' fast_release=0
    local split_roles=0 profile roles_settings roles_changed=0
    local services=() previous=('' '' '') images=() inputs=('' '' '') db_flags=(--wait)
    local health_services=(db web)
    local release_root=$PWD compose_file="$PWD/compose.yml"
    local compose_env=/dev/null roles_env=/dev/null
    [[ ! -f archive.env ]] || compose_env=archive.env
    [[ ! -f postgres-roles.env ]] || roles_env=postgres-roles.env

    IFS= read -r -t 10 header
    IFS= read -r -t 10 registry_user
    [[ $registry_user =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]
    IFS= read -r -t 10 registry_token
    if [[ $header == predict-images-fast-v1 ]]; then
        fast_release=1
    else
        [[ $header == predict-images-v1 ]]
    fi
    for index in 0 1 2; do
        read -r -t 10 "images[$index]" "inputs[$index]" extra
        [[ ${images[$index]} =~ $digest_pattern && ${inputs[$index]} =~ $inputs_pattern && -z $extra ]]
    done

    read_installed
    archive_settings=$(sha256sum < "$compose_env")
    if [[ -f applied-archive-env && $archive_settings != $(<applied-archive-env) ]]; then
        archive_changed=1
    fi
    roles_settings=$(sha256sum < "$roles_env")
    if [[ -f applied-postgres-roles-env ]]; then
        [[ $roles_settings == $(<applied-postgres-roles-env) ]] || roles_changed=1
    elif [[ -f postgres-roles.env ]]; then
        roles_changed=1
    fi
    registry_config=$(mktemp -d)
    staging=$(mktemp -d "$release_root/.release.XXXXXXXX")
    trap "rm -rf -- $(printf '%q' "$registry_config") $(printf '%q' "$staging")" EXIT
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

    if ! prepare_managed; then
        echo 'Managed host configuration validation failed; no services or installed configuration changed.' >&2
        return 1
    fi
    profile=$(python3 -I "$staging/managed-config.py" database-profile "$staging/candidate-compose.json" "$release_root") || return 1
    [[ $profile != split ]] || split_roles=1
    if (( fast_release )); then
        if ! pending=$(migration_count) || [[ ! $pending =~ ^[0-9]+$ ]]; then
            echo 'Fast release could not verify the existing schema; current services unchanged.' >&2
            return 1
        fi
        if (( pending > 0 )); then
            echo 'Schema maintenance required; current services unchanged. Use the full maintenance release for backup and migration.' >&2
            return 1
        fi
    fi
    compose_file="$staging/compose.yml"
    if [[ -n ${previous[0]} ]] && ! cmp -s "$compose_file" applied-compose.yml; then
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

    if (( split_roles && (host_changed || archive_changed || roles_changed || ${#previous[0]} == 0) )); then
        if ! verify_socket_roles; then
            echo 'Database role authentication check failed. Inspect the split socket and role files before rollout.' >&2
            resume_previous
            return 1
        fi
    fi

    if (( pending > 0 )); then
        archive_was_running=${archive_was_running:-$(compose ps --status running --quiet archive)}
        compose stop web collector
        [[ -z $archive_was_running ]] || compose stop archive
        backup=$(mktemp backups/before-migration.XXXXXXXX.dump)
        if ! compose exec -T db pg_dump -h /run/predict-postgres -U prediction_arb -p 55432 -Fc -Z1 -d prediction_arb > "$backup"; then
            rm -f -- "$backup"
            resume_previous
            return 1
        fi
        if ! migrate_database; then
            resume_previous
            return 1
        fi
    fi

    if needs_rollout 0; then services+=(web); fi
    if [[ -f collection-enabled ]] && needs_rollout 1; then services+=(collector); fi
    if [[ ${#services[@]} -gt 0 ]] && ! compose up -d --no-deps --wait --wait-timeout 180 "${services[@]}"; then
        [[ -z $archive_was_running ]] || services+=(archive)
        failed_release 'A candidate service failed its health check.' "${services[@]-}"
        return 1
    fi

    if [[ -f archive.env ]] && needs_rollout 2; then
        archive_rollout=1
        if ! compose up -d --no-deps --wait --wait-timeout 180 archive; then
            failed_release 'The candidate archive failed its health check.' "${services[@]-}" archive
            return 1
        fi
    fi
    [[ ! -f collection-enabled ]] || health_services+=(collector)
    [[ ! -f archive.env ]] || health_services+=(archive)
    if ! verify_health "${health_services[@]}"; then
        (( archive_rollout == 0 )) || services+=(archive)
        failed_release "Configured service is not healthy: $unhealthy_service" "${services[@]-}" "$unhealthy_service"
        return 1
    fi
    if ! install_managed; then
        (( archive_rollout == 0 )) || services+=(archive)
        (( host_changed == 0 )) || services+=(db)
        failed_release 'Managed host configuration installation/reload failed; inspect configuration recovery.' "${services[@]-}"
        return 1
    fi

    if [[ -n ${previous[0]} && ${images[*]} != "${previous[*]}" ]]; then
        write_images previous-images.env "${previous[@]}"
    fi
    write_images current-images.env "${images[@]}"
    cp compose.yml applied-compose.yml
    printf '%s\n' "$archive_settings" > applied-archive-env.tmp
    mv applied-archive-env.tmp applied-archive-env
    printf '%s\n' "$roles_settings" > applied-postgres-roles-env.tmp
    mv applied-postgres-roles-env.tmp applied-postgres-roles-env
    echo 'Verified images, managed host configuration and all configured service health.'
    if ! cleanup_images; then
        echo 'Maintenance warning: obsolete-image cleanup failed; the verified release remains installed.' >&2
    fi
}

resume_previous() {
    # A failed backup or migration leaves the previous schema in place.
    compose_file="$release_root/compose.yml"
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
