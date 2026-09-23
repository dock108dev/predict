"""Offline browser-boundary regressions; owner cannot collect or read credentials."""
import json
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from aiohttp.test_utils import AioHTTPTestCase
from app.dashboard.multi_game_server import create_app
from app.dashboard.local_security import HEADERS
from app.dashboard.query_policy import decimal_input


class BrowserBoundary(AioHTTPTestCase):
    async def get_application(self):
        self.owner = Mock()
        self.owner.session = None
        self.owner.active.return_value = False
        self.owner.saved.return_value = []
        self.owner.status.return_value = {'active': False}
        self.owner.start = AsyncMock(return_value='synthetic-session')
        self.owner.stop = AsyncMock()
        self.owner.close = AsyncMock()
        return create_app(owner=self.owner, sessions={})

    def origin(self):
        return str(self.client.make_url('/')).rstrip('/')

    async def assert_response(self, response, status):
        self.assertEqual(response.status, status, await response.text())
        for key, value in HEADERS.items():
            self.assertEqual(response.headers.get(key), value)

    async def test_host_and_browser_context(self):
        for headers in [
            {'Host': 'attacker.example'}, {'Host': '127.0.0.1:1'},
            {'Host': 'localhost:invalid'}, {'Origin': 'null'},
            {'Origin': 'https://attacker.example'}, {'Sec-Fetch-Site': 'cross-site'},
        ]:
            await self.assert_response(await self.client.get('/api/status', headers=headers), 403)
        await self.assert_response(await self.client.get('/api/status'), 200)
        port=self.client.server.port
        await self.assert_response(await self.client.get('/api/status', headers={'Host':f'localhost:{port}'}),200)

    async def test_mutations_require_origin_json_and_small_valid_body(self):
        await self.assert_response(await self.client.post('/api/start', json={}), 403)
        headers={'Origin': self.origin()}
        await self.assert_response(await self.client.post('/api/start', data='{}', headers=headers), 415)
        headers['Content-Type']='application/json'
        for body in ('{', '[]', '{"unexpected":1}'):
            await self.assert_response(await self.client.post('/api/start', data=body, headers=headers),422)
        await self.assert_response(await self.client.post('/api/start',data=' '*4097,headers=headers),413)
        await self.assert_response(await self.client.post('/api/stop',json={'unexpected':1},headers=headers),422)
        self.owner.start.assert_not_awaited()
        self.owner.stop.assert_not_awaited()
        await self.assert_response(await self.client.post('/api/start',json={'max_games':2,'duration':5},headers=headers),200)
        self.owner.start.assert_awaited_once_with(max_games=2,duration=5)
        await self.assert_response(await self.client.post('/api/stop',json={},headers=headers),200)
        self.owner.stop.assert_awaited_once()

    async def test_chunked_control_limit_is_enforced_before_dispatch(self):
        headers = {'Origin': self.origin(), 'Content-Type': 'application/json'}
        for route in ('start', 'stop'):
            async def chunks():
                yield b' ' * 4096
                yield b'{}'
            await self.assert_response(
                await self.client.post('/api/' + route, data=chunks(), headers=headers), 413)
        self.owner.start.assert_not_awaited()
        self.owner.stop.assert_not_awaited()

    async def test_ambiguous_and_excessively_nested_json_rejected(self):
        headers = {'Origin': self.origin(), 'Content-Type': 'application/json'}
        for body in ('{"duration":1,"duration":180}', '{"duration":NaN}',
                     '{"duration":Infinity}', '{"duration":1e9999}', '[' * 1100 + '0' + ']' * 1100):
            await self.assert_response(
                await self.client.post('/api/start', data=body, headers=headers), 422)
        self.owner.start.assert_not_awaited()

    async def test_encoded_request_bodies_are_not_supported(self):
        import gzip
        headers = {'Origin': self.origin(), 'Content-Type': 'application/json',
                   'Content-Encoding': 'gzip'}
        await self.assert_response(await self.client.post(
            '/api/start', data=gzip.compress(b'{}'), headers=headers), 415)
        self.owner.start.assert_not_awaited()

    async def test_imports_keep_their_separate_streamed_byte_limit(self):
        self.owner.active.return_value = True
        self.owner.session = Mock(sid='synthetic', queue=Mock(join=AsyncMock()))
        self.owner.spec_factory.return_value = {'mode': 'mock'}
        headers = {'Origin': self.origin(), 'Content-Type': 'application/json'}
        for route, target in (('references', 'app.reference.product.emit_references'),
                              ('resolutions', 'app.resolution.core.emit_records')):
            with patch(target) as emit:
                async def permitted():
                    yield b' ' * 4096
                    yield b'[{}]'
                await self.assert_response(await self.client.post(
                    '/api/' + route, data=permitted(), headers=headers), 200)
                emit.assert_called_once_with(self.owner.session, [{}])
                emit.reset_mock()
                async def oversized():
                    for _ in range(17):
                        yield b' ' * 65536
                    yield b'[{}]'
                await self.assert_response(await self.client.post(
                    '/api/' + route, data=oversized(), headers=headers), 413)
                emit.assert_not_called()

    async def test_invalid_assumptions_and_decimal_expansion(self):
        for value in ('1e-999999999','0e999999999','NaN','Infinity','1'*129):
            for key in ('probability','quantity'):
                await self.assert_response(await self.client.get('/api/dashboard',params={key:value}),422)
        for value in ([],None,{'x':[]},{'x':{'basis':5}}, {'x':{'probability':'1e-999999999'}}, {'x':{'probability':True}}):
            await self.assert_response(await self.client.get('/api/dashboard',params={'assumptions':json.dumps(value)}),422)
        self.assertEqual(decimal_input('0.342524773804','probability'),Decimal('0.342524773804'))

    async def test_error_headers_and_private_failure(self):
        await self.assert_response(await self.client.get('/'),200)
        await self.assert_response(await self.client.get('/view/dashboard.js'),200)
        await self.assert_response(await self.client.get('/missing'),404)
        await self.assert_response(await self.client.put('/api/status',json={},headers={'Origin':self.origin()}),405)
        self.owner.status.side_effect=RuntimeError('private-token-or-local-path')
        with self.assertLogs('app.dashboard.multi_game_server',level='WARNING') as logs:
            response=await self.client.get('/api/status')
        await self.assert_response(response,503)
        self.assertNotIn('private-token',await response.text())
        self.assertNotIn('private-token',' '.join(logs.output))
        self.assertIn('RuntimeError',' '.join(logs.output))


if __name__=='__main__':
    unittest.main()
