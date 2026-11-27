"""Bounded, passive market comparisons over frozen acquisition membership.

SQL chooses a scope's newest covering attempt before considering prices. It
then selects the exact main offer before filtering, counting and pagination.
An incomplete newer attempt consequently cannot inherit an older positive EV.
"""

from fractions import Fraction
from copy import deepcopy

from app.comparison.snapshot_fee_outcome import VENUES
from app.comparison.sportsbooks import SPORTSBOOKS
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


def _offer_guards(filters):
    # The acquisition owner is the authority for whether a request covers the
    # unrestricted board. Browser filters never expand declared membership.
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
    venue = filters.get('venue')
    args = [[candidate for candidate in VENUES if not venue or candidate == venue]]
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
    return " AND ".join(candidates), args


LATEST_SCOPES = """WITH covered AS MATERIALIZED (
      SELECT s.*,p.started_order,p.requested_at,p.request_scope,p.details,
        row_number() OVER(PARTITION BY s.event_id,s.family,s.period ORDER BY p.started_order DESC) newest
      FROM public.market_pull_scope s JOIN public.market_pull p USING(pull_id)
      WHERE s.period='full_game' AND s.family IN ('moneyline','spread','total')
        AND s.coverage->>'covers_board'='true'
    ), current_scope AS MATERIALIZED (SELECT * FROM covered WHERE newest=1)"""

NET_EV = """split_part(o.value#>>'{calculation_payload,raw,net_ev}','/',1)::numeric /
          CASE WHEN position('/' IN o.value#>>'{calculation_payload,raw,net_ev}')>0
            THEN NULLIF(split_part(o.value#>>'{calculation_payload,raw,net_ev}','/',2)::numeric,0) ELSE 1 END"""
KICKOFF = """COALESCE(s.snapshot#>>'{event,scheduled_start}',s.details#>>'{event,starts_at}')::timestamptz"""
SPORT = """COALESCE(s.snapshot#>>'{event,competition}',s.snapshot#>>'{event,league}',
                       s.details#>>'{event,competition}',s.details#>>'{event,league}')"""


