"""Record observed arb episodes in the ordinary publication transaction."""

from psycopg.types.json import Jsonb

MAX_CLOSED = 10_000
RETENTION_DAYS = 30
EXPIRED_BATCH = 1000


def observe(db, *, at, generation, opportunities):
    """Record openings and closures; the serialized caller owns the transaction."""
    changes = db.execute('''WITH incoming AS (
            SELECT key AS pair_id, value AS facts FROM jsonb_each(%s)
        ), closed AS (
            UPDATE arb_appearance a SET disappeared_at=greatest(a.appeared_at, %s::timestamptz)
            WHERE a.disappeared_at IS NULL
                AND NOT EXISTS (SELECT 1 FROM incoming i WHERE i.pair_id=a.pair_id)
            RETURNING id
        ), opened AS (
            INSERT INTO arb_appearance (pair_id, appeared_at, generation, facts)
            SELECT i.pair_id, %s, %s, i.facts FROM incoming i
            WHERE NOT EXISTS (SELECT 1 FROM arb_appearance a
                WHERE a.pair_id=i.pair_id AND a.disappeared_at IS NULL)
            ON CONFLICT (pair_id) WHERE disappeared_at IS NULL DO NOTHING
            RETURNING id
        ) SELECT EXISTS (SELECT 1 FROM closed) AS closed, (SELECT count(*) FROM opened) AS opened''',
        (Jsonb(opportunities), at, at, generation)).fetchone()
    db.execute('''DELETE FROM arb_appearance WHERE id IN (
        SELECT id FROM arb_appearance WHERE disappeared_at < %s::timestamptz - make_interval(days => %s)
        ORDER BY disappeared_at, id LIMIT %s
    )''', (at, RETENTION_DAYS, EXPIRED_BATCH))
    if changes['closed']:
        db.execute('''WITH cutoff AS (
            SELECT disappeared_at, id FROM arb_appearance WHERE disappeared_at IS NOT NULL
            ORDER BY disappeared_at DESC, id DESC OFFSET %s LIMIT 1
        ) DELETE FROM arb_appearance a USING cutoff c WHERE a.disappeared_at IS NOT NULL
            AND (a.disappeared_at, a.id) <= (c.disappeared_at, c.id)''', (MAX_CLOSED,))
    return changes['opened']
