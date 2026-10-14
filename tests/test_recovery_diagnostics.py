"""Controlled failures; no provider requests or ordinary ledger writes."""
import asyncio
import json
import socket
import ssl
import time
from types import SimpleNamespace
from unittest.mock import patch
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.current_aggregate import CurrentOddsTransport
from app.collection.current_quota import QuotaStop
from app.collection.current_transport_diagnostics import exception_kind
from tests.test_current_conservative_recovery import RecoveryTransport,counters


class DiagnosticRecovery(RecoveryTransport):
    async def test_failure_categories_are_safe_and_cleanup_does_not_mask_primary(self):
        ck=SimpleNamespace(ssl=True,host='CONTROLLED',port=443)
        failures=[(aiohttp.ClientConnectorDNSError(ck,socket.gaierror('apiKey=SECRET')),'dns'),
            (aiohttp.ClientConnectorError(ck,OSError('apiKey=SECRET')),'connection'),
            (aiohttp.ClientConnectorCertificateError(ck,ssl.CertificateError('apiKey=SECRET')),'tls_certificate'),
            (TimeoutError('apiKey=SECRET'),'timeout'),(aiohttp.ClientPayloadError('apiKey=SECRET'),'body')]
        for i,(error,kind) in enumerate(failures):
            wire=self.wire();wire.phase='body' if kind=='body' else 'connection'
            async def request(req,key):
                wire.calls+=1
                if kind=='body':wire.response_receipt=dict(status=200,headers=counters(650),received_at=self.at)
                raise error
            async def close():raise OSError('apiKey=SECRET')
            wire.request=request;wire.close=close
            with self.assertRaisesRegex(QuotaStop,'observation_failed'):await self.observe(wire,identity='CONTROLLED-'+str(i))
            v=self.q._read();p=v['recovery_probes'][-1];d=p['diagnostics']
            self.assertEqual(d['primary_failure']['category'],kind);self.assertEqual(d['cleanup']['outcome'],'failed')
            self.assertEqual(d['receipt_present'],kind=='body');self.assertEqual(wire.calls,1)
            self.assertNotIn('SECRET',json.dumps(v));self.assertEqual(v['attempts'][self.aid],self.old)
            self.q.pause(None)
    async def test_quota_headers_refuse_without_activation(self):
        for i,h in enumerate(([['x-requests-used','bad']],counters(650)+[['x-requests-used','650']])):
            wire=self.wire();old=wire.request
            async def request(req,key):
                r=await old(req,key);r['headers']=h;wire.response_receipt=dict(r,body=None);return r
            wire.request=request
            with self.assertRaisesRegex(QuotaStop,'quota_missing'):await self.observe(wire,identity='bad-'+str(i))
            p=self.q._read()['recovery_probes'][-1]
            self.assertEqual(p['diagnostics']['primary_failure']['phase'],'validation')
            self.assertTrue(p['diagnostics']['receipt_present']);self.assertEqual(p['diagnostics']['http_status'],200)
            self.assertEqual(self.q._read().get('conservative_recoveries',[]),[]);self.q.pause(None)
    async def test_cancellation_propagates_and_probe_finishes(self):
        wire=self.wire();entered=asyncio.Event()
        async def request(req,key):entered.set();await asyncio.Event().wait()
        wire.request=request
        task=asyncio.create_task(self.observe(wire));await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        p=self.q._read()['recovery_probes'][-1]
        self.assertEqual(p['state'],'failed');self.assertEqual(p['diagnostics']['primary_failure']['category'],'cancelled')
        self.assertTrue(wire.closed);self.assertEqual(self.q.snapshot()['reserved'],3)
    async def test_cleanup_precedes_activation(self):
        wire=self.wire()
        async def close():
            self.assertEqual(self.q._read().get('conservative_recoveries',[]),[])
            raise OSError('SECRET')
        wire.close=close
        with self.assertRaisesRegex(QuotaStop,'cleanup'):await self.observe(wire)
        self.assertEqual(self.q._read().get('conservative_recoveries',[]),[])
    async def test_delayed_callback_is_recorded(self):
        wire=self.wire();old=wire.request
        async def request(req,key):
            await asyncio.sleep(.06);time.sleep(.15);await asyncio.sleep(.06)
            return await old(req,key)
        wire.request=request;await self.observe(wire)
        self.assertGreater(self.q._read()['recovery_probes'][-1]['diagnostics']['max_callback_delay_seconds'],.1)
    async def test_real_transport_partial_body_receipt_and_secret_suppression(self):
        async def handler(req):
            r=web.StreamResponse(headers=dict(counters(650)));r.enable_chunked_encoding();await r.prepare(req)
            await r.write(b'[');req.transport.close();return r
        app=web.Application();app.router.add_get('/v4/sports',handler)
        async with TestServer(app) as server:
            wire=CurrentOddsTransport()
            with patch('app.collection.current_aggregate.BASE',str(server.make_url('')).rstrip('/')):
                with self.assertRaises(aiohttp.ClientPayloadError):await wire.request(dict(path='/v4/sports',params={}), 'CONTROLLED-key')
            self.assertEqual(wire.response_receipt['status'],200);self.assertEqual(wire.phase,'body');await wire.close()
    async def test_real_timeout_before_headers_retains_no_receipt(self):
        from dataclasses import replace
        from app.collection.current_aggregate import POLICY
        async def handler(req):
            await asyncio.sleep(.2);return web.json_response([])
        app=web.Application();app.router.add_get('/v4/sports',handler)
        async with TestServer(app) as server:
            wire=CurrentOddsTransport()
            with patch('app.collection.current_aggregate.BASE',str(server.make_url('')).rstrip('/')),patch('app.collection.current_aggregate.POLICY',replace(POLICY,timeout_seconds=.05)):
                with self.assertRaises(TimeoutError):await wire.request(dict(path='/v4/sports',params={}), 'CONTROLLED-key')
            self.assertIsNone(wire.response_receipt);self.assertEqual(wire.phase,'awaiting_headers');await wire.close()
    async def test_real_transport_suppresses_secret_echo(self):
        async def handler(req):return web.json_response({'apiKey':'CONTROLLED-key'},headers=dict(counters(650)))
        app=web.Application();app.router.add_get('/v4/sports',handler)
        async with TestServer(app) as server:
            wire=CurrentOddsTransport()
            with patch('app.collection.current_aggregate.BASE',str(server.make_url('')).rstrip('/')):
                with self.assertRaisesRegex(QuotaStop,'secret_echo'):await wire.request(dict(path='/v4/sports',params={}), 'CONTROLLED-key')
            self.assertEqual(wire.response_receipt['status'],200);await wire.close()
