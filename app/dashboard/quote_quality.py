"""Read-only Admin comparison of retained native and aggregate observations."""
import asyncio
from fractions import Fraction

from aiohttp import web

from app.collection.sportsgameodds_current_rows import linked_event_ids
from app.comparison.sgo_reference import BEST_BOOKS
from app.storage.sportsgameodds_reference import read_event, read_event_frame
from app.storage.store import connect
from .local_security import PublicRequestError
from .snapshot_display import odds
from .trade_desk import sportsbook_selection

BOOKS = {'kalshi': 'kalshi', 'polymarket_us': 'polymarket'}


def compare(db, event_id):
    event = db.execute("""SELECT native_event_id, competition, scheduled_start,
                                 facts->>'home' AS home, facts->>'away' AS away,
                                 facts->>'title' AS title
                          FROM current_event
                          WHERE provider='sportsgameodds' AND native_event_id=%s""", (event_id,)).fetchone()
    frame = read_event_frame(db, event_id)
    if not event or not frame:
        raise PublicRequestError('Select an event with a retained SportsGameOdds frame.')
    facts = frame['facts']
    members = dict(facts['members'])
    links = (facts.get('event_context') or {}).get('bookmaker_event_links') or {}
    kalshi_id = linked_event_ids(links).get('kalshi_event')
    aggregate = {book: [] for book in BOOKS.values()}
    references = {book: [] for book in BEST_BOOKS}
    try:
        observations = read_event(db, event_id, bookmakers=(*BOOKS.values(), *BEST_BOOKS))
    except ValueError:
        raise PublicRequestError('This event exceeds the diagnostic read capacity.') from None
    for row in observations:
        fact = row['facts']
        if fact['period'] == 'game' and members.get(row['id']) == row['revision']:
            collection = aggregate if fact['venue'] in aggregate else references
            collection[fact['venue']].append({k: fact.get(k) for k in (
                'odd_id', 'market', 'side', 'line', 'price_american', 'source_at', 'received_at', 'available',
                'fair', 'consensus', 'bookmaker_market_link')})

    quotes = db.execute("""SELECT e.provider, e.native_event_id, c.native_market_id, c.native_outcome_id,
                                  c.native_side, c.facts->'market_identity' AS market,
                                  c.facts->'selection' AS selection, o.price_value, o.price_units,
                                  o.facts->'original'->>'payout' AS payout, o.source_at, o.received_at,
                                  o.facts->>'state' AS state
                           FROM current_event e JOIN current_contract c ON c.event_id=e.id
                           JOIN current_offer o ON o.contract_id=c.id
                           WHERE e.provider IN ('kalshi','polymarket_us') AND c.venue=e.provider
                             AND e.competition=%s AND e.scheduled_start::timestamptz=%s::timestamptz
                             AND e.facts->>'home'=%s AND e.facts->>'away'=%s
                           ORDER BY e.provider,c.native_market_id,c.native_outcome_id,c.native_side LIMIT 501""",
                        (event['competition'], event['scheduled_start'], event['home'], event['away'])).fetchall()
    rows = []
    roles = {event['home']: 'home', event['away']: 'away'}
    for quote in quotes[:500]:
        provider = quote['provider']
        market = quote['market']
        family = 'winner' if market['family'] == 'moneyline' else market['family']
        key = sportsbook_selection(dict(market=dict(market=family, period=market['period']),
                                        selection=quote['selection']), roles)
        candidates = [fact for fact in aggregate[BOOKS[provider]]
                      if key and key == (fact['market'], fact['side'],
                                        None if fact['line'] is None else Fraction(fact['line']))]
        link_status = ('polymarket_us_unverified' if provider == 'polymarket_us' else
                       'provider_event_link' if quote['native_event_id'] == kalshi_id else 'schedule_and_teams')
        contract_status = ('unverified' if provider == 'polymarket_us' or link_status != 'provider_event_link'
                           else 'exact_side_and_line_only') if candidates else 'unobserved'
        rows.append(dict(native=quote, aggregate=candidates, event_match=link_status, contract_match=contract_status,
                         native_american=odds(quote['price_value'], quote['price_units'], quote['payout'])['american']))
    return dict(event=event, aggregate_received_at=facts['received_at'], links=links, rows=rows,
                aggregate_counts={book: len(items) for book, items in aggregate.items()},
                aggregate_observations=aggregate, sportsbook_observations=references,
                truncated=len(quotes) > 500, provider_requests=0)


def mount(app):
    async def quality(request):
        if set(request.query) - {'event_id'}:
            raise PublicRequestError('Select a retained event.')
        event_id = request.query.get('event_id', '')
        if len(event_id) > 256:
            raise PublicRequestError('Invalid event identity.')

        def read():
            with connect() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                if event_id:
                    return compare(db, event_id)
                events = db.execute("""SELECT e.native_event_id AS id, e.competition AS league,
                                              e.scheduled_start AS start, e.facts->>'title' AS title
                                       FROM current_sgo_event_frame f JOIN current_event e
                                         ON e.provider='sportsgameodds' AND e.native_event_id=f.event_id
                                       ORDER BY f.received_order DESC, e.native_event_id LIMIT 250""").fetchall()
                return dict(events=events, provider_requests=0)

        return web.json_response(await asyncio.to_thread(read))

    app.router.add_get('/api/admin/quote-quality', quality)
