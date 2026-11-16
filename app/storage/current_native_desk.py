"""Native prices and their evidence from one committed SQL read."""
from datetime import timedelta
from fractions import Fraction

from app.comparison.cashflows import exact_wire
from app.comparison.public_sportsbook_estimate import select, signature
from app.comparison.snapshot_fee_outcome import outcome, reviews
from app.comparison.snapshot_fee_scope import applicability
from app.comparison.source_clock import NATIVE_BOOK_MAX_AGE_SECONDS
from app.comparison.sporting_scope import supported
from app.comparison.trade_preview import order_step
from app.dashboard.current_contract import price
from app.fees import product_schedules
from app.normalization.registry import Registry
from .current_rows import contract_id, event_id, project_contract, project_quote
from .ordinary_projection import source_allowed
from .store import hashed, stamp


VENUES = ('kalshi', 'polymarket_us')


def active_records(db, *, at, venues, contract=None, phase='pregame', event_ids=None, posted=False):
    # Strict consumers retain the current-book query. The pregame display
    # also reads the last admitted price, including a detached rotated book.
    posted = posted and phase == 'pregame'
    rows = db.execute("""SELECT c.id, c.event_id, o.price_dependency AS price,
                                c.revision AS contract, e.revision AS event,
                                b.id AS book_id, b.revision AS book_revision, b.quantity_units,
                                d.levels->0 AS best_ask
        FROM current_offer_storage o
        JOIN current_contract c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id
        LEFT JOIN native_book_revision b ON b.id=o.native_book_id
        LEFT JOIN native_ladder_revision d ON d.id=b.ladder_refs#>>ARRAY[c.native_outcome_id,'asks']
        WHERE c.venue=ANY(%s) AND e.provider=c.venue
          AND (%s::text IS NULL OR c.id=%s)
          AND (%s::text[] IS NULL OR e.id=ANY(%s))
          AND e.scheduled_start::timestamptz <= %s
          AND (e.scheduled_start::timestamptz > %s) = %s
          AND e.expires_order >= extract(epoch FROM %s::timestamptz)
          AND o.received_order <= extract(epoch FROM %s::timestamptz)
          AND (b.is_current AND b.state='active' AND b.sync='synchronized' AND o.facts->>'state'='available'
               OR %s AND o.facts->>'state'='resyncing' AND o.price_value IS NOT NULL)
          AND (%s OR o.received_order >= extract(epoch FROM %s::timestamptz))""",
        (venues, contract, contract, event_ids, event_ids, at + timedelta(hours=72), at, phase == 'pregame',
         at, at, posted, posted,
         at - timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS))).fetchall()
    if not rows:
        return [], {}, {}
    # These rows already passed the exact native book join. Read the referenced
    # contracts only, using the same normalized offer view as the full capture.
    # Loading frame-wide source states, metadata hashes and unrelated books is
    # unnecessary here. Event facts are read once per event and only inspected.
    events = {row['id']: row['facts'] for row in db.execute(
        'SELECT id,facts FROM current_event WHERE id=ANY(%s)', (list({row['event_id'] for row in rows}),))}
    records = []
    for row in db.execute('''SELECT c.event_id,c.facts AS contract,o.facts AS quote,o.source_at,o.received_at
        FROM current_contract c JOIN current_offer o ON o.contract_id=c.id
        WHERE c.id=ANY(%s) ORDER BY c.id''', ([row['id'] for row in rows],)):
        event = events[row['event_id']]
        records.append(dict(project_contract(event, row['contract'], row['received_at']),
                            event=event, quote=project_quote(row)))
    dependencies = {row['id']: [row[field] for field in ('price', 'contract', 'event')] for row in rows}
    return records, dependencies, {row['id']: row for row in rows}


def supported_occurrence(record):
    event, quote = record['event'], record['quote']
    market = record['market_identity']
    league = event['competition']
    if (quote['state'] not in ('available', 'resyncing') or market['period'] != 'full_game'
            or market['family'] not in ('moneyline', 'spread', 'total')
            or not supported(league, market['family'], market['period'])
            or event.get('conflicting_duplicate') or event.get('occurrence_conflict')
            or event.get('schedule_conflict') or not event.get('home') or not event.get('away')
            or event['home'] == event['away']
            or event.get('source_participant_roles') != {role: event.get(role) for role in ('home', 'away')}):
        return None
    admission = (record.get('comparison_source_metadata') or {}).get('comparison_admission') or {}
    if admission.get('supported') is False and (
            admission.get('reason') != 'comparison_context_missing'
            or not set(admission.get('missing_fields', ())) <= {'season', 'stage'}):
        return None
    return signature(event, league)


