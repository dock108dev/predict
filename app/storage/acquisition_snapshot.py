"""Durable logical pulls, accepted page membership and atomic scope publication.

No fetch, retry, eviction or reconstruction from nearby timestamps. An event
object returned in a closed explicit-ID request proves returned coverage, not
that every requested book quotes every line or that omissions are withdrawals.
"""
from dataclasses import dataclass
from uuid import uuid4
from hashlib import sha256
import json
import zlib
from psycopg.types.json import Jsonb

from app.collection.sportsgameodds_transport import ODD_IDS
from app.comparison.reference_scope import REQUEST_BOOKS
from .store import encoded, stamp, hashed

FAMILIES = ('moneyline', 'spread', 'total')


def _admit(db, size):
    from app.research.experiment import _admit as admit, _lock
    _lock(db)
    admit(db, size)


def requested_families(params):
    odds = set(params.get('oddID','').split(','))
    return tuple(family for family,token in (('moneyline','-ml-'),('spread','-sp-'),('total','-ou-'))
                 if any(token in odd for odd in odds))


def coverage(params, family=None):
    books = set(params.get('bookmakerID', '').split(',')) - {''}
    odds = set(params.get('oddID', '').split(',')) - {''}
    required = set(ODD_IDS)
    if family:
        token = {'moneyline':'-ml-','spread':'-sp-','total':'-ou-'}[family]
        required = {odd for odd in required if token in odd}
    effective = set(odds)
    if params.get('includeOpposingOdds') is True:
        for selected in requested_families(params):
            token = {'moneyline':'-ml-','spread':'-sp-','total':'-ou-'}[selected]
            effective.update(odd for odd in ODD_IDS if token in odd)
    return dict(bookmakers=sorted(books), odd_ids=sorted(odds),
        include_alt_lines=params.get('includeAltLines') is True,
        covers_board=set(REQUEST_BOOKS) <= books and required <= effective
            and params.get('includeAltLines') is True,
        omissions='not_returned; no_source_withdrawal_inferred')


def start(db, params, *, at, pull_id=None, event=None, started_order=None, late_task=None):
    """Must commit before dispatch. Ordering is allocated at start, never finish."""
    pull_id = pull_id or str(uuid4())
    scope = {k:v for k,v in params.items() if k != 'cursor'}
    details = dict(event=event) if event else {}
    scopes = [(event_id, family, coverage(params, family))
              for event_id in sorted(set(params.get('eventIDs', '').split(',')) - {''})
              for family in requested_families(params)]
    size = 256 + 2 * (len(encoded(scope)) + len(encoded(details)))
    size += sum(256 + 2 * len(encoded(description)) for _, _, description in scopes)
    with db.transaction():
        if late_task:
            # The manifest is written before a late response can release its
            # reservation. Charge that small write to the active claim's own
            # allowance, under the same lock as all research budget checks.
            from app.research.experiment import _lock
            _lock(db)
            db.execute('''UPDATE public.ev_experiment_game g
                SET late_reserved_bytes=greatest(0, g.late_reserved_bytes-%s)
                WHERE g.id=%s AND EXISTS(SELECT 1 FROM public.ev_experiment_task t
                    WHERE t.game_id=g.id AND t.checkpoint='late' AND t.state='claimed' AND t.token=%s)''',
                (size, late_task['game_id'], late_task['token']))
        _admit(db, size)
        if started_order is None:
            db.execute('''INSERT INTO public.market_pull(pull_id,requested_at,request_scope,state,details)
                VALUES(%s,%s,%s,'in_progress',%s)''',
                (pull_id, at, Jsonb(scope), Jsonb(details)))
        else:
            db.execute('''INSERT INTO public.market_pull(pull_id,started_order,requested_at,request_scope,state,details)
                VALUES(%s,%s,%s,%s,'in_progress',%s)''',
                (pull_id,started_order,at,Jsonb(scope),Jsonb(details)))
        for event_id, family, description in scopes:
            db.execute('''INSERT INTO public.market_pull_scope
                (pull_id,event_id,family,coverage,state) VALUES(%s,%s,%s,%s,'in_progress')''',
                (pull_id,event_id,family,Jsonb(description)))
    return pull_id


def begin(db, params, *, at):
    """Resume only a declared discovery chain's exact accepted next cursor."""
    if params.get('cursor'):
        scope = {key:value for key,value in params.items() if key != 'cursor'}
        cursor_hash = sha256(params['cursor'].encode()).hexdigest()
        row = db.execute('''SELECT pull_id FROM public.market_pull WHERE state='in_progress'
            AND request_scope=%s AND details->>'next_cursor_hash'=%s
            ORDER BY started_order DESC LIMIT 1''', (Jsonb(scope),cursor_hash)).fetchone()
        if row:
            return row['pull_id']
        # A resumed old traversal without its authentic manifest remains a
        # narrower, uncertain operation, never a fabricated complete pull.
    return start(db, params, at=at)


