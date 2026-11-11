"""Bounded current SGO bookmaker observations, independent of execution venues.

No settlement authority or complete-scope absence is inferred. All updates must
share the calling source-ingress transaction with the product current rows.
"""
from decimal import Decimal
from datetime import timedelta
import re
from psycopg.types.json import Jsonb

from app.storage.current_rows import LOCK
from app.storage.store import encoded, exact_time, hashed, stamp

MAX_ROWS = 16000
MAX_BYTES = 8 * 1024 * 1024
MAX_CURRENT_ROWS = 250000
PRUNE_BATCH = 10000


def prepare_page(page):
    """Capture all bookmaker originals, including books not executable in Predict."""
    if not isinstance(page.receipt_sha256, str) or not re.fullmatch('[0-9a-f]{64}', page.receipt_sha256):
        raise ValueError('sgo reference receipt identity')
    events = {event['event_id']: event for event in page.events}
    if len(page.quotes) > MAX_ROWS or len(events) != len(page.events):
        raise ValueError('sgo reference page capacity or identity')
    rows, ids = [], set()
    for quote in page.quotes:
        event = events[quote['event_id']]
        line = quote['line']
        if line is not None:
            value = Decimal(line)
            line = '0' if value == 0 else str(value.normalize())
        identity = ['sportsgameodds', quote['event_id'], quote['venue'], quote['odd_id'], line]
        row_id = hashed(identity)
        if row_id in ids:
            raise ValueError('ambiguous repeated SGO book/side/line')
        ids.add(row_id)
        facts = dict(provider='sportsgameodds', event_id=quote['event_id'],
                     aliases=event['aliases'], league=quote['league'], teams=event['teams'],
                     starts_at=event['starts_at'], phase=quote['phase'], event_status=event['status'],
                     period=quote['period'], market=quote['market'], side=quote['side'],
                     odd_id=quote['odd_id'], opposing_odd_id=quote['opposing_odd_id'],
                     venue=quote['venue'], line=quote['line'], price_american=quote['price_american'],
                     available=quote['available'], provider_available=quote['provider_available'],
                     unavailable_reason=quote['unavailable_reason'], source_at=quote['source_at'],
                     source_at_original=quote['source_at_original'], received_at=quote['received_at'],
                     receipt_sha256=page.receipt_sha256, fair=quote['fair'], settlement='unverified')
        revision = hashed({k: v for k, v in facts.items() if k not in ('received_at', 'receipt_sha256')})
        rows.append(dict(id=row_id, event_id=quote['event_id'], bookmaker_id=quote['venue'],
                         source_order=str(exact_time(quote['source_at'])) if quote['source_at'] else None,
                         received_order=str(exact_time(quote['received_at'])),
                         expires_at=max(stamp(event['starts_at']) + timedelta(days=14),
                                        stamp(quote['received_at']) + timedelta(days=1)).isoformat(),
                         revision=revision, facts=facts))
    if len(encoded(rows)) > MAX_BYTES:
        raise ValueError('sgo reference page byte capacity')
    return rows


