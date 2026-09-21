"""Offline native frame replay; saved receipts used, no economics or network."""
import base64
from dataclasses import asdict, replace
from datetime import datetime
import json
from app.models.core import EvidenceKind, ReceiptFreshness
from app.adapters.kalshi import Response as KR, parse_market as km
from app.adapters.polymarket_us import Response as PR, parse_market as pm
from app.adapters.kalshi_stream import BookReconstructor, RecoveryRequired
from app.adapters.polymarket_us_stream import MarketStream
from .transport_session import reopen


def verify_native(path):
    return verify_native_saved(reopen(path))

def verify_native_saved(saved):
    engines={}; markets={}; last={}; counts={'kalshi':0,'polymarket_us':0}; gaps=[]
    kind=EvidenceKind.OBSERVATION if saved['rows'][0].get('spec',{}).get('mode')=='real' else EvidenceKind.SYNTHETIC
    def dump(book):return json.loads(json.dumps(asdict(book),default=str))
    for row in saved['rows']:
        venue=row.get('source')
        if row['type']=='market_selected' and venue not in engines:
            m=row['market'];raw=m['raw'];r=(KR if venue=='kalshi' else PR)(raw['json_text'],raw['source'],datetime.fromisoformat(raw['received_at']),kind)
            payload=json.loads(raw['json_text']);mid=raw['ref']['market_id'];eid=raw['ref']['event_id']
            if venue=='kalshi':
                market=km(r,next(x for x in payload['markets'] if x['ticker']==mid),eid,'KXNFLGAME')
                markets.setdefault(venue,{})[mid]=market
            else:
                native = payload.get('markets') if 'markets' in payload else [x for e in payload['events'] for x in e.get('markets',[])]
                market=pm(r,next(x for x in native if str(x['id'])==mid),eid)
                markets.setdefault(venue,{})[mid]=market
        elif row['type']=='prediction_command':
            command=json.loads(row['body'])
            if venue not in engines:
                engines[venue]=(BookReconstructor(list(markets[venue].values()),kind=kind) if venue=='kalshi' else MarketStream(list(markets[venue].values()),None,kind=kind))
            e=engines[venue]
            if venue=='kalshi':e.begin(command['id'])
            else:e.begin_subscription(command['subscribe']['requestId'])
            last.pop(venue,None)
        elif row['type']=='prediction_frame':
            e=engines[venue];body=base64.b64decode(row['body_b64']).decode()
            try:
                book=(e.feed(body,e.generation,datetime.fromisoformat(row['received_at'])) if venue=='kalshi' else e.parse(body,e.subscription_id,generation=e.generation))
                if book is not None:
                    last[venue]=book
            except (ValueError,RecoveryRequired):
                gaps.append(dict(source=venue,ingress_id=row.get('ingress_id'),reason='native_frame_rejected'))
                last.pop(venue,None)
        elif row['type']=='prediction_book':
            expected=row['book']
            if expected['sync']!='synchronized' or expected['receipt_freshness']!='recent':continue
            if venue not in last:raise ValueError('saved book has no replayable native image')
            book=last[venue]
            # Native parsers sample wall time after recv; that exact saved clock is replay input.
            book=replace(book,raw=replace(book.raw,received_at=datetime.fromisoformat(expected['raw']['received_at'])),receipt_freshness=ReceiptFreshness.RECENT)
            if dump(book)!=expected:raise ValueError('native book replay mismatch: '+venue)
            counts[venue]+=1
            # Verify derived quote packets too, using the existing converter.
            from app.arbitrage import book_observations
            from app.storage.workflow import packet
            packets=[]
            for observation in book_observations(book,environment='production' if kind==EvidenceKind.OBSERVATION else 'synthetic',evidence_class='current' if kind==EvidenceKind.OBSERVATION else 'synthetic',source_time_semantics='unknown'):
                p=packet(observation);p['raw_b64']=base64.b64encode(p.pop('raw')).decode();packets.append(p)
            if packets!=row['packets']:raise ValueError('native quote packet replay mismatch')
    return dict(exact_native_books=counts,exact_packets=True,gaps=gaps,journal_sha256=saved['sha256'],state=saved['state'])
