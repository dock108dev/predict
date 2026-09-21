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
