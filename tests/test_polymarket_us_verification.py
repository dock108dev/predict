"""Synthetic bounded verification runner; captured public REST regressions."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.adapters.polymarket_us import Response,parse_book,parse_bbo,decode
from app.adapters.polymarket_us_stream import MarketStream
from app.polymarket_us_verify import load_market,verify,save_stream_evidence
from app.models.core import EvidenceKind,BookSync
from tests.test_polymarket_us import market,no_sleep
from tests.test_polymarket_us_stream import message

CAPTURE=Path(__file__).resolve().parents[1]/'evidence/slice-2/verification-20260911T231849Z/public-smoke'

class Verification(unittest.IsolatedAsyncioTestCase):
    async def test_deliberate_disconnect_reconnect_cancel_runner(self):
        class FakeSocket:
            def __init__(self):self.closed=asyncio.Event();self.request_id=None;self.first=True
            async def send(self,body):self.request_id=json.loads(body)['subscribe']['requestId']
            async def recv(self):
                if self.first:
                    self.first=False
                    return message(self.request_id)
                await self.closed.wait()
                raise ConnectionError('synthetic close')
            async def close(self):self.closed.set()
        sockets=[]
        async def factory():
            sock=FakeSocket();sockets.append(sock);return sock
        with tempfile.TemporaryDirectory() as folder, patch('app.polymarket_us_verify.datetime', wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,9,11,tzinfo=timezone.utc)
            result=await verify(market(),None,Path(folder)/'result',factory=factory,
                disconnect_after=.01,cancel_after=.06,duration=.2,stale_seconds=.005,
                kind=EvidenceKind.SYNTHETIC,retry_sleep=no_sleep)
            self.assertEqual(result['evidence_kind'],'synthetic_transport_test')
            self.assertEqual(len(sockets),2)
            self.assertTrue(all(s.closed.is_set() for s in sockets))
            self.assertTrue(all(result['exercise'].values()))
            self.assertNotEqual(sockets[0].request_id,sockets[1].request_id)
            self.assertIn('market_data_stale',result['diagnostics'])
            self.assertEqual(len([m for m in result['messages'] if 'file' in m]),2)

    def test_evidence_excludes_credentials_and_unknown_envelopes(self):
        stream=MarketStream([market()],None,kind=EvidenceKind.SYNTHETIC)
        for body in ['{"authorization":"synthetic-secret"}', '{"error":"synthetic-secret"}', 'invalid']:
            stream.responses.append(Response(body,'synthetic://test',datetime.now(timezone.utc),EvidenceKind.SYNTHETIC))
        with tempfile.TemporaryDirectory() as folder:
            save_stream_evidence(Path(folder),stream,market(),{})
            self.assertNotIn('synthetic-secret',(Path(folder)/'result.json').read_text())
            self.assertEqual(len(list(Path(folder).glob('market-frame-*'))),0)

    def test_new_public_capture_preserves_units_identity_and_clocks(self):
        m=load_market(CAPTURE)
        provenance=json.loads((CAPTURE/'provenance.json').read_text())
        row=next(r for r in provenance if r['source'].endswith('/book'))
        response=Response((CAPTURE/row['file']).read_text(),row['source'],datetime.fromisoformat(row['received_at']))
        b=parse_book(response,decode(response.body)['marketData'],m)
        self.assertEqual(m.raw.ref.market_id,'381955')
        self.assertEqual([o.native_id for o in m.outcomes],['763424','763425'])
        self.assertEqual(len(b.outcomes[0].bids.levels),26)
        self.assertEqual(len(b.outcomes[0].asks.levels),27)
        self.assertEqual(str(b.outcomes[0].bids.levels[0].quantity.value),'145489.5600')
        self.assertIn('2026-09-11T23:06:03.697243528Z',response.body)
        self.assertEqual(b.sync,BookSync.UNKNOWN)
        self.assertGreater(b.raw.source_age_at_receipt.total_seconds(), 12*60)
        row=next(r for r in provenance if r['source'].endswith('/bbo'))
        response=Response((CAPTURE/row['file']).read_text(),row['source'],datetime.fromisoformat(row['received_at']))
        q=parse_bbo(response,decode(response.body)['marketData'],m)
        self.assertIsNone(q.bid.quantity)
        self.assertIsNone(q.raw.exchange_at) # lastPriceSample.ts is not BBO transactTime

    def test_authenticated_capture_native_images_and_reconnect(self):
        path=CAPTURE.parent/'authenticated-01'
        m=load_market(CAPTURE)
        stream=MarketStream([m],None)
        frames=sorted(path.glob('market-frame-*.json'))
        self.assertEqual(len(frames),12)
        request_ids=set()
        for f in frames:
            data=decode(f.read_text())
            request_ids.add(data['requestId'])
            if stream.subscription_id != data['requestId']:
                generation=stream.begin_subscription(data['requestId'])
            b=stream.parse(f.read_text(),data['requestId'],generation=generation)
            self.assertEqual(b.sync,BookSync.SYNCHRONIZED)
            self.assertEqual(b.outcomes[0].outcome_id,'763424')
            self.assertIsNone(b.outcomes[1].bids)
            self.assertEqual(len(b.outcomes[0].bids.levels),26)
            self.assertEqual(len(b.outcomes[0].asks.levels),27)
        self.assertEqual(len(request_ids),2)
        # The observed reconnect image repeats the last pre-disconnect image.
        self.assertEqual(decode(frames[3].read_text())['marketData'],decode(frames[4].read_text())['marketData'])

    async def test_failed_response_and_safe_cache_metadata_preserved(self):
        import httpx
        from app.adapters.polymarket_us import PolymarketUSAdapter
        async with PolymarketUSAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r:httpx.Response(404,text='{"error":"unavailable"}',headers={
                'Cache-Control':'public, max-age=30','Age':'12','Set-Cookie':'synthetic-private'})))) as a:
            with self.assertRaises(LookupError):await a.discover_events()
            self.assertEqual(a.responses[0].http_status,404)
            self.assertEqual(decode(a.responses[0].body)['error'],'unavailable')
            self.assertEqual(dict(a.responses[0].http_headers)['age'],'12')
            self.assertNotIn('set-cookie',dict(a.responses[0].http_headers))
