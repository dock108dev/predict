"""Current v2 transport and financial traces using labeled retained adapter facts."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.comparison_board import response, details, entries
from app.storage.comparison_board import ReadContext, discover, calculate_current, context_identity
from app.storage.store import encoded
from tests.test_ev09_n01 import retained, AT


def frame(records=None,epoch='authored-current-epoch'):
    return dict(epoch=epoch,revision='authored-current-revision',records=deepcopy(records if records is not None else retained()[0]['records']))


def context(value=None,at=AT):
    with patch('app.storage.current_rows.CurrentRowStore.capture',return_value=value or frame()):return ReadContext(SimpleNamespace(db=None),at=at)


def bundle(c,policy=DEFAULT_POLICY):
    b=discover(c.store,context=c,benchmark_venue=policy.benchmark_venue)[0]
    b['calculation_context']=context_identity(b,policy,c)
    return b


class CurrentBoardReads(unittest.TestCase):
    def test_current_rows_only_and_no_envelope_membership(self):
        c=context();b=bundle(c)
        self.assertEqual(c.catalog()['version'],'predict-board-catalog-2')
        self.assertEqual(c.catalog()['limits']['maximum_games'],500)
        self.assertEqual(b['envelopes'],[])
        self.assertNotIn('combined_envelope_id',json.dumps(b['records']))
        self.assertEqual(c.catalog()['games'][0]['input_version'],b['input_version'])

    def test_authentic_financial_owner_trace_survives_current_adapter(self):
        c=context();b=bundle(c);v=calculate_current(b,DEFAULT_POLICY,context=c)
        expected={q['id']:q['calculations']['funded_estimate'] for _,_,q in entries(retained()[1])}
        for _,_,q in entries(v['state']):
            r=q['calculations']['funded_estimate']
            self.assertEqual(r['financial_metrics'],expected[q['id']]['financial_metrics'])
            self.assertEqual(r['funding'],expected[q['id']]['funding'])
        originals={p['id']:p for p in retained()[1]['events'][0]['funded_pairs']}
        for p in v['state']['events'][0]['funded_pairs']:
            self.assertEqual(p['financial_metrics'],originals[p['id']]['financial_metrics'])
            self.assertEqual(p['funding'],originals[p['id']]['funding'])

    def test_context_binds_policy_engine_reset_and_changed_receipt(self):
        c=context();b=bundle(c);identity=b['calculation_context']
        self.assertEqual(identity,context_identity(bundle(context()),DEFAULT_POLICY,context()))
        other=replace(DEFAULT_POLICY,capital_ceiling_usd='500')
        self.assertNotEqual(identity['context_id'],context_identity(b,other,c)['context_id'])
        changed=context(frame(epoch='reset-epoch'))
        self.assertNotEqual(identity['context_id'],bundle(changed)['calculation_context']['context_id'])
        rows=deepcopy(retained()[0]['records']);rows[0]['quote']['times']['received_at']='2026-10-14T01:15:10Z'
        changed=context(frame(rows));cb=bundle(changed)
        self.assertNotEqual(identity['context_id'],cb['calculation_context']['context_id'])
        self.assertNotEqual(c.read_revision,changed.read_revision)
        self.assertEqual(b['records'][0]['quote']['times']['source_at'],cb['records'][0]['quote']['times']['source_at'])
        c.engine='changed-engine'
        self.assertNotEqual(identity['context_id'],context_identity(b,DEFAULT_POLICY,c)['context_id'])

    def test_details_expiry_changes_context_and_preserves_whole_frame(self):
        c=context();b=bundle(c);later=context(at='2026-10-14T03:00:00Z');lb=bundle(later)
        self.assertNotEqual(b['calculation_context']['context_id'],lb['calculation_context']['context_id'])
        v=calculate_current(b,DEFAULT_POLICY,context=c,details=True)
        q=next(q for _,_,q in entries(v['state']) if q['venue']=='kalshi')
        d=details(v,quote=q['id'],at=AT,current=b['state_inputs'])
        self.assertEqual(d['version'],'predict-board-details-2')
        self.assertEqual(d['calculation_context'],b['calculation_context'])
        self.assertNotIn('snapshot_id',d);self.assertNotIn('result_id',d)
        self.assertEqual(d['quote']['original'],q['original'])

    def test_details_percentage_companions_match_board_for_singles_and_pairs(self):
        c=context();b=bundle(c);v=calculate_current(b,DEFAULT_POLICY,context=c,details=True)
        for view in ('ev','arbs'):
            board=response(b,v,DEFAULT_POLICY,view=view,filter='all',at=AT)
            for row in board['rows']:
                kwargs={'pair':row['pair_id']} if view=='arbs' else {'quote':row['quote_id']}
                d=details(v,at=AT,current=b['state_inputs'],**kwargs)
                selected=d['pair'] or d['quote']['calculations']['funded_estimate']
                self.assertEqual(selected['financial_metrics'],row['financial_metrics'])

    def test_read_clocks_do_not_change_context_before_temporal_boundary(self):
        c=context();b=bundle(c);later=context(at='2026-10-14T01:16:00Z')
        self.assertEqual(b['calculation_context'],bundle(later)['calculation_context'])
        self.assertEqual(b['input_version'],bundle(later)['input_version'])

    def test_empty_first_use_and_expired_occurrence_are_honest(self):
        self.assertEqual(context(frame([])) .catalog()['games'],[])
        self.assertEqual(context(at='2026-10-17T00:00:00Z').catalog()['games'],[])

    def test_version2_odds_financial_and_details_contracts(self):
        c=context();b=bundle(c)
        result=calculate_current(b,DEFAULT_POLICY,context=c)
        for view in ('odds','ev','arbs'):
            out=response(b,None if view=='odds' else result,DEFAULT_POLICY,view=view,filter='all',at=AT)
            self.assertEqual(out['version'],'predict-comparison-board-2')
            self.assertEqual(out['delivery_state'],'complete')
            self.assertEqual(out['calculation_context'],b['calculation_context'])
            self.assertNotIn('result_id',out);self.assertNotIn('snapshot_id',out)
            for p in out['prices']:self.assertEqual(p['inputs_identity']['context_id'],out['calculation_context']['context_id'])
            for r in out['rows'] if view!='odds' else []:
                self.assertEqual(r['details']['context_id'],out['calculation_context']['context_id'])
                if view=='arbs':self.assertEqual(len({leg['venue'] for leg in r['legs']}),2)


class _ReadOnlyDB:
    def __init__(self):self.statements=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def transaction(self):return self
    def execute(self,statement,*args):
        self.statements.append(str(statement))
        if not str(statement).startswith('SET TRANSACTION'):raise AssertionError('unexpected ordinary SQL '+str(statement))


class CurrentBoardAPI(unittest.IsolatedAsyncioTestCase):
    async def test_real_routes_context_changes_history_and_no_archive_sql(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        database=_ReadOnlyDB()
        provider=SimpleNamespace(closed=False,closing=False,dispatch=True,database=SimpleNamespace(status=lambda:dict(state='available')))
        app=web.Application();mount(app,provider)
        current=frame()
        patches=[patch('app.dashboard.comparison_board_api.connect',return_value=database),patch('app.storage.current_rows.CurrentRowStore.capture',side_effect=lambda **kwargs:deepcopy(current)),patch('app.storage.comparison_board.utc',return_value=AT)]
        for item in patches:item.start()
        try:
            async with TestClient(TestServer(app)) as client:
                r=await client.get('/api/boards/games');self.assertEqual(r.status,200)
                game=(await r.json())['games'][0]['game_key'];params=dict(game=game,filter='all')
                output={}
                for view in ('odds','ev','arbs'):
                    r=await client.get('/api/boards/'+view,params=params)
                    output[view]=await r.json();self.assertEqual(r.status,200,output[view])
                selected=output['ev']['rows'][0]['details'];identity=selected['context_id'];quote=selected['quote_id']
                for view in ('details','inputs'):
                    r=await client.get('/api/boards/'+view,params=dict(params,context_id=identity,quote=quote))
                    output[view]=await r.json();self.assertEqual(r.status,200,output[view])
                    self.assertEqual(output[view]['calculation_context']['context_id'],identity)
                r=await client.get('/api/boards/slate',params=dict(view='odds',filter='all',limit='50'))
                output['slate']=await r.json();self.assertEqual(r.status,200,output['slate'])
                r=await client.get('/api/boards/slate',params=dict(view='odds',expected_revision='superseded'))
                self.assertEqual(r.status,409);self.assertEqual((await r.json())['reason'],'current_slate_changed')
                r=await client.get('/api/boards/history',params=dict(game=game));self.assertEqual(r.status,410)
                r=await client.get('/api/boards/details',params=dict(params,context_id='superseded',quote=quote))
                self.assertEqual(r.status,409);self.assertEqual((await r.json())['reason'],'current_inputs_changed_or_removed')
                current['records']=[]
                r=await client.get('/api/boards/details',params=dict(params,context_id=identity,quote=quote))
                self.assertEqual(r.status,409)
                path=Path('/tmp/predict-current-board-v2-test-output.json');path.write_bytes(encoded(output))
        finally:
            for item in reversed(patches):item.stop()
        self.assertTrue(database.statements)

    async def test_stop_during_nonfinancial_capture_refuses_completed_response(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        database=_ReadOnlyDB();provider=SimpleNamespace(closed=False,closing=False,dispatch=True)
        def catalog():
            provider.dispatch=False
            return dict(version='predict-board-catalog-2',games=[],limits=dict(maximum_games=500),provider_requests=0)
        app=web.Application();mount(app,provider)
        with patch('app.dashboard.comparison_board_api.connect',return_value=database),patch('app.dashboard.comparison_board_api.ReadContext',return_value=SimpleNamespace(catalog=catalog)):
            async with TestClient(TestServer(app)) as client:
                result=await client.get('/api/boards/games')
                self.assertEqual(result.status,409)
                self.assertEqual((await result.json())['error'],'current_read_stopped')

    async def test_only_one_read_active_four_waiting_excess_refused(self):
        import asyncio
        from threading import Event
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        database=_ReadOnlyDB();provider=SimpleNamespace(closed=False,closing=False,dispatch=True)
        entered=Event();release=Event();calls=[]
        def capture(*args):
            calls.append(1);entered.set()
            if not release.wait(5):raise AssertionError('bounded reader test timed out')
            return SimpleNamespace(catalog=lambda:dict(version='predict-board-catalog-2',games=[],provider_requests=0))
        app=web.Application();mount(app,provider)
        with patch('app.dashboard.comparison_board_api.connect',return_value=database),patch('app.dashboard.comparison_board_api.ReadContext',side_effect=capture):
            async with TestClient(TestServer(app)) as client:
                first=asyncio.create_task(client.get('/api/boards/games'))
                self.assertTrue(await asyncio.to_thread(entered.wait,3))
                queued=[asyncio.create_task(client.get('/api/boards/games')) for _ in range(4)]
                await asyncio.sleep(.05)
                excess=await client.get('/api/boards/games');self.assertEqual(excess.status,429)
                self.assertEqual(len(calls),1)
                release.set()
                responses=await asyncio.gather(first,*queued)
                self.assertEqual([response.status for response in responses],[200]*5)


if __name__=='__main__':unittest.main()
