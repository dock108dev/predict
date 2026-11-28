"""Append-only public depth, linked to the paper decision's exact schedule."""
from datetime import timezone
from email.utils import parsedate_to_datetime
from fractions import Fraction
from hashlib import sha256

from psycopg.types.json import Jsonb

from app.storage.store import encoded, exact_time, hashed, stamp

VERSION = 'experiment-public-depth-1'
POLICY = 'public-book-win25-1'
ALL_SPORTS_POLICY = 'public-book-win25-2'
# Canonical UTF-8 JSON bytes, shared with collector staging and charged to
# research retention. Broad inventories carry identities for every side.
MAX_BYTES = 8 * 1024 * 1024


def clock(value):
    return stamp(value).astimezone(timezone.utc).isoformat()


def offer_key(record):
    """Identify a quoted side across pre-decision discovery and the late snapshot."""
    quote, market, selection = (record[k] for k in ('quote', 'market_identity', 'selection'))
    source = quote['source']
    line = selection.get('signed_line')
    link = (record.get('comparison_source_metadata') or {}).get('bookmaker_market_link')
    if quote['venue'] == 'novig':
        # The full native inventory is anchored by the aggregate event link.
        # Any explicit outcome link is checked against the resolved side.
        link = (record['event'].get('shared_provider_ids') or {}).get('novig_event')
    return hashed([quote['venue'], source['provider'], source['native_event_id'],
        source['native_outcome_id'], market['family'], market['period'],
        selection.get('predicate'), selection.get('participant'),
        str(Fraction(line)) if line is not None else None, link])


def receipt_for(offer, observations):
    record = offer['record']
    receipt = observations.get(offer_key(record))
    if not receipt or receipt.get('venue') != 'novig' or receipt.get('reason'):
        return receipt
    from app.comparison.sgo_native_binding import event_link_id, outcome_link_id

    link = (record.get('comparison_source_metadata') or {}).get('bookmaker_market_link')
    selected = outcome_link_id(link)
    if receipt.get('explicit_link_required') and selected != receipt.get('outcome_id'):
        return dict(receipt, reason='unmatched_ambiguous_native_contract')
    if link and (selected != receipt.get('outcome_id') if selected
                 else event_link_id(link) != receipt.get('event_id')):
        return dict(receipt, reason='unmatched_native_outcome_link')
    return receipt


def _bundle(row):
    if row is None:
        return None
    payload = row['payload']
    if hashed(payload) != row['id'] or len(encoded(payload)) != row['payload_bytes']:
        raise ValueError('experiment_depth_integrity')
    return dict(payload, id=row['id'])


def read(db, game_id, schedule_id, target_at, *, kind='decision'):
    row = db.execute('''SELECT id,payload,payload_bytes FROM public.ev_experiment_depth
        WHERE (game_id,schedule_id,target_at,kind)=(%s,%s,%s,%s)''',
        (game_id, schedule_id, stamp(target_at), kind)).fetchone()
    return _bundle(row)


def input_ids(db, task_refs):
    tasks = list(task_refs)
    if not tasks:
        return {}
    games, schedules, targets = zip(*tasks, strict=True)
    return {row['game_id']: row['id'] for row in db.execute('''
        SELECT d.game_id,d.id FROM unnest(%s::text[],%s::text[],%s::timestamptz[])
            AS t(game_id,schedule_id,target_at)
        JOIN public.ev_experiment_depth d USING(game_id,schedule_id,target_at)
        WHERE d.kind='decision'
        ''', (list(games), list(schedules), list(map(stamp, targets))))}


def read_ids(db, identities):
    identities = sorted(set(identities))
    if not identities:
        return {}
    rows = db.execute('''SELECT id,payload,payload_bytes FROM public.ev_experiment_depth
        WHERE id=ANY(%s)''', (identities,)).fetchall()
    if len(rows) != len(identities):
        raise ValueError('experiment_depth_receipt_missing')
    return {row['id']: _bundle(row) for row in rows}


def followups(db, original_ids):
    originals = sorted(set(original_ids))
    if not originals:
        return {}
    return {row['origin_id']: _bundle(row) for row in db.execute('''
        SELECT id,origin_id,payload,payload_bytes FROM public.ev_experiment_depth
        WHERE kind='followup' AND origin_id=ANY(%s)''', (originals,))}


def _metrics(http_receipts, identity_receipts, cutoff, observations):
    ages, latency = [], []
    for receipt in http_receipts.values():
        received = stamp(receipt['received_at'])
        latency.append((received - stamp(receipt['requested_at'])).total_seconds() * 1000)
        try:
            age = receipt.get('age', (receipt.get('headers') or {}).get('age', '0'))
            if not isinstance(age, str) or not age.isascii() or not age.isdecimal() or len(age) > 10:
                continue
            date = parsedate_to_datetime(receipt['date'])
            ages.append(max(int(age) + (cutoff - received).total_seconds(), (cutoff - date).total_seconds()))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return dict(public_requests=len(http_receipts),
        preparation_requests=sum('requested_at' in evidence for evidence in identity_receipts.values()),
        max_response_age_seconds=round(max(ages), 3) if ages else None,
        max_request_latency_ms=round(max(latency), 3) if latency else None,
        cache_reuse_sides=sum(r.get('reason') == 'followup_cache_reuse' for r in observations.values()))


def _evidence_time(value):
    return exact_time(value if isinstance(value, str) else value.isoformat())


