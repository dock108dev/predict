"""Persist the compact canonical current-price catalog from an exact capture.

The bounded active expanded graphs remain compatibility/calculation projections;
this persistent catalog owns shared game facts and small venue revision history.
It does not calculate fair prices, invent a missing instrument or renew a clock.
"""
from collections import defaultdict
from copy import deepcopy
from .current_prices import CurrentPriceStore
from .store import stamp

def observe_bundle(db,bundle):
    events=bundle['state_inputs']['events']
    if len(events)!=1:return []
    event=events[0]
    game=dict(game_key=bundle['game_key'],sport=event['sport'],league=event.get('league'),
        start_at=event['start_at'],participants=event['participants'],title=event['title'])
    grouped=defaultdict(list)
    for row in bundle['records']:grouped[row['quote']['venue']].append(row)
    out=[]
    for venue,rows in sorted(grouped.items()):
        participants=sorted({r['selection']['participant'] for r in rows if r['selection'].get('predicate')=='win'})
        if len(participants)!=2:continue  # genuine incomplete coverage stays absent
        sides=[]
        for participant in participants:
            instruments=[]
            for r in rows:
                if r['selection']['participant']!=participant:continue
                q=r['quote']
                instruments.append(dict(selection=deepcopy(r['selection']),source=deepcopy(q['source']),
                    original=deepcopy(q['original']),times=deepcopy(q['times']),
                    native_side=q['source'].get('native_side'),depth=deepcopy(q.get('depth'))))
            sides.append(dict(participant=participant,instruments=instruments))
        sources=[r['quote']['times'].get('source_at') for r in rows]
        receipts=[r['quote']['times'].get('received_at') for r in rows]
        receipts=[x for x in receipts if x]
        if not receipts:raise ValueError('compact_price_original_receipt_absent')
        evidence=dict(source_at=max((x for x in sources if x),key=stamp,default=None),
            received_at=max(receipts,key=stamp),source_clock_status='unknown' if any(x is None for x in sources) else 'observed',
            reference_only=venue=='pinnacle')
        # All actual native depth is preserved once per venue revision, instead
        # of copied into each direction/derived scenario report.
        books={}
        originals={item['id']:item['record'] for item in bundle['envelopes']}
        for row in rows if venue in ('kalshi','polymarket_us') else ():
            quote=row['quote'];source=quote['source'];times=quote['times']
            binding=row.get('comparison_source_metadata',{}).get('combined_native_binding',{})
            original=originals.get(binding.get('book_envelope_id'))
            if not original or original.get('source')!=venue or original.get('kind')!='admitted_books':
                raise ValueError('compact_price_native_book_reference_missing')
            candidates=[]
            for observation in original['value']['observations']:
                book=observation['book'];raw=book['raw'];ref=raw['ref']
                if (ref.get('venue'),ref.get('event_id'),ref.get('market_id'))!=(venue,source['native_event_id'],source['native_market_id']):continue
                if raw.get('exchange_at')!=times.get('source_at') or raw['received_at']!=times['received_at']:continue
                value=dict(ref=deepcopy(ref),quantity_unit=book['quantity_unit'],
                    source_at=raw.get('exchange_at'),received_at=raw['received_at'],outcomes=deepcopy(book['outcomes']))
                if value not in candidates:candidates.append(value)
            if len(candidates)!=1:raise ValueError('compact_price_native_book_binding_conflict')
            value=candidates[0];market=source['native_market_id']
            if market in books and books[market]!=value:raise ValueError('compact_price_native_market_identity_conflict')
            books[market]=value
        evidence['native_books']=books if venue in ('kalshi','polymarket_us') else None
        out.append(CurrentPriceStore(db).upsert(game,venue,sides,evidence))
    return out