def _population(filters):
    candidates, args = _offer_guards(filters)
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
    query = LATEST_SCOPES + """,
    projected AS (
      SELECT s.*,
        """ + _game_identity_sql('s','s.started_order','s.details') + """ game_id,
        COALESCE(s.snapshot#>>'{event,title}',s.details#>>'{event,title}',s.event_id) title,
        COALESCE(s.snapshot#>>'{event,competition}',s.details#>>'{event,league}') sport,
        COALESCE(s.snapshot#>>'{event,scheduled_start}',s.details#>>'{event,starts_at}')::timestamptz start_at,
        winner.best,winner.net_ev
      FROM current_scope s LEFT JOIN LATERAL (
        SELECT o.value best,
          """ + NET_EV + """ net_ev
        FROM jsonb_array_elements(COALESCE(s.snapshot->'offers','[]'::jsonb)) WITH ORDINALITY o(value,ordinal)
        WHERE s.state='complete' AND o.value#>>'{record,market_identity,family}'=s.family
          AND o.value#>>'{record,market_identity,period}'=s.period AND """ + candidates + """
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


def dashboard_outcome_key(identity):
    """Group venue quotes only when their exact outcome and settlement agree."""
    event = identity['event']
    return hashed([event['home'], event['away'], *(identity[name]
        for name in ('family', 'period', 'outcome', 'line', 'settlement'))])


def _retained_outcome_keys(db, pull_id):
    from app.research.ev_movement import exact_bet_identity
    from .acquisition_snapshot import read_snapshot

    try:
        snapshot = read_snapshot(db, pull_id)
    except ValueError:
        # An unavailable witness cannot establish cross-venue equivalence.
        return {}
    keys = {}
    for value in snapshot['offers']:
        identity = exact_bet_identity(value['record'])
        display = value.get('display_offer') or {}
        exact_id = display.get('id', identity['id'])
        revision = display.get('revision') or value.get('evidence_revision') or hashed([pull_id, value])
        keys[exact_id, revision] = dashboard_outcome_key(identity)
    return keys


def _dashboard_groups(db, values):
    grouped = {}
    retained_keys = {}
    for value in values:
        details = value['quote']
        pull_id = value['pull_id']
        outcome_key = value['outcome_key']
        if not outcome_key:
            if pull_id not in retained_keys:
                retained_keys[pull_id] = _retained_outcome_keys(db, pull_id)
            outcome_key = retained_keys[pull_id].get((details['id'], details['revision']), details['id'])
        key = (value['game_id'], value['start_at'], value['family'], value['period'], outcome_key)
        group = grouped.setdefault(key, {})
        # Keep the highest eligible observation for a venue, including when
        # one occurrence has more than one authentic provider event link.
        group.setdefault(details['venue'], value)
    groups = [(key, list(venues.values())) for key, venues in grouped.items()]
    return [(key, group) for key, group in groups if Fraction(group[0]['effective_ev']) > 0]


def _dashboard_quote(value):
    quote = value['quote']
    # Exact evidence reads reopen the immutable pull and require its ID and revision.
    return dict(id=quote['id'], revision=quote['revision'], pull_id=value['pull_id'],
        market_id=value['game_id']+'|'+value['family']+'|'+value['period'], game=value['game'],
        league=value['league'], eligible_until=value['eligible_until'], kickoff=value['start_at'],
        family=value['family'], period=value['period'], venue=quote['venue'], selection_label=quote['outcome'],
        line=quote['line'], times=quote['times'], display=value['display'] or {},
        posted=dict(value=quote['price'], units=quote['price_units']), calculation=quote['calculation'],
        liquidity=value['liquidity'], line_role=value['line_role'])


def dashboard(db, *, at, until, freshness_seconds, offset=0, limit=30, sport=None, family=None, venue=None):
    """Rank exact offers after applying the latest current native execution projection."""
    from app.comparison.fee_mode import read as read_fee_mode
    from .pregame_known_withdrawals import phase_closed, reference_known_unavailable

    candidates, args = _offer_guards({'venue': venue, 'include_alternates': '1'})
    filters = [(expression, value) for expression, value in ((SPORT, sport), ('s.family', family)) if value]
    scope_conditions = ''.join(f' AND {expression}=%s' for expression, _ in filters)
    # Mature compact projections retain the winning reference book and exact side
    # and line even when the individual source IDs live in compressed evidence.
    # Match that same pair when checking a later explicit withdrawal.
    line = """(split_part(o.value#>>'{display_offer,line}','/',1)::numeric /
        COALESCE(NULLIF(split_part(o.value#>>'{display_offer,line}','/',2),''),'1')::numeric)"""
    sql = LATEST_SCOPES + """,
        read_clock AS (SELECT %s::timestamptz AS at),
        upcoming AS MATERIALIZED (
          SELECT s.*, """ + KICKOFF + """ start_at, """ + SPORT + """ league,
            known.scheduled_start::timestamptz confirmed_start,
            COALESCE(""" + phase_closed('known') + """,false) phase_closed,
            """ + _game_identity_sql('s','s.started_order','s.details') + """ game_id
          FROM current_scope s
          LEFT JOIN public.current_event known
            ON known.provider='sportsgameodds' AND known.native_event_id=s.event_id
          WHERE """ + KICKOFF + """ BETWEEN %s AND %s""" + scope_conditions + """
        ), eligible AS MATERIALIZED (
          SELECT s.event_id,s.family,s.period,s.pull_id,s.game_id,s.details,s.snapshot->'event' event,
            s.start_at,s.state,s.league,
            winner.best,winner.net_ev,winner.effective_ev,winner.liquidity,winner.eligible_until,
            winner.depth_until,winner.current AND winner.eligible_until>(SELECT at FROM read_clock) current
          FROM upcoming s LEFT JOIN LATERAL (
            SELECT o.value best, """ + NET_EV + """ net_ev,
              CASE WHEN book.projection->>'effective_ev' IS NOT NULL
                  THEN (book.projection->>'effective_ev')::numeric
                WHEN book.projection#>>'{result,size_status}' IN ('partial_size','confirmed_empty','above_limit') THEN 0
                ELSE """ + NET_EV + """ END effective_ev,
              CASE WHEN book.projection IS NOT NULL
                  THEN book.projection->'result' || jsonb_build_object('valid_until',d.valid_until,
                     'published_at',d.published_at,'book_known_at',d.known_at)
                ELSE jsonb_build_object('status','unknown','size_status','unknown',
                  'reason',CASE WHEN d.receipt_id IS NULL THEN 'book_unobserved'
                    WHEN NOT book.current THEN 'stale_book' ELSE 'reference_revision_changed' END,
                  'intended_stake_usd','100') END liquidity,
              CASE WHEN book.projection IS NOT NULL AND book.projection->'result'->>'status'<>'unknown'
                   THEN d.valid_until END depth_until,
              LEAST(s.start_at,(o.value#>>'{calculation_payload,acquisition,received_from}')::timestamptz
                + %s*interval '1 second') eligible_until,
              (NOT s.phase_closed AND (s.confirmed_start IS NULL OR s.confirmed_start=s.start_at)
                AND (o.value#>>'{calculation_payload,acquisition,received_until}')::timestamptz<=%s
                AND COALESCE((o.value#>>'{calculation_payload,fee_mode,enabled}')::boolean,
                  (s.snapshot#>>'{fee_mode,enabled}')::boolean,true)=%s
                AND NOT EXISTS (SELECT 1 FROM public.current_contract_storage known
                  WHERE known.id=o.value#>>'{calculation_payload,id}' AND known.active=false)
                AND NOT EXISTS (SELECT 1 FROM public.current_offer_storage known
                  LEFT JOIN public.sgo_line_presence lp ON lp.quote_id=known.sgo_quote_id
                  WHERE known.contract_id=o.value#>>'{calculation_payload,id}'
                    AND (known.facts->>'state'='unavailable' OR lp.expired))
                AND NOT EXISTS (SELECT 1 FROM public.current_sgo_reference r
                  WHERE r.event_id=s.event_id AND r.bookmaker_id=o.value#>>'{calculation_payload,reference,book}'
                    AND r.facts->>'market'=s.family AND r.facts->>'period'=s.period
                    AND (s.family='moneyline' OR (r.facts->>'line')::numeric=""" + line + """ * CASE
                      WHEN s.family='spread' AND r.facts->>'side'<>o.value#>>'{display_offer,side}' THEN -1 ELSE 1 END)
                    AND """ + reference_known_unavailable('r.id') + """)) current
            FROM jsonb_array_elements(COALESCE(s.snapshot->'offers','[]'::jsonb)) o(value)
            LEFT JOIN public.current_contract_storage identity ON identity.id=o.value#>>'{calculation_payload,id}' AND identity.active
            LEFT JOIN public.current_pregame_depth d ON d.contract_id=identity.id AND d.contract_revision=identity.revision
            LEFT JOIN LATERAL (SELECT d.valid_until>(SELECT at FROM read_clock)
                       AND d.known_at<=(SELECT at FROM read_clock) AND d.published_at<=(SELECT at FROM read_clock) current,
                       CASE WHEN d.valid_until>(SELECT at FROM read_clock) AND d.known_at<=(SELECT at FROM read_clock)
                             AND d.published_at<=(SELECT at FROM read_clock)
                         THEN d.valuations->('dashboard:'||s.pull_id||':'||(o.value#>>'{display_offer,revision}')) END projection
            ) book ON true
            WHERE s.state='complete' AND o.value#>>'{record,market_identity,family}'=s.family
              AND o.value#>>'{record,market_identity,period}'=s.period AND """ + candidates + """
              AND (o.value#>>'{main,status}'='main' OR (book.projection->>'effective_ev')::numeric>0)
          ) winner ON true
          WHERE s.start_at>%s AND (s.confirmed_start IS NULL OR s.confirmed_start>%s)
        ), positive_scopes AS (
          SELECT DISTINCT game_id,start_at,family,period FROM eligible WHERE current AND effective_ev>0
        ), current_offers AS (
          SELECT event_id,family,period,pull_id,game_id,COALESCE(event->>'title',details#>>'{event,title}',event_id) game,
            start_at,league,LEAST(eligible_until,depth_until) eligible_until,best->'display_offer' quote,
            effective_ev::text,liquidity,best#>>'{main,status}' line_role,
            best->>'dashboard_outcome_key' outcome_key,best#>'{calculation_payload,display}' display
          FROM eligible JOIN positive_scopes USING(game_id,start_at,family,period)
          WHERE current
        )
        SELECT COALESCE(bool_or(best IS NOT NULL AND current),false) price_available,
          COALESCE(bool_or(best IS NULL),false) inputs_unavailable,
          COALESCE(bool_or(state<>'complete'),false) pull_incomplete,
          COALESCE(bool_or(net_ev>0 AND NOT current),false) expired_positive,
          (SELECT jsonb_agg(current_offers) FROM current_offers) entries
        FROM eligible"""
    data = db.execute(sql, (at, at, until, *(value for _, value in filters), freshness_seconds, at, read_fee_mode(db)['enabled'],
        *args, at, at)).fetchone()
    offers = sorted(data['entries'] or [], key=lambda value: (
        -Fraction(value['effective_ev']), value['event_id'], value['family'],
        value['quote']['venue'], value['quote']['id'], value['quote']['revision']))
    groups = _dashboard_groups(db, offers)
    rows = [dict(_dashboard_quote(quotes[0]), bet_id=hashed(key),
                 other_quotes=[_dashboard_quote(value) for value in quotes[1:]])
            for key, quotes in groups[offset:offset + limit]]
    return dict(rows=rows, total=len(groups), offset=offset, availability={key:data[key]
        for key in ('price_available','inputs_unavailable','pull_incomplete','expired_positive')})


def dashboard_liquidity(db, detail, *, at, stake='100'):
    """Reprice the exact current Dashboard quote without changing saved evidence."""
    from app.collection.activity_mode import DEFAULT_SETTINGS
    from .current_pregame_depth import _dashboard_inputs, preview, unknown
    from .store import stamp
    from datetime import timedelta

    offer = detail.get('selected_offer') or {}
    payload, record = offer.get('calculation_payload'), offer.get('normalized_record')
    if not payload or not record or offer['calculation']['status'] == 'unavailable':
        return unknown('reference_unavailable', stake=stake), None
    source = record['quote']['source']
    contract = payload['id']
    reference_key = 'dashboard:' + detail['acquisition']['pull_id'] + ':' + offer['revision']
    current = _dashboard_inputs(db, [source['native_event_id']], [contract])
    if not any(row['key'] == reference_key for row in current):
        return unknown('reference_revision_changed', stake=stake), None
    mode = db.execute('SELECT settings FROM public.activity_mode WHERE singleton').fetchone()
    freshness = (mode['settings'] if mode else DEFAULT_SETTINGS)['monitor_interval_seconds']
    if not at < min(stamp(record['event']['scheduled_start']),
                    stamp(payload['acquisition']['received_from'])+timedelta(seconds=freshness)):
        return unknown('reference_stale', stake=stake), None
    return preview(db, payload, record, at=at, stake=stake, evidence=True)

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


def offer(snapshot, value, pull_id, *, family=None, for_projection=False):
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
    if for_projection:
        result['dashboard_outcome_key'] = dashboard_outcome_key(identity)
    return result


def _capture(value):
    snapshot = value.get('snapshot') or {}
    times = snapshot.get('times') or {}
    return dict(pull_id=value['pull_id'], state=value['state'],
        market_id=value['market_id'],
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
        ''' + _game_identity_sql('s','p.started_order','p.details') + '''||'|'||s.family||'|'||s.period market_id,
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
        ''' + _game_identity_sql('s','p.started_order','p.details') + '''||'|'||s.family||'|'||s.period market_id,
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
            if (item.get('facts') or item).get('market')==selected['family']
            and (item.get('facts') or item).get('venue') in SPORTSBOOKS],
        raw_quotes=[item for item in snapshot.get('raw_quotes',[]) if item.get('market')==selected['family']],
        history=[_capture(item) for item in history], snapshot=snapshot,
        acquisition=dict(pull_id=pull_id,request_scope=selected['request_scope'],details=selected['details'],
            coverage=selected['coverage'],state=selected['state']),
        provider_requests=0, scheduled_calculations=0)
