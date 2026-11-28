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
OFFICIAL_SHADOW_POLICY = 'official-native-book-win25-shadow-1'
SHADOW_KIND = 'official_shadow'
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


def shadow_inputs(db, original_ids):
    originals = sorted(set(original_ids))
    if not originals:
        return {}
    return {row['original_id']: {field: row[field] for field in ('id', 'checkpoint_id', 'reason')}
            for row in db.execute('''SELECT original_id,id,checkpoint_id,reason
                FROM public.ev_experiment_depth_shadow WHERE original_id=ANY(%s)''', (originals,))}


def _shadow_bundle(row):
    return dict(_bundle(row), checkpoint_id=row['checkpoint_id'], recorded_at=clock(row['recorded_at']))


def read_shadow_ids(db, identities):
    identities = sorted(set(identities))
    if not identities:
        return {}
    rows = db.execute('''SELECT id,payload,payload_bytes,checkpoint_id,recorded_at
        FROM public.ev_experiment_depth_shadow WHERE id=ANY(%s)''', (identities,)).fetchall()
    if len(rows) != len(identities):
        raise ValueError('experiment_depth_shadow_missing')
    return {row['id']: _shadow_bundle(row) for row in rows}


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
    disposition = kind == SHADOW_KIND and payload['reason'] is not None
    if (known > cutoff and not disposition or kind == 'decision' and (cutoff != target or origin_id is not None)
            or kind == 'followup' and (not origin_id or not target < known <= cutoff)
            or kind == SHADOW_KIND and (not origin_id or cutoff != target or payload['observations'])
            or kind not in ('decision', 'followup', SHADOW_KIND)):
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
    observations = list(payload['observations'].values())
    shadow = payload.get('official_shadow')
    if shadow is not None:
        if (kind not in ('decision', SHADOW_KIND) or shadow['policy'] != OFFICIAL_SHADOW_POLICY
                or disposition and (shadow['candidates'] or http_receipts or identity_receipts)):
            raise ValueError('experiment_depth_shadow_policy')
        for cid, evidence in shadow['candidates'].items():
            from app.comparison.execution_contract import expected

            observations.append(evidence['book'])
            record, book, link = evidence['record'], evidence['book'], evidence['game_link']
            source = record['quote']['source']
            if (expected(record)['contract_id'] != cid or source['provider'] != book['venue']
                    or any(source['native_' + field] != book[field]
                           for field in ('event_id', 'market_id', 'outcome_id'))
                    or not evidence.get('reason') and (link['status'] != 'matched'
                        or _evidence_time(link['sgo_start']) != target + 600)):
                raise ValueError('experiment_depth_shadow_identity')
            for field in ('catalog_committed_at', 'book_committed_at'):
                if evidence[field] and _evidence_time(evidence[field]) > known:
                    raise ValueError('experiment_depth_receipt_clock')
            reference = evidence.get('reference') or {}
            for quote in reference.get('required_input_prices') or reference.get('prices', ()):
                if not _evidence_time(quote['source_at']) <= _evidence_time(quote['received_at']) <= known:
                    raise ValueError('experiment_depth_receipt_clock')
            if any(_evidence_time(quote['sgo_received_at']) > known for quote in evidence.get('sgo_comparison', ())):
                raise ValueError('experiment_depth_receipt_clock')
    for observation in observations:
        received = observation.get('received_at')
        if received and _evidence_time(received) > known:
            raise ValueError('experiment_depth_receipt_clock')
        if (any(ref not in http_receipts for ref in observation['receipt_refs'])
                or any(ref not in identity_receipts for ref in observation['identity_receipt_refs'])):
            raise ValueError('experiment_depth_receipt_reference')


def normalize(task, *, known_at, observations, reason=None, kind='decision', cutoff_at=None,
              origin_id=None, source_gaps=None, preparation=(), official_shadow=None):
    """Freeze the same evidence for staging and eventual publication."""
    game_id, schedule_id = task['game_id'], task['schedule_id']
    target_at = clock(task['target_at'])
    known_at, cutoff_at = clock(known_at), clock(cutoff_at or target_at)
    http_receipts, identity_receipts = {}, {}
    for receipt in preparation:
        if not _evidence_time(receipt['requested_at']) <= _evidence_time(receipt['received_at']) <= exact_time(known_at):
            raise ValueError('experiment_depth_receipt_clock')
        identity_receipts[hashed(receipt)] = receipt
    def normalize_book(observation, *, shadow=False):
        refs, identity_refs = [], []
        for receipt in observation.get('receipts', ()):
            ref = hashed(receipt)
            if shadow and 'requested_at' not in receipt:
                identity_receipts[ref] = receipt
                identity_refs.append(ref)
            else:
                http_receipts[ref] = receipt
                refs.append(ref)
        for receipt in observation.get('identity_receipts', ()):
            ref = hashed(receipt)
            identity_receipts[ref] = receipt
            identity_refs.append(ref)
        return dict({k: v for k, v in observation.items() if k not in ('receipts', 'identity_receipts')},
                    receipt_refs=refs, identity_receipt_refs=identity_refs)

    payload = dict(version=VERSION, game_id=game_id, schedule_id=schedule_id,
        target_at=target_at, known_at=known_at, cutoff_at=cutoff_at, kind=kind,
        observations={key: normalize_book(book) for key, book in observations.items()},
        http_receipts=http_receipts, identity_receipts=identity_receipts, reason=reason,
        source_gaps=source_gaps or {}, origin_id=origin_id)
    payload['metrics'] = _metrics(http_receipts, identity_receipts, stamp(cutoff_at), observations)
    if official_shadow is not None:
        payload['official_shadow'] = dict(official_shadow, policy=OFFICIAL_SHADOW_POLICY,
            candidates={key: dict(candidate, book=normalize_book(candidate['book'], shadow=True))
                        for key, candidate in official_shadow['candidates'].items()})
    validate(payload)
    return payload