def upsert_rows(db, rows):
    """Order and write rows in the caller's transaction, without any withdrawal."""
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or len(encoded(rows)) > MAX_BYTES:
        raise ValueError('sgo reference page capacity')
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'event_id', 'bookmaker_id', 'source_order', 'received_order', 'expires_at', 'revision', 'facts'}:
            raise ValueError('sgo reference row shape')
        facts = row['facts']
        if not isinstance(facts, dict) or facts.get('provider') != 'sportsgameodds' or facts.get('settlement') != 'unverified':
            raise ValueError('sgo reference provenance')
        if facts.get('event_id') != row['event_id'] or facts.get('venue') != row['bookmaker_id']:
            raise ValueError('sgo reference identity')
        if type(facts.get('available')) is not bool or type(facts.get('provider_available')) is not bool:
            raise ValueError('sgo reference availability')
        if not isinstance(facts.get('receipt_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', facts['receipt_sha256']):
            raise ValueError('sgo reference receipt')
        line = facts.get('line')
        if line is not None:
            value = Decimal(line)
            line = '0' if value == 0 else str(value.normalize())
        if row['id'] != hashed(['sportsgameodds', row['event_id'], row['bookmaker_id'], facts['odd_id'], line]):
            raise ValueError('sgo reference identity')
        if row['id'] in identities:
            raise ValueError('sgo duplicate reference')
        identities.add(row['id'])
        if row['revision'] != hashed({k: v for k, v in facts.items() if k not in ('received_at', 'receipt_sha256')}):
            raise ValueError('sgo reference revision')
        if row['source_order'] != (str(exact_time(facts['source_at'])) if facts['source_at'] else None) or row['received_order'] != str(exact_time(facts['received_at'])):
            raise ValueError('sgo reference clocks')
        expected_expiry = max(stamp(facts['starts_at']) + timedelta(days=14), stamp(facts['received_at']) + timedelta(days=1))
        if stamp(row['expires_at']) != expected_expiry:
            raise ValueError('sgo reference retention')
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    existing = db.execute('SELECT count(*) AS n FROM current_sgo_reference WHERE id=ANY(%s)', (list(identities),)).fetchone()['n']
    total = db.execute('SELECT count(*) AS n FROM current_sgo_reference').fetchone()['n']
    if total + len(rows) - existing > MAX_CURRENT_ROWS:
        raise ValueError('sgo reference storage capacity')
    changed = 0
    for row in rows:
        # Unknown clocks cannot supersede a timestamped observation. A later
        # receipt of an unchanged quote does not refresh it or rewrite the row.
        # At identical provider clocks, an explicit unavailable observation
        # can conservatively withdraw usability; conflicting usable prices do
        # not overwrite one another without a newer source clock.
        result = db.execute('''INSERT INTO current_sgo_reference
            (id,event_id,bookmaker_id,source_order,received_order,expires_at,revision,facts)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              source_order=CASE WHEN current_sgo_reference.revision=EXCLUDED.revision THEN current_sgo_reference.source_order ELSE EXCLUDED.source_order END,
              received_order=CASE WHEN current_sgo_reference.revision=EXCLUDED.revision THEN current_sgo_reference.received_order ELSE EXCLUDED.received_order END,
              expires_at=EXCLUDED.expires_at,
              revision=EXCLUDED.revision,
              facts=CASE WHEN current_sgo_reference.revision=EXCLUDED.revision THEN current_sgo_reference.facts ELSE EXCLUDED.facts END
            WHERE (current_sgo_reference.revision<>EXCLUDED.revision AND (
              (EXCLUDED.source_order IS NOT NULL AND current_sgo_reference.source_order IS NULL)
              OR (EXCLUDED.source_order > current_sgo_reference.source_order)
              OR (EXCLUDED.source_order IS NULL AND current_sgo_reference.source_order IS NULL
                  AND EXCLUDED.received_order > current_sgo_reference.received_order)
              OR (EXCLUDED.source_order = current_sgo_reference.source_order
                  AND EXCLUDED.received_order >= current_sgo_reference.received_order
                  AND EXCLUDED.facts->>'available'='false'
                  AND current_sgo_reference.facts->>'available'='true')
            )) OR (current_sgo_reference.revision=EXCLUDED.revision
              AND EXCLUDED.received_order >= current_sgo_reference.received_order
              AND EXCLUDED.expires_at > current_sgo_reference.expires_at
              AND current_sgo_reference.expires_at < to_timestamp(EXCLUDED.received_order) + interval '2 days')''', (row['id'], row['event_id'], row['bookmaker_id'], row['source_order'],
                    row['received_order'], row['expires_at'], row['revision'], Jsonb(row['facts'])))
        changed += result.rowcount
    return changed


def read_event(db, event_id, *, limit=MAX_ROWS):
    """Read one bounded event within the caller's coherent snapshot transaction."""
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise ValueError('sgo event identity')
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError('sgo read capacity')
    rows = db.execute('SELECT id,revision,facts FROM current_sgo_reference WHERE event_id=%s ORDER BY id LIMIT %s',
                      (event_id, limit + 1)).fetchall()
    if len(rows) > limit:
        raise ValueError('sgo event exceeds read capacity')
    return rows


def prune(db, *, at, limit=PRUNE_BATCH):
    """Remove only expired current reference facts; never touches audit or controls."""
    if type(limit) is not int or not 1 <= limit <= PRUNE_BATCH:
        raise ValueError('sgo prune capacity')
    stamp(at)
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    return db.execute('''DELETE FROM current_sgo_reference WHERE id IN
        (SELECT id FROM current_sgo_reference WHERE expires_at < %s
         ORDER BY expires_at,id LIMIT %s)''', (at, limit)).rowcount


MAX_FRAMES = 25000
MAX_FRAME_TOTAL_BYTES = 128 * 1024 * 1024


def prepare_frames(page, rows):
    """Bind row revisions co-observed in each event's actual received page."""
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or len(encoded(rows)) > MAX_BYTES:
        raise ValueError('sgo frame page capacity')
    expected_rows = prepare_page(page)
    if {(r['id'], r['revision']) for r in rows} != {(r['id'], r['revision']) for r in expected_rows} or len(rows) != len(expected_rows):
        raise ValueError('sgo frame observations incomplete')
    events = {event['event_id']: event for event in page.events}
    if len(events) != len(page.events) or len(events) > 100:
        raise ValueError('sgo frame event scope')
    members = {event_id: [] for event_id in events}
    seen = set()
    for row in rows:
        if row['event_id'] not in events or row['facts']['receipt_sha256'] != page.receipt_sha256 or row['id'] in seen:
            raise ValueError('sgo frame input identity')
        seen.add(row['id'])
        members[row['event_id']].append([row['id'], row['revision']])
    frames = []
    for event_id, event in events.items():
        facts = dict(provider='sportsgameodds', event_id=event_id,
                     receipt_sha256=page.receipt_sha256, received_at=event['received_at'],
                     starts_at=event['starts_at'], members=sorted(members[event_id]))
        frames.append(dict(event_id=event_id, received_order=str(exact_time(event['received_at'])),
                           expires_at=max(stamp(event['starts_at']) + timedelta(days=14),
                                          stamp(event['received_at']) + timedelta(days=1)).isoformat(),
                           facts=facts))
    if len(encoded(frames)) > MAX_BYTES:
        raise ValueError('sgo frame page byte capacity')
    return frames


def upsert_frames(db, frames):
    """Write only newer page witnesses under the source-ingress transaction."""
    if not isinstance(frames, list) or len(frames) > 100 or len(encoded(frames)) > MAX_BYTES:
        raise ValueError('sgo frame page capacity')
    ids = set()
    for frame in frames:
        if not isinstance(frame, dict) or set(frame) != {'event_id', 'received_order', 'expires_at', 'facts'}:
            raise ValueError('sgo frame shape')
        facts = frame['facts']
        if not isinstance(facts, dict) or set(facts) != {'provider', 'event_id', 'receipt_sha256', 'received_at', 'starts_at', 'members'}:
            raise ValueError('sgo frame facts')
        if (facts['provider'] != 'sportsgameodds' or facts['event_id'] != frame['event_id']
                or not isinstance(frame['event_id'], str) or not frame['event_id'] or len(frame['event_id']) > 256
                or frame['event_id'] in ids):
            raise ValueError('sgo frame identity')
        ids.add(frame['event_id'])
        if not isinstance(facts['receipt_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', facts['receipt_sha256']):
            raise ValueError('sgo frame receipt')
        if not isinstance(facts['members'], list) or len(facts['members']) > MAX_ROWS:
            raise ValueError('sgo frame members')
        if any(not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(x, str) or not re.fullmatch('[0-9a-f]{64}', x) for x in pair) for pair in facts['members']):
            raise ValueError('sgo frame members')
        if len({pair[0] for pair in facts['members']}) != len(facts['members']):
            raise ValueError('sgo duplicate frame member')
        if frame['received_order'] != str(exact_time(facts['received_at'])):
            raise ValueError('sgo frame clock')
        expiry = max(stamp(facts['starts_at']) + timedelta(days=14), stamp(facts['received_at']) + timedelta(days=1))
        if stamp(frame['expires_at']) != expiry:
            raise ValueError('sgo frame retention')
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    existing = db.execute('SELECT count(*) AS n,COALESCE(sum(payload_bytes),0) AS bytes FROM current_sgo_event_frame WHERE event_id=ANY(%s)', (list(ids),)).fetchone()
    total = db.execute('SELECT count(*) AS n,COALESCE(sum(payload_bytes),0) AS bytes FROM current_sgo_event_frame').fetchone()
    incoming_bytes = sum(len(encoded(frame['facts'])) for frame in frames)
    if total['n'] + len(frames) - existing['n'] > MAX_FRAMES or total['bytes'] + incoming_bytes - existing['bytes'] > MAX_FRAME_TOTAL_BYTES:
        raise ValueError('sgo frame storage capacity')
    changed = 0
    for frame in frames:
        result = db.execute('''INSERT INTO current_sgo_event_frame (event_id,received_order,expires_at,payload_bytes,facts)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO UPDATE
            SET received_order=EXCLUDED.received_order,expires_at=EXCLUDED.expires_at,payload_bytes=EXCLUDED.payload_bytes,facts=EXCLUDED.facts
            WHERE EXCLUDED.received_order > current_sgo_event_frame.received_order''',
            (frame['event_id'], frame['received_order'], frame['expires_at'], len(encoded(frame['facts'])), Jsonb(frame['facts'])))
        changed += result.rowcount
    return changed


def read_event_frame(db, event_id):
    """Read latest frame in the caller's repeatable-read reference snapshot."""
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise ValueError('sgo event identity')
    return db.execute('SELECT facts FROM current_sgo_event_frame WHERE event_id=%s', (event_id,)).fetchone()


def prune_frames(db, *, at, limit=PRUNE_BATCH):
    if type(limit) is not int or not 1 <= limit <= PRUNE_BATCH:
        raise ValueError('sgo frame prune capacity')
    stamp(at)
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    return db.execute('''DELETE FROM current_sgo_event_frame WHERE event_id IN
        (SELECT event_id FROM current_sgo_event_frame WHERE expires_at < %s
         ORDER BY expires_at,event_id LIMIT %s)''', (at, limit)).rowcount
