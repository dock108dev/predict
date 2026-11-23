"""Bounded, passive market comparisons over frozen acquisition membership.

SQL chooses a scope's newest covering attempt before considering prices. It
then selects the exact main offer before filtering, counting and pagination.
An incomplete newer attempt consequently cannot inherit an older positive EV.
"""

from fractions import Fraction
from copy import deepcopy

from app.comparison.snapshot_fee_outcome import VENUES
from app.storage.store import hashed


READ_FILTERS = ('sport', 'date', 'search', 'family', 'calculation_status',
                'include_alternates', 'sort', 'provider', 'reference_scope',
                'original_bookmaker_id', 'max_age_minutes')


def _game_identity_sql(scope, order, details):
    # These aliases are internal SQL fragments. Identity can carry forward only
    # through an authentic source-event link, never a title or a clock match.
    return f"""COALESCE({scope}.snapshot->>'canonical_game_id',
        {details}#>>'{{event,canonical_game_id}}',
        (SELECT linked.snapshot->>'canonical_game_id'
         FROM public.market_pull_scope linked JOIN public.market_pull operation USING(pull_id)
         WHERE linked.event_id={scope}.event_id AND operation.started_order<{order}
           AND linked.snapshot->>'canonical_game_id' IS NOT NULL
         ORDER BY operation.started_order DESC,linked.family LIMIT 1),
        'source:sportsgameodds:'||{scope}.event_id)"""


