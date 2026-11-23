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
	@wrongHost not header Host 127.0.0.1:8784
	respond @wrongHost 500
	@wrongOrigin {
		header Origin *
		not header Origin http://127.0.0.1:8784
	}
	respond @wrongOrigin 500
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
    if [[ $(curl --max-time 1 -s -o /dev/null -w '%{http_code}' -u "fixture:$password" "$base/" || true) == 200 ]]; then break; fi
    if ! kill -0 "$proxy_pid" 2>/dev/null; then cat "$work/caddy.log" >&2; exit 1; fi
    sleep 0.2
done

check() {
    local expected=$1 method=$2 path=$3 actual
    shift 3
    local method_args=(-X "$method")
    if [[ $method == HEAD ]]; then method_args=(--head); fi
    actual=$(curl --max-time 3 -sS -o /dev/null -D "$work/headers" -w '%{http_code}' \
        "${method_args[@]}" "$@" "$base$path")
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

for path in / /opportunities /ev /arbs /browse-odds /game /replay /about /trading-fees \
            /research /admin /my-bets /raw-odds /odds /coverage /current/coverage /scanner \
            /api/trading-fees /api/pregame /api/pregame/updates /api/health \
            /api/comparison-current /api/comparison-current/updates /api/comparison-current/selection \
            /api/comparison-snapshot/details /api/odds-replay /api/odds-replay/details \
            /api/research/catalog /api/research/input /api/research/export /api/research/coverage \
            /api/research/cohorts /api/research/experiment /api/bet-journal /api/admin/status \
            /view/current/desk.js /view/current/research.js /view/current/admin.html \
            /view/current/raw-odds.html /view/current/predict-icon.png /view/current/sora-400.ttf \
            /style.css /shared-state.js /favicon.ico /apple-touch-icon.png \
            /apple-touch-icon-precomposed.png /manifest.webmanifest /future/private/feature; do
    check 401 GET "$path"
    check 401 HEAD "$path"
done

for path in /api/comparison-current/lease /api/admin/current /api/comparison-current/settings \
            /api/bet-journal /api/research/read /future/private/feature; do
    check 401 POST "$path" -H 'Origin: https://predict.dock108.dev'
    check 401 DELETE "$path" -H 'Origin: https://predict.dock108.dev'
done
check 401 OPTIONS /api/research/catalog
for path in / /research /api/research/catalog /api/admin/current /view/current/research.js /favicon.ico; do
    check 401 GET "$path" -u fixture:wrong-password
done
check 401 GET / -u "unknown:$password"

check 403 GET / -H 'Origin: https://unrelated.invalid'
check 403 GET /research -u "fixture:$password" -H 'Origin: https://unrelated.invalid'
check 403 POST /api/admin/current -u "fixture:$password" -H 'Origin: https://unrelated.invalid'

# The fixture backend returns 500 if credentials leak upstream, the loopback Host
# binding changes, or the public Origin is not rewritten for the app boundary.
for path in / /research /opportunities /api/pregame /api/health /api/research/catalog \
            /api/research/experiment /api/research/export /my-bets /api/bet-journal \
            /admin /api/admin/status /view/current/research.js /view/current/predict-icon.png \
            /manifest.webmanifest /future/private/feature; do
    check 200 GET "$path" -u "fixture:$password"
done
check 200 HEAD /api/research/catalog -u "fixture:$password"
check 200 GET /research -u "fixture:$password" -H 'Origin: https://predict.dock108.dev'
check 200 POST /api/comparison-current/lease -u "fixture:$password" -H 'Origin: https://predict.dock108.dev'
check 200 DELETE /api/comparison-current/lease -u "fixture:$password" -H 'Origin: https://predict.dock108.dev'
for path in /favicon.ico /apple-touch-icon.png /apple-touch-icon-precomposed.png; do
    check 302 GET "$path" -u "fixture:$password"
    grep -qi '^location: /view/current/predict-icon.png' "$work/headers"
done
echo 'Private whole-site authentication, same-origin forwarding and credential stripping passed.'
