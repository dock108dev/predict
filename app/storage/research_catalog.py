"""Read-only received-data catalog, independent of price/fee/EV admission.

Current SGO observations include reference-only books and withdrawn lines. Native
inputs that have not reached normalized storage remain inspectable as raw books.
This catalog never acquires data or recalculates an input during a browser read.
"""

from fractions import Fraction

from psycopg.types.json import Jsonb

from app.comparison.snapshot_fee_outcome import VENUES as TRADING_VENUES
from app.comparison.reference_scope import HISTORICAL_TRADING_BOOKS, REFERENCE_BOOKS

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
 CASE WHEN q.bookmaker_id='polymarket' AND COALESCE(linked.fees_enabled,'true')<>'false' THEN 'provider_venue_fee_applicability_unestablished'
  ELSE linked.reason END reason,
 CASE WHEN q.bookmaker_id='polymarket' AND COALESCE(linked.fees_enabled,'true')<>'false' THEN NULL ELSE linked.net_ev END net_ev,
 linked.input_revision calculation_revision,(q.facts->>'starts_at')::timestamptz start_at
FROM sgo_quote_revision q
LEFT JOIN (
 SELECT DISTINCT ON (o.sgo_quote_id,o.sgo_quote_revision)
  o.sgo_quote_id,o.sgo_quote_revision,c.id contract_id,k.reason,k.net_ev,k.input_revision,
  COALESCE(k.payload#>>'{fee_mode,enabled}',p.payload#>>'{fee_mode,enabled}',
    p.fee_input#>>'{fee_mode,enabled}') fees_enabled
 FROM current_offer_storage o JOIN current_contract_storage c ON c.id=o.contract_id
 LEFT JOIN current_pregame_calculation k ON k.contract_id=c.id
 LEFT JOIN current_pregame_price p ON p.contract_id=c.id
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
 CASE WHEN e.provider='sportsgameodds' AND c.venue='polymarket_us' AND COALESCE(k.payload#>>'{fee_mode,enabled}',p.payload#>>'{fee_mode,enabled}',p.fee_input#>>'{fee_mode,enabled}','true')<>'false'
  THEN 'provider_venue_fee_applicability_unestablished' ELSE k.reason END,
 CASE WHEN e.provider='sportsgameodds' AND c.venue='polymarket_us' AND COALESCE(k.payload#>>'{fee_mode,enabled}',p.payload#>>'{fee_mode,enabled}',p.fee_input#>>'{fee_mode,enabled}','true')<>'false' THEN NULL ELSE k.net_ev END,
 k.input_revision,e.scheduled_start::timestamptz
FROM current_contract_storage c JOIN current_event e ON e.id=c.event_id
JOIN current_offer_storage o ON o.contract_id=c.id
LEFT JOIN current_pregame_calculation k ON k.contract_id=c.id
LEFT JOIN current_pregame_price p ON p.contract_id=c.id
WHERE e.provider<>'sportsgameodds' OR o.sgo_quote_id IS NULL
UNION ALL
SELECT 'raw:'||h.kind||':'||h.venue||':'||h.sport||':'||h.event_id||':'||h.market_id,
 'raw',CASE WHEN h.kind='native' THEN h.venue ELSE 'the_odds_api' END,
 h.venue,h.venue,h.event_id,h.market_id,h.sport,h.family,h.period,h.title,
 h.received_at,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,
 NULL::numeric,NULL::text,NULL::timestamptz
FROM (""" + raw_prices.HEADER + """) h
WHERE NOT EXISTS (
 SELECT 1 FROM current_contract_storage c JOIN current_event e ON e.id=c.event_id
 JOIN current_offer_storage o ON o.contract_id=c.id
 WHERE e.provider=CASE WHEN h.kind='native' THEN h.venue ELSE 'the_odds_api' END
 AND e.native_event_id=h.event_id AND c.venue=h.venue
 AND c.native_market_id=h.market_id AND o.received_at::timestamptz=h.received_at)
"""

# The calculation owner has already resolved occurrences and conflicts. Reuse
# that identity; a matching title or kickoff is never a grouping authority.
EVENT_IDENTITIES = """
SELECT e.provider,e.native_event_id,
 min(e.scheduled_start::timestamptz) start_at,
 CASE WHEN count(DISTINCT k.game_key)=1
   AND NOT bool_or(COALESCE(k.reason,'') IN
     ('occurrence_identity_conflict','occurrence_conflict','occurrence_schedule_conflict'))
   THEN min(k.game_key) END game_key
FROM current_event e
LEFT JOIN current_contract_storage c ON c.event_id=e.id
LEFT JOIN current_pregame_calculation k ON k.contract_id=c.id
GROUP BY e.provider,e.native_event_id
"""

CATALOG = """SELECT source.*,
 COALESCE('canonical:'||identity.game_key,'source:'||source.provider||':'||source.event_id) game_id,
 COALESCE(source.start_at,identity.start_at) game_start_at
FROM (""" + SOURCES + """) source
LEFT JOIN (""" + EVENT_IDENTITIES + """) identity
 ON identity.provider=source.provider AND identity.native_event_id=source.event_id
 AND (source.start_at IS NULL OR source.start_at=identity.start_at)
"""

# Frozen checkpoint games remain reachable after current working rows expire.
# Metadata contributes no received quote, calculation, or fictitious bookmaker.
GAME_POPULATION = """SELECT catalog.*,true is_observation FROM (""" + CATALOG + """) catalog
UNION ALL
SELECT NULL::text,'experiment',g.provider,NULL::text,NULL::text,g.source_event_id,
 NULL::text,g.event->>'league',NULL::text,NULL::text,g.event->>'title',
 NULL::timestamptz,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,
 NULL::numeric,NULL::text,(g.event->>'starts_at')::timestamptz,
 COALESCE('canonical:'||identity.game_key,'source:'||g.provider||':'||g.source_event_id),
 (g.event->>'starts_at')::timestamptz,false
FROM public.ev_experiment_game g
LEFT JOIN (""" + EVENT_IDENTITIES + """) identity
 ON identity.provider=g.provider AND identity.native_event_id=g.source_event_id
 AND (g.event->>'starts_at')::timestamptz=identity.start_at
"""

STATUS = """CASE WHEN venue IS NULL THEN 'unavailable'
 WHEN venue IN (""" + ','.join("'" + venue + "'" for venue in HISTORICAL_TRADING_BOOKS) + """) THEN 'unavailable'
 WHEN venue NOT IN (""" + ','.join("'" + venue + "'" for venue in TRADING_VENUES) + """) THEN 'reference_only'
 WHEN net_ev>0 THEN 'positive' WHEN net_ev<0 THEN 'negative'
 WHEN net_ev=0 THEN 'zero' ELSE 'unavailable' END"""
FILTERS = ('provider', 'original_bookmaker_id', 'sport', 'family', 'event_id')
READ_FILTERS = (*FILTERS, 'search', 'calculation_status', 'max_age_minutes', 'date', 'reference_scope',
                'include_alternates', 'sort')
SCOPED_SELECTIONS = ('game_id', 'contract_id', 'exact_bet_id')


def selection(filters):
    clauses, args = [], []
    if filters.get('reference_scope') != 'all':
        clauses.append("(kind='experiment' OR venue=ANY(%s) OR original_bookmaker_id=ANY(%s))")
        args.extend((list(TRADING_VENUES), list(REFERENCE_BOOKS)))
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
    if filters.get('date'):
        clauses.append("(game_start_at AT TIME ZONE 'America/New_York')::date=%s::date")
        args.append(filters['date'])
    if filters.get('game_id'):
        clauses.append('game_id=%s')
        args.append(filters['game_id'])
    if filters.get('contract_id'):
        clauses.append('contract_id=%s')
        args.append(filters['contract_id'])
    if filters.get('exact_bet_id'):
        clauses.append('contract_id IN (SELECT contract_id FROM current_pregame_calculation WHERE bet_id=%s)')
        args.append(filters['exact_bet_id'])
    return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), args


def headers(db, filters, *, offset=0, limit=50, entry_id=None):
    clause, args = selection(filters)
    if entry_id is not None:
        clause += (' AND ' if clause else ' WHERE ') + 'id=%s'
        args.append(entry_id)
    return db.execute('SELECT *,transaction_timestamp() snapshot_at FROM (' + CATALOG + ') catalog' + clause +
        ' ORDER BY received_at DESC,id LIMIT %s OFFSET %s', (*args, limit, offset)).fetchall()


def counts(db, filters):
    clause, args = selection(filters)
    row = db.execute('SELECT count(*) records,count(DISTINCT (provider,event_id)) source_events,'
        'count(DISTINCT event_id) event_identifiers FROM (' + CATALOG + ') catalog' + clause, args).fetchone()
    row['event_count_meaning'] = 'Source-event identities; cross-provider events may overlap.'
    return row


def _grouped_games(filters):
    context_filters = dict(filters)
    calculation_status = context_filters.pop('calculation_status', None)
    clause, args = selection(context_filters)
    qualification = ''
    if calculation_status:
        qualification = ' WHERE game_id IN (SELECT game_id FROM scoped WHERE is_observation AND trading_status=%s)'
        args.append(calculation_status)
    trading_ids = ','.join("'" + venue + "'" for venue in (*TRADING_VENUES, *HISTORICAL_TRADING_BOOKS))
    return """WITH scoped AS (SELECT *,""" + STATUS + " AS trading_status FROM (" + GAME_POPULATION + ") population" + clause + "), selected AS (SELECT * FROM scoped" + qualification + """),
      games AS (SELECT game_id id,min(title) title,min(sport) sport,min(game_start_at) start_at,
        count(*) FILTER(WHERE is_observation) records,
        jsonb_build_object(
          'positive',count(*) FILTER(WHERE is_observation AND trading_status='positive'),
          'negative',count(*) FILTER(WHERE is_observation AND trading_status='negative'),
          'zero',count(*) FILTER(WHERE is_observation AND trading_status='zero'),
          'unavailable',count(*) FILTER(WHERE is_observation AND trading_status='unavailable'),
          'reference_only',count(*) FILTER(WHERE is_observation AND trading_status='reference_only')) calculation_counts,
        max(net_ev) FILTER(WHERE is_observation AND trading_status IN ('positive','negative','zero')) best_net_ev,
        array_agg(DISTINCT original_bookmaker_id ORDER BY original_bookmaker_id)
          FILTER(WHERE original_bookmaker_id IS NOT NULL) books,
        array_agg(DISTINCT original_bookmaker_id ORDER BY original_bookmaker_id)
          FILTER(WHERE is_observation AND original_bookmaker_id IS NOT NULL AND venue IN (""" + trading_ids + """)) trading_books,
        array_agg(DISTINCT original_bookmaker_id ORDER BY original_bookmaker_id)
          FILTER(WHERE is_observation AND original_bookmaker_id IS NOT NULL AND venue NOT IN (""" + trading_ids + """)) reference_books,
        array_agg(DISTINCT family ORDER BY family) FILTER(WHERE family IS NOT NULL) markets,
        array_agg(DISTINCT provider ORDER BY provider) providers,
        jsonb_agg(DISTINCT jsonb_build_object('provider',provider,'event_id',event_id)) source_events,
        max(received_at) latest_received_at
      FROM selected GROUP BY game_id) """, args


def game_counts(db, filters):
    query, args = _grouped_games(filters)
    return db.execute(query + "SELECT count(*) games,count(*) FILTER(WHERE id LIKE 'canonical:%%') canonical_games,"
        "count(*) FILTER(WHERE id LIKE 'source:%%') source_local_games FROM games", args).fetchone()


def games(db, filters, *, offset=0, limit=50):
    query, args = _grouped_games(filters)
    rows = db.execute(query + 'SELECT * FROM games ORDER BY latest_received_at DESC NULLS LAST,start_at DESC NULLS LAST,id LIMIT %s OFFSET %s',
        (*args, limit, offset)).fetchall()
    from app.research.experiment import _revision
    for row in rows:
        row['identity_status'] = 'canonical' if row['id'].startswith('canonical:') else 'source_local'
        row['books'] = row['books'] or []
        row['trading_books'] = row['trading_books'] or []
        row['reference_books'] = row['reference_books'] or []
        row['trading_book_count'] = len(row['trading_books'])
        row['reference_book_count'] = len(row['reference_books'])
        best = row.pop('best_net_ev')
        row['best_net_ev_percent'] = str(Fraction(str(best))*100) if best is not None else None
        row['calculation_summary_scope'] = 'All calculation statuses for the game within the other selected filters. Status filters qualify games; numeric EV applies only to trading-market offers.'
        row['markets'] = row['markets'] or []
        for key in ('start_at', 'latest_received_at'):
            row[key] = row[key].isoformat() if row[key] else None
        members = row['source_events']
        experiment = db.execute('''SELECT g.* FROM public.ev_experiment_game g
            JOIN jsonb_to_recordset(%s) member(provider text,event_id text)
              ON member.provider=g.provider AND member.event_id=g.source_event_id
            ORDER BY g.first_observed_at,g.id LIMIT 1''',
            (Jsonb(members),)).fetchone()
        row['experiment'] = dict(id=experiment['id'], revision=_revision(db, experiment)) if experiment else None
        row['revision'] = hashed(row)
    return rows


def checkpoint_source_match(db, header, source_input):
    """Link an expired current SGO input to immutable exact checkpoint evidence.

    This is a source tuple lookup, not normalization or a financial calculation.
    Different settlement identities for one source tuple make the link refuse.
    The current record keeps its independent source-local identity.
    """
    from app.collection.sportsgameodds_current_rows import source_bookmaker
    from app.comparison.current_pregame import reference_key
    from app.research import experiment
    from app.research.ev_movement import exact_bet_identity

    game = db.execute('''SELECT * FROM public.ev_experiment_game
        WHERE provider=%s AND source_event_id=%s''',
        (header['provider'], header['event_id'])).fetchone()
    if not game:
        return None, 'no_retained_checkpoint_game'
    roots = [game[key] for key in ('early_id', 'late_id', 'baseline_correction_id') if game.get(key)]
    index = experiment._closure(db, roots)
    matches, checkpoints = {}, []
    for label in ('early', 'late'):
        checkpoint = experiment._checkpoint_view(db, game, label, index)
        if checkpoint.get('status') not in (None, 'captured', 'complete'):
            continue
        for offer in (checkpoint.get('snapshot') or {}).get('offers', []):
            record = offer['record']
            source = record['quote']['source']
            family, side, _ = reference_key(record)
            line = record['selection'].get('signed_line') if family != 'moneyline' else None
            expected_line = source_input.get('line') if source_input['market'] != 'moneyline' else None
            if (source['provider'] != header['provider']
                    or source['native_event_id'] != header['event_id']
                    or source.get('native_outcome_id') != header['market_id']
                    or source_bookmaker(record) != header['original_bookmaker_id']
                    or family != source_input['market'] or side != source_input['side']
                    or record['market_identity']['period'] != ('full_game' if source_input['period'] == 'game' else source_input['period'])
                    or (line is None) != (expected_line is None)
                    or line is not None and Fraction(str(line)) != Fraction(str(expected_line))):
                continue
            identity = exact_bet_identity(record)
            matches[identity['id']] = identity
            checkpoints.append(label)
    if len(matches) != 1:
        return None, 'checkpoint_source_identity_ambiguous' if matches else 'exact_source_line_not_in_checkpoint_offers'
    identity = next(iter(matches.values()))
    return dict(id=identity['id'], game_id=game['id'], revision=experiment._revision(db, game),
        checkpoints=sorted(set(checkpoints)), identity=identity,
        scope='Exact retained provider/event/book/market/outcome/line tuple; current source-local identity remains unchanged.'), None


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
            k.payload,k.reason,k.version,k.input_revision,k.calculated_at,k.valid_until,k.bet_id,
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
    trading_market = header['venue'] in TRADING_VENUES
    trading_side = trading_market or header['original_bookmaker_id'] in HISTORICAL_TRADING_BOOKS
    from app.comparison.snapshot_fee_scope import provider_venue_fee_reason
    fee_mode = ((payload or {}).get('fee_mode') or
        ((stored['price_payload'] or {}).get('fee_mode') if stored else None) or
        ((stored['fee_input'] or {}).get('fee_mode') if stored else None))
    if fee_mode is None and payload:
        from app.comparison.fee_mode import mode_for_fee
        fee_mode = mode_for_fee(stored['fee_input'] or {})
    applicability_reason = (None if fee_mode and fee_mode.get('enabled') is False else
        provider_venue_fee_reason(dict(quote=dict(
            source=dict(provider=header['provider']), venue=header['venue']))))
    historical_conditional = payload if applicability_reason and trading_market else None
    if applicability_reason or not trading_market:
        payload = None
    state = calculation_state(payload,
        applicability_reason or (stored['reason'] if stored else None), contract_id=cid)
    if not trading_market:
        state = dict(status='unavailable' if trading_side else 'reference_only', net_ev_percent=None, net_ev_ratio=None,
            display=None, reason='unsupported_trading_venue' if trading_side else 'reference_price_only')
    state['evidence_scope'] = ('stored_calculation; catalog grants no execution authority' if trading_market else
        'unsupported_trading_price_only; no trading EV result' if trading_side else 'reference_price_only; no trading EV result')
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
    alternate = ((source_input or {}).get('alternate') if kind == 'sgo' else
        (stored['contract'].get('comparison_source_metadata') or {}).get('alternate') if stored else None)
    result = dict(id=header['id'], revision=revision, kind=kind,
        fee_mode=fee_mode if trading_market else None,
        provider=header['provider'], original_bookmaker_id=original,
        represented_venue=header['venue'], venue_equivalence=equivalence,
        trading_role='prediction_market' if trading_side else 'reference_only',
        event_id=header['event_id'], source_market_id=header['market_id'],
        sport=header['sport'], family=header['family'], period=header['period'], title=header['title'],
        game_id=header['game_id'], start_at=header['game_start_at'].isoformat() if header['game_start_at'] else None,
        main_role='alternate' if alternate is True else 'main' if alternate is False else 'unknown',
        exact_bet_id=stored['bet_id'] if stored else None,
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
        if applicability_reason and cid and trading_market:
            from app.research.records import conditional_history
            history = conditional_history(db, cid, limit=1)
            if historical_conditional is None and history:
                historical_conditional = history[0]['original_calculation']
        normalized = stored['record'] if stored else None
        if stored and normalized is None:
            from .current_rows import project_contract, project_quote
            normalized = dict(project_contract(stored['event'], stored['contract'], stored['received_at']),
                event=stored['event'], quote=project_quote(stored))
        checkpoint_bet_id, checkpoint_identity_reason = None, None
        checkpoint_match = None
        if normalized and trading_market:
            from app.research.ev_movement import exact_bet_identity
            try:
                checkpoint_bet_id = exact_bet_identity(normalized)['id']
            except (ValueError, KeyError, TypeError) as exc:
                checkpoint_identity_reason = str(exc)
        elif kind == 'sgo' and trading_market:
            checkpoint_match, checkpoint_identity_reason = checkpoint_source_match(db, header, source_input)
            if checkpoint_match:
                checkpoint_bet_id = checkpoint_match['id']
        elif not trading_market:
            checkpoint_identity_reason = 'unsupported_trading_venue' if trading_side else 'reference_price_only'
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
            checkpoint_bet_id=checkpoint_bet_id, checkpoint_identity_reason=checkpoint_identity_reason,
            checkpoint_match=checkpoint_match,
            contract=stored['contract'] if stored else None,
            event=stored['event'] if stored else None,
            fee_input=stored['fee_input'] if stored and not applicability_reason and trading_market else None,
            calculation_payload=payload,
            price_payload=stored['price_payload'] if stored and not applicability_reason and trading_market else None,
            historical_conditional_calculation=historical_conditional,
            historical_conditional_history=history,
            reproduction='Exact source, identity, fee and calculation revisions from the captured read. '
                'Unknown fees, probability inputs and settlement remain null/unavailable.')
    return result