def _membership(page):
    return dict(event_ids=sorted(event['event_id'] for event in page.events),
                next_cursor_present=bool(page.next_cursor))


def accept(db, page):
    """Store the child ledger attempt and exact accepted response membership."""
    if not page.pull_id or not page.attempt_id or not page.received_at:
        raise ValueError('acquisition_membership_unverified')
    membership = _membership(page)
    with db.transaction():
        _admit(db, len(encoded(membership))+256)
        previous = db.execute('''SELECT receipt_sha256,received_at,membership FROM public.market_pull_receipt
            WHERE pull_id=%s AND attempt_id=%s''',(page.pull_id,page.attempt_id)).fetchone()
        if previous:
            if (previous['receipt_sha256'] != page.receipt_sha256
                    or previous['received_at'] != stamp(page.received_at) or previous['membership'] != membership):
                raise ValueError('acquisition_response_membership_contradictory')
            return
        db.execute('''INSERT INTO public.market_pull_receipt
            (pull_id,attempt_id,receipt_sha256,received_at,membership) VALUES(%s,%s,%s,%s,%s)''',
            (page.pull_id,page.attempt_id,page.receipt_sha256,page.received_at,Jsonb(membership)))
        db.execute('''UPDATE public.market_pull SET details=details||%s WHERE pull_id=%s AND state='in_progress' ''',
            (Jsonb(dict(next_cursor_hash=sha256(page.next_cursor.encode()).hexdigest() if page.next_cursor else None)),page.pull_id))


def finish(db, pull_id, state, *, details=None):
    if state not in ('complete','partial','failed','cancelled','refused'):
        raise ValueError('invalid_acquisition_terminal_state')
    with db.transaction():
        db.execute('''UPDATE public.market_pull SET state=%s,details=details||%s
            WHERE pull_id=%s AND state='in_progress' ''', (state,Jsonb(details or {}),pull_id))
        db.execute('''UPDATE public.market_pull_scope SET state=%s WHERE pull_id=%s
            AND state='in_progress' ''', (state,pull_id))


def compact_snapshot(snapshot, pull_id, family=None):
    """SQL ranking facts, with full evidence stored once in compressed form."""
    result = {key:value for key,value in snapshot.items()
              if key not in ('offers','references','raw_quotes')}
    offers = []
    for value in snapshot['offers']:
        record = value['record']
        meta = record.get('comparison_source_metadata') or {}
        item = {key:value[key] for key in ('main','reason') if key in value}
        item['record'] = dict(market_identity={key:record['market_identity'][key] for key in ('family','period')},
            quote={key:record['quote'][key] for key in ('venue','state','times')},
            comparison_source_metadata={key:meta[key] for key in ('provider_bookmaker_id','acquisition') if key in meta})
        from .market_board import offer
        display = offer(snapshot,value,pull_id)
        for key in ('normalized_record','calculation_payload','fee_input','source_input'):
            display.pop(key,None)
        if display.get('reference'):
            display['reference'] = {key:display['reference'][key] for key in
                ('book','probability','selection_policy','trusted_book_count') if key in display['reference']}
        item['display_offer'] = display
        item['evidence_revision'] = hashed([pull_id,value])
        payload = value.get('calculation_payload')
        if payload:
            small = {key:payload[key] for key in ('id','input_revision','version','display','fee_mode') if key in payload}
            small['raw'] = dict(net_ev=(payload.get('raw') or {}).get('net_ev'))
            if payload.get('reference'):
                small['reference'] = {key:payload['reference'][key] for key in
                    ('book','probability','selection_policy','trusted_book_count') if key in payload['reference']}
                prices = payload['reference'].get('required_input_prices', payload['reference'].get('prices',[]))
                small['reference_source_times'] = list(dict.fromkeys(price.get('source_at') for price in prices))
            acquisition = payload.get('acquisition')
            if acquisition:
                witnesses = {hashed(proof):proof for proof in acquisition.get('required_inputs', [])}
                small['acquisition'] = dict(acquisition, required_inputs=list(witnesses.values()))
            item['calculation_payload'] = small
        offers.append(item)
    if family is not None:
        offers = [item for item in offers if item['record']['market_identity']['family'] == family]
    return dict(result, offers=offers, compact=True)


@dataclass(frozen=True)
class PreparedPublication:
    body: bytes
    digest: str
    raw_bytes: int
    scope_snapshots: dict
    allocation_bytes: int


