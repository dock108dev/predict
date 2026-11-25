"""Read-only browsing of stored acquisitions, original responses and results."""

import asyncio
from datetime import date, timedelta
import re
from zoneinfo import ZoneInfo

from aiohttp import web

from app.collection import original_receipts
from app.collection.sportsgameodds_adapter import parse_page
from app.storage.acquisition_snapshot import read_snapshot
from app.storage.market_board import offer
from app.storage.mens_d1_coverage import PUBLIC_SOURCE, SOURCE
from app.storage.store import connect, encoded, stamp
from .local_security import HEADERS, PublicRequestError

PAGE_SIZE = 25
RECORD_PAGE_SIZE = 50
FILTERS = {'date', 'sport', 'search', 'event_id', 'provider', 'original_bookmaker_id', 'family'}
EASTERN = ZoneInfo("America/New_York")
EASTERN_DATE = "((%s)::timestamptz AT TIME ZONE 'America/New_York')::date"


def entry_page(rows, offset, limit=PAGE_SIZE):
    return dict(rows=rows[:limit], offset=offset,
                next_offset=offset + limit if len(rows) > limit else None, provider_requests=0)


def like(term):
    return '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def pull_page(db, query):
    where, params = [], []
    scoped, scope_params = [], []
    if query.get('provider') not in (None, 'sportsgameodds'):
        return entry_page([], query['offset'])
    scope_start = "COALESCE(s.snapshot#>>'{event,scheduled_start}',p.details#>>'{event,starts_at}')"
    league = "COALESCE(s.snapshot#>>'{event,competition}',p.details#>>'{event,league}',p.request_scope->>'leagueID')"
    title = "COALESCE(s.snapshot#>>'{event,title}',p.details#>>'{event,title}',s.event_id)"
    if query.get('date'):
        scoped.append((EASTERN_DATE % scope_start) + '=%s::date')
        scope_params.append(query['date'])
    if query.get('sport'):
        scoped.append(league + '=%s')
        scope_params.append(query['sport'])
    if query.get('search'):
        scoped.append(f"({title} ILIKE %s OR s.event_id ILIKE %s)")
        scope_params.extend([like(query['search'])] * 2)
    if query.get('event_id'):
        scoped.append('s.event_id=%s')
        scope_params.append(query['event_id'])
    if query.get('family'):
        scoped.append('s.family=%s')
        scope_params.append(query['family'])
    if scoped:
        predicate = ('EXISTS (SELECT 1 FROM public.market_pull_scope s WHERE s.pull_id=p.pull_id AND '
                     + ' AND '.join(scoped) + ')')
        params.extend(scope_params)
        # Discovery pulls lack per-game scopes. Their request date and league
        # describe the attempt, while exact records are filtered after opening.
        if not any(query.get(key) for key in ('search', 'event_id', 'family')):
            discovery = ["p.request_scope ? 'leagueID'",
                         'NOT EXISTS (SELECT 1 FROM public.market_pull_scope s WHERE s.pull_id=p.pull_id)']
            if query.get('date'):
                discovery.append("p.requested_at >= (%s::date::timestamp AT TIME ZONE 'America/New_York')")
                discovery.append("p.requested_at < (%s::date::timestamp AT TIME ZONE 'America/New_York')")
                params.extend((query['date'], (date.fromisoformat(query['date']) + timedelta(days=1)).isoformat()))
            if query.get('sport'):
                discovery.append("%s=ANY(string_to_array(p.request_scope->>'leagueID',','))")
                params.append(query['sport'])
            predicate = '(' + predicate + ' OR (' + ' AND '.join(discovery) + '))'
        where.append(predicate)
    if query.get('original_bookmaker_id'):
        where.append("%s=ANY(string_to_array(p.request_scope->>'bookmakerID',','))")
        params.append(query['original_bookmaker_id'])
    rows = db.execute("""
        SELECT p.pull_id,p.requested_at,p.state,p.details->'event' AS event,
            p.details->>'reason' AS reason,p.request_scope->>'leagueID' AS league,
            p.request_scope->>'eventIDs' AS event_ids
        FROM public.market_pull p
        """ + ('WHERE ' + ' AND '.join(where) if where else '') + """
        ORDER BY p.started_order DESC LIMIT %s OFFSET %s
        """, (*params, PAGE_SIZE + 1, query['offset'])).fetchall()
    for row in rows:
        row['requested_at'] = row['requested_at'].isoformat()
    return entry_page(rows, query['offset'])


