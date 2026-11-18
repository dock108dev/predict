"""Exact line eligibility for ordinary desk lists and retained comparisons."""
from fractions import Fraction
from functools import lru_cache

from app.comparison.sgo_reference import BEST_BOOKS

from .snapshot_display import outcome_id
from .u0_display import quote_display


@lru_cache(maxsize=2048)
def quote_supported(value, units, payout):
    """Reuse the formatter's support predicate for identical price inputs."""
    return quote_display(value, units, payout)['supported']


def quote_places(group, *, retained=False, minimum_places=3):
    """Count quotes for this exact outcome, once per exchange or sportsbook."""
    books = {
        book for book, prices in group['sportsbook_quotes'].items() if book in BEST_BOOKS
        and any((retained or price.get('current')) and price.get('price_american') not in (None, 0, '0') for price in prices)}
    offers = [quote for quote in group['offers'] if retained or quote['current']]
    if not retained and len(books | {quote['venue'] for quote in offers}) < minimum_places:
        return set()
    for quote in offers:
        original = quote['original']
        inputs = original['value'], original['units'], original.get('payout', '1')
        if all(isinstance(part, str) for part in inputs) and quote_supported(*inputs):
            books.add(quote['venue'])
    return books


def main_line_key(group, roles):
    market = group['market']
    family = market['market']
    selection = group['offers'][0]['selection'] or {}
    line = selection.get('signed_line')
    if family in ('spread', 'total') and line is not None:
        line = Fraction(line)
        if family == 'spread':
            participant = selection.get('participant')
            role = group.get('line_participant_role') or roles.get(participant)
            # Express both spread sides as the home team's handicap.
            line = ('home', -line if role == 'away' else line) if role else (participant, line)
    return (group['game_key'], market['period'], family), line


def line_role(row):
    alternate = row.get('alternate')
    source = row.get('source') or {}
    if alternate is None:
        if (source.get('native_market_id') or '').startswith('alternate:'):
            alternate = True
        elif source.get('provider') in ('sportsgameodds', 'oddslink_public_board'):
            # Legacy SGO publication wrote the boolean for alternates only.
            # Its adapter emits the root bookmaker entry before altLines.
            alternate = False
    return alternate


def published_lines(groups, games, *, alternates, requested=None):
    """Resolve roles from the complete slate, without pricing or rank inputs."""
    participants = {game['game_key']: {p['id']: p['role'] for p in game['participants']
                    if p.get('id') and p.get('role') in ('home', 'away')} for game in games}
    markets, group_lines = {}, {}
    for key, rows in groups.items():
        row = rows[0]
        market, line = main_line_key(dict(row, offers=[row]), participants.get(row['game_key'], {}))
        if market[2] in ('spread', 'total'):
            group_lines[key] = market, line
            featured, unknown = markets.setdefault(market, {}).setdefault(line, (set(), set()))
            for quote in rows:
                role = line_role(quote)
                if role is False:
                    featured.add(quote['venue'])
                elif role is None:
                    unknown.add(quote['venue'])
                baseline = quote.get('sportsbook_baseline') or {}
                pair = baseline.get('prices') or ()
                if baseline.get('book') in BEST_BOOKS and len(pair) == 2 and all(
                        price.get('alternate') is False for price in pair):
                    featured.add(baseline['book'])

    mains = {}
    for market, lines in markets.items():
        strength = max(len(evidence[0]) for evidence in lines.values())
        strongest = [line for line, (featured, _) in lines.items() if strength and len(featured) == strength]
        if len(strongest) == 1:
            mains[market] = strongest[0]

    eligible, roles = {}, {}
    for key, rows in groups.items():
        identifier = outcome_id(key)
        if key not in group_lines:
            eligible[key] = rows
            continue
        market, line = group_lines[key]
        featured, unknown = markets[market][line]
        role = ('main' if line == mains[market] else 'alternate') if market in mains else (
            'unknown' if featured or unknown else 'alternate')
        roles[identifier] = role
        if alternates or role == 'main' or identifier == requested:
            eligible[key] = rows
    return eligible, roles


def comparable_groups(groups, games, *, alternates, requested, retained=False, minimum_places=3):
    roles = {game['game_key']: {p['id']: p['role'] for p in game['participants']
                              if p.get('id') and p.get('role') in ('home', 'away')} for game in games}
    eligible, lines = [], {}
    for group in groups:
        current = quote_places(group, minimum_places=minimum_places)
        places = quote_places(group, retained=True) if retained else current
        if not places or not retained and len(current) < minimum_places:
            continue
        market, line = main_line_key(group, roles.get(group['game_key'], {}))
        eligible.append((group, market, line))
        live_places, line_places, featured = lines.setdefault(market, {}).setdefault(line, (set(), set(), set()))
        live_places.update(current)
        line_places.update(places)
        featured.update(quote['venue'] for quote in group['offers']
                        if quote['current'] and quote['venue'] in places and quote['alternate'] is not True)
        featured.update(book for book, prices in group['sportsbook_quotes'].items() if book in places
                        and any(price.get('current') and price.get('alternate') is False for price in prices))
    # Widest coverage wins. Break ties with featured exchange prices, then a
    # stable line key. Never use EV to select the line we show.
    mains = {market: min(choices, key=lambda line: (
        -len(choices[line][0]), -len(choices[line][1]), -len(choices[line][2]), repr(line)))
        for market, choices in lines.items()}
    return [group['id'] for group, market, line in eligible
            if alternates or line == mains[market] or group['id'] == requested]
