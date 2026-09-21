"""Wholly synthetic NBX example; no network or credentials."""
import json
from datetime import datetime, timezone
from app.adapters.novig import Response, parse_market, OrderImage, quotes
from app.models.core import EvidenceKind

MARKET={'id':'synthetic-market','eventId':'synthetic-event','description':'Synthetic away at home',
    'type':'MONEY','status':'OPEN','outcomeIds':['home','away'],
    'outcomes':[{'id':'home','description':'Home'},{'id':'away','description':'Away'}]}

def order(id='o1',qty='100',price='0.550'):
    return {'id':id,'marketId':'synthetic-market','outcomeId':'home','price':price,
            'qty':qty,'originalQty':'100','currency':'CASH','status':'RESTING',
            'created_at':'2026-01-01T00:00:00Z'}

def snapshot():
    return {'marketId':'synthetic-market','marketDescription':'Synthetic',
        'outcomeLadders':[{'outcomeId':'home','bids':[order(),order('o2','200')]},
                          {'outcomeId':'away','bids':[]}]}

def response(d):
    return Response(json.dumps(d),'synthetic:novig',datetime.now(timezone.utc),EvidenceKind.SYNTHETIC)

def main():
    m=parse_market(response(MARKET),MARKET,'synthetic-event'); image=OrderImage(m)
    image.snapshot(snapshot()); image.tick('PLACE',order(qty='40'))
    book=image.book(response({'type':'PLACE','order':order(qty='40')}).raw('synthetic-event','synthetic-market'))
    print('SYNTHETIC NBX: 100 payout cents = one $1 payout contract; probability prices unchanged.')
    print('Two orders aggregate to 240 payout cents after replacement, not 340.')
    print(book); print(quotes(book))
    print('Depth and snapshot/tick ordering guarantees UNKNOWN. No live qualification.')

if __name__=='__main__': main()