def matching_quote(row, query):
    for key, field in (('sport', 'league'), ('event_id', 'event_id')):
        if query.get(key) and query[key] != row.get(field):
            return False
    if query.get('search') and query['search'].casefold() not in (
            f"{row.get('game', '')} {row.get('event_id', '')}".casefold()):
        return False
    if query.get('date') and row.get('starts_at'):
        if stamp(row['starts_at']).astimezone(EASTERN).date().isoformat() != query['date']:
            return False
    if query.get('family') and row.get('family') != query['family']:
        return False
    if query.get('original_bookmaker_id') and row.get('original_bookmaker_id') != query['original_bookmaker_id']:
        return False
    return query.get('provider') in (None, 'sportsgameodds')


def source_quote(quote, event):
    side = quote.get('side')
    names = event.get('teams') or {}
    participant = (names.get(side) or {}).get('name')
    return dict(game=event.get('title'), event_id=quote.get('event_id'), league=quote.get('league'),
                starts_at=event.get('starts_at'), family=quote.get('market'),
                original_bookmaker_id=quote.get('venue'), selection=participant or side,
                line=quote.get('line'), price=quote.get('price_american'), price_units='american_odds',
                available=quote.get('available'), reason=quote.get('unavailable_reason'),
                received_at=quote.get('received_at'), source_at=quote.get('source_at'),
                alternate=quote.get('alternate'), record=quote)


def selected_pull(db, query):
    pull = db.execute("""
        SELECT p.pull_id,p.requested_at,p.state,p.details,p.request_scope,e.sha256,e.raw_bytes
        FROM public.market_pull p LEFT JOIN public.market_pull_evidence e USING (pull_id)
        WHERE p.pull_id=%s
        """, (query['pull'],)).fetchone()
    if not pull:
        raise web.HTTPNotFound(reason='This acquisition attempt is unavailable.')
    pull['requested_at'] = pull['requested_at'].isoformat()
    offset = query['offset']
    receipts = db.execute("""
        SELECT attempt_id,receipt_sha256,received_at,membership
        FROM public.market_pull_receipt WHERE pull_id=%s
        ORDER BY received_at,attempt_id LIMIT %s OFFSET %s
        """, (query['pull'], PAGE_SIZE + 1, query['receipt_offset'])).fetchall()
    extra = len(receipts) > PAGE_SIZE
    receipts = receipts[:PAGE_SIZE]
    for receipt in receipts:
        retained = original_receipts.lookup(receipt['receipt_sha256'])
        # A repeated body hash does not identify the physical request clock.
        exact = next((item for item in retained['captures']
                      if item['state'] == 'retained' and stamp(item['received_at']) == receipt['received_at']), None)
        receipt['received_at'] = receipt['received_at'].isoformat()
        receipt['original'] = exact if retained['state'] == 'retained' and exact else None
        receipt['retention_reason'] = (None if receipt['original']
                                       else retained.get('reason') or 'exact_receipt_clock_unavailable')
    rows = []
    if pull['sha256']:
        snapshot = read_snapshot(db, query['pull'])
        event = snapshot.get('event') or {}
        source = snapshot.get('source_event') or {}
        declared = pull['details'].get('event') or {}
        quote_event = dict(title=event.get('title') or declared.get('title'), teams=source.get('teams') or {},
                           starts_at=event.get('scheduled_start') or declared.get('starts_at'))
        event_id = declared.get('source_event_id') or pull['request_scope'].get('eventIDs')
        league = event.get('competition') or declared.get('league')
        for item in snapshot.get('offers', []):
            value = offer(snapshot, item, query['pull'])
            row = dict(game=quote_event['title'], event_id=event_id, league=league, starts_at=quote_event['starts_at'],
                       family=value['family'], selection=value['outcome'],
                       original_bookmaker_id=value['original_bookmaker_id'], price=value['price'],
                       price_units=value['price_units'], available=value['available'],
                       line=value['line'], received_at=value['times'].get('received_at'),
                       source_at=value['times'].get('source_at'), alternate=value['main_role']=='alternate',
                       calculation=value['calculation'], record=value)
            if matching_quote(row, query):
                rows.append(row)
        for quote in snapshot.get('raw_quotes', []):
            row = source_quote(quote, quote_event)
            if matching_quote(row, query):
                rows.append(row)
    value = entry_page(rows[offset:offset + RECORD_PAGE_SIZE + 1], offset, RECORD_PAGE_SIZE)
    return dict(value, pull=pull, receipts=receipts, total_records=len(rows),
                receipt_offset=query['receipt_offset'],
                next_receipt_offset=query['receipt_offset'] + PAGE_SIZE if extra else None)


