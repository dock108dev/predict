import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.collection.continuous import ContinuousSession
from app.collection.segmented import SegmentedReader,POLICY
from app.dashboard.coverage_owner import CoverageOwner,spec
from tests.segmented_collector_fixture import Fixture


class Integration(unittest.IsolatedAsyncioTestCase):
    async def test_busy_refresh_active_stop_exact_incremental_finalization(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            f=Fixture();o=await f.start(tmp)
            try:
                s=o.session
                await f.busy(1100)
                self.assertGreaterEqual(len(s.journal.history.segments),1)
                connections=s.connection_attempts
                await s.discovery.discover(force=True)
                await f.wait(lambda:all(p.applied_generation==2 for p in s.producers.values()))
                self.assertEqual(s.connection_attempts,connections)
                await f.busy(2200)
                self.assertTrue(all(c['socket'].closed is False for c in f.active()))
                self.assertTrue(all(p.snapshot()['usable']>0 for p in s.producers.values()))
                await o.stop();await o.finalizer
                self.assertEqual(s.reason,'manual_stop');self.assertIsNone(o.error,o.mock_result)
                self.assertTrue(o.mock_result['operator_stop']);self.assertFalse(o.active());self.assertIsNone(o.owner_lock)
                self.assertEqual(s.queue.qsize(),0);self.assertEqual(s.delivered,s.persisted)
                self.assertTrue(all(g['task'].done() and g['producer'].stream.closed for p in s.producers.values() for g in p.groups.values()))
                replay=json.loads((s.output/'replay.json').read_text())
                self.assertEqual(replay['sequence_sha256'],f.sequence.hexdigest())
                self.assertEqual(replay['counts']['prediction_book'],f.books)
                self.assertEqual(replay['counts']['session_finished'],1)
                self.assertEqual(replay['published_generations'],[1,2])
                self.assertGreater(f.books,600)
                with self.assertRaises(ValueError):await o.start()
                restarted=CoverageOwner(Path(tmp)/'unused',pilot_output=Path(tmp)/'pilot',endpoints=f.endpoints,mock_segmented=True)
                with self.assertRaises(ValueError):await restarted.start()
                for row in SegmentedReader(s.output/'history').rows():
                    if row['type']=='prediction_book':self.assertEqual(row['book']['raw']['kind'],'synthetic')
                for segment in s.journal.history.segments:
                    self.assertLess(segment['expanded_physical'],POLICY['segment_expanded'])
                    self.assertLess(segment['bytes'],POLICY['segment_encoded'])
            finally:await f.close()

    async def test_isolation_rejects_real_spec_credentials_and_destinations(self):
        value=spec();value['mode']='mock'
        good={v:dict(rest='http://127.0.0.1:1234',ws='ws://127.0.0.1:1234/ws') for v in ('kalshi','polymarket_us')}
        with tempfile.TemporaryDirectory() as t,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            for changes,ep,credentials in [({'mode':'real'},good,None),({},good,{'kalshi':object()}),({'reference_enabled':True},good,None),
                    ({},{**good,'kalshi':dict(rest='https://external-api.kalshi.com',ws=good['kalshi']['ws'])},None),
                    ({},{**good,'kalshi':dict(rest='http://localhost:1234',ws=good['kalshi']['ws'])},None)]:
                with self.subTest(changes=changes,ep=ep),self.assertRaises(ValueError):
                    ContinuousSession(dict(value,**changes),Path(t),ep,credentials=credentials,mock_segmented=True)
            s=ContinuousSession(value,Path(t),good,mock_segmented=True);s.spec['mode']='real'
            with self.assertRaises(ValueError):await s.start()

    async def test_refresh_rotates_publication_and_new_market_waits_for_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.start(tmp)
            try:
                s=o.session
                await f.at_local(1019)  # Four REST receipts, then catalog publication rotates.
                old_budget={v:p.budget.requests for v,p in s.producers.items()}
                stages=[]
                s.journal.history.fault=lambda stage:stages.append((stage,s.discovery.published_generation))
                await s.discovery.discover(force=True)
                self.assertIn(('seal_fsynced',1),stages)
                self.assertEqual(s.discovery.published_generation,2)
                await f.wait(lambda:all(p.applied_generation==2 for p in s.producers.values()))
                self.assertTrue(all(s.producers[v].budget.requests>old_budget[v] for v in old_budget))
                self.assertEqual(s.connection_attempts,2)
                # Next refresh changes the US subscription. A published/then-applied
                # plan cannot count newly selected markets as usable without images.
                f.us_markets=2
                old_tasks=[g['task'] for g in s.producers['polymarket_us'].groups.values()]
                await s.discovery.discover(force=True)
                c=s.status_coverage()['polymarket_us']
                self.assertEqual(c['generation'],3);self.assertEqual(c['applied_generation'],2)
                self.assertEqual(c['selected'],2);self.assertEqual(c['applied_selected'],1)
                await f.wait(lambda:s.producers['polymarket_us'].applied_generation==3)
                self.assertEqual(s.status_coverage()['polymarket_us']['usable'],0)
                self.assertTrue(all(t.done() for t in old_tasks))
                await f.wait(lambda:len([c for c in f.active() if c['venue']=='polymarket_us'])==1)
                await f.images()
                self.assertEqual(s.status_coverage()['polymarket_us']['usable'],2)
                await o.stop();await o.finalizer
                self.assertIsNone(o.error,o.mock_result)
                replay=json.loads((s.output/'replay.json').read_text())
                self.assertEqual(replay['published_generations'],[1,2,3])
                self.assertEqual(replay['sequence_sha256'],f.sequence.hexdigest())
            finally:await f.close()

    async def test_stop_requested_at_rotation_keeps_durable_catalog_coherent(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.start(tmp)
            try:
                s=o.session;await f.at_local(1019);stages=[]
                def pending_stop(stage):
                    stages.append(stage)
                    if stage=='seal_fsynced':
                        # Rotation is synchronous: Stop becomes pending while its
                        # admitted write completes, before the next producer turn.
                        s.request_stop('manual_stop')
                        asyncio.create_task(o.stop())
                s.journal.history.fault=pending_stop
                await s.discovery.discover(force=True)
                await o.finalizer
                self.assertIn('seal_fsynced',stages)
                self.assertEqual(s.discovery.published_generation,2)
                self.assertTrue(o.mock_result['operator_stop'],o.mock_result)
                self.assertEqual(o.mock_result['applied_generations'],{'kalshi':1,'polymarket_us':1})
                self.assertEqual(s.delivered,s.persisted);self.assertEqual(s.queue.qsize(),0)
                self.assertEqual(json.loads((s.output/'replay.json').read_text())['sequence_sha256'],f.sequence.hexdigest())
            finally:await f.close()

    async def test_stop_with_pending_work_drains_before_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.start(tmp)
            try:
                s=o.session;blocked=asyncio.Event();release=asyncio.Event();real_get=s.queue.get
                async def pending_get():
                    blocked.set();await release.wait();return await real_get()
                s.queue.get=pending_get
                # Let the existing waiting get finish, then block the next queue get.
                c=f.active()[0]
                sending=asyncio.create_task(f.send(c))
                await blocked.wait()
                await f.wait(lambda:s.queue.qsize()>0)
                pending=s.queue.qsize();await o.stop()
                self.assertGreater(pending,0);self.assertFalse(o.finalizer.done())
                release.set();await sending;await o.finalizer
                self.assertTrue(o.mock_result['operator_stop'],o.mock_result)
                self.assertEqual(s.persisted,s.delivered);self.assertEqual(s.queue.qsize(),0)
            finally:await f.close()

    async def test_resource_stop_before_intended_stop_is_not_operator_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(kalshi_markets=21);o=await f.start(tmp)
            try:
                s=o.session
                await f.busy(4096);await o.finalizer
                self.assertEqual(s.reason,'offline_segment_cap',o.mock_result)
                self.assertEqual(s.delivered,4092)
                self.assertFalse(o.mock_result['operator_stop']);self.assertEqual(o.mock_result['status'],'complete')
                self.assertEqual(s.counts['accepted'],s.counts['durably_acknowledged'])
                self.assertGreater(s.counts['rejected'],0)
                self.assertEqual(s.queue.qsize(),0);self.assertEqual(len(s.journal.history.segments),4)
                for p in s.producers.values():
                    for g in p.groups.values():
                        self.assertLess(g['producer'].bytes,16*1024*1024)
                # A later click cannot rewrite an earlier resource stop.
                await o.stop();self.assertEqual(s.reason,'offline_segment_cap')
            finally:await f.close()

    async def test_rotation_io_failure_preserves_interrupted_history_without_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.start(tmp)
            try:
                s=o.session;await f.at_local(1023)
                def fail(stage):
                    if stage=='manifest_fsynced':raise OSError('injected publication failure')
                s.journal.history.fault=fail
                await f.send(f.active()[0]);await o.finalizer
                self.assertEqual(s.reason,'storage_failure')
                self.assertFalse(s.journal.terminal_acknowledged)
                self.assertEqual(o.mock_result['status'],'failed');self.assertFalse(o.mock_result['operator_stop'])
                self.assertFalse((s.output/'manifest.json').exists());self.assertIsNone(o.owner_lock)
                self.assertEqual(SegmentedReader(s.output/'history').inspect()['state'],'interrupted')
                self.assertGreater(s.accounting()['unresolved'],0)
            finally:await f.close()

    async def test_final_manifest_failure_is_not_successful_stop(self):
        from app.dashboard import coverage_owner
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.start(tmp)
            try:
                save=coverage_owner.save_json
                def fail(path,value):
                    if path.name=='manifest.pending.json':raise OSError('injected manifest failure')
                    save(path,value)
                with patch.object(coverage_owner,'save_json',fail):
                    await o.stop();await o.finalizer
                self.assertEqual(o.mock_result['status'],'failed');self.assertFalse(o.mock_result['operator_stop'])
                self.assertFalse((o.session.output/'manifest.json').exists())
                self.assertEqual(json.loads((o.session.output/'finalization-failure.json').read_text())['status'],'failed')
            finally:await f.close()

    async def test_local_redirects_never_contact_external_hosts(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        async def redirect(req):return web.Response(status=302,headers={'Location':'http://example.invalid/forbidden'})
        app=web.Application();app.router.add_get('/{path:.*}',redirect)
        server=TestServer(app);await server.start_server()
        url=str(server.make_url('/')).rstrip('/')
        ep={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        try:
            with tempfile.TemporaryDirectory() as t,patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')):
                o=CoverageOwner(Path(t)/'unused',pilot_output=Path(t)/'pilot',endpoints=ep,mock_segmented=True)
                await o.start(duration=5);await o.finalizer
                self.assertEqual(o.session.discovery.published_generation,None)
                self.assertIn('discovery_failure',o.session.reason)
                # Exercise the real WebSocket connector too; redirect is not followed.
                from app.collection.prediction_producer import PredictionProducer
                # Reuse valid fixture metadata without external lookups.
                from app.adapters.kalshi import Response,parse_market
                from tests.test_coverage import km
                from datetime import datetime,timezone
                value=spec();value['mode']='mock'
                p=PredictionProducer('kalshi',value,url,ep['kalshi']['ws'],lambda *a:None,lambda *a:None)
                p.mock_segmented=True
                market=parse_market(Response(json.dumps({'markets':[km()]}),'fixture',datetime.now(timezone.utc)),km(),'k','KXNFLGAME')
                await p.run([market]);await p.aclose()
                self.assertTrue(p.stream.closed)
        finally:await server.close()

    async def test_queue_rejection_keeps_durable_native_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.start(tmp)
            try:
                s=o.session;blocked=asyncio.Event();release=asyncio.Event();real_get=s.queue.get
                async def pending_get():
                    blocked.set();await release.wait();return await real_get()
                s.queue.get=pending_get
                sending=asyncio.create_task(f.control())
                await blocked.wait()
                c=next(c for c in f.active() if c['venue']=='kalshi')
                for _ in range(49):
                    c['seq']+=1
                    await c['socket'].send_json(dict(type='ok',sid=1,seq=c['seq'],msg={}))
                await f.wait(lambda:s.stop_event.is_set())
                self.assertEqual(s.reason,'queue_capacity')
                release.set();await sending;await o.finalizer
                self.assertEqual(s.accounting()['durable_not_queued'],1)
                self.assertEqual(s.accounting()['unresolved'],0)
                self.assertEqual(s.queue.high_items,48);self.assertEqual(s.queue.qsize(),0)
                self.assertFalse(o.mock_result['operator_stop']);self.assertTrue(o.mock_result['native_verified'])
                self.assertEqual(json.loads((s.output/'replay.json').read_text())['sequence_sha256'],f.sequence.hexdigest())
            finally:
                release.set()
                await f.close()

    async def test_stop_during_new_group_metadata_does_not_start_or_apply_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.start(tmp)
            try:
                s=o.session;f.us_markets=2;save=s.journal.save
                def pending_stop(row):
                    save(row)
                    if row['type']=='market_selected' and row.get('stream_group')=='polymarket_us-2':
                        s.request_stop('manual_stop')
                s.journal.save=pending_stop
                await s.discovery.discover(force=True)
                await o.finalizer
                self.assertTrue(o.mock_result['operator_stop'],o.mock_result)
                p=s.producers['polymarket_us']
                self.assertEqual(p.applied_generation,1)
                self.assertNotIn('task',p.groups['polymarket_us-2'])
                self.assertEqual(s.connection_attempts,2)
                self.assertTrue(s.cleanup_complete)
            finally:await f.close()

    async def test_startup_budget_failure_releases_history_and_consumes_attempt(self):
        from app.collection.mock_history import SegmentedTransportJournal
        from app.collection.odds_http import BudgetStop
        good={v:dict(rest='http://127.0.0.1:1234',ws='ws://127.0.0.1:1234/ws') for v in ('kalshi','polymarket_us')}
        with tempfile.TemporaryDirectory() as t:
            o=CoverageOwner(Path(t)/'unused',pilot_output=Path(t)/'pilot',endpoints=good,mock_segmented=True)
            with patch.object(SegmentedTransportJournal,'save',side_effect=BudgetStop('injected_start_budget')):
                with self.assertRaises(BudgetStop):await o.start()
            self.assertIsNone(o.owner_lock)
            self.assertTrue(o.session.journal.history.closed)
            self.assertFalse(o.session.journal.terminal_acknowledged)
            self.assertEqual(SegmentedReader(o.session.output/'history').inspect()['state'],'interrupted')
            with self.assertRaises(ValueError):await o.start()
