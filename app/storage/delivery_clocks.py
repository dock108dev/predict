"""Bounded aggregate admission, capture and publication write clocks."""

TABLES = {'the_odds_api': 'comparison_delivery_clock', 'sportsgameodds': 'current_sgo_delivery_clock'}


def receipts(rows):
    return sorted({(r['source']['provider'], r['league'], r['times']['received_at']) for r in rows
        if r.get('source', {}).get('provider') in TABLES and r.get('times', {}).get('received_at')})


def sgo_clock_available(db):
    # The calculation child can read updated code before its owner has
    # restarted and applied the migration. Telemetry must never block it.
    return db.execute("SELECT to_regclass('public.current_sgo_delivery_clock') AS name").fetchone()['name'] is not None


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


def published(db, keys):
    # Retained ordinary fragments can carry provider-less legacy receipt keys.
    keys = {('the_odds_api', *key) if len(key) == 2 else tuple(key) for key in keys}
    for provider, table in TABLES.items():
        observed = sorted((league, receipt) for p, league, receipt in keys if p == provider)
        if not observed or provider == 'sportsgameodds' and not sgo_clock_available(db):
            continue
        with db.cursor() as cur:
            cur.executemany(f'''UPDATE {table} SET first_publication_write_at=clock_timestamp()
                WHERE league=%s AND received_at=%s AND first_publication_write_at IS NULL''', observed)


def recent(db):
    legacy = "SELECT 'the_odds_api' provider, d.*, NULL::timestamptz admitted_at FROM comparison_delivery_clock d"
    sgo = """SELECT 'sportsgameodds' provider, league, received_at, first_recorded_capture_at,
             last_capture_at, capture_count, first_publication_write_at, admitted_at FROM current_sgo_delivery_clock"""
    sources = f'{legacy} UNION ALL {sgo}' if sgo_clock_available(db) else legacy
    rows = db.execute(sources + ' ORDER BY received_at DESC,league LIMIT 24').fetchall()
    return [{k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in row.items()} for row in rows]