def normalize_shadow(task, *, origin_id, known_at, evidence=None, reason=None):
    if reason:
        evidence = dict(candidates={}, source_gaps={'scope': reason})
    if evidence is None:
        raise ValueError('experiment_depth_shadow_evidence_missing')
    return normalize(task, known_at=known_at, observations={}, kind=SHADOW_KIND, origin_id=origin_id,
                     reason=reason, official_shadow=evidence)


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


def publish_shadow(db, payload, *, protect_checkpoint=False):
    """Admit the optional envelope only after its exact original commits."""
    from app.research import experiment, records

    if payload['kind'] != SHADOW_KIND:
        raise ValueError('experiment_depth_shadow_policy')
    validate(payload)
    body = encoded(payload)
    if len(body) > MAX_BYTES:
        raise ValueError('experiment_depth_shadow_capacity')
    origin = payload['origin_id']
    game, schedule, target = payload['game_id'], payload['schedule_id'], stamp(payload['target_at'])
    with db.transaction():
        for lock in (records.CURRENT_LOCK, records.LOCK):
            if not db.execute('SELECT pg_try_advisory_xact_lock(%s) held', (lock,)).fetchone()['held']:
                raise BlockingIOError('experiment_depth_writer_busy')
        if protect_checkpoint:
            from app.collection.mens_d1_jobs import _late_capture_due

            if _late_capture_due(db, experiment._dbclock(db)):
                raise BlockingIOError('protected_tminus10_capture_due')
        original = db.execute('''SELECT id FROM public.ev_experiment_depth
            WHERE (game_id,schedule_id,target_at,kind)=(%s,%s,%s,'decision')''',
            (game, schedule, target)).fetchone()
        task = db.execute('''SELECT t.result_id,t.state FROM public.ev_experiment_task t
            JOIN public.ev_experiment_game g ON g.id=t.game_id AND g.schedule_id=t.schedule_id
            WHERE (t.game_id,t.schedule_id,t.target_at,t.checkpoint)=(%s,%s,%s,'late') AND g.state<>'cancelled' ''',
            (game, schedule, target)).fetchone()
        if original is None:
            if task:
                raise BlockingIOError('experiment_depth_shadow_original_pending')
            return None
        if original['id'] != origin:
            return None
        existing = db.execute('''SELECT id,payload,payload_bytes,checkpoint_id,recorded_at
            FROM public.ev_experiment_depth_shadow WHERE original_id=%s''', (origin,)).fetchone()
        if existing:
            return _shadow_bundle(existing)
        if task and task['state'] in ('pending', 'claimed'):
            raise BlockingIOError('experiment_depth_shadow_checkpoint_pending')
        checkpoint = task['result_id'] if task and task['state'] == 'captured' else None
        if payload['reason']:
            if len(body) > records.DISPOSITION_SLOT_BYTES:
                raise ValueError('experiment_depth_shadow_disposition_capacity')
            experiment._storage_runway(db, len(body))
        else:
            used = db.execute('''SELECT coalesce(sum(payload_bytes),0) n FROM public.ev_experiment_depth_shadow
                WHERE reason IS NULL''').fetchone()['n']
            if used + len(body) > records.OBSERVATION_BYTE_CAP:
                raise ValueError('experiment_depth_shadow_capacity')
            experiment._admit(db, len(body))
        identity = sha256(body).hexdigest()
        row = db.execute('''INSERT INTO public.ev_experiment_depth_shadow
            (id,original_id,checkpoint_id,game_id,schedule_id,target_at,known_at,payload_bytes,reason,payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING recorded_at''',
            (identity, origin, checkpoint, game, schedule, target,
             stamp(payload['known_at']), len(body), payload['reason'], Jsonb(body, dumps=bytes))).fetchone()
    return dict(payload, id=identity, checkpoint_id=checkpoint, recorded_at=clock(row['recorded_at']))
