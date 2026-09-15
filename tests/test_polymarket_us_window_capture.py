"""Offline replay of unmodified live evidence; no venue requests."""
import json
from pathlib import Path
from datetime import datetime
from decimal import Decimal
import unittest
from app.adapters.polymarket_us import Response, decode, parse_market
from app.adapters.polymarket_us_stream import MarketStream
from app.models.core import BookSync, Depth

CAPTURE=Path(__file__).resolve().parents[1]/'evidence/slice-2/qualification-20260911T234447Z/live'

def replay():
    rows=json.loads((CAPTURE/'discovery-provenance.json').read_text())
    events=decode((CAPTURE/rows[0]['file']).read_text())['events']
    markets=[]
    for row in rows[1:]:
        response=Response((CAPTURE/row['file']).read_text(),row['source'],datetime.fromisoformat(row['received_at']))
        data=decode(response.body)['market']
        event=next(e for e in events if any(str(m['id'])==str(data['id']) for m in e['markets']))
        markets.append(parse_market(response,data,str(event['id'])))
    stream=MarketStream(markets,None)
    removed=[];previous={};images={};count=0
    for file in sorted(CAPTURE.glob('market-frame-*.json')):
        body=file.read_text();data=decode(body);rid=data['requestId'];md=data['marketData']
        if rid!=stream.subscription_id:
            generation=stream.begin_subscription(rid)
            assert all(b.sync==BookSync.UNSYNCHRONIZED for b in stream.last.values())
        book=stream.parse(body,rid,generation=generation)
        assert book.sync==BookSync.SYNCHRONIZED
        assert book.raw.json_text==body
        images.setdefault(generation,set()).add(md['marketSlug'])
        for wire,ladder in [('bids',book.outcomes[0].bids),('offers',book.outcomes[0].asks)]:
            expected={Decimal(r['px']['value']):Decimal(r['qty']) for r in md[wire] if Decimal(r['qty'])>0}
            actual={r.price.value:r.quantity.value for r in ladder.levels}
            assert actual==expected
            assert ladder.depth==Depth.PARTIAL
            key=(md['marketSlug'],wire)
            for price in set(previous.get(key,{}))-set(actual):
                removed.append({'file':file.name,'market':key[0],'side':wire,'price':str(price)})
            previous[key]=actual
        count+=1
    return {'frames_replayed':count,'connection_generations':len(images),
        'markets_per_generation':{k:len(v) for k,v in images.items()},
        'removed_levels':removed,'all_images_equal_supplied_nonzero_window':True,
        'basis':'offline replay of live raw frames through revised adapter; not another live session'}

class WindowCaptureTests(unittest.TestCase):
    def test_live_window_replacement_and_initial_recovery_images(self):
        result=replay()
        self.assertEqual(result['frames_replayed'],42)
        self.assertEqual(result['markets_per_generation'],{1:3,2:3})
        self.assertEqual(result['removed_levels'],[{'file':'market-frame-042.json','market':'aec-nfl-bal-ind-2026-09-13','side':'bids','price':'0.5000'}])
