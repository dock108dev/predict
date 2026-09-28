"""Offline injected failures, disposable output, no credentials or providers."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from app.diagnostics import failure
from app.dashboard.multi_game import MultiOwner
from app.dashboard.e6_live import save_json
from app.collection.transport_session import TransportSession
from tests.test_e6_transport import spec


class SafeDiagnostics(unittest.TestCase):
    def test_lock_failure_closes_file_without_masking_original(self):
        from app.collection.transport_session import ObservationJournal
        original=BlockingIOError('lock unavailable')
        file=Mock();file.close.side_effect=OSError('close unavailable')
        with patch('pathlib.Path.open',return_value=file),patch('fcntl.flock',side_effect=original):
            with self.assertLogs('app.collection.transport_session',level='ERROR'):
                with self.assertRaises(BlockingIOError) as caught:ObservationJournal('unused')
        self.assertIs(caught.exception,original)
        file.close.assert_called_once()

    def test_traceback_locations_without_payloads(self):
        try:
            raise RuntimeError('SECRET private payload')
        except RuntimeError as exc:
            with self.assertLogs('diagnostic-test',level='ERROR') as logs:
                failure('diagnostic-test','injected_failure',exc)
        output=' '.join(logs.output)
        self.assertIn('test_traceback_locations_without_payloads',output)
        self.assertIn('RuntimeError',output)
        self.assertNotIn('SECRET',output)

    def test_storage_reporting_cannot_mask_primary_error(self):
        from app.storage.store import Store
        primary=RuntimeError('primary secret')
        store=object.__new__(Store);store.db=Mock()
        store.db.execute.side_effect=primary
        store.event=Mock(side_effect=OSError('db unavailable'))
        with patch('pathlib.Path.mkdir',side_effect=OSError('disk unavailable')):
            with self.assertLogs('app.storage.store',level='ERROR'):
                with self.assertRaises(RuntimeError) as caught:store.ingest('synthetic',[])
        self.assertIs(caught.exception,primary)


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_failure_attempts_all_resources_and_blocks_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=TransportSession(spec(),tmp,{})
            session.producers={'kalshi':SimpleNamespace(aclose=AsyncMock(side_effect=OSError('SECRET'))),
                               'polymarket_us':SimpleNamespace(aclose=AsyncMock())}
            with self.assertLogs('app.collection.transport_session',level='ERROR'):
                await session.close_resources()
            session.producers['polymarket_us'].aclose.assert_awaited_once()
            self.assertEqual(session.cleanup_errors,['kalshi:OSError'])
            owner=MultiOwner(tmp,personal_beta=True);owner.session=session
            self.assertFalse(owner.status()['start_available'])
            with self.assertRaisesRegex(ValueError,'cleanup failed'):await owner.start()

    async def test_failed_storage_never_publishes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner=MultiOwner(tmp)
            owner.session=SimpleNamespace(task=asyncio.create_task(asyncio.sleep(0)),
                persistence_error='Storage failure at fsync',cleanup_errors=[])
            await owner.finish(Path(tmp))
            self.assertEqual(owner.error,'Storage failure at fsync')
            self.assertFalse((Path(tmp)/'manifest.json').exists())

    async def test_manifest_fsync_failure_not_catalogued(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner=MultiOwner(tmp);folder=Path(tmp)/'synthetic';folder.mkdir()
            for name in ('run-spec.json','selection.json','aggregate-limits.json'):
                save_json(folder/name,{})
            original=folder/'original.jsonl';original.write_text('synthetic')
            owner.session=SimpleNamespace(task=asyncio.create_task(asyncio.sleep(0)),
                persistence_error=None,cleanup_errors=[],state='stopped',journal=SimpleNamespace(path=original))
            def injected(path,value):
                if path.name=='manifest.pending.json':
                    with patch('os.fsync',side_effect=OSError('SECRET')):save_json(path,value)
                else:save_json(path,value)
            with patch('app.dashboard.multi_game.reopen',return_value={'sha256':'synthetic','rows':[],'state':'complete'}),patch('app.collection.native_replay.verify_native_saved',return_value={}),patch('app.dashboard.multi_game.save_json',injected):
                with self.assertLogs('app.dashboard.multi_game',level='ERROR'):
                    await owner.finish(folder)
            self.assertEqual(owner.session.state,'failed')
            self.assertEqual(owner.saved(),[])
            self.assertTrue((folder/'manifest.pending.json').exists())
            self.assertFalse((folder/'manifest.json').exists())
            self.assertNotIn('SECRET',owner.error)

    async def test_terminal_budget_failure_marks_storage_unknown(self):
        from app.collection.odds_http import BudgetStop
        with tempfile.TemporaryDirectory() as tmp:
            session=TransportSession(spec(),tmp,{})
            session.producers={}
            session.journal=Mock()
            session.journal.save.side_effect=BudgetStop('observation_storage_cap')
            session.report_failure=Mock()
            session.request_stop('manual_stop')
            await session.run()
            self.assertEqual(session.state,'failed')
            self.assertEqual(session.reason,'storage_failure')
            self.assertIn('terminal',session.persistence_error)
            session.journal.close.assert_called_once()

    async def test_run_retains_cleanup_error_in_terminal_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=TransportSession(spec(),tmp,{})
            session.producers={'kalshi':SimpleNamespace(
                discover=AsyncMock(return_value=[]),aclose=AsyncMock(side_effect=OSError('SECRET')),
                budget=SimpleNamespace(requests=0,connections=0,dollars=0,bytes=0))}
            session.journal=Mock()
            session.request_stop('manual_stop')
            with self.assertLogs('app.collection.transport_session',level='ERROR'):
                await session.run()
            self.assertFalse(session.cleanup_complete)
            self.assertEqual(session.state,'failed')
            row=session.journal.save.call_args.args[0]
            self.assertEqual(row['cleanup_errors'],['kalshi:OSError'])
            session.journal.close.assert_called_once()


class NativeCleanup(unittest.IsolatedAsyncioTestCase):
    def streams(self, factory):
        from app.adapters.kalshi_stream import MarketStream as Kalshi
        from app.adapters.polymarket_us_stream import MarketStream as US
        from tests.test_kalshi import market as kalshi_market
        from tests.test_polymarket_us import market as us_market
        return [Kalshi([kalshi_market('synthetic')], factory), US([us_market()], factory)]

    async def test_failed_socket_close_is_sticky_and_reaches_owner(self):
        from app.collection.prediction_producer import PredictionProducer
        for stream in self.streams(AsyncMock()):
            with self.subTest(stream=type(stream).__module__):
                socket=SimpleNamespace(close=AsyncMock(side_effect=TimeoutError('SECRET')))
                stream.connection=socket
                with self.assertLogs(level='ERROR') as logs:
                    with self.assertRaisesRegex(OSError,'closure unconfirmed'):
                        await stream.aclose()
                self.assertNotIn('SECRET',' '.join(logs.output))
                self.assertTrue(stream.closed)
                self.assertEqual(stream.cleanup_errors,['TimeoutError'])
                with self.assertRaises(OSError):await stream.aclose()
                socket.close.assert_awaited_once()
                producer=object.__new__(PredictionProducer)
                producer.stream=stream
                producer.adapter=SimpleNamespace(aclose=AsyncMock())
                with tempfile.TemporaryDirectory() as tmp:
                    session=TransportSession(spec(),tmp,{})
                    session.producers={'synthetic':producer}
                    with self.assertLogs(level='ERROR'):await session.close_resources()
                    self.assertEqual(session.cleanup_errors,['synthetic:OSError'])
                producer.adapter.aclose.assert_awaited_once()

    async def test_stop_during_close_waits_and_preserves_real_failures(self):
        for fail in (False, True):
            for stream in self.streams(AsyncMock()):
                with self.subTest(stream=type(stream).__module__, fail=fail):
                    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
                    async def close():
                        entered.set()
                        await release.wait()
                        finished.set()
                        if fail:
                            raise OSError('SECRET close failure')
                    stream.connection = SimpleNamespace(close=close)
                    task = asyncio.create_task(stream.aclose())
                    await asyncio.wait_for(entered.wait(), 1)
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    release.set()
                    if fail:
                        with self.assertLogs(level='ERROR') as logs:
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                        self.assertNotIn('SECRET', ' '.join(logs.output))
                        self.assertEqual(stream.cleanup_errors, ['OSError'])
                        with self.assertRaises(OSError):
                            await stream.aclose()
                    else:
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        self.assertEqual(stream.cleanup_errors, [])
                        await stream.aclose()
                    self.assertTrue(finished.is_set())

    async def test_failed_close_prevents_reconnect(self):
        for stream in self.streams(AsyncMock()):
            socket=SimpleNamespace(send=AsyncMock(),recv=AsyncMock(side_effect=ConnectionError()),
                                   close=AsyncMock(side_effect=OSError('SECRET')))
            stream.factory=AsyncMock(return_value=socket)
            with self.assertLogs(level='ERROR'):
                with self.assertRaisesRegex(OSError,'closure unconfirmed'):
                    async for _ in stream.run():pass
            stream.factory.assert_awaited_once()

    async def test_cancellation_survives_secondary_socket_failure(self):
        for stream in self.streams(AsyncMock()):
            started=asyncio.Event()
            async def receive():
                started.set()
                await asyncio.Event().wait()
            socket=SimpleNamespace(send=AsyncMock(),recv=receive,
                                   close=AsyncMock(side_effect=OSError('SECRET')))
            stream.factory=AsyncMock(return_value=socket)
            async def consume():
                async for _ in stream.run():pass
            task=asyncio.create_task(consume())
            await asyncio.wait_for(started.wait(),1)
            with self.assertLogs(level='ERROR'):
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            self.assertEqual(stream.cleanup_errors,['OSError'])
            stream.factory.assert_awaited_once()
            with self.assertRaises(OSError):await stream.aclose()

    async def test_venue_closes_later_groups_and_discovery_after_failure(self):
        from app.collection.continuous import Venue
        primary=OSError('SECRET first')
        resources=[SimpleNamespace(aclose=AsyncMock(side_effect=primary)),
                   SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError('SECRET second'))),
                   SimpleNamespace(aclose=AsyncMock())]
        venue=object.__new__(Venue);venue.venue='kalshi'
        venue.groups={str(i):{'producer':r} for i,r in enumerate(resources[:2])}
        venue.session=SimpleNamespace(discovery=SimpleNamespace(clients={'kalshi':resources[2]}))
        with self.assertLogs('app.cleanup',level='ERROR') as logs:
            with self.assertRaises(OSError) as caught:await venue.aclose()
        self.assertIs(caught.exception,primary)
        for r in resources:r.aclose.assert_awaited_once()
        self.assertEqual(len(logs.output),2)
        self.assertNotIn('SECRET',' '.join(logs.output))

    async def test_adapter_client_closes_after_stream_failure(self):
        from app.adapters.kalshi import KalshiAdapter
        from app.adapters.polymarket_us import PolymarketUSAdapter
        from app.adapters.novig import NovigAdapter
        from app.adapters.prophetx import ProphetXAdapter
        for cls in (KalshiAdapter,PolymarketUSAdapter,NovigAdapter,ProphetXAdapter):
            adapter=object.__new__(cls);adapter.closed=False
            stream=Mock();stream.aclose=AsyncMock(side_effect=OSError('SECRET'))
            adapter.streams={stream};adapter.stream=stream
            adapter.client=SimpleNamespace(aclose=AsyncMock())
            with self.assertLogs('app.cleanup',level='ERROR'):
                with self.assertRaises(OSError):await adapter.aclose()
            adapter.client.aclose.assert_awaited_once()

    async def test_native_rest_closes_every_adapter(self):
        from app.collection.native_product import NativeVenue
        venue=object.__new__(NativeVenue)
        venue.adapters=[SimpleNamespace(aclose=AsyncMock(side_effect=OSError('SECRET'))),
                        SimpleNamespace(aclose=AsyncMock())]
        with self.assertLogs('app.cleanup',level='ERROR'):
            with self.assertRaises(OSError):await venue.aclose()
        venue.adapters[1].aclose.assert_awaited_once()

    async def test_resource_cancellation_does_not_skip_sibling_close(self):
        from app.cleanup import close_all
        resources=[SimpleNamespace(aclose=AsyncMock(side_effect=asyncio.CancelledError())),
                   SimpleNamespace(aclose=AsyncMock())]
        with self.assertLogs('app.cleanup',level='ERROR'):
            with self.assertRaises(asyncio.CancelledError):await close_all(resources)
        resources[1].aclose.assert_awaited_once()

    async def test_optional_reference_failure_remains_visible_and_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=TransportSession(spec(),tmp,{})
            session.references=AsyncMock(side_effect=RuntimeError('SECRET'))
            session.set_health=Mock();session.emit=Mock()
            with self.assertLogs(level='ERROR') as logs:await session.optional_references()
            self.assertNotIn('SECRET',' '.join(logs.output))
            session.set_health.assert_called_once_with('reference','unavailable')
            self.assertEqual(session.emit.call_args.args[1]['reason'],'RuntimeError')
            self.assertFalse(session.stop_event.is_set())

    async def test_projection_failure_preserves_acknowledgement_and_logs_each_failure(self):
        from app.collection.transport_session import ObservationJournal
        with tempfile.TemporaryDirectory() as tmp:
            session=TransportSession(spec(),tmp,{})
            session.journal=ObservationJournal(Path(tmp)/'synthetic.jsonl')
            session.acknowledged_observer=Mock(side_effect=RuntimeError('SECRET'))
            try:
                with self.assertLogs('app.collection.transport_session',level='ERROR') as logs:
                    session.emit('kalshi',{'type':'synthetic'})
                    session.emit('kalshi',{'type':'synthetic'})
                self.assertEqual(len(logs.output),2)
                self.assertNotIn('SECRET',' '.join(logs.output))
                self.assertEqual(session.counts['durably_acknowledged'],2)
                self.assertEqual(session.projection_error,'RuntimeError')
                self.assertIsNone(session.persistence_error)
            finally:session.journal.close()
