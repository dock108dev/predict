"""SGO's implemented request/parser/projection boundary, never observed coverage."""
VERSION = 'sgo-capabilities-1'
LEAGUES = frozenset(('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'))
MARKET_TYPES = {'ml': 'moneyline', 'ml3way': 'moneyline', 'sp': 'spread', 'ou': 'total'}
CORE_ODD_IDS = frozenset(('points-home-game-ml-home', 'points-away-game-ml-away',
                         'points-home-game-sp-home', 'points-away-game-sp-away',
                         'points-all-game-ou-over', 'points-all-game-ou-under'))
PROPHETX_BOOKMAKER_ID = 'prophetexchange'
CURRENT_BOOKS = frozenset(('novig', PROPHETX_BOOKMAKER_ID, 'prophetx', 'pinnacle',
                           'kalshi', 'polymarket'))
DISPLAY_NAMES = {PROPHETX_BOOKMAKER_ID: 'prophetx', 'polymarket': 'polymarket_us'}


def supported_odd(odd):
    """Exact participant/stat/period/partition boundary shared with the parser."""
    if not isinstance(odd, dict) or odd.get('periodID') != 'game' or odd.get('statID') != 'points':
        return False
    typ, side, entity = odd.get('betTypeID'), odd.get('sideID'), odd.get('statEntityID')
    if typ in ('ml', 'sp'):
        return side in ('home', 'away') and entity == side
    if typ == 'ml3way':
        return side in ('home', 'away') and entity == side or side == 'draw' and entity in ('all', 'draw')
    return typ == 'ou' and side in ('over', 'under') and entity == 'all'


def book_capability(book):
    represented = DISPLAY_NAMES.get(book, book)
    return dict(version=VERSION, provider='sportsgameodds', original_bookmaker_id=book,
                represented_venue=represented if book in CURRENT_BOOKS else None,
                normalized_reference_supported=True, ordinary_offer_projection=book in CURRENT_BOOKS,
                venue_equivalence='unestablished' if book == 'polymarket' else
                'provider_alias' if book in DISPLAY_NAMES else 'source_identity_only',
                scope=dict(statistic='points', participant='team', period='game',
                           markets=['moneyline', 'spread', 'total']),
                execution_and_settlement='not_established_by_capability')


def catalog():
    return dict(version=VERSION, leagues=sorted(LEAGUES), requested_odd_ids=sorted(CORE_ODD_IDS),
                parser_market_types=dict(MARKET_TYPES), normalized_statistic='points',
                normalized_period='game', ordinary_projected_books=sorted(CURRENT_BOOKS),
                original_response_retention='separately_bounded',
                game_results=dict(supported='final_full_game_team_points',
                                  venue_settlement=False, player_props=False),
                player_markets='not_requested_or_calculation_supported')
