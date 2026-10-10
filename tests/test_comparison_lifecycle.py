"""Authored ownership/continuity sequences plus concrete current-worker seam."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from app.comparison.event_links import EventLinks, ProviderEdge
from app.comparison.lifecycle import LifecycleOwner, worker_selections
from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT
from tests.test_current_service import native_fixture

AUTHORED=json.loads((Path(__file__).resolve().parents[1]/'app/fixtures/comparison-lifecycle-v1.json').read_text())
AT=datetime.fromisoformat(AUTHORED['at'].replace('Z','+00:00'))


def selected(mid='A'):
    return dict(market_id=mid,event=deepcopy(AUTHORED['event_a' if mid=='A' else 'event_b']),
        material_revision='authored-terms-1',discovery_eligible=True,payout_eligible=None)


def edges():
    event=AUTHORED['event_a']
    return EventLinks([ProviderEdge('kalshi',event['id'],'authored-occurrence-A','NFL',event['home'],event['away'],
        'a'*64,AUTHORED['at'],AUTHORED['at'],AUTHORED['edge_expiry'],'authored','manual_review')])


def book(mid='A',source=AUTHORED['expected']['source_clock'],received=AUTHORED['at']):
    _,value=native_fixture()
    value['raw'].update(ref=dict(venue='kalshi',event_id=selected(mid)['event']['id'],market_id=mid),exchange_at=source,received_at=received)
    return value


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def owner(self):
        return LifecycleOwner('kalshi',AUTHORED['runtime_id'],attempt_id=AUTHORED['attempt_id'],links=edges())

    async def test_schedule_live_metadata_continuity_and_exact_inventory_deltas(self):
        owner=self.owner()
        created=owner.reconcile([selected('A'),selected('B')],AT)
        self.assertEqual([(a['action'],a['market_id']) for a in created['actions']],[('create','A'),('create','B')])
        token=owner.leases['A']['owner_token']
        updated=selected();updated['event']['scheduled_start']=AUTHORED['expected']['metadata_schedule'];updated['event']['status']['live']=True
        changed=owner.reconcile([updated,selected('B')],AT+timedelta(seconds=20))
        self.assertEqual([(a['action'],a['market_id']) for a in changed['actions']],[('metadata','A')])
        self.assertEqual(owner.leases['A']['owner_token'],token)
        self.assertEqual(owner.leases['A']['selection']['occurrence_id'],'authored-occurrence-A')
        self.assertIsNone(owner.leases['A']['selection']['payout_eligible'])
        self.assertEqual(owner.reconcile([updated,selected('B')],AT+timedelta(seconds=25))['actions'],[])
        removed=owner.reconcile([selected('B')],AT+timedelta(seconds=30))
        self.assertEqual([(a['action'],a['market_id']) for a in removed['actions']],[('close','A')])
        self.assertIn('B',owner.leases)

    async def test_reconnect_requires_complete_new_generation_retirement_and_original_clock(self):
        owner=self.owner();owner.reconcile([selected('A'),selected('B')],AT);owner.begin_connection(1)
        first=owner.admit_book(book(),generation=1)
        self.assertTrue(owner.freshness('A',AT)['current'])
        later=book(source=AUTHORED['expected']['unchanged_confirmation_clock'],received='2026-10-08T20:00:21Z')
        confirmed=owner.admit_book(later,generation=1)
        self.assertEqual(confirmed['raw']['exchange_at'],first['raw']['exchange_at'])
        self.assertEqual(owner.books['A']['confirmation_source_at'],'2026-10-08T20:00:20Z')
        self.assertFalse(owner.freshness('A',AT+timedelta(seconds=40))['current'])
        owner.begin_connection(2)
        self.assertFalse(owner.leases['A']['image_current'])
        with self.assertRaises(ValueError):owner.admit_book(book(),generation=1)
        incomplete=book();incomplete['sync']='resyncing'
        with self.assertRaises(ValueError):owner.admit_book(incomplete,generation=2)
        owner.admit_book(later,generation=2)
        owner.reconcile([selected('B')],AT+timedelta(seconds=30))
        self.assertNotIn('A',owner.books)
        with self.assertRaises(ValueError):owner.admit_book(later,generation=2)
        owner.admit_book(book('B'),generation=2)
        self.assertIn('B',owner.books)

    async def test_changed_price_has_own_clock_and_regression_is_refused(self):
        owner=self.owner();owner.reconcile([selected()],AT);owner.begin_connection(1)
        owner.admit_book(book(),generation=1)
        changed=book(source='2026-10-08T20:00:20Z',received='2026-10-08T20:00:21Z')
        changed['outcomes'][0]['asks']['levels'][0]['price']['value']='0.47'
        self.assertEqual(owner.admit_book(changed,generation=1)['raw']['exchange_at'],'2026-10-08T20:00:20Z')
        with self.assertRaises(ValueError):owner.admit_book(book(),generation=1)
        self.assertEqual(owner.books['A']['book']['outcomes'][0]['asks']['levels'][0]['price']['value'],'0.47')

    async def test_expired_review_is_local_and_never_erases_unrelated_markets(self):
        owner=self.owner();owner.reconcile([selected('A'),selected('B')],AT);owner.begin_connection(1)
        owner.admit_book(book('A'),generation=1);owner.admit_book(book('B'),generation=1)
        owner.reconcile([selected('A'),selected('B')],AT+timedelta(minutes=3))
        self.assertIsNone(owner.leases['A']['selection']['occurrence_id'])
        self.assertEqual(owner.leases['A']['selection']['occurrence_reason'],'provider_edge_expired_or_not_effective')
        self.assertEqual(set(owner.books),{'A','B'})
        conflict=selected();conflict['event']['id']='replacement-without-edge'
        result=owner.reconcile([conflict,selected('B')],AT+timedelta(minutes=4))
        self.assertEqual(result['rejected'],[dict(market_id='A',reason='market_event_identity_conflict')])
        self.assertEqual(owner.leases['A']['selection']['event']['id'],'native-A')
        self.assertFalse(owner.leases['A']['image_current'])
        self.assertIn('B',owner.books)

    async def test_stop_revokes_before_cleanup_and_preserves_consumed_attempt(self):
        owner=self.owner();owner.reconcile([selected('A'),selected('B')],AT)
        closed=[]
        async def close(mid,token):
            self.assertFalse(owner.dispatch)
            with self.assertRaises(ValueError):owner.reconcile([selected()],AT)
            closed.append(mid)
        await owner.stop(close)
        self.assertEqual(closed,['A','B'])
        self.assertEqual(owner.attempt_id,AUTHORED['attempt_id'])
        self.assertEqual(owner.leases,{})
        self.assertEqual(owner.books,{})
        with self.assertRaises(ValueError):owner.begin_connection(1)

    async def test_current_worker_queue_uses_owned_latest_book_and_revocation(self):
        published=[]
        service=SimpleNamespace(config=deepcopy(DEFAULT),runtime_id='CONTROLLED-worker',dispatch=True,
            books=lambda venue,values:published.extend(deepcopy(values)))
        worker=NativeWorker(service,'kalshi')
        worker.lifecycle=self.owner();worker.lifecycle.reconcile([selected()],AT);worker.lifecycle.begin_connection(1)
        worker.lifecycle_initialized=True;worker.metrics['connections']=1
        worker.queue_book(book())
        worker.queue_book(book(source='2026-10-08T20:00:20Z',received='2026-10-08T20:00:21Z'))
        self.assertEqual(len(worker.pending_books),1)
        worker.flush_books()
        self.assertEqual(len(published),1)
        self.assertEqual(published[0]['raw']['exchange_at'],AUTHORED['expected']['source_clock'])
        await worker.close()
        self.assertFalse(worker.lifecycle.dispatch)
        with self.assertRaises(ValueError):worker.queue_book(book())

    def test_current_worker_material_signature_excludes_schedule_status_and_receipt(self):
        cat,_=native_fixture();mid=cat['markets'][0]['id'];eid=cat['events'][0]['id']
        parsed={mid:SimpleNamespace(raw=SimpleNamespace(ref=SimpleNamespace(event_id=eid)),state=SimpleNamespace(value='active'))}
        before=worker_selections('kalshi',parsed,cat)
        cat['events'][0]['scheduled_start']='2026-10-08T20:18:00Z'
        cat['events'][0]['status']={'live':True}
        cat['markets'][0]['v1_raw_binding']['sha256']='new-receipt-hash'
        cat['markets'][0]['v1_raw_binding']['identity']['scheduled_start']='2026-10-08T20:18:00Z'
        after=worker_selections('kalshi',parsed,cat)
        self.assertEqual(before[0]['material_revision'],after[0]['material_revision'])
        self.assertNotEqual(before[0]['event'],after[0]['event'])
        cat['markets'][0]['v1_raw_binding']['identity']['period']='first_half'
        self.assertNotEqual(after[0]['material_revision'],worker_selections('kalshi',parsed,cat)[0]['material_revision'])

    def test_exact_subscription_and_latest_book_resource_bounds(self):
        owner=self.owner()
        rows=[dict(selected('B'),market_id=str(i)) for i in range(20)]
        owner.reconcile(rows,AT);owner.begin_connection(1)
        for i in range(20):
            value=book('B');value['raw']['ref']['market_id']=str(i)
            owner.admit_book(value,generation=1)
            owner.admit_book(value,generation=1)
        self.assertEqual(len(owner.leases),20);self.assertEqual(len(owner.books),20)
        with self.assertRaises(ValueError):owner.reconcile(rows+[dict(selected('B'),market_id='extra')],AT)
        large=book('B');large['raw']['ref']['market_id']='0';large['raw']['json_text']='x'*(256*1024)
        with self.assertRaises(ValueError):owner.admit_book(large,generation=1)


if __name__=='__main__':unittest.main()
