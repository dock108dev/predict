"""Bounded late-pregame cadence measurements; no provider or accounting writes."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3

MAX_SAMPLES = 10000


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def report(path):
    if not Path(path).is_file():
        return dict(state='awaiting_final_30_minutes', samples=0)
    with sqlite3.connect(f'file:{Path(path)}?mode=ro', uri=True, timeout=2) as db:
        rows = db.execute('SELECT event_id,received_at,price_hash,clock_hash FROM sample ORDER BY received_at,event_id').fetchall()
    prior, retained, last_at = {}, {}, {}
    changes = clocks = clock_only = redundant = comparisons = early = 0
    gaps = []
    for event, at, price, clock in rows:
        moment = datetime.fromisoformat(at)
        if event in prior:
            comparisons += 1
            changes += int(price != prior[event][0])
            clocks += int(clock != prior[event][1])
            clock_only += int(price == prior[event][0] and clock != prior[event][1])
            redundant += int((price, clock) == prior[event])
            gaps.append((moment-last_at[event]).total_seconds())
        previous = retained.get(event)
        if previous is None or moment-previous[0] >= timedelta(minutes=3):
            retained[event] = (moment, price)
        elif price != previous[1]:
            early += 1
        prior[event] = (price, clock)
        last_at[event] = moment
    return dict(state='measuring' if rows else 'awaiting_final_30_minutes',
                samples=len(rows), events=len(prior), comparable_polls=comparisons,
                quote_image_changes=changes, source_clock_image_changes=clocks,
                clock_only_changes=clock_only,
                fully_repeated_polls=redundant, earlier_changed_images_vs_3m=early,
                poll_gap_seconds=dict(min=min(gaps),max=max(gaps),mean=round(sum(gaps)/len(gaps),3)) if gaps else None,
                first_received_at=rows[0][1] if rows else None,
                last_received_at=rows[-1][1] if rows else None,
                note='Quote images cover prices, lines and availability. First samples are baselines. Three-minute replay measures earlier observations, not executions.')


def observe(path, page, admitted_at):
    """Measure only successfully admitted pregame pages inside the final 30m."""
    samples = []
    for event in page.events:
        starts = datetime.fromisoformat(event['starts_at']).astimezone(timezone.utc)
        if event.get('phase') != 'pregame' or not timedelta(0) < starts-admitted_at <= timedelta(minutes=30):
            continue
        quotes = [q for q in page.quotes if q.get('event_id') == event['event_id']]
        # Canonical sorting ignores response order, receipt hashes and clocks
        # when testing whether the quoted prices/availability actually changed.
        values, clocks = [], []
        for quote in quotes:
            key = [quote.get(k) for k in ('venue', 'odd_id', 'line')]
            values.append(key+[quote.get(k) for k in ('price_american', 'available', 'provider_available', 'alternate')])
            clocks.append(key+[quote.get('source_at')])
        values.sort(key=lambda value: json.dumps(value))
        clocks.sort(key=lambda value: json.dumps(value))
        at = datetime.fromisoformat(event['received_at']).astimezone(timezone.utc).isoformat()
        samples.append((event['event_id'], at, starts.isoformat(), digest(values), digest(clocks), len(quotes)))
    if not samples:
        return report(path)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(path, timeout=2) as db:
        os.chmod(path, 0o600)
        db.execute('''CREATE TABLE IF NOT EXISTS sample (
            event_id TEXT NOT NULL,received_at TEXT NOT NULL,starts_at TEXT NOT NULL,
            price_hash TEXT NOT NULL,clock_hash TEXT NOT NULL,quotes INTEGER NOT NULL,
            PRIMARY KEY(event_id,received_at))''')
        db.executemany('INSERT OR IGNORE INTO sample VALUES(?,?,?,?,?,?)', samples)
        db.execute('DELETE FROM sample WHERE received_at<?',
                   ((admitted_at-timedelta(days=7)).astimezone(timezone.utc).isoformat(),))
        db.execute('''DELETE FROM sample WHERE rowid IN (
            SELECT rowid FROM sample ORDER BY received_at DESC,event_id LIMIT -1 OFFSET ?)''', (MAX_SAMPLES,))
    return report(path)


if __name__ == '__main__':
    from .current_policy import ROOT

    print(json.dumps(report(ROOT/'.local/predict-odds/diagnostics/sgo-refresh-study.sqlite3'), indent=2))
