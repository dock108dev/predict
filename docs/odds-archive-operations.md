# Odds archive deployment and verification

Archive capture is opt-in. The collector continues publishing live prices and
calculations while the archive runs. The export worker uses the PostgreSQL Unix
socket and an off-host filesystem supplied by the administrator. It has no
provider credentials or network access.

Long-term history covers only pregame observations. Activate capture after
the off-host mount verifies. The collector keeps in-game prices for the
working desk and exact evidence for saved or pinned inspections.

## Set up the off-host destination

Provision a private NFSv4 export on a separate host or equivalent durable POSIX
storage. Give application UID and GID 10001 read and write access to the export
root. Restrict access to the participating hosts and protect the transport using
the private network or VPN. The destination must support hard links, file and
directory fsync, and read-after-write from the collector host. Use a server-side
durable export and backup policy. NFS authentication, routing and any mount
credentials belong to the host, outside Compose and the provider secret mount.

On the Hetzner server, create and persist the mount using the actual server and
export. Use the following values in the host's mount unit or fstab.

```sh
sudo install -d -m 0750 /srv/predict/odds-archive
sudo mount -t nfs4 -o hard,nosuid,nodev,noexec ARCHIVE_HOST:/predict /srv/predict/odds-archive
mountpoint -q /srv/predict/odds-archive
findmnt -n -o TARGET,SOURCE,FSTYPE --target /srv/predict/odds-archive
```

Set a unique marker on the **remote export root**. The deployment configuration
must use the same exact string.

```sh
archive_id=$(cat /proc/sys/kernel/random/uuid)
printf '%s\n' "$archive_id" |
    sudo -u '#10001' tee /srv/predict/odds-archive/.predict-archive-id >/dev/null
sudo -u '#10001' sh -c '
    set -eu
    probe=$(mktemp /srv/predict/odds-archive/.probe.XXXXXX)
    trap "rm -f \"$probe\" \"$probe.link\"" EXIT
    printf "predict archive probe\n" > "$probe"
    ln "$probe" "$probe.link"
    cmp "$probe" "$probe.link"
'
```

Install the updated `deploy/compose.yml` and `deploy/release.sh` under
`/srv/predict` using the existing administrator access. Create
`/srv/predict/archive.env` as a root-owned file readable by the restricted
deploy account. Begin with capture disabled while validating the mount. Use the
marker value from above.

```dotenv
PREDICT_ODDS_ARCHIVE_CAPTURE=0
PREDICT_ODDS_ARCHIVE_MOUNT=/srv/predict/odds-archive
PREDICT_ODDS_ARCHIVE_ID=REPLACE_WITH_REMOTE_MARKER
```

Deploy the owner-approved image containing migration 092 using the normal
release command. It backs up SQL before applying the additive migration.
The existing `collection-enabled` deployment marker and persisted operator
controls still govern acquisition. The archive is a separate Compose profile.
A configured archive starts after web and collector startup. Archive failure has
its own health check and logs.

From `/srv/predict`, use this wrapper for release-day checks.

```sh
export PREDICT_IMAGE=$(cat current-image)
predict() {
    docker compose --env-file ./archive.env --profile collection --profile archive "$@"
}
mountpoint -q /srv/predict/odds-archive
predict config --quiet
predict ps db web collector archive
predict exec -T archive python -m app.storage.odds_archive_export --check
predict exec -T archive python -m app.storage.odds_archive_export --status
```

Use the actual v1 exporter for the initial mounted-file check before authorizing
live staging. This provider-free probe uses a hidden test key and cleans it up
after the same file and directory fsync and read-back the worker uses.

```sh
predict exec -T archive python - <<'PY'
from pathlib import Path
import os
import tempfile
import gzip
from app.storage.odds_archive_export import DirectoryArchive, _sync_directory

archive = DirectoryArchive(os.environ['PREDICT_ODDS_ARCHIVE_ROOT'], os.environ['PREDICT_ODDS_ARCHIVE_ID'])
archive.verify_mount()
with tempfile.TemporaryDirectory(prefix='.probe-', dir=archive.path) as directory:
    root = Path(directory)
    source, target = root/'source', root/'published'
    raw = b'predict archive probe\n'
    with source.open('xb') as file:
        file.write(gzip.compress(raw, mtime=0))
        file.flush()
        os.fsync(file.fileno())
    os.link(source,target)
    _sync_directory(root)
    assert gzip.decompress(target.read_bytes()) == raw
    _sync_directory(archive.path)
PY
```

Set `PREDICT_ODDS_ARCHIVE_CAPTURE=1` in `archive.env` after the mount check
passes. Recreate the collector during the approved change window
with `predict up -d --no-deps --wait collector`. This uses normal source
reconnection and dispatch guards. The archive itself and its test commands
generate zero provider requests.

## Watch a busy slate

Before and during the approved idle-web test, take the following measurements
at 30-second intervals. Stop only web with `predict stop web`. Take enough
samples to cross an already scheduled poll and an archive flush. Restart web
with `predict up -d --no-deps --wait web`. Compare the first
`curl -fsS 'http://127.0.0.1:8784/api/comparison-current/updates'` result ID
and generation to the last complete sampled head, allowing for an intervening
collector publication. Verify Odds, Arb and EV separately and exercise filters
and Refresh against the same published cursor. Selected custom stake sizing
should use the leased pair only.

