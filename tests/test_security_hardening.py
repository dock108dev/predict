"""Local browser and private-write boundaries; no owner data or provider access."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from multidict import CIMultiDict
from app.collection.continuous import Discovery
from app.dashboard.local_security import check_browser, read_json
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.multi_game_server import create_app
from app.dashboard.opportunity_history import WatchStore
from tests.test_coverage import fixture, AS_OF


class BrowserHardening(AioHTTPTestCase):
    async def get_application(self):
        self.owner = Mock()
        self.owner.start_controls = frozenset({'duration'})
        self.owner.session = None
        self.owner.status.return_value = {'active':False}
        self.owner.start = AsyncMock(return_value='synthetic')
        self.owner.stop = AsyncMock()
        self.owner.close = AsyncMock()
        return create_app(owner=self.owner, sessions={})

    async def test_same_site_other_local_origin_and_ambiguous_metadata_denied(self):
        for site in ('same-site', 'cross-site', 'invalid'):
            response = await self.client.get('/api/status', headers={'Sec-Fetch-Site':site})
            self.assertEqual(response.status, 403)
        for site in ('same-origin', 'none'):
            response = await self.client.get('/api/status', headers={'Sec-Fetch-Site':site})
            self.assertEqual(response.status, 200)
        headers = CIMultiDict([('Host','localhost:8783'),
                              ('Sec-Fetch-Site','same-origin'), ('Sec-Fetch-Site','cross-site')])
        request = SimpleNamespace(headers=headers, method='GET',
            transport=Mock(get_extra_info=Mock(return_value=('127.0.0.1',8783))))
        with self.assertRaises(web.HTTPForbidden):check_browser(request)

    async def test_incomplete_body_deadline_closes_connection_without_dispatch(self):
        stalled = asyncio.Event()
        async def chunks():
            yield b'{'
            await stalled.wait()
        origin = str(self.client.make_url('/')).rstrip('/')
        with patch('app.dashboard.local_security.BODY_READ_SECONDS', .05):
            response = await self.client.post('/api/start', data=chunks(),
                headers={'Origin':origin, 'Content-Type':'application/json'})
        self.assertEqual(response.status, 408)
        self.assertEqual(response.headers.get('Connection'), 'close')
        self.assertEqual((await response.json())['error'], 'JSON body deadline exceeded')
        self.owner.start.assert_not_awaited()
        # Timed-out uploads do not consume a subscription or control slot.
        self.assertEqual((await self.client.get('/api/status')).status, 200)
        self.assertEqual((await self.client.post('/api/stop', json={},
            headers={'Origin':origin})).status, 200)
        self.owner.stop.assert_awaited_once()

    async def test_progress_does_not_reset_body_deadline(self):
        async def chunks():
            yield b' '
            for _ in range(10):
                await asyncio.sleep(.015)
                yield b' '
            yield b'{}'
        with patch('app.dashboard.local_security.BODY_READ_SECONDS', .05):
            response = await self.client.post('/api/stop', data=chunks(), headers={
                'Origin':str(self.client.make_url('/')).rstrip('/'), 'Content-Type':'application/json'})
        self.assertEqual(response.status, 408)
        await response.read()
        self.owner.stop.assert_not_awaited()

    async def test_body_reader_preserves_external_cancellation(self):
        original = asyncio.CancelledError()
        request = SimpleNamespace(path='/api/start',content_length=None,
            content=Mock(read=AsyncMock(side_effect=original)))
        with self.assertRaises(asyncio.CancelledError) as caught:await read_json(request)
        self.assertIs(caught.exception,original)

    async def test_internal_value_errors_and_chains_are_private(self):
        errors = (ValueError('SECRET provider URL or local path'),
                  json.JSONDecodeError('SECRET parser detail', '{}', 0),
                  UnicodeDecodeError('utf-8', b'SECRET\xff', 6, 7, 'SECRET encoding detail'))
        for error in errors:
            with self.subTest(error=type(error).__name__):
                error.__cause__ = RuntimeError('SECRET nested cause')
                self.owner.status.side_effect = error
                with self.assertLogs('app.dashboard.multi_game_server', level='ERROR') as logs:
                    response = await self.client.get('/api/status')
                self.assertEqual(response.status, 422)
                self.assertNotIn('SECRET', await response.text() + ' '.join(logs.output))
                self.assertIn(type(error).__name__, ' '.join(logs.output))
                self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_authored_validation_remains_actionable(self):
        response = await self.client.post('/api/start', json={'unexpected':'SECRET'},
            headers={'Origin':str(self.client.make_url('/')).rstrip('/')})
        self.assertEqual(response.status, 422)
        self.assertEqual((await response.json())['error'], 'Unknown scan controls')
        self.owner.start.assert_not_awaited()
        response = await self.client.get('/api/dashboard', params={'assumptions':'{"SECRET":'})
        self.assertEqual(response.status, 422)
        self.assertNotIn('SECRET', await response.text())

    async def test_duplicate_query_fields_rejected_before_handlers(self):
        self.owner.status.reset_mock()
        for path, key, first, second in (
            ('/api/status', 'unused', 'a', 'b'),
            ('/api/current/changes', 'state_revision', '1', '2'),
            ('/api/arbs', 'market', 'winner', 'spread'),
            ('/api/comparison', 'ceiling', '20', '100'),
            ('/api/coverage', 'venue', 'kalshi', 'novig'),
            ('/api/dashboard', 'quantity', '20', '100'),
        ):
            with self.subTest(path=path):
                response = await self.client.get(path, params=[(key, first), (key, second)])
                self.assertEqual(response.status, 422)
                self.assertEqual((await response.json())['error'], 'Duplicate selection')
        self.owner.status.assert_not_called()
        self.assertEqual((await self.client.get('/api/status')).status, 200)

    async def test_admin_requires_an_object_without_dispatch(self):
        provider = Mock(status=Mock(return_value={'state':'stopped'}), close=AsyncMock(),
                        refresh_aggregate=AsyncMock(), pause=AsyncMock(), recover=AsyncMock())
        self.app[CURRENT_KEY].provider = provider
        origin = str(self.client.make_url('/')).rstrip('/')
        for value in (None, [], [{}], 'stop', 1, True):
            with self.subTest(value=value):
                response = await self.client.post('/api/admin/current', data=json.dumps(value),
                    headers={'Origin':origin, 'Content-Type':'application/json'})
                self.assertEqual(response.status, 422)
                self.assertEqual((await response.json())['error'], 'Exact native admin control object required')
        provider.close.assert_not_awaited()
        provider.pause.assert_not_awaited()
        provider.refresh_aggregate.assert_not_awaited()
        provider.recover.assert_not_awaited()
        response = await self.client.post('/api/admin/current', json={'action':'stop'},
            params=[('action','stop'), ('action','recover')], headers={'Origin':origin})
        self.assertEqual(response.status, 422)
        provider.close.assert_not_awaited()
        response = await self.client.post('/api/admin/current', json={'action':'stop'}, headers={'Origin':origin})
        self.assertEqual(response.status, 200)
        provider.close.assert_awaited_once()


class SyntheticCollectionBoundary(AioHTTPTestCase):
    """Exercise the auxiliary router without PostgreSQL or a collection session."""
    async def get_application(self):
        from app.collection.server import create_app as synthetic_app
        self.tmp = tempfile.TemporaryDirectory(prefix='synthetic-browser-boundary-')
        root = Path(self.tmp.name)
        (root/'e6-environment.json').write_text('{}')
        self.db = Mock()
        self.db.execute.return_value.fetchone.return_value = {'n':0}
        self.env = Mock(root=root, connect=Mock(return_value=MagicMock()))
        self.env.connect.return_value.__enter__.return_value = self.db
        with patch('app.collection.server.Repository') as repository:
            repository.return_value.recover.return_value = []
            app = synthetic_app(self.env, root/'output')
        self.env.connect.reset_mock()
        return app

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    def origin(self):
        return str(self.client.make_url('/')).rstrip('/')

    async def test_host_origin_and_metadata_reject_before_database_access(self):
        for headers in ({'Host':'127.0.0.1:1'}, {'Host':'localhost:1'},
                        {'Sec-Fetch-Site':'same-site'}, {'Sec-Fetch-Site':'cross-site'}):
            response = await self.client.get('/api/status', headers=headers)
            self.assertEqual(response.status, 403)
            self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        for headers in ({}, {'Origin':'null'}, {'Origin':'https://example.invalid'}):
            response = await self.client.post('/api/start', json={'seconds':30}, headers=headers)
            self.assertEqual(response.status, 403)
        self.env.connect.assert_not_called()
        response = await self.client.post('/api/start', data='{}', headers={'Origin':self.origin()})
        self.assertEqual(response.status, 415)
        self.env.connect.assert_not_called()
        self.assertEqual((await self.client.get('/api/status')).status, 200)
        response = await self.client.post('/api/stop', json={}, headers={'Origin':self.origin()})
        self.assertEqual(response.status, 200)

    async def test_small_strict_body_and_deadline_preserve_controls(self):
        headers = {'Origin':self.origin(), 'Content-Type':'application/json'}
        for body, status in ((' '*2049, 413), ('{"a":1,"a":2}', 422), ('{', 422)):
            response = await self.client.post('/api/stop', data=body, headers=headers)
            self.assertEqual(response.status, status)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        async def oversized():
            yield b' '*2048
            yield b'{}'
        response = await self.client.post('/api/stop', data=oversized(), headers=headers)
        self.assertEqual(response.status, 413)
        async def stalled():
            yield b'{'
            await asyncio.Event().wait()
        with patch('app.dashboard.local_security.BODY_READ_SECONDS', .05):
            response = await self.client.post('/api/stop', data=stalled(), headers=headers)
        self.assertEqual(response.status, 408)
        self.assertEqual(response.headers['Connection'], 'close')
        self.assertEqual(self.app['active_requests'], 0)
        self.env.connect.assert_not_called()
        response = await self.client.post('/api/stop', json={}, headers=headers)
        self.assertEqual(response.status, 200)

    async def test_internal_errors_and_duplicate_queries_stay_private(self):
        self.db.execute.side_effect = ValueError('SECRET internal database detail')
        with self.assertLogs('app.collection.server', level='ERROR') as logs:
            response = await self.client.post('/api/start', json={'seconds':30},
                headers={'Origin':self.origin()})
        self.assertEqual(response.status, 422)
        self.assertNotIn('SECRET', await response.text() + ' '.join(logs.output))
        self.assertEqual(self.app['active_requests'], 0)
        response = await self.client.get('/api/status', params=[('x','1'), ('x','2')])
        self.assertEqual(response.status, 422)


class WatchWriteHardening(unittest.TestCase):
    def watch(self):
        return dict(name='Synthetic watch', metric='raw_gap', threshold='0', quantity='1', filters={})

    def test_predictable_staging_symlink_cannot_overwrite_other_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root/'victim.txt';victim.write_text('preserve')
            path = root/'watch.json'
            path.with_suffix('.tmp').symlink_to(victim)
            result = WatchStore(path).save([self.watch()])
            self.assertEqual(victim.read_text(),'preserve')
            self.assertEqual(WatchStore(path).read(),result)
            self.assertTrue(path.with_suffix('.tmp').is_symlink())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)

    def test_destination_symlink_replaced_without_touching_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root/'victim.txt';victim.write_text('preserve')
            path = root/'watch.json';path.symlink_to(victim)
            WatchStore(path).save([self.watch()])
            self.assertFalse(path.is_symlink())
            self.assertEqual(victim.read_text(),'preserve')

    def test_private_new_directory_and_atomic_failures_preserve_previous_data(self):
        for stage in ('fsync','replace'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'new-local/watch.json'
                store = WatchStore(path);store.save([self.watch()])
                original = path.read_bytes()
                changed = dict(self.watch(),name='Changed')
                with patch('app.dashboard.opportunity_history.os.'+stage,
                           side_effect=OSError('synthetic write failure')):
                    with self.assertRaises(OSError):store.save([changed])
                self.assertEqual(path.read_bytes(),original)
                self.assertEqual(list(path.parent.iterdir()),[path])
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode),0o700)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)

    def test_secondary_staging_cleanup_preserves_primary_write_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'watch.json';store=WatchStore(path)
            store.save([self.watch()]);original_bytes=path.read_bytes()
            original=OSError('SECRET replace failure')
            with patch('app.dashboard.opportunity_history.os.replace',side_effect=original), \
                 patch.object(Path,'unlink',side_effect=OSError('SECRET cleanup')):
                with self.assertLogs('app.dashboard.opportunity_history',level='ERROR') as logs:
                    with self.assertRaises(OSError) as caught:store.save([self.watch()])
            self.assertIs(caught.exception,original)
            self.assertEqual(path.read_bytes(),original_bytes)
            self.assertNotIn('SECRET',' '.join(logs.output))


class NativeFailurePrivacy(unittest.IsolatedAsyncioTestCase):
    async def test_source_and_refresh_failures_never_publish_exception_text(self):
        for product in (True, False):
            with self.subTest(product=product):
                emitted=[]
                session=SimpleNamespace(spec={},credentials={},producers={},
                    product_session=product, emit=lambda source,row:emitted.append(row))
                discovery=Discovery(session)
                async def venue(source):
                    if source == 'kalshi':raise OSError('SECRET credential-bearing URL')
                    discovery.pages.extend(p for p in deepcopy(fixture()) if p['source']==source)
                discovery.venue=venue
                with patch('app.collection.continuous.now',return_value=AS_OF):
                    with self.assertLogs('app.collection.continuous',level='ERROR') as logs:
                        if product:await discovery.discover()
                        else:
                            with self.assertRaises(ValueError):await discovery.discover()
                public=json.dumps(dict(status=discovery.status(),rows=emitted))
                self.assertNotIn('SECRET',public+' '.join(logs.output))
                self.assertIn('OSError',public+' '.join(logs.output))
                if product:
                    self.assertEqual(discovery.source_stops['kalshi'],'OSError')
                    self.assertTrue(discovery.inventory['polymarket_us']['markets'])
                else:self.assertEqual(discovery.refresh['reason'],'ValueError')


if __name__ == '__main__':unittest.main()
