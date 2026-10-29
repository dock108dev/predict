"""Independent native quote slots and deduplicated aggregate route identities.

Slots include empty/unavailable ladders. Synthetic purchase complements are not
additional source-native quotes. No received-only count claims a complete census.
"""
from decimal import Decimal, InvalidOperation
from app.comparison.offered_scope import identity


def native_slots(source, metadata):
    if source == 'kalshi':
        return [('yes','bids'),('no','bids')]
    sides=metadata.get('marketSides')
    if not isinstance(sides,list):
        return None
    long=[s for s in sides if isinstance(s,dict) and s.get('long') is True and s.get('id') is not None]
    if len(long)!=1:
        return None
    return [(str(long[0]['id']),'bids'),(str(long[0]['id']),'asks')]


def native_boundary(source, metadata, image):
    slots=native_slots(source,metadata)
    result=dict(expected_slots=None if slots is None else len(slots),offered=0,empty=0,
                unavailable=0,missing=0,units=[])
    if slots is None:
        result['reason']='listing_native_outcome_identity_missing'
        return result
    outcomes={str(o['outcome_id']):o for o in (image or {}).get('outcomes',[])}
    for outcome,side in slots:
        ladder=outcomes.get(outcome,{}).get(side)
        state=('missing_image' if image is None else 'unavailable_side' if ladder is None
               else 'offered' if ladder.get('levels') else 'empty_book_side')
        key={'missing_image':'missing','unavailable_side':'unavailable','offered':'offered','empty_book_side':'empty'}[state]
        result[key]+=1
        result['units'].append(dict(outcome=outcome,side=side,disposition=state,
            source_representation='native_bid' if source=='kalshi' or side=='bids' else 'native_offer'))
    result['transformations']=(['yes ask = 1 - no bid','no ask = 1 - yes bid'] if source=='kalshi'
                               else ['short ask = 1 - long bid'])
    return result


def aggregate_units(events, venue, family, route):
    keys={'h2h':'moneyline','spreads':'spread','alternate_spreads':'spread','totals':'total','alternate_totals':'total'}
    units={}
    for event in events:
        for book in event.get('bookmakers',[]):
            if book.get('key')!=venue:
                continue
            for market in book.get('markets',[]):
                if keys.get(market.get('key'))!=family:
                    continue
                for outcome in market.get('outcomes',[]):
                    line=outcome.get('point')
                    try:
                        if line is not None:
                            number=Decimal(str(line))
                            if not number.is_finite():raise InvalidOperation()
                            line=str(number.normalize()) if number else '0'
                    except InvalidOperation:
                        line='invalid:'+str(line)
                    uid=identity(venue,event.get('id'),family,'full_game',outcome.get('name'),line,'bookmaker_outcome')
                    units[uid]=dict(event_id=event.get('id'),outcome=outcome.get('name'),line=line,
                        period='full_game',representation='bookmaker_outcome',routes=[route],
                        disposition='offered' if outcome.get('price') is not None else 'absent_quote')
    return units


def merge_units(target, incoming):
    for uid,row in incoming.items():
        if uid not in target:
            target[uid]=row
        else:
            old=target[uid]
            old['routes']=sorted(set(old['routes']+row['routes']))
            if old['disposition']!=row['disposition']:
                old['disposition']='route_quote_presence_conflict'
    return target
