"""Actual HTTP ticket integration and transition protocol, no provider access."""
from copy import deepcopy
import json
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from aiohttp.test_utils import TestClient, TestServer
from tests.sc05_preview import create_app

ROOT=Path(__file__).resolve().parents[1]


class HTTP(IsolatedAsyncioTestCase):
    async def test_binding_specific_commands_and_transition_read_is_free(self):
        async with TestClient(TestServer(create_app())) as c:
            page=await (await c.get('/api/scanner?category=conditional_hedge&limit=100')).json()
            row=page['rows'][0]
            q={k:page[k] for k in ('server_id','epoch')}
            q.update(row_id=row['id'],dependency_revision=row['dependency_revision'],economic_revision=row['economic_revision'])
            bound=(await (await c.get('/api/scanner/ticket/binding',params=q)).json())['selection']
            command=dict(operation='select',client_id='authored_http_sc05_01',sequence=1,selection=bound,amount='40')
            selected=await (await c.post('/api/scanner/ticket',json=command)).json()
            self.assertTrue(selected['ready_for_manual_action'])
            revalidate=dict(operation='revalidate',client_id=command['client_id'],sequence=2,ticket_id=selected['ticket_id'],amount='50')
            invalid=await c.post('/api/scanner/ticket',json=dict(revalidate,selection=bound))
            self.assertEqual(invalid.status,409)
            changed=await (await c.post('/api/scanner/ticket',json=revalidate)).json()
            self.assertFalse(changed['ready_for_manual_action']);self.assertEqual(changed['selected_frame'],selected['selected_frame'])
            self.assertEqual(changed['replacement_frame']['result']['funding']['requested_amount_usd'],'50')
            adopted=await (await c.post('/api/scanner/ticket',json=dict(operation='adopt',client_id=command['client_id'],sequence=3,ticket_id=selected['ticket_id'],replacement_frame_id=changed['replacement_frame']['id']))).json()
            self.assertTrue(adopted['ready_for_manual_action'])
            before=await (await c.post('/__test/state',json={})).json()
            base=await (await c.get('/api/scanner/transitions')).json()
            self.assertEqual(base['events'],[])
            params={k:base[k] for k in ('server_id','epoch','scope','cursor')}
            for _ in range(10):
                response=await c.get('/api/scanner/transitions',params=params);v=await response.json()
                self.assertEqual(v['financial_evaluations'],0);self.assertEqual(v['provider_requests'],0)
            after=await (await c.post('/__test/state',json={})).json()
            self.assertEqual(before['financial_evaluations'],after['financial_evaluations'])
            for query in ('limit=100','amount=40','client_id=authored_http_sc05_01','fixture=true'):
                self.assertEqual((await c.get('/api/scanner/transitions?'+query)).status,400)
            self.assertEqual((await c.post('/api/scanner/ticket',json=dict(revalidate,sequence=4,allow_authored=True))).status,409)

    async def test_missing_destination_and_mandatory_facts_remove_authority(self):
        async with TestClient(TestServer(create_app())) as c:
            await c.post('/__test/state',json=dict(action='missing'))
            page=await (await c.get('/api/scanner?category=conditional_hedge&limit=100')).json();row=page['rows'][0]
            query=dict(server_id=page['server_id'],epoch=page['epoch'],row_id=row['id'],dependency_revision=row['dependency_revision'],economic_revision=row['economic_revision'])
            b=await (await c.get('/api/scanner/ticket/binding',params=query)).json()
            command=dict(operation='select',client_id='authored_http_sc05_02',sequence=1,selection=b['selection'])
            r=await (await c.post('/api/scanner/ticket',json=command)).json();self.assertFalse(r['ready_for_manual_action']);self.assertTrue(all(d['url'] is None for d in r['selected_frame']['destinations']))
            await c.post('/__test/state',json=dict(action='unknown'))
            r=await (await c.get('/api/scanner/ticket',params=dict(client_id=command['client_id'],ticket_id=r['ticket_id']))).json()
            self.assertFalse(r['ready_for_manual_action']);self.assertEqual(r['state'],'temporarily_unavailable')
