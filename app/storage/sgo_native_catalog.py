"""Bounded, replaceable official metadata for SportsGameOdds venue links."""
from datetime import timedelta

from psycopg.types.json import Jsonb

from app.comparison.sgo_native_binding import event_link_id, outcome_link_id
from .store import encoded, hashed, now, stamp

MAX_EVENTS = 512
MAX_BYTES = 128 * 1024


def targets(db, *, at, exclude=()):
    """Pick the newest in-scope receipts that need independent catalog terms."""
    frames = db.execute('''SELECT f.event_id, f.facts
        FROM current_sgo_event_frame f LEFT JOIN current_sgo_native_catalog c USING (event_id)
        WHERE f.facts->'event_context'->'bookmaker_event_links' ? 'novig'
          AND (f.facts->>'starts_at')::timestamptz BETWEEN %s::timestamptz - interval '4 hours'
                                                        AND %s::timestamptz + interval '72 hours'
          AND f.facts->'event_context'->>'phase' IN ('pregame','live')
          AND (c.observed_at IS NULL OR NOT c.facts ? 'subject_roles'
               OR c.observed_at < %s::timestamptz - interval '10 minutes')
          AND NOT f.event_id=ANY(%s)
          AND EXISTS (SELECT 1 FROM current_sgo_reference r WHERE r.event_id=f.event_id
              AND r.bookmaker_id='novig' AND r.facts ? 'bookmaker_market_link'
              AND r.facts->>'available'='true')
        ORDER BY (f.facts->'event_context'->>'phase'='live') DESC,
          abs(extract(epoch from (f.facts->>'starts_at')::timestamptz - %s::timestamptz)),
          f.received_order DESC, f.event_id LIMIT 12''', (at, at, at, list(exclude), at)).fetchall()
    result = []
    for frame in frames:
        facts = frame['facts']
        event_id = frame['event_id']
        native = event_link_id(facts['event_context']['bookmaker_event_links'].get('novig'))
        if native is None:
            continue
        members = dict(facts['members'])
        rows = db.execute('''SELECT id,revision,facts FROM current_sgo_reference WHERE event_id=%s
            AND id=ANY(%s) AND bookmaker_id='novig' AND facts ? 'bookmaker_market_link'
            AND facts->>'available'='true' ''', (event_id, list(members)))
        outcomes = {}
        for row in rows:
            original = row['facts']
            link = outcome_link_id(original.get('bookmaker_market_link'))
            if link and members[row['id']] == row['revision']:
                outcomes.setdefault(link, []).append({key:original.get(key) for key in (
                    'odd_id','opposing_odd_id','side','line','market','period')})
        if outcomes:
            result.append((event_id, native, outcomes, facts.get('receipt_sha256')))
        if len(result) == 2:
            break
    return result


def _exists(db):
    return bool(db.execute("SELECT to_regclass('public.current_sgo_native_catalog') name").fetchone()['name'])


def read(db, event_ids):
    if not event_ids or not _exists(db):
        return {}
    return {row['event_id']: dict(row['facts'], revision=row['revision']) for row in db.execute('''
        SELECT event_id,revision,facts FROM current_sgo_native_catalog WHERE event_id=ANY(%s)''', (list(event_ids),))}


def dependency_id(event_id):
    return 'sgo-native-catalog:novig:' + event_id


def dependencies(db, event_ids=None, *, at=None):
    if not _exists(db):
        return []
    at = stamp(at or now())
    return db.execute('''SELECT 'sgo-native-catalog:novig:'||c.event_id id,
        c.revision price,c.revision contract,c.revision event,c.revision receipt,e.id event_id
        FROM current_sgo_native_catalog c JOIN current_event e
          ON e.provider='sportsgameodds' AND e.native_event_id=c.event_id
        WHERE c.expires_at > %s AND ((%s::text[] IS NULL AND e.scheduled_start::timestamptz >= %s
          AND e.scheduled_start::timestamptz < %s) OR e.id=ANY(%s)) ORDER BY id''',
        (at,event_ids,at-timedelta(hours=24),at+timedelta(hours=72),event_ids)).fetchall()


def write(db, event_id, facts):
    """Replace this bounded cache without changing SGO prices or accounting."""
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage

    body = encoded(facts)
    if len(body) > MAX_BYTES:
        raise ValueError('sgo_native_catalog_capacity')
    at, expiry = (stamp(facts[field]) for field in ('observed_at','expires_at'))
    with db.transaction():
        db.execute('DELETE FROM current_sgo_native_catalog WHERE expires_at < %s', (at,))
        count = db.execute('SELECT count(*) n FROM current_sgo_native_catalog WHERE event_id<>%s',
                           (event_id,)).fetchone()['n']
        if count >= MAX_EVENTS or sql_usage(db) + 2 * len(body) >= SQL_BYTE_CAP:
            raise ValueError('sgo_native_catalog_storage_capacity')
        db.execute('''INSERT INTO current_sgo_native_catalog (event_id,observed_at,expires_at,revision,facts)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO UPDATE
            SET observed_at=EXCLUDED.observed_at,expires_at=EXCLUDED.expires_at,
                revision=EXCLUDED.revision,facts=EXCLUDED.facts
            WHERE EXCLUDED.observed_at > current_sgo_native_catalog.observed_at''',
            (event_id, at, expiry, hashed(facts), Jsonb(facts)))