def prepare_publication(page, snapshot, *, details=None):
    """Encode the exact witness once and estimate its complete SQL allocation."""
    raw = encoded(snapshot)
    body = zlib.compress(raw, level=6)
    projection = compact_snapshot(snapshot, page.pull_id)
    params = page.request_scope or {}
    scope_snapshots = {family: dict(projection, offers=[offer for offer in projection['offers']
                            if offer['record']['market_identity']['family'] == family])
                       for family in requested_families(params)}
    membership = _membership(page)
    allocation = len(body) + 256 + len(encoded(membership)) * 2 + len(encoded(details or {})) * 2 + 1024
    for family, scope_snapshot in scope_snapshots.items():
        allocation += 256 + 2 * (len(encoded(scope_snapshot)) + len(encoded(coverage(params, family))))
    return PreparedPublication(body, sha256(raw).hexdigest(), len(raw), scope_snapshots, allocation)


def store_evidence(db, pull_id, snapshot, *, prepared=None):
    """Write one canonical compressed witness; callers own the publication tx."""
    if prepared is None:
        raw = encoded(snapshot)
        body, digest, raw_bytes = zlib.compress(raw, level=6), sha256(raw).hexdigest(), len(raw)
    else:
        body, digest, raw_bytes = prepared.body, prepared.digest, prepared.raw_bytes
    _admit(db, len(body)+256)
    db.execute('''INSERT INTO public.market_pull_evidence(pull_id,body,sha256,raw_bytes)
        VALUES(%s,%s,%s,%s)''', (pull_id,body,digest,raw_bytes))
    return len(body)


def read_snapshot(db, pull_id, family=None):
    """Read immutable canonical evidence, verifying its bounded byte identity."""
    row = db.execute('SELECT body,sha256,raw_bytes FROM public.market_pull_evidence WHERE pull_id=%s',
                     (pull_id,)).fetchone()
    if not row:
        raise ValueError('market_snapshot_evidence_missing')
    from app.research.records import EVIDENCE_RESPONSE_BYTE_CAP
    if not 0 < row['raw_bytes'] <= EVIDENCE_RESPONSE_BYTE_CAP:
        raise ValueError('market_snapshot_evidence_capacity')
    decoder = zlib.decompressobj()
    body = decoder.decompress(bytes(row['body']), row['raw_bytes']+1)
    if (len(body) != row['raw_bytes'] or not decoder.eof or decoder.unused_data
            or sha256(body).hexdigest() != row['sha256']):
        raise ValueError('market_snapshot_evidence_integrity')
    snapshot = json.loads(body)
    if family is not None:
        snapshot = dict(snapshot,
            offers=[offer for offer in snapshot['offers'] if offer['record']['market_identity']['family'] == family],
            references=[entry for entry in snapshot['references'] if entry['facts']['market'] == family],
            raw_quotes=[quote for quote in snapshot['raw_quotes'] if quote['market'] == family])
    return snapshot


def publish(db, page, snapshot, *, details=None, prepared=None):
    """Accepted membership, snapshot and calculation bindings publish together."""
    pull_id = page.pull_id
    if not pull_id or not page.attempt_id or not page.received_at:
        raise ValueError('acquisition_membership_unverified')
    params = page.request_scope or {}
    expected = set(params.get('eventIDs', '').split(',')) - {''}
    returned = {event['event_id'] for event in page.events}
    # Cursor pagination enumerates Events, not partial odds inside an Event.
    # Returning the sole explicit requested Event closes this relevant scope,
    # even when SGO supplies its documented redundant nextCursor. Broader
    # moving discovery walks still cannot establish omission authority.
    closed = (len(expected) == 1 and returned == expected
              and not page.conflicting_alternate_lines and not page.ignored_bookmaker_groups)
    state = 'complete' if closed else 'partial'
    prepared = prepared or prepare_publication(page, snapshot, details=details)
    with db.transaction():
        _admit(db, prepared.allocation_bytes)
        accept(db, page)
        store_evidence(db, pull_id, snapshot, prepared=prepared)
        source = snapshot['source_event']
        for family, market_snapshot in prepared.scope_snapshots.items():
            db.execute('''INSERT INTO public.market_pull_scope
                (pull_id,event_id,family,coverage,state,snapshot) VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(pull_id,event_id,family,period) DO UPDATE SET
                  state=excluded.state,snapshot=excluded.snapshot
                WHERE market_pull_scope.state='in_progress' ''',
                (pull_id,source['event_id'],family,Jsonb(coverage(params,family)),state,Jsonb(market_snapshot)))
        db.execute('''UPDATE public.market_pull SET state=%s,details=details||%s
            WHERE pull_id=%s AND state='in_progress' ''', (state,Jsonb(details or {}),pull_id))
    return state
