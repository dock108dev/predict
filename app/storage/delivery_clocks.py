"""Bounded aggregate admission, capture and publication write clocks."""
from psycopg.types.json import Jsonb

from .store import stamp

PROVIDERS = frozenset(('the_odds_api', 'sportsgameodds'))


def receipts(rows):
    return sorted({(r['source']['provider'], r['league'], r['times']['received_at']) for r in rows
        if r.get('source', {}).get('provider') in PROVIDERS and r.get('times', {}).get('received_at')})


def live_sportsbook_deadlines(rows):
    """Newest usable deadline per SGO receipt in the immutable member."""
    deadlines = {}
    for row in rows:
        baseline = row.get('sportsbook_baseline')
        price = row['current_authority']['price']
        if (not baseline or baseline.get('verified_native') or price.get('provider') != 'sportsgameodds'
                or price.get('reasons') or price.get('lifecycle', {}).get('state') != 'live'):
            continue
        key = (row['league'], baseline.get('frame_received_at') or row['times']['received_at'])
        deadline = min(stamp(price['current_until']), stamp(baseline['current_until']))
        if key not in deadlines or deadline > deadlines[key]:
            deadlines[key] = deadline
    return [[league, received, deadline.isoformat()] for (league, received), deadline in deadlines.items()]


def available(db):
    # The calculation child can read updated code before its owner has
    # restarted and applied the migration. Telemetry must never block it.
    return db.execute("SELECT to_regclass('public.delivery_clock') IS NOT NULL AS present").fetchone()['present']


def prune(db, provider):
    db.execute('''DELETE FROM delivery_clock WHERE provider=%s AND (league,received_at) IN
        (SELECT league,received_at FROM delivery_clock WHERE provider=%s
         ORDER BY received_at DESC,league OFFSET 2048)''', (provider, provider))


def sgo_admitted(db, leagues, received_at):
    if not available(db):
        return
    db.execute('''INSERT INTO delivery_clock (provider,league,received_at,admitted_at,capture_count)
        SELECT 'sportsgameodds',league,%s::timestamptz,admitted_at,0 FROM unnest(%s::text[]) AS leagues(league)
        CROSS JOIN (SELECT clock_timestamp() AS admitted_at) AS receipt
        ON CONFLICT DO NOTHING''', (received_at, sorted(leagues)))
    prune(db, 'sportsgameodds')


def captured(db, rows, at):
    keys = receipts(rows)
    if not keys or not available(db):
        return
    with db.cursor() as cur:
        cur.executemany('''INSERT INTO delivery_clock
            (provider,league,received_at,first_recorded_capture_at,last_capture_at,capture_count)
            VALUES (%s,%s,%s,%s,%s,1)
            ON CONFLICT(provider,league,received_at) DO UPDATE SET
            first_recorded_capture_at=COALESCE(delivery_clock.first_recorded_capture_at,EXCLUDED.first_recorded_capture_at),
            last_capture_at=EXCLUDED.last_capture_at, capture_count=delivery_clock.capture_count+1''',
            [(provider, league, receipt, at, at) for provider, league, receipt in keys])
    for provider in sorted({key[0] for key in keys}):
        prune(db, provider)


def published(db, keys, *, live_sportsbook=()):
    # Retained ordinary fragments can carry provider-less legacy receipt keys.
    keys = {('the_odds_api', *key) if len(key) == 2 else tuple(key) for key in keys}
    if not (keys or live_sportsbook) or not available(db):
        return
    observed = [dict(provider=provider, league=league, received_at=receipt)
                for provider, league, receipt in sorted(keys) if provider in PROVIDERS]
    if observed:
        db.execute('''UPDATE delivery_clock d SET first_publication_write_at=statement_timestamp()
            FROM jsonb_to_recordset(%s) AS r(provider text, league text, received_at timestamptz)
            WHERE (d.provider,d.league,d.received_at)=(r.provider,r.league,r.received_at)
            AND d.first_publication_write_at IS NULL''', (Jsonb(observed),))
    if live_sportsbook:
        rows = [dict(league=league, received_at=receipt, deadline=deadline) for league, receipt, deadline in live_sportsbook]
        db.execute('''UPDATE delivery_clock d SET first_live_sportsbook_write_at=statement_timestamp()
            FROM jsonb_to_recordset(%s) AS r(league text, received_at timestamptz, deadline timestamptz)
            WHERE d.provider='sportsgameodds' AND (d.league,d.received_at)=(r.league,r.received_at)
            AND d.first_live_sportsbook_write_at IS NULL
            AND r.deadline >= statement_timestamp()''', (Jsonb(rows),))


def recent(db):
    if not available(db):
        return []
    rows = db.execute('SELECT * FROM delivery_clock ORDER BY received_at DESC,league,provider LIMIT 24')
    return [{k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in row.items()} for row in rows]
