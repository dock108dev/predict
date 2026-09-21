"""B3 purchase interpretation, separate from immutable legacy replay semantics."""
from dataclasses import replace
from decimal import Decimal, localcontext
from app.models.core import BookLevel, Ladder, Probability, Quantity

SEMANTICS = {
    'kalshi': dict(price='1 minus opposite bid', quantity='contracts', fees='Kalshi pinned schedule; event override and account precision required', settlement='listing-specific; exceptional outcomes may remain unknown'),
    'polymarket_us': dict(price='Long offers; Short = 1 minus Long bid', quantity='contracts', fees='US pinned schedule and retained coefficient', settlement='US listing-specific; settlement charge unknown unless explicitly assumed'),
    'novig': dict(price='1 minus opposite outcome bid', quantity='CASH payout cents / 100 = contracts', fees='Novig schedule; applicability/account terms unverified', settlement='listing-specific contract association unverified'),
    'prophetx': dict(price='American odds converted to payout probability', quantity='unknown; neither quantity nor value used for sizing', fees='ProphetX applicability unverified', settlement='listing-specific terms unverified'),
}


def purchase_book(book):
    """Retain raw bytes and clocks. Never promote depth or synchronization."""
    venue = book.raw.ref.venue.value
    if venue not in ('novig', 'polymarket_us'):
        return book
    if len(book.outcomes) != 2:
        raise ValueError('binary purchase conversion requires two native outcomes')
    with localcontext() as ctx:
        ctx.prec = 100
        def convert(ladder, complement=False):
            if ladder is None:
                return None
            levels = []
            for level in ladder.levels:
                unit = level.quantity.unit
                expected = 'payout_cents' if venue == 'novig' else 'contracts'
                if unit != expected:
                    raise ValueError('native quantity unit mismatch')
                q = level.quantity.value / (Decimal(100) if venue == 'novig' else Decimal(1))
                p = Decimal(1)-level.price.value if complement else level.price.value
                levels.append(BookLevel(price=Probability(value=p), quantity=Quantity(value=q, unit='contracts')))
            return Ladder(depth=ladder.depth, levels=tuple(sorted(levels,key=lambda x:x.price.value,reverse=not complement)))
        a,b = book.outcomes
        if venue == 'novig':
            sides = (replace(a,bids=convert(a.bids),asks=convert(b.bids,True)),
                     replace(b,bids=convert(b.bids),asks=convert(a.bids,True)))
        else:
            # parse_book fixes the first outcome to native marketSides.long=True.
            sides = (a,replace(b,asks=convert(a.bids,True)))
        return replace(book,outcomes=sides,quantity_unit='contracts')