def original_page(query, *, download=False):
    try:
        metadata, body = original_receipts.read(query['id'])
    except (KeyError, OSError, ValueError) as error:
        raise web.HTTPNotFound(reason='Exact original response bytes are unavailable.') from error
    if download:
        return body
    offset = query['offset']
    try:
        page = parse_page(body, metadata['received_at'])
    except ValueError:
        return dict(entry_page([], offset), receipt=metadata, total_records=0,
                    reason='The current parser cannot read this retained response. Original bytes are available.')
    events = {}
    for event in page.events:
        names = event['teams']
        events[event['event_id']] = dict(event, title=f"{names['away']['name']} at {names['home']['name']}")
    rows = []
    for quote in page.quotes:
        event = events[quote['event_id']]
        row = source_quote(quote, event)
        if matching_quote(row, query):
            rows.append(row)
    return dict(entry_page(rows[offset:offset + RECORD_PAGE_SIZE + 1], offset, RECORD_PAGE_SIZE),
                receipt=metadata, total_records=len(rows), events=len(events))


def result_page(db, query):
    from app.research.experiment import _closure, _value

    params = []
    branches = []
    provider = query.get('provider')
    if provider in (None, 'sportsgameodds'):
        selected = ['outcome_id IS NOT NULL', "provider='sportsgameodds'"]
        if query.get('date'):
            selected.append((EASTERN_DATE % "(event->>'starts_at')") + '=%s::date')
            params.append(query['date'])
        if query.get('sport'):
            selected.append("event->>'league'=%s")
            params.append(query['sport'])
        if query.get('id'):
            selected.append('id=%s')
            params.append(query['id'])
        branches.append("""
            SELECT id,source_event_id,provider AS source,event->>'title' AS title,
                event->>'league' AS league,event->>'starts_at' AS starts_at,event,outcome_id,
                NULL::text AS receipt_id,first_observed_at AS sort_at
            FROM public.ev_experiment_game WHERE """ + ' AND '.join(selected))
    if provider in (None, PUBLIC_SOURCE, SOURCE) and query.get('sport') in (None, 'NCAAB') and not query.get('id'):
        selected = ["kind IN ('results','detail')"]
        if query.get('date'):
            selected.append('game_date=%s::date')
            params.append(query['date'])
        if provider:
            selected.append('source=%s')
            params.append(provider)
        branches.append("""
            SELECT id,source_event_id,source,title,'NCAAB' AS league,starts_at,event,
                   NULL::text AS outcome_id,receipt_id,sort_at
            FROM (
                SELECT DISTINCT ON (r.source,r.kind,g->>'source_game_id')
                    r.id || ':' || (g->>'source_game_id') AS id,
                    g->>'source_game_id' AS source_event_id,r.source,
                    COALESCE((SELECT string_agg(t->>'name',' vs ' ORDER BY n)
                        FROM jsonb_array_elements(g->'teams') WITH ORDINALITY AS team(t,n)),
                        g->>'source_game_id') AS title,
                    g->>'scheduled_start' AS starts_at, g AS event,r.receipt_id,r.observed_at AS sort_at
                FROM public.mens_d1_revision r CROSS JOIN LATERAL jsonb_array_elements(r.facts) AS g
                WHERE """ + ' AND '.join(selected) + """
                ORDER BY r.source,r.kind,g->>'source_game_id',r.observed_at DESC,r.immutable_sequence DESC
            ) source_results
        """)
    offset = query['offset']
    if not branches:
        return entry_page([], offset)
    selected = []
    if query.get('event_id'):
        selected.append('source_event_id=%s')
        params.append(query['event_id'])
    if query.get('search'):
        selected.append('(title ILIKE %s OR source_event_id ILIKE %s)')
        params.extend([like(query['search'])] * 2)
    rows = db.execute("SELECT * FROM (" + ' UNION ALL '.join(branches) + ') results '
                      + (' WHERE ' + ' AND '.join(selected) if selected else '')
                      + " ORDER BY sort_at DESC,id LIMIT %s OFFSET %s",
                      (*params, PAGE_SIZE + 1, offset)).fetchall()
    index = _closure(db, [row['outcome_id'] for row in rows[:PAGE_SIZE] if row['outcome_id']])
    for row in rows[:PAGE_SIZE]:
        observed_at = row.pop('sort_at').isoformat()
        if row['outcome_id']:
            row['outcome'] = _value(index[row['outcome_id']], index)
            row['original'] = _original_for_result(row['outcome'].get('data') or {})
        else:
            event = row['event']
            row['outcome'] = dict(data=dict(result=event.get('status'), source=row['source'],
                final=event.get('status') == 'final', observed_at=observed_at, teams=event.get('teams')))
    return entry_page(rows, offset)


