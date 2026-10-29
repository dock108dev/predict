"""Expanded metadata replacement never carries an old image into changed terms."""
from copy import deepcopy
from datetime import datetime,timezone
import unittest
from tests.multisport_fixtures import source_case,fake_discovery,current_book
from tests.test_current_multisport_ingress import worker


class MaterialQuarantine(unittest.IsolatedAsyncioTestCase):
    async def test_large_changed_material_replaces_catalog_and_requires_fresh_image(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                value,published=worker(venue,['NFL'],['total'])
                old=source_case('NFL','total','owned-material-change',line='45.5')
                peer=source_case('NFL','total','unrelated-owned-peer',line='51.5')
                cases=[old,peer];fake_discovery(value,cases)
                writes=[];value.service.books=lambda v,b:writes.append(deepcopy(b))
                await value.discover();value.lifecycle.begin_connection(1);value.metrics['connections']=1
                original=current_book(old,venue);mid=original['raw']['ref']['market_id']
                value.queue_book(original);value.flush_books()
                token=value.lifecycle.leases[mid]['owner_token']
                changed=source_case('NFL','total','owned-material-change',clock=old['clock'],line='46.5')
                native=changed['markets'][venue]
                native['rules_primary' if venue=='kalshi' else 'description']+=' Complete changed wording.'*40000
                if venue=='polymarket_us':changed['events'][venue]['markets']=[deepcopy(native)]
                cases[:]=[changed,peer]
                try:
                    await value.discover()
                    self.assertEqual(value.metrics['catalog_projection']['state'],'complete_traversal')
                    self.assertEqual(value.lifecycle.leases[mid]['owner_token'],token)
                    self.assertTrue(any(a['action']=='reimage' and a['market_id']==mid for a in value.metrics['subscription_changes']['actions']))
                    self.assertFalse(value.lifecycle.leases[mid]['image_current'])
                    self.assertEqual(len(value.markets),2)
                    self.assertEqual(next(m for m in value.catalog['markets'] if m['id']==mid)['_native'],native)
                    value.lifecycle.begin_connection(2);value.metrics['connections']=2
                    value.queue_book(current_book(changed,venue,price='0.67'));value.flush_books()
                    self.assertTrue(value.lifecycle.freshness(mid,datetime.now(timezone.utc))['current'])
                    self.assertEqual(writes[-1][0]['raw']['ref']['market_id'],mid)
                finally:await value.close()
                self.assertEqual(value.lifecycle.leases,{})
                self.assertEqual(value.pending_books,{})

    async def test_changed_nonmaterial_volume_keeps_subscription_identity(self):
        value,_=worker('kalshi',['NFL'],['total'])
        case=source_case('NFL','total','same-material',line='45.5')
        case['markets']['kalshi']['volume_fp']='1'
        cases=[case];fake_discovery(value,cases)
        try:
            await value.discover();signature=value.signature
            changed=deepcopy(case);changed['markets']['kalshi']['volume_fp']='1'*400000
            cases[:]=[changed];await value.discover()
            self.assertEqual(value.signature,signature)
            self.assertEqual(value.material_quarantine,{})
        finally:await value.close()
