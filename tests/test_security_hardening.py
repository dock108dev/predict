"""Local browser and private-write boundaries; no owner data or provider access."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from multidict import CIMultiDict
from app.collection.continuous import Discovery
from app.dashboard.local_security import check_browser, read_json
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
