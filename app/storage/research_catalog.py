"""Read-only received-data catalog, independent of price/fee/EV admission.

Current SGO observations include reference-only books and withdrawn lines. Native
inputs that have not reached normalized storage remain inspectable as raw books.
This catalog never acquires data or recalculates an input during a browser read.
"""

from fractions import Fraction

from . import raw_prices
from .store import hashed


SOURCES = """
SELECT 'sgo:'||q.id AS id,'sgo'::text kind,'sportsgameodds'::text provider,
 q.bookmaker_id original_bookmaker_id,
 CASE q.bookmaker_id WHEN 'polymarket' THEN 'polymarket_us'
  WHEN 'prophetx' THEN 'prophetx' WHEN 'prophetexchange' THEN 'prophetx'
  ELSE q.bookmaker_id END venue,
 q.event_id,q.facts->>'odd_id' market_id,q.facts->>'league' sport,
 q.facts->>'market' family,q.facts->>'period' period,
 concat(q.facts#>>'{teams,away,name}',' at ',q.facts#>>'{teams,home,name}') title,
 (q.facts->>'received_at')::timestamptz received_at,q.facts->>'source_at' source_at,
 q.id source_id,q.revision source_revision,linked.contract_id,
 CASE WHEN q.bookmaker_id='polymarket' THEN 'provider_venue_fee_applicability_unestablished'
  ELSE linked.reason END reason,
 CASE WHEN q.bookmaker_id='polymarket' THEN NULL ELSE linked.net_ev END net_ev,
 linked.input_revision calculation_revision
FROM sgo_quote_revision q
LEFT JOIN (
 SELECT DISTINCT ON (o.sgo_quote_id,o.sgo_quote_revision)
  o.sgo_quote_id,o.sgo_quote_revision,c.id contract_id,k.reason,k.net_ev,k.input_revision
 FROM current_offer_storage o JOIN current_contract_storage c ON c.id=o.contract_id
 LEFT JOIN current_pregame_calculation k ON k.contract_id=c.id
 WHERE o.sgo_quote_id IS NOT NULL
 ORDER BY o.sgo_quote_id,o.sgo_quote_revision,c.active DESC,c.id
) linked ON (linked.sgo_quote_id,linked.sgo_quote_revision)=(q.id,q.revision)
WHERE q.is_current
UNION ALL
SELECT 'offer:'||c.id,'offer',e.provider,
 COALESCE(c.facts#>>'{comparison_source_metadata,provider_bookmaker_id}',c.venue),
 c.venue,e.native_event_id,c.native_market_id,e.competition,
 c.facts#>>'{market_identity,family}',c.facts#>>'{market_identity,period}',
 e.facts->>'title',o.received_at::timestamptz,o.source_at,c.id,o.revision,c.id,
 CASE WHEN e.provider='sportsgameodds' AND c.venue='polymarket_us'
  THEN 'provider_venue_fee_applicability_unestablished' ELSE k.reason END,
 CASE WHEN e.provider='sportsgameodds' AND c.venue='polymarket_us' THEN NULL ELSE k.net_ev END,
 k.input_revision
FROM current_contract_storage c JOIN current_event e ON e.id=c.event_id
JOIN current_offer_storage o ON o.contract_id=c.id
LEFT JOIN current_pregame_calculation k ON k.contract_id=c.id
WHERE e.provider<>'sportsgameodds' OR o.sgo_quote_id IS NULL
UNION ALL
SELECT 'raw:'||h.kind||':'||h.venue||':'||h.sport||':'||h.event_id||':'||h.market_id,
 'raw',CASE WHEN h.kind='native' THEN h.venue ELSE 'the_odds_api' END,
 h.venue,h.venue,h.event_id,h.market_id,h.sport,h.family,h.period,h.title,
 h.received_at,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,
 NULL::numeric,NULL::text
FROM (""" + raw_prices.HEADER + """) h
WHERE NOT EXISTS (
 SELECT 1 FROM current_contract_storage c JOIN current_event e ON e.id=c.event_id
 JOIN current_offer_storage o ON o.contract_id=c.id
 WHERE e.provider=CASE WHEN h.kind='native' THEN h.venue ELSE 'the_odds_api' END
 AND e.native_event_id=h.event_id AND c.venue=h.venue
 AND c.native_market_id=h.market_id AND o.received_at::timestamptz=h.received_at)
"""

STATUS = """CASE WHEN net_ev>0 THEN 'positive' WHEN net_ev<0 THEN 'negative'
 WHEN net_ev=0 THEN 'zero' ELSE 'unavailable' END"""
FILTERS = ('provider', 'original_bookmaker_id', 'sport', 'family', 'event_id')


