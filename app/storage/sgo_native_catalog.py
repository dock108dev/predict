"""Bounded, replaceable official metadata for SportsGameOdds venue links."""
from datetime import timedelta

from psycopg.types.json import Jsonb

from app.comparison.sgo_native_binding import event_link_id, outcome_link_id
from .store import encoded, hashed, now, stamp

MAX_EVENTS = 512
MAX_BYTES = 128 * 1024


def targets(db, *, at, exclude=(), include_live=True):
    """Prioritize uncaptured terms for eligible games over periodic rechecks."""
    frames = db.execute('''SELECT f.event_id, f.facts
        FROM current_sgo_event_frame f LEFT JOIN current_sgo_native_catalog c USING (event_id)
        CROSS JOIN LATERAL (SELECT (f.facts->>'starts_at')::timestamptz AS kickoff,
            f.facts->'event_context'->>'phase' AS phase) scope
        WHERE f.facts->'event_context'->'bookmaker_event_links' ? 'novig'
          AND ((scope.phase='pregame' AND scope.kickoff > %(at)s
                AND scope.kickoff <= %(at)s::timestamptz + interval '72 hours')
               OR (%(include_live)s AND scope.phase='live' AND scope.kickoff <= %(at)s
                   AND scope.kickoff >= %(at)s::timestamptz - interval '4 hours'))
          AND (c.observed_at IS NULL OR NOT c.facts ? 'subject_roles'
               OR c.observed_at < %(at)s::timestamptz - interval '10 minutes')
          AND NOT f.event_id=ANY(%(exclude)s)
          AND EXISTS (SELECT 1 FROM current_sgo_reference r WHERE r.event_id=f.event_id
              AND r.bookmaker_id='novig' AND r.facts ? 'bookmaker_market_link'
              AND r.facts->>'available'='true')
        ORDER BY (c.observed_at IS NOT NULL), (scope.phase='live') DESC,
          c.observed_at NULLS FIRST, abs(extract(epoch from scope.kickoff - %(at)s::timestamptz)),
          f.received_order DESC, f.event_id LIMIT 12''',
        dict(at=at, exclude=list(exclude), include_live=include_live)).fetchall()
    result = []
    for frame in frames:
        facts = frame['facts']
        event_id = frame['event_id']
        native = event_link_id(facts['event_context']['bookmaker_event_links'].get('novig'))
        if native is None:
            continue
        members = dict(facts['members'])
        rows = db.execute('''SELECT id,revision,facts FROM current_sgo_reference WHERE event_id=%s
            AND bookmaker_id='novig' AND facts ? 'bookmaker_market_link'
            AND facts->>'available'='true' ORDER BY id LIMIT 4097''', (event_id,)).fetchall()
        if len(rows) > 4096:
            continue
        outcomes = {}
        for row in rows:
            original = row['facts']
            link = outcome_link_id(original.get('bookmaker_market_link'))
            if link and (row['id'] not in members and facts['event_context']['phase'] == 'pregame'
                         or members.get(row['id']) == row['revision']):
                outcomes.setdefault(link, []).append({key:original.get(key) for key in (
                    'odd_id','opposing_odd_id','side','line','market','period')})
        if outcomes:
            result.append((event_id, native, outcomes, facts.get('receipt_sha256')))
        if len(result) == 2:
            break
    return result


def _exists(db):
    return bool(db.execute("SELECT to_regclass('public.current_sgo_native_catalog') name").fetchone()['name'])


def read(db, event_ids, *, include_markets=True):
    if not event_ids or not _exists(db):
        return {}
    facts = 'facts' if include_markets else "facts - 'markets' AS facts"
    return {row['event_id']: dict(row['facts'], revision=row['revision']) for row in db.execute(f'''
        SELECT event_id,revision,{facts} FROM current_sgo_native_catalog WHERE event_id=ANY(%s)''', (list(event_ids),))}


def dependency_id(event_id):
    return 'sgo-native-catalog:novig:' + event_id


def dependencies(db, event_ids=None, *, at=None, native_ids=None):
    if not _exists(db):
        return []
    at = stamp(at or now())
    target = ' AND c.event_id=ANY(%s)' if native_ids is not None else ''
    params = (at,at,event_ids,at-timedelta(hours=24),at+timedelta(hours=72),event_ids)
    if native_ids is not None:
        params += (native_ids,)
    return db.execute('''SELECT 'sgo-native-catalog:novig:'||c.event_id id,
        c.revision price,c.revision contract,c.revision event,c.revision receipt,e.id event_id
        FROM current_sgo_native_catalog c JOIN current_event e
          ON e.provider='sportsgameodds' AND e.native_event_id=c.event_id
        WHERE (c.expires_at > %s OR e.scheduled_start::timestamptz > %s) AND ((%s::text[] IS NULL AND e.scheduled_start::timestamptz >= %s
          AND e.scheduled_start::timestamptz < %s) OR e.id=ANY(%s))'''+target+' ORDER BY id', params).fetchall()


def write(db, event_id, facts):
    """Replace this bounded cache without changing SGO prices or accounting."""
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage

    body = encoded(facts)
    if len(body) > MAX_BYTES:
        raise ValueError('sgo_native_catalog_capacity')
    at, expiry = (stamp(facts[field]) for field in ('observed_at','expires_at'))
    with db.transaction():
        db.execute('''DELETE FROM sgo_event_evidence c WHERE kind='catalog' AND expires_at < %s
            AND NOT EXISTS (SELECT 1 FROM current_event e WHERE e.provider='sportsgameodds'
                AND e.native_event_id=c.event_id AND e.scheduled_start::timestamptz > %s)''', (at, at))
        count = db.execute('SELECT count(*) n FROM current_sgo_native_catalog WHERE event_id<>%s',
                           (event_id,)).fetchone()['n']
        if count >= MAX_EVENTS or sql_usage(db) + 2 * len(body) >= SQL_BYTE_CAP:
            raise ValueError('sgo_native_catalog_storage_capacity')
        db.execute('''INSERT INTO sgo_event_evidence (kind,event_id,observed_at,expires_at,revision,facts)
            VALUES ('catalog',%s,%s,%s,%s,%s) ON CONFLICT(kind,event_id) DO UPDATE
            SET observed_at=EXCLUDED.observed_at,expires_at=EXCLUDED.expires_at,
                revision=EXCLUDED.revision,facts=EXCLUDED.facts
            WHERE EXCLUDED.observed_at > sgo_event_evidence.observed_at''',
            (event_id, at, expiry, hashed(facts), Jsonb(facts)))
