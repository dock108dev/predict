"""Dense complete native receipts stay bounded; transport is generated locally."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

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
        if field=='events' and venue=='polymarket_us':
            for event in data['events']:
                event['markets']=ladder(event['markets'][0],venue,count)
            rows=data['events']
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
    async def test_dense_multi_family_pages_project_whole_records_before_expansion(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                value,published=worker(venue)
                cases=[source_case(sport,family,'dense-'+sport+'-'+family) for sport in SPORTS for family in FAMILIES]
                calls,originals,receipts=dense_transport(value,cases,50)
                expected={(sport,family) for sport in SPORTS for family in FAMILIES}
                seen=set();seen_ids=set()
                real_catalog=coverage.catalog
                def bounded_catalog(*args,**kwargs):
                    selection=kwargs.get('current_selection')
                    if selection is not None:
                        self.assertLessEqual(len(selection['events']),24)
                        self.assertLessEqual(len(selection['markets']),72)
                    return real_catalog(*args,**kwargs)
                try:
                    with patch('app.collection.current_native.coverage.catalog',side_effect=bounded_catalog):
                        for attempt in range(3):
                            before=len(calls)
                            await value.discover()
                            self.assertLessEqual(len(calls)-before,value.config['discovery_pages'])
                            self.assertFalse(value.failed)
                            self.assertEqual(value.pages,[])
                            self.assertLessEqual(len(value.catalog['events']),200)
                            self.assertLessEqual(len(value.catalog['markets']),512)
                            self.assertLessEqual(len(json.dumps(value.catalog,default=str).encode()),CATALOG_BYTES)
                            self.assertGreater(value.metrics['catalog_projection']['candidate_markets'],512)
                            self.assertGreater(value.metrics['catalog_projection']['omitted_markets'],0)
                            events={e['id']:e for e in value.catalog['events']}
                            seen.update((events[m['event_id']]['competition'],m['market_type']) for m in value.catalog['markets'])
                            seen_ids.update(value.markets)
                            for market in value.catalog['markets']:
                                self.assertEqual(market['_native'],originals[market['id']])
                                raw=originals[market['id']]
                                wording=raw['rules_primary'] if venue=='kalshi' else raw['description']
                                self.assertIn(wording,market['terms'].values())
                    self.assertEqual(seen,expected)
                    self.assertGreater(len(seen_ids),value.config['markets_per_source'])
                    self.assertEqual(len(published),3)
                    self.assertEqual(value.catalog_cursor,3)
                    # Complete source receipt bodies are never repackaged by the
                    # catalog selection, and every receipt hash remains valid.
                    for page in receipts:
                        raw=base64.b64decode(page['body_b64'])
                        self.assertEqual(sha256(raw).hexdigest(),page['body_sha256'])
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

    async def test_more_than_200_listed_events_are_filtered_before_catalog_expansion(self):
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
            self.assertLessEqual(len(base_calls),value.config['discovery_pages'])
            self.assertLessEqual(len(value.catalog['events']),24)
            self.assertEqual(len(value.markets),value.config['markets_per_source'])
            self.assertFalse(value.failed)
        finally:await value.close()


if __name__=='__main__':unittest.main()