def game_signature(game):
    roles = {p['role']: p['id'] for p in game['participants'] if p['role'] in ('away', 'home')}
    if roles.keys() == {'away', 'home'}:
        return game['league'], stamp(game['start_at']), roles['home'], roles['away']
    return None


def game_for(record, occurrence, published, prior, dependencies, registry):
    # Carry an existing occurrence only when its exact contract and event
    # revisions still match. A separate source-local identity covers a new game.
    if prior:
        expected = prior['current_authority']['price'].get('expected') or ()
        game = published.get(prior['game_key'])
        if len(expected) >= 3 and expected[1:3] == dependencies[1:3] and game and game_signature(game) == occurrence:
            return game
    event, source = record['event'], record['quote']['source']
    league, start, home, away = occurrence
    participants = [dict(id=team, role=role, name=registry.entities.get(team, {}).get('name', team))
                    for role, team in (('away', away), ('home', home))]
    # The presence of a sportsbook reference changes EV eligibility without
    # changing the occurrence or its link. Cross-venue aliases are adjudicated
    # from schedule evidence by the desk, independently of reference freshness.
    key = event_id(source['provider'], source['native_event_id'])
    return dict(game_key='native-current:' + key, title=event.get('title') or ' vs. '.join(p['name'] for p in participants),
                league=league, start_at=start.isoformat(), participants=participants)


def carry_published_finance(row, prior):
    """Reuse exact ordinary finance when it covers this same committed quote."""
    if not prior or not prior.get('price_current') or prior.get('trade_fee') != row['trade_fee']:
        return
    previous = prior['current_authority']['price']
    price_authority = row['current_authority']['price']
    if (previous.get('expected') != price_authority['expected']
            or previous.get('clock_at') != price_authority['clock_at']
            or prior['times'] != row['times'] or prior['original'] != row['original']):
        return
    from .comparison_snapshot import expand_row

    prior = expand_row(prior)
    fields = ('probability', 'probability_missing', 'gross_return_percent', 'gross_profit_per_claim',
              'conditional_trade_benchmark', 'conditional_return_percent', 'conservative_trade_benchmark',
              'conservative_return_percent', 'snapshot_benchmark_reason', 'reference_calculation',
              'metric_status', 'same_outcome', 'binding')
    row.update({key: prior[key] for key in fields if key in prior})
    row['current_authority'] = dict(prior['current_authority'], price=price_authority)
    row['economic_revision'] = hashed([row['economic_revision'], prior.get('economic_revision')])


