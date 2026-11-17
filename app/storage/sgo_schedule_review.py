"""Exact occurrence corrections from the host school and linked native event."""
import json
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from psycopg.types.json import Jsonb

from .store import exact_time, hashed, stamp

EVIDENCE = Path(__file__).resolve().parents[1] / 'fixtures/sgo-reviewed-occurrences-20261116.json'


@lru_cache(maxsize=1)
def reviews():
    return json.loads(EVIDENCE.read_bytes())


def review(event_id, league, *, at):
    document = reviews()
    entry = document['events'].get(event_id)
    if entry and entry['league'] == league and stamp(document['reviewed_at']) <= stamp(at):
        return entry
    return None


def correct(event, *, at):
    """Keep the provider's own timestamp, revision and receipt with the correction."""
    from .schedule_metadata import witness

    if not event or event.get('schedule_conflict'):
        return event
    entry = review(event['id'], event['competition'], at=at)
    raw = witness(event)
    if not entry or not raw or raw.get('reviewed_correction'):
        return event
    expected = {entry['teams'][role]['name']: event[role] for role in ('home', 'away')}
    if (raw['authority'] != ['sportsgameodds', 'event', event['id']]
            or expected != event.get('participants')
            or entry['novig_event_id'] != (event.get('shared_provider_ids') or {}).get('novig_event')):
        return event
    start = stamp(event['scheduled_start'])
    official = stamp(entry['official_start'])
    receipts = {p['body_sha256'] for p in raw['proofs']}
    if start == official or not any(start == stamp(x['start']) and x['body_sha256'] in receipts
                                    for x in entry['source_observations']):
        return event
    correction = dict(version=reviews()['version'], effective_at=reviews()['reviewed_at'],
                      school_url=entry['school_url'], native_event_id=entry['novig_event_id'],
                      native_event_receipt=entry['native_event_receipt'], original=raw)
    metadata = dict(raw, start=entry['official_start'], reviewed_correction=correction)
    metadata.pop('revision')
    return dict(event, scheduled_start=metadata['start'],
                schedule_metadata=dict(metadata, revision=hashed(metadata)))


def frame_start(event_id, league, teams, raw_start, receipt, *, at):
    """Return the reviewed schedule for a matching frame without changing its facts."""
    entry = review(event_id, league, at=at)
    if (entry and teams == entry['teams']
            and any(stamp(raw_start) == stamp(x['start']) and receipt == x['body_sha256']
                    for x in entry['source_observations'])):
        return entry['official_start']
    return raw_start


def canonical_roles(event_id, occurrence, *, at):
    league, start, home, away = occurrence
    entry = review(event_id, league, at=at)
    if not entry or start != stamp(entry['official_start']):
        return occurrence
    teams = entry['canonical_roles']
    if all(value in (teams[role], f'sportsgameodds:{league}:{event_id}:{role}')
           for role, value in (('home', home), ('away', away))):
        return league, start, teams['home'], teams['away']
    return occurrence


def reconcile_stored(db, *, at):
    """Apply the review to rows that arrived before the review was available."""
    from .current_rows import LOCK

    ids = list(reviews()['events'])
    with db.transaction():
        candidates = db.execute("""
            SELECT id FROM current_event WHERE provider='sportsgameodds'
              AND native_event_id=ANY(%s) AND scheduled_start::timestamptz > %s
              AND facts#>>'{schedule_metadata,proofs,0,body_sha256}'=ANY(%s)
              AND NOT jsonb_exists(facts->'schedule_metadata','reviewed_correction')
            """, (ids, stamp(at) - timedelta(hours=24),
                  [x['body_sha256'] for e in reviews()['events'].values() for x in e['source_observations']])
        ).fetchall()
        if not candidates:
            return
        db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        for row in db.execute('SELECT id,facts FROM current_event WHERE id=ANY(%s)',
                              ([r['id'] for r in candidates],)).fetchall():
            event = correct(row['facts'], at=at)
            if event is row['facts']:
                continue
            start = event['scheduled_start']
            db.execute("""UPDATE current_event SET scheduled_start=%s, facts=%s, revision=%s,
                          expires_order=greatest(expires_order,%s) WHERE id=%s""",
                       (start, Jsonb(event), hashed(event), exact_time(start), row['id']))
