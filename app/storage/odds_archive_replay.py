"""Verify archived shards and reproduce the original Odds witness for one event."""
import argparse
from collections import Counter
from datetime import date
import gzip
import json
from pathlib import Path

from .odds_archive import FEEDS, VERSION, digest
from .odds_archive_export import SHARD_BYTES, SHARD_ROWS
from .store import exact_time


def read_shard(path, feed, day):
    with gzip.open(path, 'rb') as file:
        raw = file.read(SHARD_BYTES + SHARD_ROWS * 70 + 1)
        if file.read(1):
            raise ValueError('odds_archive_shard_size')
    rows = [json.loads(line) for line in raw.splitlines()]
    ids = sorted(row[0] for row in rows)
    if (not rows or len(rows) > SHARD_ROWS or len(ids) != len(set(ids))
            or path.name != digest([feed, day, ids])+'.jsonl.gz'):
        raise ValueError('odds_archive_shard_identity')
    for identity, *body in rows:
        if len(body) != 8 or body[0] != VERSION or identity != digest(body):
            raise ValueError('odds_archive_change_identity')
    return rows


def replay_event(root, feed, event_id, first_day, last_day, as_of):
    """Use receipt time for causality, including late arrivals in any shard."""
    if feed not in FEEDS or first_day > last_day:
        raise ValueError('odds_archive_replay_scope')
    deadline = exact_time(as_of)
    days = Path(root) / 'v1' / feed
    changes, seen = [], set()
    for day in sorted(days.iterdir()):
        if not day.is_dir() or len(day.name) != 10:
            continue
        day_value = date.fromisoformat(day.name)
        if not first_day <= day_value <= last_day:
            continue
        for path in sorted(day.glob('*.jsonl.gz')):
            for row in read_shard(path,feed,day.name):
                identity, _, kind, _, event, _, received, _, _ = row
                if event not in (event_id,None) or exact_time(received) > deadline:
                    continue
                if identity in seen:
                    raise ValueError('odds_archive_duplicate_change')
                seen.add(identity)
                changes.append(row)
    changes.sort(key=lambda row: (exact_time(row[6]), row[0]))
    return changes


def daily(root, day):
    totals = {}
    for feed in sorted(FEEDS):
        counts = Counter()
        size = files = 0
        seen = set()
        for path in (Path(root)/'v1'/feed/day.isoformat()).glob('*.jsonl.gz'):
            for identity, _, kind, *_ in read_shard(path,feed,day.isoformat()):
                if identity in seen:
                    raise ValueError('odds_archive_duplicate_change')
                seen.add(identity)
                counts[kind] += 1
            size += path.stat().st_size
            files += 1
        totals[feed] = dict(compressed_bytes=size, files=files, records_by_kind=dict(counts))
    return totals


def odds(changes, feed, event_id, identity):
    """Reproduce a selected original price and retain its separate definition."""
    scope = digest([feed,event_id,identity])
    selected = [row for row in changes if row[2]=='top' and row[3]==scope]
    if not selected:
        return None
    head = selected[-1]
    _, _, _, _, _, source, received, evidence, values = head
    at_price = [row for row in changes if exact_time(row[6])<=exact_time(received)]
    if feed == 'sportsgameodds':
        price, units, size, size_units, availability = values[:5]
        definitions = [row for row in at_price if row[2]=='definition' and row[3]==scope]
    else:
        market, outcome, side, price, units, size, size_units, availability = values
        definitions = [row for row in at_price if row[2]=='definition' and row[4]==event_id and
                       (row[8]['source']['native_market_id'], row[8]['source']['native_outcome_id'])==(market,outcome)]
    gaps = [row[0] for row in changes if exact_time(row[6])>=exact_time(received) and (
        row[2] in ('source_status','runtime_status') or feed!='sportsgameodds' and
        row[2] in ('discovery_gap','book_status') and row[8][0]==identity[0])]
    definition = definitions[-1] if definitions else None
    match = next((row for row in reversed(at_price) if
                  definition and row[2]=='matching' and row[3]==definition[3]), None)
    from app.dashboard.u0_display import quote_display
    # Top and witness records have exact causal clocks. Currentness may also
    # depend on unretained intermediate clocks and runtime/consumer state.
    return dict(change_id=head[0], event_id=event_id, source_at=source, received_at=received,
                price=price, price_units=units, size=size, size_units=size_units, availability=availability,
                evidence=evidence, definition=definition[8] if definition else None,
                definition_change_id=definition[0] if definition else None,
                matching=match[8] if match else None, matching_change_id=match[0] if match else None,
                display=quote_display(price, units) if price is not None else None,
                subsequent_status_changes=gaps, freshness='not_established')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--daily', type=date.fromisoformat)
    parser.add_argument('--feed', choices=sorted(FEEDS))
    parser.add_argument('--event')
    parser.add_argument('--from-day', type=date.fromisoformat)
    parser.add_argument('--through-day', type=date.fromisoformat)
    parser.add_argument('--as-of')
    parser.add_argument('--identity', type=json.loads,
        help='Native ["market","outcome","asks"] or the quoted SGO reference identity')
    args = parser.parse_args()
    if args.daily:
        print(json.dumps(dict(utc_day=args.daily.isoformat(), feeds=daily(args.root,args.daily),
                              provider_requests=0)))
        return 0
    if not all((args.feed,args.event,args.from_day,args.through_day,args.as_of,args.identity)):
        parser.error('Replay needs feed, event, day range, as-of receipt clock and exact quote identity')
    if (args.feed=='sportsgameodds' and not isinstance(args.identity,str)
            or args.feed!='sportsgameodds' and (
                not isinstance(args.identity,list) or len(args.identity)!=3
                or args.identity[2] not in ('asks','bids'))):
        parser.error('Exact native or SGO quote identity required')
    changes = replay_event(args.root,args.feed,args.event,args.from_day,args.through_day,args.as_of)
    result = odds(changes,args.feed,args.event,args.identity)
    print(json.dumps(dict(verified_event_records=len(changes), odds=result, provider_requests=0)))
    return 0 if result else 2


if __name__ == '__main__':
    raise SystemExit(main())