def selection(filters):
    clauses, args = [], []
    for key in FILTERS:
        if filters.get(key):
            clauses.append(key + '=%s')
            args.append(filters[key])
    if filters.get('search'):
        clauses.append("(title ILIKE %s OR event_id ILIKE %s OR market_id ILIKE %s)")
        term = '%' + filters['search'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        args.extend([term] * 3)
    if filters.get('calculation_status'):
        clauses.append(STATUS + '=%s')
        args.append(filters['calculation_status'])
    if filters.get('max_age_minutes'):
        clauses.append("source_at::timestamptz >= transaction_timestamp()-(%s::int*interval '1 minute')")
        args.append(int(filters['max_age_minutes']))
    return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), args


def headers(db, filters, *, offset=0, limit=50, entry_id=None):
    clause, args = selection(filters)
    if entry_id is not None:
        clause += (' AND ' if clause else ' WHERE ') + 'id=%s'
        args.append(entry_id)
    return db.execute('SELECT *,transaction_timestamp() snapshot_at FROM (' + SOURCES + ') catalog' + clause +
        ' ORDER BY received_at DESC,id LIMIT %s OFFSET %s', (*args, limit, offset)).fetchall()


def counts(db, filters):
    clause, args = selection(filters)
    row = db.execute('SELECT count(*) records,count(DISTINCT (provider,event_id)) source_events,'
        'count(DISTINCT event_id) event_identifiers FROM (' + SOURCES + ') catalog' + clause, args).fetchone()
    row['event_count_meaning'] = 'Source-event identities; cross-provider events may overlap.'
    return row


def calculation_state(payload, reason, *, contract_id):
    if payload is None:
        return dict(status='unavailable', net_ev_percent=None,
            reason=reason or ('not_calculated' if contract_id else 'not_linked_to_current_calculation'))
    value = (payload.get('raw') or {}).get('net_ev')
    if value is None:
        return dict(status='unavailable', net_ev_percent=None, reason='result_value_unavailable')
    number = Fraction(str(value))
    return dict(status='positive' if number > 0 else 'negative' if number < 0 else 'zero',
        net_ev_percent=str(number*100), net_ev_ratio=value,
        display=(payload.get('display') or {}).get('net_ev'), reason=None)


def _receipt(digest):
    if not digest:
        return dict(state='not_recorded', reason='No original receipt hash retained.')
    from app.collection.original_receipts import lookup
    return lookup(digest)


