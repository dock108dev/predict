"""Native purchase interpretation, separate from immutable legacy replay semantics."""
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


def purchase_saved_book(row, outcomes):
    """Versioned derived view of a validated saved US image; originals remain intact.

    Rehydrate the shared immutable model and call purchase_book, rather than
    maintaining a second complement or quantity engine for historical captures.
    """
    from dataclasses import asdict
    import json
    from datetime import datetime
    from app.models.core import (OrderBook,OutcomeBook,RawPayload,NativeRef,Venue,
        EvidenceKind,MarketState,BookSync,ReceiptFreshness,SourceTimeProgress,Depth)
    b=row['book'];raw=b['raw'];ref=raw['ref']
    if ref['venue']!='polymarket_us':return row
    long=[n for n,s in outcomes.items() if s.get('native_direction')=='long']
    if len(long)!=1 or len(b['outcomes'])!=2 or b['outcomes'][0]['outcome_id']!=long[0]:raise ValueError('Saved US Long orientation differs from explicit review')
    def ladder(value):
        if value is None:return None
        return Ladder(depth=Depth(value['depth']),levels=tuple(BookLevel(price=Probability(value=Decimal(x['price']['value'])),quantity=Quantity(value=Decimal(x['quantity']['value']),unit=x['quantity']['unit'])) for x in value['levels']))
    model=OrderBook(raw=RawPayload(ref=NativeRef(venue=Venue(ref['venue']),event_id=ref['event_id'],market_id=ref['market_id']),source=raw['source'],received_at=datetime.fromisoformat(raw['received_at']),json_text=raw['json_text'],exchange_at=None if not raw.get('exchange_at') else datetime.fromisoformat(raw['exchange_at']),kind=EvidenceKind(raw['kind'])),quantity_unit=b['quantity_unit'],outcomes=tuple(OutcomeBook(outcome_id=o['outcome_id'],bids=ladder(o['bids']),asks=ladder(o['asks'])) for o in b['outcomes']),state=MarketState(b['state']),sync=BookSync(b['sync']),receipt_freshness=ReceiptFreshness(b['receipt_freshness']),source_time_progress=SourceTimeProgress(b['source_time_progress']),sequence=b['sequence'])
    derived=purchase_book(model)
    from app.arbitrage import book_observations
    from app.storage.workflow import packet
    import base64
    packets=[]
    for observation in book_observations(derived,environment='production' if raw['kind']=='observation' else 'synthetic',evidence_class='current' if raw['kind']=='observation' else 'synthetic',source_time_semantics='unknown'):
        value=packet(observation);value['raw_b64']=base64.b64encode(value.pop('raw')).decode();packets.append(value)
    return dict(row,book=json.loads(json.dumps(asdict(derived),default=str)),packets=packets)