def _population(filters):
    # The acquisition owner is the authority for whether a request covers the
    # unrestricted board. Browser filters never expand declared membership.
    coverage, args = "s.coverage->>'covers_board'='true'", []
    candidates = ["o.value#>>'{record,quote,venue}'=ANY(%s)",
        "o.value->>'reason' IS NULL",
        "o.value#>>'{record,quote,state}'='available'",
        "o.value#>>'{calculation_payload,raw,net_ev}' IS NOT NULL",
        "o.value#>>'{display_offer,calculation,net_ev_ratio}'=o.value#>>'{calculation_payload,raw,net_ev}'",
        "o.value#>>'{calculation_payload,acquisition,eligible}'='true'",
        "o.value#>>'{calculation_payload,acquisition,pull_id}'=s.pull_id",
        "o.value#>>'{record,comparison_source_metadata,acquisition,pull_id}'=s.pull_id",
        """o.value#>'{calculation_payload,acquisition,required_inputs}' @> jsonb_build_array(
            (o.value#>'{record,comparison_source_metadata,acquisition}') || jsonb_build_object(
                'received_at',o.value#>>'{record,quote,times,received_at}'))""",
        "jsonb_array_length(COALESCE(o.value#>'{calculation_payload,acquisition,required_inputs}','[]'::jsonb))>0",
        """NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
            COALESCE(o.value#>'{calculation_payload,acquisition,required_inputs}','[]'::jsonb)) required
            WHERE required->>'pull_id' IS DISTINCT FROM s.pull_id OR NOT EXISTS (
              SELECT 1 FROM public.market_pull_receipt accepted
              WHERE accepted.pull_id=s.pull_id AND accepted.attempt_id=required->>'attempt_id'
                AND accepted.receipt_sha256=required->>'receipt_sha256'
                AND accepted.received_at=(required->>'received_at')::timestamptz))""",
        """(SELECT max((required->>'received_at')::timestamptz)-min((required->>'received_at')::timestamptz)
            FROM jsonb_array_elements(o.value#>'{calculation_payload,acquisition,required_inputs}') required)
            <= interval '600 seconds'""",
        "o.value#>>'{main,status}' IN ('main'" + (",'alternate'" if filters.get('include_alternates') == '1' else '') + ")"]
    args = [*args, list(VENUES)]
    if filters.get('original_bookmaker_id'):
        candidates.append("COALESCE(o.value#>>'{record,comparison_source_metadata,provider_bookmaker_id}',o.value#>>'{record,quote,venue}')=%s")
        args.append(filters['original_bookmaker_id'])
    if filters.get('max_age_minutes'):
        # Age is an explicit user control over the same candidate set that
        # supplies the headline and ranking, never acquisition membership.
        candidates.append("(o.value#>>'{record,quote,times,source_at}')::timestamptz>=transaction_timestamp()-(%s::int*interval '1 minute')")
        args.append(int(filters['max_age_minutes']))
        candidates.append("jsonb_array_length(COALESCE(o.value#>'{calculation_payload,reference_source_times}','[]'::jsonb))>0")
        candidates.append("""NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(
            COALESCE(o.value#>'{calculation_payload,reference_source_times}','[]'::jsonb)) ref(source_at)
            WHERE source_at IS NULL OR source_at::timestamptz<
              transaction_timestamp()-(%s::int*interval '1 minute'))""")
        args.append(int(filters['max_age_minutes']))
    clause = []
    if filters.get('provider') not in (None, '', 'sportsgameodds'):
        clause.append('false')
    if filters.get('event_id'):
        clause.append('event_id=%s')
        args.append(filters['event_id'])
    for key, column in (('sport', 'sport'), ('family', 'family')):
        if filters.get(key):
            clause.append(column + '=%s')
            args.append(filters[key])
    if filters.get('date'):
        clause.append("(start_at AT TIME ZONE 'America/New_York')::date=%s::date")
        args.append(filters['date'])
    if filters.get('search'):
        term = '%' + filters['search'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        clause.append('(title ILIKE %s OR event_id ILIKE %s)')
        args.extend([term, term])
    status = filters.get('calculation_status')
    if status in ('positive', 'negative', 'zero', 'unavailable'):
        clause.append({'positive': 'net_ev>0', 'negative': 'net_ev<0',
                       'zero': 'net_ev=0', 'unavailable': 'net_ev IS NULL'}[status])
    elif status == 'reference_only':
        clause.append('false')
    where = ' WHERE ' + ' AND '.join(clause) if clause else ''
    # A fraction is parsed only from a successfully stored calculation; no
    # probability, fee or financial calculation runs in this reader.
    query = """WITH covered AS MATERIALIZED (
      SELECT s.*,p.started_order,p.requested_at,p.request_scope,p.details,
        row_number() OVER(PARTITION BY s.event_id,s.family,s.period ORDER BY p.started_order DESC) newest
      FROM public.market_pull_scope s JOIN public.market_pull p USING(pull_id)
      WHERE s.period='full_game' AND s.family IN ('moneyline','spread','total') AND """ + coverage + """
    ), current_scope AS MATERIALIZED (SELECT * FROM covered WHERE newest=1),
    projected AS (
      SELECT s.*,
        """ + _game_identity_sql('s','s.started_order','s.details') + """ game_id,
        COALESCE(s.snapshot#>>'{event,title}',s.details#>>'{event,title}',s.event_id) title,
        COALESCE(s.snapshot#>>'{event,competition}',s.details#>>'{event,league}') sport,
        COALESCE(s.snapshot#>>'{event,scheduled_start}',s.details#>>'{event,starts_at}')::timestamptz start_at,
        winner.best,winner.net_ev
      FROM current_scope s LEFT JOIN LATERAL (
        SELECT o.value best,
          split_part(o.value#>>'{calculation_payload,raw,net_ev}','/',1)::numeric /
          CASE WHEN position('/' IN o.value#>>'{calculation_payload,raw,net_ev}')>0
            THEN NULLIF(split_part(o.value#>>'{calculation_payload,raw,net_ev}','/',2)::numeric,0) ELSE 1 END net_ev
        FROM jsonb_array_elements(COALESCE(s.snapshot->'offers','[]'::jsonb)) WITH ORDINALITY o(value,ordinal)
        WHERE s.state='complete' AND o.value#>>'{record,market_identity,family}'=s.family
          AND o.value#>>'{record,market_identity,period}'=s.period AND """ + ' AND '.join(candidates) + """
        ORDER BY net_ev DESC,o.value#>>'{record,quote,venue}',
          o.value#>>'{calculation_payload,id}',o.ordinal LIMIT 1
      ) winner ON true
    ), market_rows AS (SELECT *,game_id||'|'||family||'|'||period id FROM projected)
    """
    return query, where, args


def markets(db, filters, *, offset=0, limit=50):
    query, where, args = _population(filters)
    count = db.execute(query + 'SELECT count(*) total FROM market_rows' + where, args).fetchone()['total']
    order = 'ASC' if filters.get('sort') == 'ev_asc' else 'DESC'
    rows = db.execute(query + 'SELECT * FROM market_rows' + where +
        ' ORDER BY net_ev ' + order + ' NULLS LAST,start_at NULLS LAST,id LIMIT %s OFFSET %s',
        (*args, limit, offset)).fetchall()
    return dict(rows=[row(db, value) for value in rows], total=count)


def _selection_label(snapshot, record, payload, side):
    if side in ('over', 'under'):
        return side.title()
    selected = record.get('selection') or {}
    participant = selected.get('participant')
    names = [name for name, identity in (record.get('event', {}).get('participants') or {}).items()
             if identity == participant and name != participant]
    if len(names) == 1:
        return names[0]
    label = selected.get('label') or (payload or {}).get('selection_label')
    if label and label != participant:
        return label
    if side in ('home', 'away'):
        source_name = ((snapshot.get('source_event') or {}).get('teams', {}).get(side) or {}).get('name')
        if source_name:
            return source_name
        return side.title() + ' selection · name not recorded'
    return 'Selection identity unresolved'


def offer(snapshot, value, pull_id, *, family=None):
    """One exact received trading offer and its stored calculation witness."""
    from app.comparison.current_pregame import reference_key
    from app.research.ev_movement import exact_bet_identity

    if value.get('display_offer'):
        # This immutable scalar display was produced from the original offer
        # before its evidence was compressed. Its exact identity and revision
        # remain identical to the fully expanded inspector/export projection.
        displayed = deepcopy(value['display_offer'])
        displayed['outcome'] = _selection_label(snapshot,value['record'],
            value.get('calculation_payload'),displayed.get('side'))
        return displayed
    record = value['record']
    quote = record['quote']
    payload = value.get('calculation_payload')
    identity = exact_bet_identity(record)
    reason = value.get('reason')
    available = quote.get('state') == 'available'
    if not available:
        reason = reason or 'price_withdrawn'
    witness = (payload or {}).get('acquisition') or {}
    if payload and (not witness.get('eligible') or witness.get('pull_id') != pull_id):
        reason = reason or 'acquisition_membership_unverified'
    if payload and not reason:
        from app.comparison.acquisition import calculation, validate

        try:
            # Compact projections retain a deduplicated membership witness;
            # the immutable full calculation still carries every candidate
            # reference side and is independently checked in exact detail.
            actual = validate(witness.get('required_inputs',[])) if value.get('evidence_revision') else calculation(record,payload.get('reference') or {})
            if actual != witness:
                reason = 'acquisition_calculation_witness_mismatch'
        except (ValueError,KeyError,TypeError):
            reason = 'acquisition_membership_unverified'
    ratio = (payload or {}).get('raw', {}).get('net_ev') if not reason else None
    number = Fraction(str(ratio)) if ratio is not None else None
    role = (value.get('main') or {}).get('status', 'unknown')
    calculation = dict(status='unavailable' if number is None else 'positive' if number > 0 else 'negative' if number < 0 else 'zero',
        net_ev_ratio=ratio, net_ev_percent=str(number*100) if number is not None else None,
        reason=reason or (None if number is not None else 'No matching reference pair in this pull'))
    try:
        side = reference_key(record)[1]
    except (ValueError, KeyError, TypeError):
        side = None
    label = _selection_label(snapshot, record, payload, side)
    result = dict(id=identity['id'], revision=value.get('evidence_revision') or hashed([pull_id, value]), pull_id=pull_id,
        exact_bet_id=identity['id'], outcome=label or 'Selection identity unresolved',
        side=side, line=None if identity['family']=='moneyline' else identity['line'],
        venue=quote['venue'], represented_venue=quote['venue'],
        original_bookmaker_id=identity['book'], family=identity['family'], period=identity['period'],
        price=(quote.get('original') or {}).get('value'),
        price_units=(quote.get('original') or {}).get('units'),
        main_role=role, available=available, calculation=calculation,
        times=quote.get('times') or {}, fee_mode=(payload or {}).get('fee_mode') or snapshot.get('fee_mode'),
        reference=(payload or {}).get('reference') or value.get('screen_reference'),
        calculation_revision=(payload or {}).get('input_revision'),
        calculation_version=(payload or {}).get('version'),
        normalized_record=record, calculation_payload=payload, fee_input=value.get('fee_input'),
        source_input=value, provider_requests=0)
    return result


def _capture(value):
    snapshot = value.get('snapshot') or {}
    times = snapshot.get('times') or {}
    return dict(pull_id=value['pull_id'], state=value['state'],
        received_at=times.get('received_at') or times.get('captured_at'),
        requested_at=value['requested_at'].isoformat(),
        reason=(value.get('details') or {}).get('reason'),
        coverage=value.get('coverage'),
        scope='board' if (value.get('coverage') or {}).get('covers_board') else 'restricted')


def offer_summary(value):
    """Ordinary offer tables need prices and identity, not repeated witnesses."""
    result = {key:item for key,item in value.items()
        if key not in ('normalized_record','calculation_payload','fee_input','source_input')}
    if result.get('reference'):
        result['reference'] = {key:item for key,item in result['reference'].items()
            if key in ('book','probability','selection_policy','trusted_book_count')}
    return result


def row(db, value):
    snapshot = value.get('snapshot') or {}
    headline = offer(snapshot, value['best'], value['pull_id']) if value.get('best') else None
    previous = db.execute('''SELECT s.pull_id,s.state,s.coverage,
        jsonb_build_object('times',s.snapshot->'times') snapshot,p.requested_at,p.details
        FROM public.market_pull_scope s
        JOIN public.market_pull p USING(pull_id)
        WHERE s.event_id=%s AND s.family=%s AND s.period=%s AND p.started_order<%s
          AND s.state='complete' AND s.snapshot IS NOT NULL AND s.coverage->>'covers_board'='true'
        ORDER BY p.started_order DESC LIMIT 1''',
        (value['event_id'],value['family'],value['period'],value['started_order'])).fetchone()
    main_offers = [item for item in snapshot.get('offers', [])
        if (item.get('main') or {}).get('status') == 'main']
    consequences = sorted({item['reason'] for item in main_offers if item.get('reason')})
    missing = ('; '.join(consequences) if consequences else
        'No eligible main offer calculation in this pull' if main_offers else
        'No source-designated main trading offer returned in this pull')
    result = dict(id=value['id'], game_id=value['game_id'], event_id=value['event_id'],
        title=value['title'], sport=value['sport'],
        start_at=value['start_at'].isoformat() if value.get('start_at') else None,
        identity_status='canonical' if value['game_id'].startswith('canonical:') else 'source_local',
        family=value['family'], period=value['period'], pull_id=value['pull_id'],
        state=value['state'], received_at=(snapshot.get('times') or {}).get('received_at'),
        requested_at=value['requested_at'].isoformat(), headline=headline,
        fee_mode=snapshot.get('fee_mode'),
        reason=None if headline else (
            'Capture in progress' if value['state']=='in_progress' else
            missing if value['state']=='complete' else
            (value.get('details') or {}).get('reason') or value['state'].replace('_',' ').title()),
        previous_capture=_capture(previous) if previous else None)
    result['revision'] = hashed(result)
    return result


def detail(db, *, market_id, pull_id, offer_id=None, revision=None):
    """Resolve a frozen acquisition, even after an SQL paging lease expires."""
    from app.dashboard.local_security import PublicRequestError

    value = db.execute('''SELECT s.*,p.requested_at,p.started_order,p.details,p.request_scope,
        ''' + _game_identity_sql('s','p.started_order','p.details') + ''' game_id
        FROM public.market_pull_scope s JOIN public.market_pull p USING(pull_id)
        WHERE s.pull_id=%s''', (pull_id,)).fetchall()
    selected = None
    for candidate in value:
        snapshot = candidate.get('snapshot') or {}
        game_id = candidate['game_id']
        identity = game_id+'|'+candidate['family']+'|'+candidate['period']
        if identity == market_id:
            selected = candidate
            selected.update(id=identity,game_id=game_id,title=(snapshot.get('event') or {}).get('title') or
                (candidate.get('details') or {}).get('event',{}).get('title') or candidate['event_id'],
                sport=(snapshot.get('event') or {}).get('competition') or
                    (candidate.get('details') or {}).get('event',{}).get('league'),start_at=None,best=None)
            start = ((snapshot.get('event') or {}).get('scheduled_start') or
                (candidate.get('details') or {}).get('event',{}).get('starts_at'))
            if start:
                from .store import stamp
                selected['start_at'] = stamp(start)
            break
    if selected is None:
        raise PublicRequestError('Unknown market in the selected acquisition; selection was not substituted.')
    from .acquisition_snapshot import read_snapshot

    snapshot = read_snapshot(db,pull_id,selected['family']) if selected.get('snapshot') else {}
    offers = [offer(snapshot,item,pull_id) for item in snapshot.get('offers',[])
              if item['record']['market_identity']['family']==selected['family']
              and item['record']['market_identity']['period']==selected['period']]
    accepted = db.execute('''SELECT attempt_id,receipt_sha256,received_at
        FROM public.market_pull_receipt WHERE pull_id=%s''',(pull_id,)).fetchall()
    from .store import stamp

    membership = {(item['attempt_id'],item['receipt_sha256'],item['received_at']) for item in accepted}
    for item in offers:
        required = (item.get('calculation_payload') or {}).get('acquisition',{}).get('required_inputs',[])
        if not required or any((value.get('attempt_id'),value.get('receipt_sha256'),
                stamp(value['received_at']) if value.get('received_at') else None) not in membership for value in required):
            item['calculation'] = dict(status='unavailable',net_ev_ratio=None,net_ev_percent=None,
                reason='acquisition_receipt_membership_unverified')
    if selected['state'] != 'complete':
        for item in offers:
            item['calculation'] = dict(status='unavailable',net_ev_ratio=None,net_ev_percent=None,
                reason='Acquisition '+selected['state'].replace('_',' ')+'; no current numeric comparison')
    exact = next((item for item in offers if item['id']==offer_id),None) if offer_id else None
    if offer_id and (exact is None or not revision or exact['revision']!=revision):
        raise PublicRequestError('Exact captured offer or revision differs; selection was not substituted.')
    eligible = [(index,item) for index,item in enumerate(offers)
        if item['main_role']=='main' and item['calculation']['net_ev_ratio'] is not None]
    if eligible:
        eligible.sort(key=lambda pair:(-Fraction(pair[1]['calculation']['net_ev_ratio']),pair[1]['venue'],
            (pair[1].get('calculation_payload') or {}).get('id') or '',pair[0]))
        selected['best'] = eligible[0][1]['source_input']
    history = db.execute('''SELECT s.pull_id,s.state,s.coverage,
        jsonb_build_object('times',s.snapshot->'times') snapshot,p.requested_at,p.details
        FROM public.market_pull_scope s
        JOIN public.market_pull p USING(pull_id)
        WHERE s.event_id=%s AND s.family=%s AND s.period=%s
        ORDER BY p.started_order DESC LIMIT 100''',
        (selected['event_id'],selected['family'],selected['period'])).fetchall()
    selected_row = row(db,selected)
    if selected_row.get('headline'):
        selected_row['headline'] = offer_summary(selected_row['headline'])
    return dict(schema='predict-market-evidence-1', row=selected_row, offers=[offer_summary(item) for item in offers],
        selected_offer=exact, reference_inputs=[item for item in snapshot.get('references',[])
            if (item.get('facts') or item).get('market')==selected['family']],
        raw_quotes=[item for item in snapshot.get('raw_quotes',[]) if item.get('market')==selected['family']],
        history=[_capture(item) for item in history], snapshot=snapshot,
        acquisition=dict(pull_id=pull_id,request_scope=selected['request_scope'],details=selected['details'],
            coverage=selected['coverage'],state=selected['state']),
        provider_requests=0, scheduled_calculations=0)
