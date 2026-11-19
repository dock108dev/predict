#!/usr/bin/env bash
# Install the default no-TTL persistent archive when no destination is configured.
# Existing owner archive settings and mounted destinations always take precedence.
set -euo pipefail
cd /srv/predict
if [[ -e archive.env ]]; then
    echo 'Preserved existing archive destination.'
    exit 0
fi
archive_root=/srv/predict/odds-archive
install -d -m 0750 -o 10001 -g 10001 "$archive_root"
marker="$archive_root/.predict-archive-id"
if [[ ! -e $marker ]]; then
    archive_identity=$(cat /proc/sys/kernel/random/uuid)
    printf '%s\n' "$archive_identity" > "$marker"
    chown 10001:10001 "$marker"
    chmod 0640 "$marker"
fi
archive_identity=$(<"$marker")
[[ $archive_identity =~ ^[a-zA-Z0-9-]{1,128}$ ]]
umask 077
config=$(mktemp ./archive.env.XXXXXX)
printf '%s\n' 'PREDICT_ODDS_ARCHIVE_CAPTURE=1' \
    "PREDICT_ODDS_ARCHIVE_MOUNT=$archive_root" \
    "PREDICT_ODDS_ARCHIVE_ID=$archive_identity" > "$config"
# Atomic no-replace install; preserve a configuration created concurrently.
ln "$config" archive.env || [[ -e archive.env ]]
rm -f "$config"
echo 'Configured persistent host archive with no TTL; off-host backup is not configured.'
