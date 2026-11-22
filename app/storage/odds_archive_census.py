"""Explicit hash-verified archive content census, separate from exporter health."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from .odds_archive import FEEDS
from .odds_archive_replay import read_shard
from .store import exact_time


def census(root, *, first_day=None, last_day=None, progress=None):
    started_at = datetime.now(timezone.utc).isoformat()
    root = Path(root)
    if first_day and last_day and first_day > last_day:
        raise ValueError('odds_archive_census_scope')
    result = {}
    # Repeated page receipts dominate retained snapshots. Bound the parse cache
    # independently of record count; no all-record identity set is materialized.
    instant = lru_cache(maxsize=4096)(exact_time)
    for feed in sorted(FEEDS):
        counts = Counter()
        events = set()
        days = []
        total_bytes = files = 0
        receipt_bounds = [None, None]
        source_bounds = [None, None]
        def include(bounds, value):
            if value is None:return
            if bounds[0] is None or instant(value) < instant(bounds[0]):bounds[0] = value
            if bounds[1] is None or instant(value) > instant(bounds[1]):bounds[1] = value
        feed_root = root/'v1'/feed
        for folder in sorted(feed_root.iterdir()) if feed_root.is_dir() else ():
            if not folder.is_dir() or len(folder.name) != 10:continue
            day = date.fromisoformat(folder.name)
            if first_day and day < first_day or last_day and day > last_day:continue
            day_counts = Counter()
            day_events = set()
            day_receipts = [None, None]
            day_bytes = day_files = 0
            for path in sorted(folder.glob('*.jsonl.gz')):
                # The retained reader verifies the shard membership digest and
                # every immutable change digest before anything is counted.
                rows = read_shard(path, feed, folder.name)
                for _, _, kind, _, event, source, received, _, _ in rows:
                    counts[kind] += 1
                    day_counts[kind] += 1
                    if event is not None:
                        events.add(event)
                        day_events.add(event)
                    include(receipt_bounds, received)
                    include(day_receipts, received)
                    include(source_bounds, source)
                day_bytes += path.stat().st_size
                day_files += 1
                if progress and day_files % 128 == 0:
                    progress(feed, dict(receipt_day=folder.name, files=day_files,
                        compressed_bytes=day_bytes, records=sum(day_counts.values()),
                        records_by_kind=dict(day_counts), distinct_events=len(day_events),
                        first_received_at=day_receipts[0], last_received_at=day_receipts[1],
                        state='partial_day_checkpoint', last_verified_file=path.name))
            total_bytes += day_bytes
            files += day_files
            days.append(dict(receipt_day=folder.name, files=day_files,
                compressed_bytes=day_bytes, records=sum(day_counts.values()),
                records_by_kind=dict(day_counts), distinct_events=len(day_events),
                first_received_at=day_receipts[0], last_received_at=day_receipts[1]))
            if progress:progress(feed, days[-1])
        populated = [date.fromisoformat(d['receipt_day']) for d in days if d['files']]
        missing_days = []
        if populated:
            day = min(populated)
            while day <= max(populated):
                if day not in populated:missing_days.append(day.isoformat())
                day += timedelta(days=1)
        result[feed] = dict(files=files, compressed_bytes=total_bytes,
            verified_records=sum(counts.values()), records_by_kind=dict(counts),
            distinct_events=len(events), first_received_at=receipt_bounds[0],
            last_received_at=receipt_bounds[1], first_source_at=source_bounds[0],
            last_source_at=source_bounds[1], days=days, missing_receipt_days=missing_days,
            coverage='verified_files_with_gaps_not_complete_collection')
        instant.cache_clear()
    return dict(version='predict-odds-archive-census-1',
        scan_started_at=started_at, observed_at=datetime.now(timezone.utc).isoformat(),
        snapshot_consistency='incremental_live_filesystem_listing', feeds=result,
        scope=dict(first_day=first_day.isoformat() if first_day else None,
                   last_day=last_day.isoformat() if last_day else None),
        limitations=[
            'Distinct events use source-local event IDs; feeds must not be added as independent samples.',
            'Content and within-shard membership are verified; cross-shard duplicate detection is not performed, so counts are retained rows.',
            'No claim of continuous collection or no missing observations follows from a populated day.',
            'Files added after a folder is listed require a subsequent incremental census.',
            'Native history is top-of-book only; local archive files are not an off-host backup.'
        ], provider_requests=0)


def main():
    import argparse
    import json
    import os
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', default=os.environ.get('PREDICT_ODDS_ARCHIVE_ROOT', '/archive'))
    parser.add_argument('--from-day', type=date.fromisoformat)
    parser.add_argument('--through-day', type=date.fromisoformat)
    args = parser.parse_args()
    def progress(feed, day):
        print(json.dumps(dict(feed=feed, **day)), file=sys.stderr, flush=True)
    print(json.dumps(census(args.root, first_day=args.from_day, last_day=args.through_day,
                            progress=progress), indent=2))


if __name__ == '__main__':
    main()
