"""Bounded aggregate receipt clocks; first capture means since retained tracking."""

def receipts(rows):
    return sorted({(r['league'],r['times']['received_at']) for r in rows
        if r.get('source',{}).get('provider')=='the_odds_api' and r.get('times',{}).get('received_at')})


def captured(db,rows,at):
    keys=receipts(rows)
    if not keys:return
    with db.cursor() as cur:
        cur.executemany('''INSERT INTO comparison_delivery_clock VALUES(%s,%s,%s,%s,1,NULL)
            ON CONFLICT(league,received_at) DO UPDATE SET last_capture_at=EXCLUDED.last_capture_at,
            capture_count=comparison_delivery_clock.capture_count+1''',[(league,receipt,at,at) for league,receipt in keys])
    db.execute('''DELETE FROM comparison_delivery_clock WHERE (league,received_at) IN
        (SELECT league,received_at FROM comparison_delivery_clock ORDER BY received_at DESC,league OFFSET 2048)''')


def published(db,keys):
    if not keys:return
    with db.cursor() as cur:
        cur.executemany('''UPDATE comparison_delivery_clock SET first_publication_write_at=clock_timestamp()
            WHERE league=%s AND received_at=%s AND first_publication_write_at IS NULL''',sorted(set(map(tuple,keys))))


def recent(db):
    rows=db.execute('''SELECT * FROM comparison_delivery_clock
        ORDER BY received_at DESC,league LIMIT 24''').fetchall()
    return [{k:v.isoformat() if hasattr(v,'isoformat') else v for k,v in row.items()} for row in rows]