def entry(db, header, owner, *, detail=False):
    """Hydrate one bounded input and attach only its exact accepted projection."""
    kind, cid = header['kind'], header['contract_id']
    stored = None
    if cid:
        stored = db.execute('''SELECT c.facts contract,c.revision contract_revision,c.active,
            e.facts event,e.id canonical_event_id,o.facts quote,o.revision offer_revision,
            o.source_at,o.received_at,o.price_value,o.price_units,
            k.payload,k.reason,k.version,k.input_revision,k.calculated_at,k.valid_until,
            p.record,p.fee_input,p.payload price_payload
            FROM current_contract_storage c JOIN current_event e ON e.id=c.event_id
            JOIN current_offer o ON o.contract_id=c.id
            LEFT JOIN current_pregame_calculation k ON k.contract_id=c.id
            LEFT JOIN current_pregame_price p ON p.contract_id=c.id WHERE c.id=%s''', (cid,)).fetchone()
    raw_book, source_input = None, None
    if kind == 'sgo':
        row = db.execute('''SELECT q.facts,COALESCE(p.expired,false) withdrawn
            FROM sgo_quote_revision q LEFT JOIN sgo_line_presence p ON p.quote_id=q.id
            WHERE q.id=%s AND q.revision=%s''', (header['source_id'], header['source_revision'])).fetchone()
        source_input = row['facts']
        price, units = source_input['price_american'], 'american_odds'
        outcome, line = source_input['side'], source_input['line']
        available = source_input['available'] and not row['withdrawn']
        availability_reason = 'line_withdrawn' if row['withdrawn'] else source_input['unavailable_reason']
        digest = source_input['receipt_sha256']
        source_revision = header['source_revision']
    elif kind == 'offer':
        source_input = stored['quote']
        price, units = stored['price_value'], stored['price_units']
        market = stored['contract']['market_identity']
        selection = stored['contract']['selection']
        outcome = selection.get('label') or selection.get('predicate')
        line = selection.get('signed_line', market.get('line'))
        available = source_input.get('state') != 'unavailable' and stored['active']
        availability_reason = None if available else 'withdrawn_or_inactive'
        digest = (source_input.get('provenance') or {}).get('sha256')
        source_revision = stored['offer_revision']
    else:
        raw_kind = header['id'].split(':', 2)[1]
        raw_header = db.execute('SELECT * FROM (' + raw_prices.HEADER + ') h WHERE '
            'kind=%s AND venue=%s AND sport=%s AND event_id=%s AND market_id=%s',
            (raw_kind, header['venue'], header['sport'], header['event_id'], header['market_id'])).fetchone()
        raw_book = raw_prices.book(db, raw_header, owner)
        price, units, outcome, line = None, None, None, None
        available, availability_reason = None, 'raw_book_has_individual_observation_dispositions'
        digest, source_revision = None, raw_book['revision']
        source_input = raw_book
    payload = stored['payload'] if stored else None
    from app.comparison.snapshot_fee_scope import provider_venue_fee_reason
    applicability_reason = provider_venue_fee_reason(dict(quote=dict(
        source=dict(provider=header['provider']), venue=header['venue'])))
    historical_conditional = payload if applicability_reason else None
    if applicability_reason:
        payload = None
    state = calculation_state(payload,
        applicability_reason or (stored['reason'] if stored else None), contract_id=cid)
    state['evidence_scope'] = 'stored_calculation; catalog grants no execution authority'
    state['freshness'] = ('source_unavailable' if available is False else
        'expired' if stored and stored['valid_until'] and stored['valid_until'] <= header['snapshot_at'] else
        'within_stored_deadline' if stored and stored['valid_until'] else 'not_established')
    event_id = stored['canonical_event_id'] if stored else None
    if kind == 'sgo' and event_id is None:
        event = db.execute("SELECT id FROM current_event WHERE provider='sportsgameodds' AND native_event_id=%s",
            (header['event_id'],)).fetchone()
        event_id = event['id'] if event else None
    canonical = dict(event_id=event_id,
        contract_id=cid, market=stored['contract'].get('market_identity') if stored else None,
        selection=stored['contract'].get('selection') if stored else None,
        mapping_status='normalized' if stored else 'event_normalized_market_source_local' if event_id else 'source_local',
        settlement='unverified' if kind == 'sgo' else
            (stored['contract'].get('result_policy') if stored else None))
    original = header['original_bookmaker_id']
    equivalence = 'unestablished' if header['provider'] == 'sportsgameodds' and original == 'polymarket' else (
        'native_identity' if header['provider'] == header['venue'] else 'provider_identity_only')
    times = dict(source_at=header['source_at'] if kind != 'raw' else raw_book['source_at'],
        received_at=header['received_at'].isoformat(),
        calculated_at=stored['calculated_at'].isoformat() if stored and stored['calculated_at'] else None,
        valid_until=stored['valid_until'].isoformat() if stored and stored['valid_until'] else None)
    revision = hashed([header['id'], source_revision, times, digest,
        stored['contract_revision'] if stored else None,
        stored['input_revision'] if stored else None, state])
    result = dict(id=header['id'], revision=revision, kind=kind,
        provider=header['provider'], original_bookmaker_id=original,
        represented_venue=header['venue'], venue_equivalence=equivalence,
        event_id=header['event_id'], source_market_id=header['market_id'],
        sport=header['sport'], family=header['family'], period=header['period'], title=header['title'],
        outcome=outcome, line=line, price=price, price_units=units,
        available=available, availability_reason=availability_reason,
        identity=canonical, times=times, calculation=state,
        source_revision=source_revision, calculation_revision=stored['input_revision'] if stored else None,
        calculation_input_times=payload.get('times') if payload else None,
        calculation_association='Exact quote identity and value revision; calculation inputs retain their own receipt clocks.' if cid else None,
        calculation_version=stored['version'] if stored else None,
        probability_policy=(payload.get('reference') or {}).get('selection_policy') if payload else None,
        coherent_probability=payload.get('coherent_probability') if payload else None,
        receipt_sha256=digest, original_response=_receipt(digest) if detail else None,
        raw_observations=raw_book['observations'] if raw_book else None,
        provider_requests=0)
    if detail:
        history = []
        if applicability_reason and cid:
            from app.research.records import conditional_history
            history = conditional_history(db, cid, limit=1)
            if historical_conditional is None and history:
                historical_conditional = history[0]['original_calculation']
        normalized = stored['record'] if stored else None
        if stored and normalized is None:
            from .current_rows import project_contract, project_quote
            normalized = dict(project_contract(stored['event'], stored['contract'], stored['received_at']),
                event=stored['event'], quote=project_quote(stored))
        native_wire = None
        if header['provider'] in ('kalshi', 'polymarket_us'):
            wire = db.execute("SELECT image->'raw'->>'json_text' wire FROM current_acquisition_image "
                'WHERE source=%s AND event_id=%s AND market_id=%s AND received_at=%s',
                (header['provider'], header['event_id'], header['market_id'], header['received_at'])).fetchone()
            native_wire = wire['wire'] if wire else None
            result['original_response'] = dict(
                state='native_current_wire_retained' if native_wire else 'not_recorded',
                reason='Captured current native wire; full historical depth is not established.' if native_wire else
                    'No native wire bound to this exact receipt.', retention_owner='current_acquisition_image')
        result.update(source_input=source_input, native_wire=native_wire,
            normalized_record=normalized,
            contract=stored['contract'] if stored else None,
            event=stored['event'] if stored else None,
            fee_input=stored['fee_input'] if stored and not applicability_reason else None,
            calculation_payload=payload,
            price_payload=stored['price_payload'] if stored and not applicability_reason else None,
            historical_conditional_calculation=historical_conditional,
            historical_conditional_history=history,
            reproduction='Exact source, identity, fee and calculation revisions from the captured read. '
                'Unknown fees, probability inputs and settlement remain null/unavailable.')
    return result
