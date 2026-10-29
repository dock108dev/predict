"""Dense complete native receipts stay bounded; transport is generated locally."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
import unittest

from app.collection import coverage
from app.collection.current_native import CATALOG_BYTES, catalog_selection
from tests.multisport_fixtures import SPORTS, FAMILIES, source_case, fake_discovery
from tests.test_current_multisport_ingress import worker


def ladder(native, venue, count):
    result=[]
    for index in range(count):
        row=deepcopy(native)
        key='ticker' if venue=='kalshi' else 'id'
        row[key]+='-'+str(index)
        if venue=='polymarket_us':
            row['slug']+='-'+str(index)
            for side in row['marketSides']:
                side['id']+='-'+str(index);side['marketId']=row['id']
        result.append(row)
    return result


def dense_transport(value,cases,count):
    """Keep exact normal fake page proofs while increasing native line density."""
    calls=fake_discovery(value,cases)
    base_get=value.get;originals={};receipts=[]
    venue=value.venue
    async def get(path,params,field=None,scope=None):
        rows=await base_get(path,params,field,scope)
        page=value.pages[-1]
        raw,data=coverage.decode_page(page)
        if venue=='polymarket_us' and ('events' in data):
            for event in data['events']:
                event['markets']=ladder(event['markets'][0],venue,count)
            rows=data['events']
            for event in rows:originals.update({row['id']:deepcopy(row) for row in event['markets']})
        elif field=='markets':
            rows=[entry for native in rows for entry in ladder(native,venue,count)]
            data['markets']=rows
            originals.update({row['ticker' if venue=='kalshi' else 'id']:deepcopy(row) for row in rows})
        raw=json.dumps(data).encode()
        page.update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
        receipts.append(deepcopy(page))
        return rows
    value.get=get
    return calls,originals,receipts


class DenseCatalog(unittest.IsolatedAsyncioTestCase):
    async def test_dense_multi_family_pages_acquire_every_market_without_rotation(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                value,published=worker(venue)
                cases=[source_case(sport,family,'dense-'+sport+'-'+family) for sport in SPORTS for family in FAMILIES]
                calls,originals,receipts=dense_transport(value,cases,50)
                try:
                    await value.discover()
                    self.assertEqual(len(value.markets),900)
                    self.assertEqual(value.metrics['catalog_projection']['omitted_markets'],0)
                    events={e['id']:e for e in value.catalog['events']}
                    self.assertEqual({(events[m['event_id']]['competition'],m['market_type']) for m in value.catalog['markets']},
                                     {(s,f) for s in SPORTS for f in FAMILIES})
                    for market in value.catalog['markets']:self.assertEqual(market['_native'],originals[market['id']])
                    for page in receipts:self.assertEqual(sha256(base64.b64decode(page['body_b64'])).hexdigest(),page['body_sha256'])
                finally:await value.close()

    async def test_oversized_entries_cannot_hide_small_tail_or_reset_rotation(self):
        events=[dict(id='busy',competition='NFL'),dict(id='peer',competition='NBA')]
        natives={e['id']:dict(id=e['id']) for e in events}
        oversized=[dict(id='large-'+str(i),event_id='busy',market_type='spread',_native=dict(rules='x'*300000)) for i in range(80)]
        small=[dict(id='small-'+str(i),event_id='busy',market_type='spread',_native=dict(rules='whole '+str(i))) for i in range(80)]
        peer=dict(id='peer-market',event_id='peer',market_type='spread',_native=dict(rules='exact peer wording'))
        seen=set()
        for offset in range(20):
            selection,diagnostic=catalog_selection(events,natives,oversized+small+[peer],['spread'],offset)
            seen.update(selection['markets'])
            self.assertIn('peer-market',selection['markets'])
            self.assertFalse(any(mid.startswith('large-') for mid in selection['markets']))
            self.assertLessEqual(diagnostic['reserved_bytes'],CATALOG_BYTES)
            self.assertLessEqual(len(selection['markets']),72)
        self.assertTrue({m['id'] for m in small}<=seen)
        selection,diagnostic=catalog_selection(events,natives,oversized,['spread'],4)
        self.assertEqual(selection['markets'],[])
        self.assertEqual(diagnostic['supported_family_candidates'],80)

    async def test_more_than_200_listed_events_are_all_acquired(self):
        value,_=worker('kalshi',['NFL'],['moneyline'])
        cases=[source_case('NFL','moneyline','overreturned-'+str(i)) for i in range(205)]
        base_calls=fake_discovery(value,cases)
        base_get=value.get
        async def overreturn(path,params,field=None,scope=None):
            if field=='events':params=dict(params,limit=205)
            return await base_get(path,params,field,scope)
        value.get=overreturn
        try:
            await value.discover()
            self.assertGreater(len(base_calls),value.config['discovery_pages'])
            self.assertEqual(len(value.catalog['events']),205)
            self.assertEqual(len(value.markets),205)
            self.assertFalse(value.failed)
        finally:await value.close()


if __name__=='__main__':unittest.main()