def validate(payload):
    target, known, cutoff = (exact_time(payload[key]) for key in ('target_at', 'known_at', 'cutoff_at'))
    kind, origin_id = payload['kind'], payload['origin_id']
    if (known > cutoff or kind == 'decision' and (cutoff != target or origin_id is not None)
            or kind == 'followup' and (not origin_id or not target < known <= cutoff)
            or kind not in ('decision', 'followup')):
        raise ValueError('experiment_depth_cutoff')
    # Only causally available input is admitted. An HTTP Date or sequence
    # number is not a receipt clock.
    http_receipts, identity_receipts = payload['http_receipts'], payload['identity_receipts']
    for receipt in http_receipts.values():
        if not _evidence_time(receipt['requested_at']) <= _evidence_time(receipt['received_at']) <= known:
            raise ValueError('experiment_depth_receipt_clock')
    for receipt in identity_receipts.values():
        received = _evidence_time(receipt.get('received_at') or receipt['observed_at'])
        if received > known or 'requested_at' in receipt and _evidence_time(receipt['requested_at']) > received:
            raise ValueError('experiment_depth_receipt_clock')
    for observation in payload['observations'].values():
        received = observation.get('received_at')
        if received and _evidence_time(received) > known:
            raise ValueError('experiment_depth_receipt_clock')
        if (any(ref not in http_receipts for ref in observation['receipt_refs'])
                or any(ref not in identity_receipts for ref in observation['identity_receipt_refs'])):
            raise ValueError('experiment_depth_receipt_reference')


def normalize(task, *, known_at, observations, reason=None, kind='decision', cutoff_at=None,
              origin_id=None, source_gaps=None, preparation=()):
    """Freeze the same evidence for staging and eventual publication."""
    game_id, schedule_id = task['game_id'], task['schedule_id']
    target_at = clock(task['target_at'])
    known_at, cutoff_at = clock(known_at), clock(cutoff_at or target_at)
    http_receipts, identity_receipts, normalized = {}, {}, {}
    for receipt in preparation:
        if not _evidence_time(receipt['requested_at']) <= _evidence_time(receipt['received_at']) <= exact_time(known_at):
            raise ValueError('experiment_depth_receipt_clock')
        identity_receipts[hashed(receipt)] = receipt
    for key, observation in observations.items():
        refs, identity_refs = [], []
        for receipt in observation.get('receipts', ()):
            ref = hashed(receipt)
            http_receipts[ref] = receipt
            refs.append(ref)
        for receipt in observation.get('identity_receipts', ()):
            ref = hashed(receipt)
            identity_receipts[ref] = receipt
            identity_refs.append(ref)
        normalized[key] = dict({k: v for k, v in observation.items() if k not in ('receipts', 'identity_receipts')},
                               receipt_refs=refs, identity_receipt_refs=identity_refs)
    payload = dict(version=VERSION, game_id=game_id, schedule_id=schedule_id,
        target_at=target_at, known_at=known_at, cutoff_at=cutoff_at, kind=kind,
        observations=normalized, http_receipts=http_receipts, identity_receipts=identity_receipts, reason=reason,
        source_gaps=source_gaps or {}, origin_id=origin_id)
    validate(payload)
    payload['metrics'] = _metrics(http_receipts, identity_receipts, stamp(cutoff_at), observations)
    return payload


def save(db, task, *, known_at, observations, reason=None, kind='decision', cutoff_at=None,
         origin_id=None, source_gaps=None, preparation=(), protect_checkpoint=False):
    payload = normalize(task, known_at=known_at, observations=observations, reason=reason, kind=kind,
        cutoff_at=cutoff_at, origin_id=origin_id, source_gaps=source_gaps, preparation=preparation)
    return publish(db, payload, protect_checkpoint=protect_checkpoint)


def publish(db, payload, *, protect_checkpoint=False):
    """Commit validated evidence once, or return None when its schedule changed."""
    from app.research import experiment, records

    game_id, schedule_id, target_at, kind, origin_id = (payload[key] for key in (
        'game_id', 'schedule_id', 'target_at', 'kind', 'origin_id'))
    target, known, cutoff = (stamp(payload[key]) for key in ('target_at', 'known_at', 'cutoff_at'))
    body = encoded(payload)
    if len(body) > MAX_BYTES:
        raise ValueError('experiment_depth_retention_limit')
    identity = sha256(body).hexdigest()
    with db.transaction():
        for lock in (records.CURRENT_LOCK, records.LOCK):
            if not db.execute('SELECT pg_try_advisory_xact_lock(%s) held', (lock,)).fetchone()['held']:
                raise BlockingIOError('experiment_depth_writer_busy')
        if protect_checkpoint:
            from app.collection.mens_d1_jobs import _late_capture_due

            if _late_capture_due(db, experiment._dbclock(db)):
                raise BlockingIOError('protected_tminus10_capture_due')
        original = read(db, game_id, schedule_id, target_at, kind=kind)
        if original:
            return original
        if kind == 'followup':
            original = read(db, game_id, schedule_id, target_at)
            if not original or original['id'] != origin_id:
                raise ValueError('experiment_depth_followup_origin')
        admitted = db.execute('''SELECT 1 FROM public.ev_experiment_game g
            JOIN public.ev_experiment_task t ON t.game_id=g.id
            WHERE t.checkpoint='late' AND g.state<>'cancelled'
              AND (g.id,g.schedule_id,t.schedule_id,t.target_at)=(%s,%s,%s,%s)''',
            (game_id, schedule_id, schedule_id, target)).fetchone()
        if not admitted:
            return None
        experiment._admit(db, len(body))
        db.execute('''INSERT INTO public.ev_experiment_depth
            (id,game_id,schedule_id,target_at,kind,origin_id,cutoff_at,known_at,payload_bytes,payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (identity, game_id, schedule_id, target, kind, origin_id, cutoff, known, len(body),
             Jsonb(body, dumps=bytes)))
    return dict(payload, id=identity)
