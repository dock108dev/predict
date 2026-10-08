"""Shared finite reader in ordinary collection; only numeric loopback traffic."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection import coverage, native_payload
from app.collection.continuous import REST, Discovery
from app.collection.odds_http import BudgetStop
from app.collection.prediction_producer import PredictionBudget
from app.collection.run_spec import preflight
from app.collection.transport_session import reopen
from app.dashboard.coverage_owner import CoverageOwner, spec
from app.dashboard.session_history import load, project_rows
from tests.segmented_collector_fixture import Fixture
from tests.test_coverage import pe
from tests.test_native_http_reader import server, fixed


def configuration():
    value=spec();value.update(mode='mock',reference_enabled=False)
    value['v1_comparison_policy']=None  # Original wire-fixture interpretation.
    value['native_transport']=deepcopy(native_payload.TRANSPORT_CONTRACT)
    value['native_sources']={v:dict(state='enabled',environment='production',
        poll_seconds=10,event_cap=1,market_cap=2) for v in ('kalshi','polymarket_us')}
    value['native_sources'].update({v:dict(state='disabled',selected=False) for v in ('novig','prophetx')})
    return value


class Policy(unittest.TestCase):
    def test_explicit_ordinary_and_directed_contracts_keep_legacy_unchanged(self):
        value=configuration()
        self.assertTrue(preflight(value)['valid'],preflight(value)['errors'])
        self.assertEqual(native_payload.validate_transport(value),native_payload.TRANSPORT_CONTRACT)
        old=deepcopy(value);old.pop('native_transport')
        self.assertIsNone(native_payload.validate_transport(old))
        self.assertFalse(native_payload.enabled(old))
        from tests.test_source_session import settings
        ordinary_unified=deepcopy(value);ordinary_unified['source_session']=settings()
        self.assertEqual(native_payload.validate_transport(ordinary_unified),native_payload.TRANSPORT_CONTRACT)
        self.assertTrue(native_payload.enabled(ordinary_unified))
        directed=deepcopy(ordinary_unified)
        directed['source_session']['native_discovery']=native_payload.POLICY
        self.assertEqual(native_payload.validate_transport(directed),native_payload.TRANSPORT_CONTRACT)
        gap=deepcopy(value)
        gap['native_discovery']=dict(policy='sport-directed-games-v1',slice='native-gaps-v1')
        gap['native_transport']=deepcopy(native_payload.TRANSPORT_CONTRACT)
        self.assertEqual(native_payload.validate_transport(gap),native_payload.TRANSPORT_CONTRACT)

    def test_timeout_and_exact_contract_types_fail_before_activation(self):
        for timeout in (0,31,True,'5',float('inf'),float('nan')):
            with self.subTest(timeout=timeout):
                value=configuration();value['http']={'timeout':timeout}
                self.assertFalse(preflight(value)['valid'])
        value=configuration();value['native_transport']['json_depth']=32.0
        self.assertFalse(preflight(value)['valid'])
        page=dict(path='/v1/events/246810',transport_policy=value['native_transport'])
        with self.assertRaisesRegex(ValueError,'native_transport_contract_mismatch'):
            coverage.decode_page(page)

    def test_detail_routes_have_no_event_or_pregame_dependency(self):
        self.assertEqual(native_payload.category('/v1/events/246810'),'discovery')
        self.assertEqual(native_payload.category('/v1/market/id/7654321'),'metadata')
        # Whole delivery can establish its envelope while identity and state fail.
        event=pe('246810');event.update(startTime='2026-01-01T00:00:00Z',closed=True)
        raw=json.dumps({'event':event}).encode()
        page=dict(source='polymarket_us',path='/v1/events/246810',params={},status=200,
            complete=True,usable_metadata=True,transport_policy=deepcopy(native_payload.TRANSPORT_CONTRACT),
            acquisition_discovery_policy='sport-directed-games-v1',
            received_at=datetime.now(timezone.utc).isoformat(),
            body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
        native_payload.validate_envelope({'event':event},page['path'])
        accepted,state=coverage.traversal([page],'polymarket_us','events')
        self.assertEqual(len(accepted),1);self.assertEqual(state['state'],'exhausted')
        cat=coverage.catalog([page],'polymarket_us',datetime.now(timezone.utc))
        self.assertTrue(cat['excluded_catalog']['events'][0][3])
        from app.collection.continuous import select_inventory
        self.assertEqual(select_inventory(cat,datetime.now(timezone.utc))[0],[])
        event['id']='different';raw=json.dumps({'event':event}).encode()
        page.update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
        self.assertEqual(coverage.catalog([page],'polymarket_us',datetime.now(timezone.utc))['excluded_catalog']['events'][0][3],
                         'conflicting_query_identity')

    def test_all_supported_envelopes_validate_before_semantic_admission(self):
        for path,field in (('/v1/events','events'),('/trade-api/v2/events','events'),
                           ('/v2/leagues/nba/events','events'),('/v2/leagues','leagues'),
                           ('/v1/markets','markets'),('/v1/events/246810','event'),
                           ('/v1/market/id/7654321','market')):
            with self.subTest(path=path):
                native_payload.validate_envelope({field:{} if field in ('event','market') else []},path)
                with self.assertRaisesRegex(ValueError,'native_unexpected_envelope'):
                    native_payload.validate_envelope({field:[None]},path)

    def test_resource_measurements_follow_generations_and_keep_peak(self):
        rows=[];s=SimpleNamespace(spec=configuration(),producers={},emit=lambda v,r:rows.append(r))
        d=Discovery(s)
        with patch('app.dashboard.bounds.retained_bytes',side_effect=(400,400,100)):
            d.bound_source_catalog('polymarket_us',{});d.bound_source_catalog('polymarket_us',{})
            d.generation=2;d.bound_source_catalog('polymarket_us',{})
        self.assertEqual(len(rows),2)
        self.assertEqual(d.source_resource_measurements['polymarket_us']['last_bytes'],100)
        self.assertEqual(d.source_resource_measurements['polymarket_us']['max_bytes'],400)


class HTTP(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_discovery_status_recovery_keeps_precise_receipts(self):
        calls=[];rows=[];stops=[];value=configuration();client=None
        async def deliver(writer):
            calls.append(True)
            writer.write(fixed(b'{"error":"SIMULATED unavailable"}',status=b'503 Service Unavailable',
                               headers=b'Retry-After: 0\r\n') if len(calls)==1 else fixed(b'{"events":[]}'))
            await writer.drain()
        async with server(deliver) as (endpoint,_):
            budget=PredictionBudget(value['prediction'])
            client=REST(endpoint,value['prediction'],rows.append,1,budget)
            client.session=SimpleNamespace(spec=value,discovery=SimpleNamespace(stop_source=lambda *a:stops.append(a)),
                                           request_stop=stops.append)
            client.source_venue='polymarket_us'
            with patch.object(client,'bounded_wait',return_value=None):
                try:response=await client.get(endpoint+'/v1/events',{})
                finally:await client.aclose()
        self.assertEqual(response.status_code,200);self.assertEqual(len(calls),2)
        self.assertEqual(rows[0]['delivery_reason'],'native_http_status_503')
        self.assertTrue(rows[0]['complete']);self.assertFalse(rows[0]['usable_metadata'])
        self.assertTrue(rows[1]['envelope_valid']);self.assertFalse(stops)
        self.assertEqual(budget.bytes,sum(row['resource_usage']['wire_bytes'] for row in rows))

    async def test_scoped_http_has_no_hidden_retry_and_hard_generation_ceiling(self):
        calls=[];rows=[];stops=[];value=configuration()
        async def deliver(writer):
            calls.append(True);writer.write(fixed(b'{"error":"SIMULATED unavailable"}',status=b'503 Service Unavailable'));await writer.drain()
        async with server(deliver) as (endpoint,_):
            client=REST(endpoint,value['prediction'],rows.append,1,PredictionBudget(value['prediction']))
            client.session=SimpleNamespace(spec=value,discovery=SimpleNamespace(stop_source=lambda *a:stops.append(a)),request_stop=stops.append)
            client.source_venue='polymarket_us';client.native_scope_request_context=True;client.native_scope_generation_ceiling=1
            try:
                response=await client.get(endpoint+'/v1/events',{})
                with self.assertRaisesRegex(BudgetStop,'native_scope_generation_request_cap'):
                    await client.get(endpoint+'/v1/events',{})
            finally:await client.aclose()
        self.assertEqual(response.status_code,503);self.assertEqual(len(calls),1);self.assertEqual(client.requests,1)
        self.assertFalse(stops);self.assertEqual(rows[0]['delivery_reason'],'native_http_status_503')

    async def test_ordinary_singular_detail_uses_v2_and_rejects_bad_envelope(self):
        for body,reason in ((b'{"event":{"id":"246810","closed":true},"padding":"'+b'x'*600000+b'"}',None),
                            (b'{"events":[]}','native_unexpected_envelope')):
            with self.subTest(reason=reason):
                async def deliver(writer):writer.write(fixed(body));await writer.drain()
                async with server(deliver) as (endpoint,_):
                    value=configuration();rows=[];stops=[];budget=PredictionBudget(value['prediction'])
                    client=REST(endpoint,value['prediction'],rows.append,1,budget)
                    client.session=SimpleNamespace(spec=value,discovery=SimpleNamespace(stop_source=lambda *a:stops.append(a)),
                                                   request_stop=stops.append)
                    client.source_venue='polymarket_us'
                    try:
                        if reason:
                            with self.assertRaisesRegex(BudgetStop,'^'+reason+'$'):await client.get(endpoint+'/v1/events/246810',{})
                        else:
                            response=await client.get(endpoint+'/v1/events/246810',{})
                            self.assertEqual(response.json()['event']['id'],'246810')
                        self.assertEqual(rows[0]['delivery_reason'],reason)
                        self.assertTrue(rows[0]['complete'])
                        self.assertEqual(rows[0]['usable_metadata'],reason is None)
                        self.assertEqual(rows[0]['resource_usage']['request_category'],'discovery')
                        self.assertEqual(budget.bytes,rows[0]['resource_usage']['wire_bytes'])
                    finally:await client.aclose()

    async def test_whole_ordinary_loop_persists_large_delivery_and_exact_reopening(self):
        f=Fixture();original=f.rest
        async def rest(req):
            if req.path=='/v1/events':
                response=await original(req);body=json.loads(response.body)
                body['padding']='SIMULATED '+ 'x'*600000
                return web.json_response(body)
            return await original(req)
        feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',rest)
        f.server=TestServer(feeds);await f.server.start_server();endpoint=str(f.server.make_url('/')).rstrip('/')
        endpoints={v:dict(rest=endpoint,ws=endpoint.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        with tempfile.TemporaryDirectory() as temporary,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
            f.owner=CoverageOwner(Path(temporary)/'unused',pilot_output=Path(temporary)/'sessions',
                endpoints=endpoints,product_mode=True,spec_factory=configuration)
            try:
                await f.owner.start(duration=30)
                save=f.owner.session.journal.save
                def saved(row):save(row);f.books+=row['type']=='prediction_book';f.changed.set()
                f.owner.session.journal.save=saved
                await f.wait(lambda:len(f.active())==2);await f.images()
                await f.owner.stop();await f.owner.finalizer
                rows=reopen(f.owner.session.journal.path)['rows']
                receipts=[r for r in rows if r['type']=='prediction_discovery_http']
                self.assertTrue(all(r['transport_policy']==native_payload.TRANSPORT_CONTRACT for r in receipts))
                self.assertTrue(any(r['resource_usage']['entity_bytes_read']>524288 for r in receipts))
                self.assertFalse(f.owner.session.discovery.source_stops)
                self.assertTrue(f.owner.session.cleanup_complete)
                saved_view=load(f.owner.session.output)
                self.assertEqual(saved_view,project_rows(rows,saved_view['durable_cursor']))
                self.assertEqual({r['source'] for r in rows if r['type']=='prediction_book'},{'kalshi','polymarket_us'})
                self.assertTrue(f.owner.session.discovery.status()['source_catalog_resources'])
            finally:await f.close()


if __name__=='__main__':unittest.main()