def _original_for_result(data):
    if data.get('source') != 'sportsgameodds' or not data.get('observed_at'):
        return None
    retained = original_receipts.lookup(data.get('receipt_sha256'))
    if retained['state'] != 'retained':
        return None
    return next((item['id'] for item in retained['captures'] if item['state'] == 'retained'
                 and stamp(item['received_at']) == stamp(data['observed_at'])), None)


def mount(app, connector=connect):
    gate = asyncio.Semaphore(3)
    handlers = {'pulls': pull_page, 'pull': selected_pull, 'results': result_page}

    async def read(request):
        from app.owned_work import joined_thread

        view = request.match_info['view']
        fields = {
            'pulls': FILTERS | {'offset'},
            'pull': FILTERS | {'pull', 'offset', 'receipt_offset'},
            'results': FILTERS - {'original_bookmaker_id', 'family'} | {'offset', 'id'},
            'original': FILTERS | {'id', 'offset', 'download'},
        }[view]
        query = dict(request.query)
        if (query.keys() - fields or len(query) != len(request.query)
                or any(not value or len(value) > 200 for value in query.values())):
            raise PublicRequestError('Invalid research data filters.')
        try:
            if query.get('date'):
                day = date.fromisoformat(query['date'])
                if day.isoformat() != query['date'] or day == date.max:
                    raise ValueError()
            for field in ('offset', 'receipt_offset'):
                raw = query.get(field, '0')
                if not re.fullmatch(r'[0-9]{1,7}', raw):
                    raise ValueError()
                query[field] = int(raw)
        except ValueError:
            raise PublicRequestError('Use a date in YYYY-MM-DD format and a valid page.') from None
        if view == 'pull' and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', query.get('pull', '')):
            raise PublicRequestError('Select a recorded pull.')
        if view == 'original' and not re.fullmatch(r'[0-9a-f]{64}', query.get('id', '')):
            raise PublicRequestError('Select an original receipt identity.')
        if query.get('download') not in (None, '1'):
            raise PublicRequestError('Invalid original response download.')

        def work():
            if view == 'original':
                return original_page(query, download=query.get('download') == '1')
            with connector() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                db.execute("SET LOCAL statement_timeout='10s'")
                return handlers[view](db, query)

        if gate.locked():
            raise web.HTTPTooManyRequests(reason='Stored reads are busy. Retry shortly.')
        async with gate:
            value = await joined_thread(__name__, 'data_browse_after_cancellation', work)
        if query.get('download'):
            return web.Response(body=value, content_type='application/json', headers={
                **HEADERS, 'Content-Disposition': f'attachment; filename="predict-original-{query["id"]}.json"',
            })
        return web.Response(body=encoded(value), content_type='application/json', headers=HEADERS)

    app.router.add_get('/api/research/data/{view:pulls|pull|original|results}', read, allow_head=False)
