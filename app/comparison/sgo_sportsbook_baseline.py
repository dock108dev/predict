"""The best same-market sportsbook payout with its own two-sided de-vig."""
from datetime import timedelta
from fractions import Fraction

from app.collection.current_benchmark import proportional_probability
from app.storage.store import stamp
from .cashflows import exact_wire
from .game_phase import LIVE_SECONDS, PREGAME_SPORTSBOOK_SECONDS, original_price_phase
from .public_sportsbook_estimate import outcome
from .sgo_reference import BEST_BOOKS, OPPOSITE, american_probability
from .sgo_reference_publication import captured_frame, exact_line

BOOKS = BEST_BOOKS


def select(record, rows, frame, *, at, index=None):
    """Compare a source-local SGO offer with books from the same event frame."""
    quote = record['quote']
    source = quote['source']
    if (source['provider'] != 'sportsgameodds' or quote['state'] != 'available'
            or quote['original']['units'] != 'american_odds'):
        return None
    phase = original_price_phase(record, at)
    if phase['reason'] or phase['state'] not in ('live', 'scheduled'):
        return None
    market = record['market_identity']['family']
    if phase['state'] == 'scheduled' and (record['market_identity']['period'] != 'full_game'
            or not outcome(market, record['selection'], record['event']['home'], record['event']['away'])):
        return None
    selected_line = source.get('native_line')
    wanted = source['native_outcome_id']
    opposing = record['comparison_source_metadata'].get('provider_opposing_odd_id')
    if not opposing or wanted == opposing:
        return None
    if index is not None:
        try:
            chosen = exact_line(selected_line)
            opposite_line = -chosen if market == 'spread' and chosen is not None else chosen
            target_rows = index.selection(wanted, chosen)
            offer_rows = index.selection(wanted, record['selection'].get('signed_line'))
            rows = (*target_rows, *index.selection(opposing, opposite_line))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None
    else:
        offer_rows = rows
    observed = captured_frame(record, {'frame': frame, 'rows': offer_rows}, index=index)
    if observed is None:
        return None
    facts = frame['facts']
    members = index.members if index is not None else dict(facts['members'])
    captured = stamp(at)
    received = stamp(observed['frame_received_at'])
    start = stamp(record['event']['scheduled_start'])
    live = phase['state'] == 'live'
    if received > captured or (received >= start) != live:
        return None
    lifetime = timedelta(seconds=LIVE_SECONDS if live else PREGAME_SPORTSBOOK_SECONDS)
    book_rows = {book: [] for book in BOOKS}
    for entry in rows:
        fact = entry['facts']
        book = fact.get('venue')
        if (book not in book_rows or members.get(entry['id']) != entry['revision']
                or fact.get('provider') != 'sportsgameodds'
                or fact.get('event_id') != source['native_event_id']
                or fact.get('league') != record['event']['competition']
                or fact.get('market') != market or fact.get('period') != 'game'
                or fact.get('phase') != ('live' if live else 'pregame')
                or fact.get('available') is not True or not fact.get('source_at')
                or fact.get('odd_id') not in (wanted, opposing)):
            continue
        try:
            line = None if fact['line'] is None else Fraction(fact['line'])
            chosen_line = None if selected_line is None else Fraction(selected_line)
            target_line = -chosen_line if market == 'spread' and fact['odd_id'] == opposing else chosen_line
            clock = stamp(fact['source_at'])
            original_receipt = stamp(fact['received_at'])
            implied = american_probability(fact['price_american'])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        if (line == target_line and (clock >= start) == live
                and clock <= original_receipt <= received and captured <= clock + lifetime):
            book_rows[book].append((fact, implied, clock))
    candidates = []
    for book, prices in book_rows.items():
        if len(prices) != 2:
            continue
        by_odd = {fact['odd_id']: (fact, implied, clock) for fact, implied, clock in prices}
        if set(by_odd) != {wanted, opposing}:
            continue
        target, other = by_odd[wanted], by_odd[opposing]
        if (target[0].get('opposing_odd_id') != opposing or other[0].get('opposing_odd_id') != wanted
                or OPPOSITE.get(target[0].get('side')) != other[0].get('side')):
            continue
        candidates.append((target[1], book, target, other))
    if not candidates:
        return None
    _, book, target, other = min(candidates, key=lambda item: (item[0], BOOKS.index(item[1])))
    fair = proportional_probability([1 / target[1], 1 / other[1]], 0)
    cost = american_probability(quote['original']['value'])
    deadline = min(target[2], other[2]) + lifetime if live else min(
        min(selected[2], opposing[2]) for _, _, selected, opposing in candidates) + lifetime
    book_prices = {
        venue: [{key: leg[0][key] for key in ('price_american', 'source_at', 'side', 'line')}
                for leg in (selected, opposing)]
        for _, venue, selected, opposing in candidates
    }
    return dict(book=book, candidate_books=len(candidates), frame_id=observed['frame_id'],
                frame_received_at=observed['frame_received_at'],
                current_until=(deadline if live else min(deadline, start)).isoformat(),
                probability=exact_wire(fair), fair_decimal_odds=exact_wire(1 / fair),
                return_percent=exact_wire(100 * (fair / cost - 1)),
                prices=book_prices[book], candidates=book_prices)


def current(baseline, dependency, *, at):
    return bool(dependency and dependency[3].endswith(':' + baseline['frame_id'])
                and at <= stamp(baseline['current_until']))