def overlay(db, result, owner, states, *, at, contract=None, phase='pregame', sgo_inputs=None, event_ids=None,
            include_preview_inputs=False):
    """Replace native rows for this view using exact original clocks and pairs.

    The ordinary capture still owns archived evidence and cross-venue pairs.
    No provider request, captured row, or publication pointer is written here.
    """
    from .ordinary_publication import pregame_sportsbooks, quote_authority

    pregame = phase == 'pregame'
    running = owner.get('healthy') and owner.get('active') and not owner.get('global_stopped')
    current_venues = {venue for venue in VENUES if running and source_allowed(states.get(venue, {}))
                      and venue not in owner.get('paused_sources', ())}
    venues = list(VENUES) if pregame else sorted(current_venues)
    if not venues:
        return result
    scope = {} if event_ids is None else {'event_ids': event_ids}
    records, dependencies, books = active_records(db, at=at, venues=venues, contract=contract, phase=phase, posted=pregame, **scope)
    published = {game['game_key']: game for game in result['games']}
    prior_rows = {row['current_authority']['price']['dependency']: row for row in result['rows']
                  if (row.get('source') or {}).get('provider') in VENUES}
    captured = []
    expected_state = 'live' if phase == 'live' else 'scheduled'
    for record in records:
        if (occurrence := supported_occurrence(record)) is None:
            continue
        q = record['quote']
        cid = contract_id(record)
        row = dict(original_record=record, original=q['original'], source=q['source'],
                   venue=q['venue'], league=occurrence[0], times=q['times'])
        authority = quote_authority(row, dict(captured_at=at, dependencies=dependencies))
        reasons = set(authority['reasons'])
        if pregame:
            reasons -= {'source_expired', 'quote_resyncing'}
        if reasons or authority['lifecycle']['state'] != expected_state or not authority['expected']:
            continue
        captured.append((cid, row, authority, occurrence))
    observations = (pregame_sportsbooks(db, owner, states, at, sgo_inputs=sgo_inputs,
                    occurrences={occurrence for _, _, _, occurrence in captured}) if pregame and captured else {})
    registry = Registry.current()
    schedules = reviews(at)
    product_states = owner.get('fee_products') or {}
    blocked = {(row['game_key'], stamp(row['start_at'])) for row in result['rows']
               if row.get('game_state') in ('final', 'cancelled', 'suspended')}
    rows = {}
    for cid, row, authority, occurrence in captured:
        q, record = row['original_record']['quote'], row['original_record']
        market = record['market_identity']
        book = books[cid]
        cost = price(row)
        best = book['best_ask']
        current = row['venue'] in current_venues and not authority['reasons']
        size = (dict(quantity=best[2], quantity_unit=book['quantity_units'],
                     book_id=book['book_id'], book_revision=book['book_revision'])
                if current and best and Fraction(best[0]) == cost and Fraction(best[2]) > 0 else None)
        prior = prior_rows.get(cid)
        game = game_for(record, occurrence, published, prior, dependencies[cid], registry)
        if (game['game_key'], stamp(game['start_at'])) in blocked:
            continue
        published[game['game_key']] = game
        baseline = select(row, dict(authority, reasons=[]), observations, at=at) if pregame else None
        row.update(id='native-current:' + cid, kind='single', game_key=game['game_key'],
            game_title=game['title'], start_at=game['start_at'], live_native_desk=True,
            _desk_event=record['event'],
            market=dict(market='winner' if market['family'] == 'moneyline' else market['family'],
                        period=market['period'], line=market.get('line')),
            selection=dict({'result_interpretation': 'normal_win'}, **record['selection']),
            price_current=current, posted_price=pregame, game_state=authority['lifecycle']['state'],
            game_state_basis=authority['lifecycle'].get('basis'),
            game_state_observed_at=authority['lifecycle'].get('observed_at'), current_reasons=authority['reasons'],
            current_authority=dict(price=authority, references=[]),
            book_confirmation=q.get('book_confirmation'), captured_at=at.isoformat(),
            price_revision=hashed([*dependencies[cid], authority['clock_at']]),
            sportsbook_baseline=baseline, sportsbook_return_percent=baseline['return_percent'] if baseline else None,
            cost_per_normal_claim=exact_wire(cost), book_size=size,
            alternate=(record.get('comparison_source_metadata') or {}).get('alternate'))
        fee_input = dict(row, fee_applicability=applicability(record))
        review = product_schedules.for_offer(product_states, fee_input, at, fallback=schedules[row['venue']])
        step = order_step(fee_input) if pregame and row['venue'] == 'polymarket_us' else None
        quantity = step if step and step > 0 and 1 % step else '1'
        row['trade_fee'] = outcome(fee_input, at=at, phase=row['game_state'], review=review, quantity=quantity)
        row['economic_revision'] = hashed([baseline, row['trade_fee'], size])
        if current:
            carry_published_finance(row, prior)
        if pregame and (contract is not None or include_preview_inputs):
            row['preview_fee_input'] = fee_input['fee_applicability']
        if contract is not None:
            from app.comparison.inspection_math import offer_disclosures, offer_math

            original = dict(record, original_record=record, id=row['id'])
            row['native_inspection'] = dict(offer_math(row), **offer_disclosures(row, at.isoformat(), [original]))
        row.pop('original_record')
        rows[cid] = row
    retained = [row for row in result['rows']
                if row['current_authority']['price'].get('dependency') not in rows
                and not (pregame and row.get('game_state') == 'scheduled'
                         and (row.get('source') or {}).get('provider') in VENUES)]
    visible = retained + list(rows.values())
    current_prices = sum(bool(row.get('price_current')) for row in visible)
    return dict(result, rows=visible, games=list(published.values()),
                publication=dict(result['publication'], current_prices=current_prices, retained_prices=len(visible)-current_prices))
