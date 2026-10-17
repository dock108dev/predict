"""SC03 portable examples, integration and retained resource export contract."""
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest import TestCase,IsolatedAsyncioTestCase
from app.comparison.scanner_tickets import Tickets,selector
from app.comparison.scanner_destinations import Destinations
from tests.test_sc03_tickets import CLIENT,catalog
from tests.sc03_fixture import ready

ROOT=Path(__file__).resolve().parents[1]


async def examples():
    p,f,x,row=ready();t=Tickets(p,allow_authored=True,destinations=Destinations(catalog(f['instruments'])))
    command=dict(operation='select',client_id=CLIENT,sequence=1,selection=selector(p,row))
    values=dict(command=command)
    try:
        values['selected']=await t.command(command)
        values['binding']=dict(version='predict-ticket-selection-1',selection=command['selection'],provider_requests=0)
        values['unchanged']=await t.command(dict(operation='revalidate',client_id=CLIENT,sequence=2,ticket_id=values['selected']['ticket_id']))
        values['amount_revised']=await t.command(dict(operation='revalidate',client_id=CLIENT,sequence=3,ticket_id=values['selected']['ticket_id'],amount='40'))
        values['adopted']=await t.command(dict(operation='adopt',client_id=CLIENT,sequence=4,ticket_id=values['selected']['ticket_id'],replacement_frame_id=values['amount_revised']['replacement_frame']['id']))
        p.stop();values['stopped']=t.inspect(CLIENT,values['selected']['ticket_id'])
    finally:await t.close()
    return values


class Integrated(IsolatedAsyncioTestCase):
    async def test_http_owner_uses_selected_fresh_proof_and_storage_failure_withdraws_authority(self):
        from types import SimpleNamespace
        from aiohttp import web
        from app.dashboard.scanner_ticket_api import mount
        p,f,x,row=ready();captures=[]
        def targeted(capture):
            self.assertFalse(p.lock._is_owned())
            self.assertEqual(len(capture['instruments']),2)
            captures.append(capture['pair']['id'])
            return deepcopy(f),deepcopy(x)
        def forbidden_full_capture():raise AssertionError('selected proof rebuilt the whole scanner')
        scanner=SimpleNamespace(projection=p,stopped=lambda:False,start=lambda:None,
                                _capture_selected=targeted,_capture=forbidden_full_capture)
        tickets=mount(web.Application(),scanner)
        tickets.allow_authored=True;tickets.destinations=Destinations(catalog(f['instruments']))
        command=dict(operation='select',client_id=CLIENT,sequence=1,selection=selector(p,row))
        try:
            result=await tickets.command(command)
            self.assertTrue(result['ready_for_manual_action'])
            self.assertEqual(captures,[row['pair_id']])
            prior=deepcopy(result['selected_frame'])
            def unavailable(capture):raise OSError('private database error detail')
            scanner._capture_selected=unavailable
            result=await tickets.command(dict(operation='revalidate',client_id=CLIENT,sequence=2,
                                             ticket_id=result['ticket_id']))
            self.assertFalse(result['ready_for_manual_action'])
            self.assertEqual(result['selected_frame'],prior)
            self.assertIn('ticket_current_proof_unavailable',result['reason'])
            self.assertNotIn('private database',json.dumps(result))
            self.assertFalse(tickets.inspect(CLIENT,result['ticket_id'])['ready_for_manual_action'])
        finally:await tickets.close()

    async def test_real_finance_frame_and_requested_adoption_reconcile(self):
        values=await examples();r=values['selected'];a=r['selected_frame']['result']
        self.assertTrue(r['ready_for_manual_action']);self.assertEqual(len(a['manual_legs']),2)
        self.assertEqual(a['funding']['deployed_capital_usd'],'100')
        self.assertEqual(a['funding']['buffer_usd'],'0.5')
        self.assertEqual(a['metrics']['complete_minimum_usd']['value'],'-0.5')
        self.assertEqual(r['selection']['row_id'].rsplit(':',1)[-1],'conditional_hedge')
        self.assertFalse(values['amount_revised']['ready_for_manual_action'])
        self.assertEqual(values['adopted']['selected_frame']['result']['funding']['requested_amount_usd'],'40')
        self.assertEqual(values['adopted']['state'],'unchanged')
        self.assertEqual(values['stopped']['state'],'stopped')


class Contract(TestCase):
    def test_schema_inventory_and_authored_fixture_survive_retained_export(self):
        for name in ('predict-selected-ticket-1','predict-ticket-command-1','predict-ticket-selection-1'):
            value=json.loads((ROOT/f'docs/contracts/{name}.schema.json').read_text())
            self.assertEqual(value['$id'],name)
        spec=importlib.util.spec_from_file_location('sc03_export',ROOT/'scripts/ci/export.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from hashlib import sha256
        with tempfile.TemporaryDirectory(prefix='predict-sc03-export-') as temp:
            source=Path(temp)/'source';source.mkdir();(source/'config').mkdir()
            resource=source/'app/reviews/authored.json';resource.parent.mkdir(parents=True)
            resource.write_text('{"authored":true}\n')
            retained={'app/reviews/authored.json':sha256(resource.read_bytes()).hexdigest()}
            (source/'config/ci-retained-resources.json').write_text(json.dumps(dict(resources=retained)))
            target=Path(temp)/'clean'
            module.export(target,root=source,files=['config/ci-retained-resources.json'])
            self.assertEqual((target/'app/reviews/authored.json').read_bytes(),resource.read_bytes())
            self.assertFalse((target/'.local').exists());self.assertFalse((target/'.env').exists())
            resource.write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed retained resource'):
                module.export(Path(temp)/'rejected',root=source,files=[])
