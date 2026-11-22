#!/usr/bin/env bash
set -euo pipefail

caddy=${CADDY_BIN:-caddy}
command -v "$caddy" >/dev/null || { echo 'Caddy is required for the proxy smoke test.' >&2; exit 1; }
work=$(mktemp -d)
proxy_pid=
cleanup() {
    if [[ -n "$proxy_pid" ]]; then
        kill "$proxy_pid" 2>/dev/null || true
        wait "$proxy_pid" 2>/dev/null || true
    fi
    rm -rf -- "$work"
}
trap cleanup EXIT

password=proxy-smoke-fixture
hash=$("$caddy" hash-password --plaintext "$password")
printf 'fixture %s\n' "$hash" > "$work/auth"
{
    cat <<'CADDY'
{
	admin off
}

http://127.0.0.1:18785 {
	@credentials header Authorization *
	respond @credentials 500
	respond 200
}
CADDY
    sed -e 's|^predict\.dock108\.dev {|http://127.0.0.1:18784 {|' \
        -e 's|reverse_proxy 127.0.0.1:8784|reverse_proxy 127.0.0.1:18785|' \
        -e "s|/etc/caddy/predict-auth|$work/auth|" deploy/predict.Caddyfile
} > "$work/Caddyfile"

"$caddy" validate --config "$work/Caddyfile"
"$caddy" run --config "$work/Caddyfile" > "$work/caddy.log" 2>&1 &
proxy_pid=$!
base=http://127.0.0.1:18784
for _ in {1..30}; do
    if curl --max-time 1 -fsS -o /dev/null "$base/"; then break; fi
    if ! kill -0 "$proxy_pid" 2>/dev/null; then cat "$work/caddy.log" >&2; exit 1; fi
    sleep 0.2
done

check() {
    local expected=$1 method=$2 path=$3 actual
    shift 3
    actual=$(curl --max-time 3 -sS -o /dev/null -D "$work/headers" -w '%{http_code}' \
        -X "$method" "$@" "$base$path")
    if [[ "$actual" != "$expected" ]]; then
        printf '%s %s returned %s, expected %s\n' "$method" "$path" "$actual" "$expected" >&2
        exit 1
    fi
    if [[ "$expected" == 401 ]]; then
        grep -qi '^www-authenticate: Basic' "$work/headers"
    elif grep -qi '^www-authenticate:' "$work/headers"; then
        printf '%s %s unexpectedly requested authentication\n' "$method" "$path" >&2
        exit 1
    fi
}

for path in / /opportunities /ev /arbs /browse-odds /game /replay /trading-fees /api/trading-fees /api/pregame /api/pregame/updates /api/health /view/current/desk.js \
            /view/current/predict-icon.png /api/comparison-current /api/comparison-current/updates \
            /api/comparison-current/selection /api/comparison-snapshot/details \
            /api/odds-replay /api/odds-replay/details; do
    check 200 GET "$path"
done
check 200 POST /api/comparison-current/lease -H 'Origin: https://predict.dock108.dev'
check 200 DELETE /api/comparison-current/lease
check 302 GET /favicon.ico
check 302 GET /apple-touch-icon.png
check 404 GET /apple-touch-icon-180x180.png
check 404 GET /manifest.webmanifest
check 403 GET / -H 'Origin: https://unrelated.invalid'
check 401 GET /admin
check 401 GET /research
check 401 GET /api/research/catalog
check 401 GET /api/research/input
check 401 GET /api/research/export
check 401 GET /api/research/coverage
check 401 GET /api/research/cohorts
check 401 GET /my-bets
check 401 GET /api/bet-journal
check 401 POST /api/bet-journal
check 401 GET /view/current/admin.html
check 401 GET /view/current/raw-odds.html
check 401 GET /api/admin/status
check 401 POST /api/admin/current
check 401 POST /api/comparison-current/settings
check 200 GET /admin -u "fixture:$password"
check 200 GET /research -u "fixture:$password"
check 200 GET /api/research/catalog -u "fixture:$password"
check 200 GET /my-bets -u "fixture:$password"
check 200 GET /api/bet-journal -u "fixture:$password"
check 200 GET /api/admin/status -u "fixture:$password"
echo 'Public routes and Admin authentication passed.'
