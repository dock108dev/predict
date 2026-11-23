"""Owner-selected reference prices; separate from immutable probability policy.

The selected set bounds ordinary display, future SGO requests and market/book
comparisons. It does not expand the four-book probability/calibration policy.
"""

VERSION = 'sgo-ten-sportsbook-reference-prices-1'
PROVIDER = 'sportsgameodds'
REFERENCE_BOOKS = ('fanduel', 'draftkings', 'betmgm', 'caesars', 'betrivers',
    'hardrockbet', 'bookmakereu', 'betonline', 'bovada', 'williamhill')
TRADING_BOOKS = ('kalshi', 'polymarket', 'novig', 'prophetexchange')
HISTORICAL_TRADING_BOOKS = ('betfairexchange', 'matchbook', 'sporttrade')
REQUEST_BOOKS = (*TRADING_BOOKS, *REFERENCE_BOOKS)
LABELS = {'fanduel': 'FanDuel', 'draftkings': 'DraftKings', 'betmgm': 'BetMGM',
    'caesars': 'Caesars', 'betrivers': 'BetRivers', 'hardrockbet': 'Hard Rock Bet',
    'bookmakereu': 'BookMaker', 'betonline': 'BetOnline', 'bovada': 'Bovada',
    'williamhill': 'William Hill'}


def public_scope():
    from app.comparison.sgo_reference import BEST_BOOKS
    from app.comparison.snapshot_fee_outcome import VENUES
    return dict(version=VERSION, provider=PROVIDER,
        books=[dict(id=book, label=LABELS[book]) for book in REFERENCE_BOOKS],
        trading_venues=list(VENUES), collection_bookmakers=list(REQUEST_BOOKS),
        historical_trading_sources=list(HISTORICAL_TRADING_BOOKS),
        probability_reference_books=list(BEST_BOOKS),
        historical_scope='Other retained prices require explicit historical selection; frozen game policy remains unchanged.')
