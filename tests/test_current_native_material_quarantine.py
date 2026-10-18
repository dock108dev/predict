"""Observed changed owned terms cannot inherit retained book authority."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import base64
from hashlib import sha256
import unittest
from unittest.mock import patch

from app.comparison.combined_native import normalize
from app.collection import coverage
from app.collection.current_native import CATALOG_BYTES,QUARANTINE_HEADROOM
from app.collection.v1_comparison import annotate
from tests.multisport_fixtures import source_case,fake_discovery,current_book
from tests.test_current_multisport_ingress import worker


class MaterialQuarantine(unittest.IsolatedAsyncioTestCase):
    async def test_exact_accepted_catalog_reserves_quarantine_wrapper_room(self):
        value,_=worker('kalshi',['NFL'],['total'])
        old=source_case('NFL','total','near-bound-material',line='45.5')
        cases=[old];fake_discovery(value,cases)
        real_catalog=coverage.catalog
        def padded(*args,**kwargs):
            cat=real_catalog(*args,**kwargs)
            if args[1]=='kalshi':
                cat['reservation_test_padding']=''
                size=len(json.dumps(cat,default=str).encode())
                cat['reservation_test_padding']='x'*(CATALOG_BYTES-QUARANTINE_HEADROOM-2048-size)
            return cat
        with patch('app.collection.current_native.coverage.catalog',side_effect=padded):await value.discover()
        self.assertTrue(value.markets)
        self.assertLessEqual(len(json.dumps(value.catalog,default=str).encode()),CATALOG_BYTES-QUARANTINE_HEADROOM)
        changed=source_case('NFL','total','near-bound-material',clock=old['clock'],line='46.5')
        changed['markets']['kalshi']['rules_primary']+=' changed wording'*80000
        cases[:]=[changed]
        try:
            await value.discover()
            self.assertEqual(len(value.material_quarantine),1)
            self.assertLessEqual(len(json.dumps(value.catalog,default=str).encode()),CATALOG_BYTES)
        finally:await value.close()

    async def test_identical_repeated_milestones_and_changed_reviewed_observation_do_not_quarantine(self):
        value,_=worker('kalshi',['NFL'],['total'])
        case=source_case('NFL','total','same-semantic-capacity',line='45.5')
        case['markets']['kalshi']['volume_fp']='1'
        cases=[case];fake_discovery(value,cases)
        await value.discover()
        mid=next(iter(value.markets))
        changed=deepcopy(case);changed['markets']['kalshi']['volume_fp']='1'*400000
        cases[:]=[changed]
        base_get=value.get
        async def repeated(path,params,field=None,scope=None):
            rows=await base_get(path,params,field,scope)
            if field=='events':
                # Repeated own milestone observations across bounded receipts
                # do not establish a different material identity witness.
                page=deepcopy(value.pages[-1])
                data=json.loads(base64.b64decode(page['body_b64']))
                raw=json.dumps(dict(data,milestones=data['milestones']*2)).encode()
                page.update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
                value.pages.append(page)
            return rows
        value.get=repeated
        try:
            await value.discover()
            self.assertEqual(value.metrics['catalog_projection']['state'],'retained_previous')
            self.assertEqual(value.material_quarantine,{})
            self.assertNotIn('comparison_admission',next(m for m in value.catalog['markets'] if m['id']==mid))
        finally:await value.close()

    def rows(self,catalog,venue,books):
        at=datetime.now(timezone.utc).isoformat()
        # Ordinary service reannotation must not remove the persistent block.
        cat=deepcopy(catalog);annotate(cat,venue,policy='manual-comparison-2')
        result,excluded=normalize(dict(id='catalog',record=dict(source=venue,value=dict(inventory=cat))),
            [dict(id='books',record=dict(retained_at=at,value=dict(observations=[
                dict(type='prediction_book',source=venue,observed_at=at,book=b) for b in books])))],at=at)
        self.assertEqual(excluded,[])
        return result

    async def test_same_owned_id_changed_unfit_material_blocks_new_books_and_recovers(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                value,published=worker(venue,['NFL'],['total'])
                old=source_case('NFL','total','owned-material-change',line='45.5')
                peer=source_case('NFL','total','unrelated-owned-peer',line='51.5')
                cases=[old,peer];fake_discovery(value,cases)
                writes=[];value.service.books=lambda v,b:writes.append(deepcopy(b))
                await value.discover()
                value.lifecycle.begin_connection(1);value.metrics['connections']=1
                old_book=current_book(old,venue,price='0.48');peer_book=current_book(peer,venue,price='0.51')
                for book in (old_book,peer_book):value.queue_book(book)
                value.flush_books()
                mid=old_book['raw']['ref']['market_id'];pid=peer_book['raw']['ref']['market_id']
                original=deepcopy(value.lifecycle.books[mid]);token=value.lifecycle.leases[mid]['owner_token']
                peer_lease=deepcopy(value.lifecycle.leases[pid]);signature=value.signature
                changed=source_case('NFL','total','owned-material-change',clock=old['clock'],line='46.5')
                unfit=deepcopy(changed);native=unfit['markets'][venue]
                native['rules_primary' if venue=='kalshi' else 'description']+=' Complete changed wording.'*40000
                if venue=='polymarket_us':unfit['events'][venue]['markets']=[deepcopy(native)]
                cases[:]=[unfit]
                try:
                    await value.discover()
                    self.assertEqual(value.metrics['catalog_projection']['state'],'retained_previous')
                    self.assertIn(mid,value.material_quarantine)
                    self.assertLess(len(json.dumps(value.material_quarantine).encode()),2048)
                    self.assertEqual(value.signature,signature)
                    self.assertEqual(value.lifecycle.leases[mid]['owner_token'],token)
                    self.assertFalse(value.lifecycle.leases[mid]['image_current'])
                    self.assertEqual(value.lifecycle.books[mid],original)
                    self.assertEqual(value.lifecycle.leases[pid],peer_lease)
                    self.assertNotIn(mid,value.pending_books)
                    count=len(writes)
                    value.queue_book(current_book(changed,venue,price='0.67'));value.flush_books()
                    self.assertEqual(len(writes),count)
                    self.assertFalse(value.lifecycle.freshness(mid,datetime.now(timezone.utc))['current'])
                    rows=[r for r in self.rows(published[-1],venue,[old_book,peer_book])
                          if r['quote']['source']['native_market_id']==mid]
                    self.assertEqual(len(rows),2)
                    for row in rows:
                        self.assertEqual(row['quote']['original']['value'],'0.48')
                        self.assertEqual(row['quote']['times']['source_at'],old_book['raw']['exchange_at'])
                        self.assertEqual(row['quote']['state'],'stale')
                        self.assertFalse(row['verified'])
                        self.assertIsNone(row['comparison_source_metadata']['same_outcome']['predicate'])
                        self.assertEqual(row['comparison_source_metadata']['same_outcome']['reason'],'native_material_changed_capacity')
                    value.queue_book(current_book(peer,venue,price='0.52'));value.flush_books()
                    self.assertEqual(len(writes),count+1)
                    self.assertEqual([b['raw']['ref']['market_id'] for b in writes[-1]],[pid])
                    cases[:]=[changed]
                    await value.discover()
                    self.assertEqual(value.material_quarantine,{})
                    fresh=current_book(changed,venue,price='0.67')
                    value.queue_book(fresh);value.flush_books()
                    recovered=self.rows(published[-1],venue,[fresh])
                    self.assertEqual(len(recovered),2)
                    self.assertTrue(all(r['comparison_source_metadata']['source_predicate']['line']=='46.5' for r in recovered))
                    self.assertTrue(all(r['comparison_source_metadata']['same_outcome']['reason'] is None for r in recovered))
                    self.assertTrue(value.lifecycle.freshness(mid,datetime.now(timezone.utc))['current'])
                finally:await value.close()
                self.assertEqual(value.lifecycle.leases,{})
                self.assertEqual(value.pending_books,{})


if __name__=='__main__':unittest.main()
