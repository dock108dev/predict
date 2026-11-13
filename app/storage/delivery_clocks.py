"""Bounded aggregate admission, capture and publication write clocks."""
from psycopg.types.json import Jsonb

from .store import stamp

TABLES = {'the_odds_api': 'comparison_delivery_clock', 'sportsgameodds': 'current_sgo_delivery_clock'}


def receipts(rows):
    return sorted({(r['source']['provider'], r['league'], r['times']['received_at']) for r in rows
        if r.get('source', {}).get('provider') in TABLES and r.get('times', {}).get('received_at')})


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


def sgo_clock_available(db):
    # The calculation child can read updated code before its owner has
    # restarted and applied the migration. Telemetry must never block it.
    return db.execute("SELECT to_regclass('public.current_sgo_delivery_clock') AS name").fetchone()['name'] is not None


def live_sportsbook_clock_available(db):
    return db.execute("""SELECT EXISTS(SELECT 1 FROM pg_attribute
        WHERE attrelid=to_regclass('public.current_sgo_delivery_clock')
          AND attname='first_live_sportsbook_write_at' AND NOT attisdropped) AS available""").fetchone()['available']


def prune(db, table):
    db.execute(f'''DELETE FROM {table} WHERE (league,received_at) IN
        (SELECT league,received_at FROM {table} ORDER BY received_at DESC,league OFFSET 2048)''')


def sgo_admitted(db, leagues, received_at):
    if not sgo_clock_available(db):
        return
    db.execute('''INSERT INTO current_sgo_delivery_clock (league,received_at,admitted_at,capture_count)
        SELECT league,%s::timestamptz,admitted_at,0 FROM unnest(%s::text[]) AS leagues(league)
        CROSS JOIN (SELECT clock_timestamp() AS admitted_at) AS receipt
        ON CONFLICT DO NOTHING''', (received_at, sorted(leagues)))
    prune(db, TABLES['sportsgameodds'])


def captured(db, rows, at):
    keys = receipts(rows)
    for provider, table in TABLES.items():
        observed = [(league, receipt, at, at) for p, league, receipt in keys if p == provider]
        if not observed or provider == 'sportsgameodds' and not sgo_clock_available(db):
            continue
        with db.cursor() as cur:
            cur.executemany(f'''INSERT INTO {table}
                (league,received_at,first_recorded_capture_at,last_capture_at,capture_count)
                VALUES (%s,%s,%s,%s,1)
                ON CONFLICT(league,received_at) DO UPDATE SET
                first_recorded_capture_at=COALESCE({table}.first_recorded_capture_at,EXCLUDED.first_recorded_capture_at),
                last_capture_at=EXCLUDED.last_capture_at, capture_count={table}.capture_count+1''', observed)
        prune(db, table)


def published(db, keys, *, live_sportsbook=()):
    # Retained ordinary fragments can carry provider-less legacy receipt keys.
    keys = {('the_odds_api', *key) if len(key) == 2 else tuple(key) for key in keys}
    for provider, table in TABLES.items():
        observed = [dict(league=league, received_at=receipt) for p, league, receipt in keys if p == provider]
        if not observed or provider == 'sportsgameodds' and not sgo_clock_available(db):
            continue
        db.execute(f'''UPDATE {table} d SET first_publication_write_at=statement_timestamp()
            FROM jsonb_to_recordset(%s) AS r(league text, received_at timestamptz)
            WHERE (d.league,d.received_at)=(r.league,r.received_at) AND d.first_publication_write_at IS NULL''',
            (Jsonb(observed),))
    if live_sportsbook and live_sportsbook_clock_available(db):
        rows = [dict(league=league, received_at=receipt, deadline=deadline) for league, receipt, deadline in live_sportsbook]
        db.execute('''UPDATE current_sgo_delivery_clock d SET first_live_sportsbook_write_at=statement_timestamp()
            FROM jsonb_to_recordset(%s) AS r(league text, received_at timestamptz, deadline timestamptz)
            WHERE (d.league,d.received_at)=(r.league,r.received_at) AND d.first_live_sportsbook_write_at IS NULL
            AND r.deadline >= statement_timestamp()''', (Jsonb(rows),))


def recent(db):
    legacy = """SELECT 'the_odds_api' provider, d.*, NULL::timestamptz admitted_at,
                NULL::timestamptz first_live_sportsbook_write_at FROM comparison_delivery_clock d"""
    live_clock = 'first_live_sportsbook_write_at' if live_sportsbook_clock_available(db) else 'NULL::timestamptz'
    sgo = f"""SELECT 'sportsgameodds' provider, league, received_at, first_recorded_capture_at,
             last_capture_at, capture_count, first_publication_write_at, admitted_at,
             {live_clock} FROM current_sgo_delivery_clock"""
    sources = f'{legacy} UNION ALL {sgo}' if sgo_clock_available(db) else legacy
    rows = db.execute(sources + ' ORDER BY received_at DESC,league LIMIT 24').fetchall()
    return [{k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in row.items()} for row in rows]