```sh
predict exec -T db psql -h /run/predict-postgres -p 55432 -U prediction_arb -d prediction_arb <<'SQL'
SELECT clock_timestamp(), runtime_id, heartbeat_at, global_stopped, paused_sources FROM data_runtime;
SELECT kind, id, generation, result_id, facts->>'published_at' AS published_at
FROM comparison_publication WHERE kind='live';
SELECT venue, max(received_at::timestamptz) AS native_receipt
FROM current_native_book GROUP BY venue ORDER BY venue;
SELECT max(to_timestamp(received_order)) AS sgo_quote_receipt FROM current_sgo_reference;
SELECT feed,staged,verified,verified_file_bytes,last_staged_at,last_verified_at,
       skipped,first_gap_at,last_gap_at,gap_reason FROM odds_archive_feed_status ORDER BY feed;
SELECT pg_database_size(current_database()) database_bytes;
SELECT sum(size) wal_directory_bytes FROM pg_ls_waldir();
SELECT wal_bytes wal_bytes_generated_since_reset FROM pg_stat_wal;
SQL
predict exec -T archive python -m app.storage.odds_archive_export --status
df -B1 /srv/predict /var/lib/docker /srv/predict/odds-archive
```

The owner may use the existing authorized fault controls and a scheduled or
fixture-only feed interruption to verify independent collection. Check the
isolated feed's source clocks, stale labels and dependent Arb/EV availability.
While an archive upload is pending, restarting only `archive` must reuse the
existing batch key. Testing a deliberate interrupt between read-back and SQL
acknowledgment is automated in the disposable PostgreSQL test lane. Preserve
explicit source pauses and provider account, reservation and hold records in
every drill.

The archive reports a separate unhealthy condition after 30 minutes of staged
lag or when the destination marker is inaccessible. Staging allows up to 64 MiB
of logical records. New staged bytes cannot exceed one third of measured SQL headroom beyond
a 192 MiB reserve. It retains unacknowledged batches, records dropped counts
and receipt bounds when full, and lets live source admission continue. Normal
export starts when a group's oldest receipt reaches 15 minutes or its size
reaches the shard budget. Each file is scoped to the UTC receipt day and feed.
Late receipts for an exported day produce another immutable shard that replay
includes. Archive disk usage is the sum of verified shard lengths. WAL bytes
generated and present on disk are separate measurements.

For an incident, capture the feed's `first_gap_at`, `last_gap_at`, reason and
skipped count before any lifecycle change. `first_gap_at` and `last_gap_at`
bound all recorded missing source receipts for that feed. Recover only rows
whose original admitted evidence still exists in working SQL, a retained dump
or saved inspections. Reconcile exact identity, receipt clock and revision
before admitting a backfill. Maintain incomplete intervals as coverage gaps.
A killed exporter can leave dot-prefixed temp files. If needed, remove only
old dot-prefixed shard temporaries after stopping the exporter. Keep the marker
and every final shard.

To report a day's actual gzip bytes and record counts, run the following using
a UTC day that has passed the 15-minute export threshold. Include preceding
days when determining whether a top row is the first observation for its side.
Daily volume should cover continuously observed busy and quiet periods.

```sh
predict exec -T archive python -m app.storage.odds_archive_replay /archive --daily 2026-11-14
```

To verify a shard's content and reproduce an observed original Odds input, use
the exact event, quote identity and cutoff. This reads archived files only.

```sh
predict exec -T archive python -m app.storage.odds_archive_replay /archive \
    --feed kalshi --event EVENT_TICKER --identity '["MARKET_TICKER","OUTCOME_ID","asks"]' \
    --from-day 2026-11-14 --through-day 2026-11-14 --as-of 2026-11-14T22:00:00Z
```

For SGO, use a quoted JSON string containing the exact reference identity for
the bookmaker, event, odd ID and line. Replay verifies all selected shard and
row hashes. It returns the last observed price, size, availability, source and
receipt clocks, and the available definition and source binding. Use the live
application's existing exact evidence packets for historical custom-size
Arb, EV with specific fee evidence, or inspections requiring deeper ladders.
The v1 archive records admitted pregame material top changes, authentic
pregame native snapshot confirmations and the pregame members of successful
SGO pages. The receipt must precede the scheduled start, and source evidence
that play has begun excludes the observation. Separate source and runtime
health boundaries carry no event prices. An unchanged top can carry
one clock witness per 15-second native or five-minute SGO source bucket.
Intermediate currentness cannot be proved from these witnesses alone.
An omitted event or market gives no evidence that an offer closed.

## Rollback preserving collected evidence

The fastest rollback is functional. Set `PREDICT_ODDS_ARCHIVE_CAPTURE=0`
in `archive.env` and recreate only the collector with the wrapper above.
Existing stages can continue draining. If the mount is the fault, stop just
`archive` while investigating. Staging and published data remain in place.

For image rollback across 092, capture the currently running image digest
and current database/accounting backups before rerunning the app. The release
command enforces a forward migration ledger, so use the following exact manual
procedure with the confirmed previous 091 image. Migration 092 adds independent
archive tables. The 091 application still reads its existing schema on the
upgraded database. Stop archive while rolling back the app image. Keep the
shards, additive tables and modern image available to drain existing stages.
Do not overwrite the active database or accounting files with pre-upgrade
backups.

```sh
cd /srv/predict
rollback_image=$(cat previous-image)
PREDICT_IMAGE="$rollback_image" docker compose --env-file ./archive.env --profile archive stop archive
PREDICT_IMAGE="$rollback_image" docker compose --env-file /dev/null --profile collection \
    up -d --no-deps --wait web
if test -f collection-enabled; then
    PREDICT_IMAGE="$rollback_image" docker compose --env-file /dev/null --profile collection \
        up -d --no-deps --wait collector
fi
printf '%s\n' "$rollback_image" > current-image.tmp
mv current-image.tmp current-image
```

Verify the current root, leased/saved inspection evidence, current-row epoch,
operator controls, and account/hold state against the captured pre-rollback
values. Verify the retained staged backlog separately. Rehearse with the
previous tested image against a disposable restored database before the
hosted rollout.
