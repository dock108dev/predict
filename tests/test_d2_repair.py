"""Saved replacement pilot is immutable. Faults below are offline injections."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.collection import coverage
from app.collection.continuous import Discovery, Venue, ContinuousSession, select_inventory, MIB
from app.collection.transport_session import reopen, ObservationJournal
from app.collection.odds_http import BudgetStop
from app.dashboard.coverage_owner import spec, replay_groups

ROOT=Path('evidence/d2-coverage/replacement-20260916T161440Z-faff4a56')
JOURNAL=ROOT/'97dbc1e0-36c7-49c8-a19b-f4856278e21c/97dbc1e0-36c7-49c8-a19b-f4856278e21c.jsonl'
AT=coverage.stamp('2026-09-16T16:18:00Z')

def saved_pages():
    return [r for r in reopen(JOURNAL)['rows'] if r.get('path','').endswith(('/events','/markets'))]

class Repair(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):cls.pages=saved_pages()

    def catalog(self,g=1):
        return coverage.catalog([p for p in self.pages if p['discovery_generation']==g],'polymarket_us',AT)

    def test_saved_contradiction_and_embedded_eligibility(self):
        cat=self.catalog();self.assertEqual(len(cat['markets']),32)
        self.assertEqual(cat['market_completeness'],'unestablished')
        self.assertTrue(all(e['market_discovery']=='contradictory_listings' for e in cat['events']))
        self.assertEqual(select_inventory(cat,AT)[1],32)
        self.assertTrue(all(m['provenance'][0]['path']=='/v1/events' for m in cat['markets']))
        self.assertEqual(sum(s['purchase_support']=='unsupported' for m in cat['markets'] for s in m['sides']),32)
        for field,value in [('subscription_evidence_exclusion','missing_native_terms'),('exclusion','conflicting_duplicate')]:
            damaged=deepcopy(cat);damaged['markets'][0][field]=value
            self.assertEqual(select_inventory(damaged,AT)[1],31)

    def test_missing_terms_identity_sides_and_slug_conflict(self):
        from tests.test_coverage import page
        original=next(p for p in self.pages if p['path']=='/v1/events')
        _,body=coverage.decode_page(original)
        for change in ('terms','role','team','id','slug','closed'):
            data=deepcopy(body);m=data['events'][0]['markets'][0]
            if change=='closed':m['closed']=True
            if change=='terms':m['description']=''
            if change=='role':m['marketSides'][0]['long']=False
            if change=='team':m['marketSides'][0]['team']['name']='Unknown'
            if change=='id':m.pop('id')
            if change=='slug':m['slug']=data['events'][1]['markets'][0]['slug']
            p=page('polymarket_us',data,limit=5)
            cat=coverage.catalog([p],'polymarket_us',AT)
            self.assertLess(select_inventory(cat,AT)[1],5,change)

    async def test_interrupted_third_generation_preserves_second(self):
        session=SimpleNamespace(producers={},emit=lambda *a:None)
        d=Discovery(session)
        async def venue(v):
            d.pages.extend(p for p in self.pages if p['source']==v and p['discovery_generation']==d.generation)
            if d.generation==3 and v=='polymarket_us':raise BudgetStop('session_ingress_cap')
        d.venue=venue
        with patch('app.collection.continuous.now',return_value=AT):
            await d.discover();await d.discover(force=True)
            prior=deepcopy(d.inventory)
            with self.assertRaisesRegex(ValueError,'session_ingress_cap'):await d.discover(force=True)
            self.assertEqual(d.inventory,prior);self.assertEqual(d.published_generation,2)
            self.assertEqual(len(d.partial['polymarket_us']['events']),20)
            self.assertEqual(len(d.partial['kalshi']['markets']),6)
            self.assertEqual(d.inventory['kalshi']['selection']['eligible'],64)
            self.assertEqual(d.inventory['polymarket_us']['selection']['eligible'],32)
            self.assertEqual(d.status()['refresh']['state'],'failed')
        with patch('app.collection.continuous.now',return_value=AT+__import__('datetime').timedelta(seconds=15)):
            self.assertEqual(d.status()['age_seconds'],15)

    async def test_cap_rejected_response_is_not_durable_inventory(self):
        # Replay a saved page as a new receipt at the real serialized ingress cap.
        with tempfile.TemporaryDirectory() as tmp:
            s=ContinuousSession(spec(),Path(tmp),{},credentials={})
            s.journal=ObservationJournal(Path(tmp)/'test.jsonl')
            d=Discovery(s);s.discovery=d
            s.ingress_bytes=16*MIB
            row=next(p for p in self.pages if p['path']=='/v1/events')
            with self.assertRaises(BudgetStop):d.receipt('polymarket_us',row)
            self.assertEqual(d.pages,[])
            self.assertEqual(d.responses['polymarket_us'],dict(received=1,durably_retained=0))
            self.assertEqual(s.journal.count,0)
            self.assertEqual(s.reason,'session_ingress_cap')
            s.journal.close()

    async def test_publication_rejection_and_cancellation(self):
        s=SimpleNamespace(producers={},emit=lambda *a:None);d=Discovery(s)
        async def venue(v):d.pages.extend(p for p in self.pages if p['source']==v and p['discovery_generation']==1)
        d.venue=venue
        with patch('app.collection.continuous.now',return_value=AT):
            await d.discover();old=deepcopy(d.inventory)
            s.emit=lambda *a:False
            with self.assertRaises(BudgetStop):await d.discover(force=True)
            self.assertEqual(d.inventory,old);self.assertEqual(d.published_generation,1)
            async def cancel(v):raise asyncio.CancelledError()
            d.venue=cancel
            with self.assertRaises(ValueError):await d.discover(force=True)
            self.assertEqual(d.inventory,old)

    def test_partial_closure_and_kickoff_invalidate_old_books(self):
        s=SimpleNamespace(producers={},spec=spec(),profile=None,emit=lambda *a:None)
        d=Discovery(s);s.discovery=d;d.pages=[p for p in self.pages if p['discovery_generation']==1]
        with patch('app.collection.continuous.now',return_value=AT):
            d.inventory,d.markets=d.project()
            v=Venue(s,'polymarket_us');s.producers['polymarket_us']=v
            mid=d.inventory['polymarket_us']['markets'][0]['id']
            v.groups['g']=dict(ids=(mid,),**{k:{mid} for k in v.ever})
            from tests.test_coverage import page
            p=next(p for p in d.pages if p['path']=='/v1/events');_,data=coverage.decode_page(p)
            data['events'][0]['closed']=True
            d.pages=[page('polymarket_us',data,limit=5)]
            d.safety('polymarket_us');self.assertEqual(v.snapshot()['usable'],0)
            self.assertEqual(len(d.inventory['polymarket_us']['markets']),32)
            d.blocked['polymarket_us'].clear();v.groups['g']['usable'].add(mid)
            self.assertEqual(v.snapshot()['usable'],0)  # publication cannot revive an invalidated stream
            v.groups['g']['invalidated']=False;v.groups['g']['usable'].add(mid)
            start=coverage.stamp(d.inventory['polymarket_us']['events'][0]['scheduled_start'])
        with patch('app.collection.continuous.now',return_value=start-__import__('datetime').timedelta(seconds=300)):
            self.assertEqual(v.snapshot()['usable'],0)


    async def test_durable_receipt_survives_queue_failure(self):
        s=SimpleNamespace(counts={'durably_acknowledged':0},producers={})
        def emit(*args):
            s.counts['durably_acknowledged']+=1
            raise asyncio.QueueFull()
        s.emit=emit;d=Discovery(s)
        row=next(p for p in self.pages if p['path']=='/v1/events')
        with self.assertRaises(asyncio.QueueFull):d.receipt('polymarket_us',row)
        self.assertEqual(len(d.pages),1)
        self.assertEqual(d.responses['polymarket_us'],dict(received=1,durably_retained=1))

    def test_saved_exact_native_replay(self):
        result=replay_groups(reopen(JOURNAL))
        self.assertTrue(all(r['exact_packets'] for r in result.values()))
        self.assertEqual(sum(sum(r['exact_native_books'].values()) for r in result.values()),491)
