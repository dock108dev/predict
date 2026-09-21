"""Offline B3 REST price/quantity reconstruction; no access or clock invention."""
import base64
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
from app.models.core import EvidenceKind
from .native_semantics import purchase_book


def verify(rows):
    seen=set();metadata={};counts={'novig':0,'prophetx':0}
    for row in rows:
        source=row.get('source')
        if source not in counts:continue
        if row['type']=='native_rest_observation':
            raw=base64.b64decode(row['body_b64'],validate=True)
            if sha256(raw).hexdigest()!=row['body_sha256']:raise ValueError('native REST hash mismatch')
            seen.add((source,row['source_url'],datetime.fromisoformat(row['received_at']),raw.decode()))
        if row['type']=='market_selected':
            m=row['market'];metadata[source,m['raw']['ref']['market_id']]=m
        if row['type']!='prediction_book':continue
        b=row['book'];raw=b['raw'];mid=raw['ref']['market_id'];eid=raw['ref']['event_id']
        if (source,raw['source'],datetime.fromisoformat(raw['received_at']),raw['json_text']) not in seen:raise ValueError('book has no preceding native REST response')
        meta=metadata[source,mid];mr=meta['raw']
        if mr['ref']['event_id']!=eid:raise ValueError('market/event identity mismatch')
        if source=='novig':
            from app.adapters.novig import Response,parse_market,OrderImage,decode
            r=Response(mr['json_text'],mr['source'],datetime.fromisoformat(mr['received_at']),EvidenceKind(mr['kind']))
            market=parse_market(r,next(m for m in decode(r.body) if m['id']==mid),eid)
            response=Response(raw['json_text'],raw['source'],datetime.fromisoformat(raw['received_at']),EvidenceKind(raw['kind']))
            image=OrderImage(market);image.snapshot(decode(response.body));native=image.book(response.raw(eid,mid))
        else:
            from app.adapters.prophetx import Response,book,decode,market_key
            response=Response(raw['json_text'],raw['source'],datetime.fromisoformat(raw['received_at']),EvidenceKind(raw['kind']))
            def leaves(items):
                for m in items:
                    if m.get('market_strikes'):yield from leaves(m['market_strikes'])
                    else:yield m
            m=next(m for m in leaves(decode(response.body)['data'][eid]) if market_key(eid,m)==mid)
            native=book(response,eid,m)
        reconstructed=purchase_book(native)
        actual=json.loads(json.dumps(asdict(reconstructed),default=str))
        for key in ('outcomes','quantity_unit','sync','raw'):
            if actual[key]!=b[key]:raise ValueError('native REST reconstruction mismatch: '+key)
        from app.arbitrage import book_observations
        expected={o.quote.outcome_id:o.quote for o in book_observations(reconstructed,environment='production',evidence_class='historical',source_time_semantics='unknown')}
        expected.update({q.outcome_id:q for q in getattr(native,'normalized_quotes',())})
        packets={q['side']:q for p in row['packets'] for q in p['normalized']['quotes']}
        if set(packets)!=set(expected):raise ValueError('native REST quote identities mismatch')
        for side,q in expected.items():
            p=packets[side]
            for name in ('ask','bid'):
                value=getattr(q,name)
                price=None if value is None else str(value.price.value)
                quantity=None if value is None or value.quantity is None else str(value.quantity.value)
                if (p[name],p[name+'_size'])!=(price,quantity):raise ValueError('native REST quote mismatch')
        counts[source]+=1
    return dict(exact_native_rest_books=counts,price_quantity_packets_verified=True,
                limitations='Source-time, stream handoff, fee applicability and settlement are not qualified by replay')
