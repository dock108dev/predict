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
from app.storage.comparison_board import ReadContext, discover, calculate_current, context_identity, observation_identity
from app.storage.store import encoded, hashed
from tests.test_ev09_n01 import retained, AT


def frame(records=None,epoch='authored-current-epoch'):
    return dict(epoch=epoch,revision='authored-current-revision',records=deepcopy(records if records is not None else retained()[0]['records']))


def context(value=None,at=AT):
    with patch('app.storage.current_rows.CurrentRowStore.capture',return_value=value or frame()):return ReadContext(SimpleNamespace(db=None),at=at)


def bundle(c,policy=DEFAULT_POLICY):
    b=discover(c.store,context=c,benchmark_venue=policy.benchmark_venue)[0]
    b['calculation_context']=context_identity(b,policy,c)
    return b


def latest_frame(c=None):
    """Authored background publication for read-only API/reader unit cases."""
    c=c or context();catalog=c.catalog();rows={}
    for game in catalog['games']:
        b=discover(c.store,context=c,game=game['game_key'])[0]
        b['calculation_context']=context_identity(b,DEFAULT_POLICY,c)
        v=calculate_current(b,DEFAULT_POLICY,context=c)
        obs=c.observation_bundles(game=game['game_key'])[0]
        obs['calculation_context']=observation_identity(obs,c)
        rows[b['game_key']]=dict(game_key=b['game_key'],economic_revision=b['input_version'],calculated_at=v['calculated_at'],
            facts=dict(context=b['calculation_context'],observation_context=obs['calculation_context'],valid_until=None,
                boards={view:response(obs if view=='odds' else b,None if view=='odds' else v,DEFAULT_POLICY,view=view,filter='all',at=AT) for view in ('odds','ev','arbs')}))
    return dict(status=dict(version='predict-latest-board-1',games=catalog['games'],policy=DEFAULT_POLICY.to_dict(),
        epoch=c.epoch,as_of=AT,scope_complete=True),rows=rows,reasons=[],at=AT,
        owner=dict(active=True,healthy=True),read_revision='authored-read-revision',read_authority='authored-authority')


class CurrentBoardReads(unittest.TestCase):
    def test_large_field_pool_is_exact_and_rejects_crossed_references(self):
        from app.dashboard.comparison_board import compact_price_fields,expand_price_fields
        original=dict(prices=[dict(quote_id=str(n),original={'value':'0.47'},times={'source_at':AT},
            observed_depth={'levels':[{'price':'0.47','quantity':'100'}]*200}) for n in range(80)])
        wire=compact_price_fields(deepcopy(original))
        self.assertLess(len(encoded(wire)),len(encoded(original)))
        restored=expand_price_fields(deepcopy(wire))
        self.assertEqual(restored,original)
        restored['prices'][0]['observed_depth']['levels'][0]['quantity']='1'
        self.assertEqual(restored['prices'][1]['observed_depth']['levels'][0]['quantity'],'100')
        bad=deepcopy(wire);bad['prices'][0]['field_refs']['observed_depth']=len(wire['price_field_pool'])
        with self.assertRaisesRegex(ValueError,'comparison_field_reference_conflict'):expand_price_fields(bad)

    def test_observation_identity_survives_age_boundary_but_binds_changed_facts(self):
        from datetime import timedelta
        from app.storage.store import stamp
        from app.dashboard.comparison_board import freshness
        c=context(); observed=c.observation_bundles()[0]
        original=observation_identity(observed,c)
        event,_,quote=entries(observed['state_inputs'])[0]
        before=freshness(quote,{},event,stamp(c.at),financial=False)
        c.at=(stamp(c.at)+timedelta(hours=1)).isoformat()
        after=freshness(quote,{},event,stamp(c.at),financial=False)
        self.assertNotEqual(before['reasons'],after['reasons'])
        self.assertEqual(observation_identity(observed,c),original)
        quote['original']['value']='0.61'
        self.assertNotEqual(observation_identity(observed,c),original)

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

    def test_financial_context_binds_reviewed_native_contract_without_new_raw_input(self):
        c=context();b=bundle(c);before=deepcopy(b);identity=b['calculation_context']
        q=next(q for _,_,q in entries(b['state_inputs']) if q['venue']=='kalshi')
        q['native_contract']['id']='native-contract:authored-changed-applicability-evidence'
        changed=context_identity(b,DEFAULT_POLICY,c)
        self.assertNotEqual(changed['context_id'],identity['context_id'])
        self.assertEqual(changed['dependency_revision'],identity['dependency_revision'])
        self.assertEqual(changed['engine_binding'],identity['engine_binding'])
        self.assertEqual(changed['policy_revision'],identity['policy_revision'])
        self.assertEqual(b['input_version'],before['input_version'])
        self.assertEqual(q['native_contract']['scope'],next(other for _,_,other in entries(before['state_inputs'])
            if other['venue']=='kalshi')['native_contract']['scope'])

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
        from app.dashboard.comparison_board import price, age_observation
        from app.storage.store import stamp
        event=next(e for e,_,candidate in entries(v['state']) if candidate['id']==q['id'])
        observed=age_observation(price(q),event,stamp(AT))
        self.assertEqual(d['quote']['observation_display'],observed['observation_display'])
        self.assertEqual(d['quote']['source_state'],q['state'])
        self.assertEqual(d['quote']['times'],q['times'])

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
        if not (str(statement).startswith('SET TRANSACTION') or str(statement).startswith("SELECT set_config('")):raise AssertionError('unexpected ordinary SQL '+str(statement))


class CurrentBoardAPI(unittest.IsolatedAsyncioTestCase):
    async def test_real_routes_context_changes_history_and_no_archive_sql(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        database=_ReadOnlyDB()
        provider=SimpleNamespace(closed=False,closing=False,dispatch=True,database=SimpleNamespace(status=lambda:dict(state='available')))
        app=web.Application();mount(app,provider)
        current=frame()
        published=latest_frame()
        patches=[patch('app.dashboard.comparison_board_api.connect',return_value=database),
            patch('app.dashboard.comparison_board_api.snapshot',return_value=published),
            patch('app.storage.latest_board.snapshot',return_value=published),
            patch('app.storage.latest_board.slate_authority',return_value=hashed(['authored-authority',False])),
            patch('app.dashboard.comparison_board_api.read_context',side_effect=lambda db,**kwargs:context(current)),
            patch('app.dashboard.comparison_board_api.selected_dependencies',return_value=('fixture-dependency',['fixture-event'])),
            patch('app.dashboard.comparison_board_api.utc',return_value=AT)]
        for item in patches:item.start()
        try:
            async with TestClient(TestServer(app)) as client:
                r=await client.get('/api/boards/games');self.assertEqual(r.status,200)
                game=(await r.json())['games'][0]['game_key'];params=dict(game=game,filter='all')
                output={}
                for view in ('odds','ev','arbs'):
                    r=await client.get('/api/boards/'+view,params=params)
                    output[view]=await r.json();self.assertEqual(r.status,200,output[view])
                    # Ordinary selected reads must leave unrelated games and
                    # other optional views in SQL, retaining neighborhood proof.
                    captured=patches[1].target.snapshot.call_args.kwargs
                    self.assertEqual(captured['game'],game)
                    self.assertEqual(captured['view'],view)
                selected=output['ev']['rows'][0]['details'];identity=selected['context_id'];quote=selected['quote_id']
                for view in ('details','inputs'):
                    expected=identity if view=='details' else output['odds']['calculation_context']['context_id']
                    r=await client.get('/api/boards/'+view,params=dict(params,context_id=expected,quote=quote))
                    output[view]=await r.json();self.assertEqual(r.status,200,output[view])
                    self.assertEqual(output[view]['calculation_context']['context_id'],expected)
                r=await client.get('/api/boards/details',params=dict(params,context_id=identity,quote=quote,amount='500'))
                sized=await r.json();self.assertEqual(r.status,200,sized)
                self.assertEqual(sized['policy']['requested_amount_usd'],'500')
                self.assertEqual(sized['selection_context']['context_id'],identity)
                self.assertNotEqual(sized['calculation_context']['context_id'],identity)
                self.assertEqual(sized['calculation_context']['dependency_revision'],sized['selection_context']['dependency_revision'])
                r=await client.get('/api/boards/slate',params=dict(view='odds',filter='all',limit='50'))
                output['slate']=await r.json();self.assertEqual(r.status,200,output['slate'])
                r=await client.get('/api/boards/slate',params=dict(view='odds',expected_revision='superseded'))
                self.assertEqual(r.status,409);self.assertEqual((await r.json())['reason'],'current_slate_changed')
                r=await client.get('/api/boards/history',params=dict(game=game));self.assertEqual(r.status,410)
                r=await client.get('/api/boards/details',params=dict(params,context_id='superseded',quote=quote))
                self.assertEqual(r.status,409);refused=await r.json()
                self.assertEqual(refused['reason'],'current_inputs_changed_or_removed')
                self.assertEqual(refused['availability']['state'],'not_evaluated')
                current['records']=[]
                r=await client.get('/api/boards/details',params=dict(params,context_id=identity,quote=quote))
                self.assertEqual(r.status,409)
                path=Path('/tmp/predict-current-board-v2-test-output.json');path.write_bytes(encoded(output))
        finally:
            for item in reversed(patches):item.stop()
        self.assertTrue(database.statements)

    async def test_ordinary_latest_reads_never_enter_finance_or_capture(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from contextlib import ExitStack
        from unittest.mock import MagicMock
        from app.dashboard.comparison_board_api import mount
        database=_ReadOnlyDB();published=latest_frame()
        provider=SimpleNamespace(closed=False,closing=False,dispatch=True,
            database=SimpleNamespace(status=lambda:dict(state='available')),
            acquire=MagicMock(side_effect=AssertionError('provider forbidden')))
        app=web.Application();mount(app,provider)
        with ExitStack() as stack:
            stack.enter_context(patch('app.dashboard.comparison_board_api.connect',return_value=database))
            stack.enter_context(patch('app.dashboard.comparison_board_api.snapshot',return_value=published))
            stack.enter_context(patch('app.storage.latest_board.snapshot',return_value=published))
            stack.enter_context(patch('app.storage.latest_board.slate_authority',return_value=hashed(['authored-authority',False])))
            for target in ('app.dashboard.comparison_board_api.calculate_current','app.dashboard.comparison_board_api.read_context','app.storage.latest_board.calculate_current'):
                stack.enter_context(patch(target,side_effect=AssertionError('ordinary financial work forbidden')))
            async with TestClient(TestServer(app)) as client:
                game=published['status']['games'][0]['game_key']
                for _ in range(2):
                    for view in ('games','odds','ev','arbs','slate'):
                        params={} if view=='games' else dict(view='ev',filter='all',limit='50') if view=='slate' else dict(game=game,filter='all')
                        result=await client.get('/api/boards/'+view,params=params)
                        self.assertEqual(result.status,200,await result.text())
            provider.acquire.assert_not_called()
            self.assertTrue(all(sql.startswith("SELECT set_config('") for sql in database.statements))

    async def test_stop_during_nonfinancial_capture_refuses_completed_response(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        database=_ReadOnlyDB();provider=SimpleNamespace(closed=False,closing=False,dispatch=True)
        def capture(db,**kwargs):
            provider.dispatch=False
            return dict(status=dict(games=[],epoch='fixture'),owner=dict(active=False),read_revision='stopped')
        app=web.Application();mount(app,provider)
        with patch('app.dashboard.comparison_board_api.connect',return_value=database),patch('app.dashboard.comparison_board_api.snapshot',side_effect=capture):
            async with TestClient(TestServer(app)) as client:
                result=await client.get('/api/boards/games')
                self.assertEqual(result.status,409)
                self.assertEqual((await result.json())['error'],'current_read_stopped')

    async def test_one_ordinary_worker_two_waiting_reserve_selected_capacity(self):
        import asyncio
        from threading import Event
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        database=_ReadOnlyDB();provider=SimpleNamespace(closed=False,closing=False,dispatch=True)
        entered=Event();release=Event();calls=[]
        def capture(*args,**kwargs):
            calls.append(1);entered.set()
            if not release.wait(5):raise AssertionError('bounded reader test timed out')
            return dict(status=dict(games=[],epoch='fixture'),owner=dict(active=True),read_revision='fixture')
        app=web.Application();mount(app,provider)
        with patch('app.dashboard.comparison_board_api.connect',return_value=database),patch('app.dashboard.comparison_board_api.snapshot',side_effect=capture):
            async with TestClient(TestServer(app)) as client:
                first=asyncio.create_task(client.get('/api/boards/games'))
                self.assertTrue(await asyncio.to_thread(entered.wait,3))
                queued=[asyncio.create_task(client.get('/api/boards/games')) for _ in range(2)]
                await asyncio.sleep(.05)
                excess=await client.get('/api/boards/games');self.assertEqual(excess.status,429)
                self.assertEqual(len(calls),1)
                release.set()
                responses=await asyncio.gather(first,*queued)
                self.assertEqual([response.status for response in responses],[200]*3)


if __name__=='__main__':unittest.main()


class C1CompactProjection(unittest.TestCase):
    def authored(self):
        from app.dashboard import comparison_board as projection
        c=context();observed=c.observation_bundles()[0]
        observed['calculation_context']=observation_identity(observed,c)
        observed['source_status']={venue:dict(state='available',reason_code=None,reason=None,
            diagnostic='Authored runtime audit; not a source-price field')
            for venue in ('novig','prophetx','pinnacle','kalshi','polymarket_us')}
        for _,_,quote in entries(observed['state_inputs']):
            quote['native_contract']['wording']={'rules':('Authored unique '+quote['id']+' ').ljust(4352,'x')}
        original=deepcopy(observed)
        result=projection.response(observed,None,DEFAULT_POLICY,view='odds',filter='all',at=c.at)
        self.assertEqual(observed,original)
        self.assertLessEqual(len(encoded(result)),projection.MAX_RESPONSE)
        return result

    def test_distinct_wording_and_audit_health_share_exact_frozen_prices(self):
        from app.dashboard.comparison_board import expand_odds,compact_odds,comparison_input,expand_price_fields
        board=self.authored();captured=deepcopy(board);expand_price_fields(board)
        self.assertEqual(board['comparison_input_encoding'],'same-board-price-refs-1')
        self.assertEqual(len(board['prices']),46)
        byid={p['quote_id']:p for p in board['prices']}
        available=0
        for price in board['prices']:
            for field in ('gross_comparison','current_comparison'):
                value=price[field]
                if not value['available']:continue
                available+=1
                self.assertEqual(value['inputs'],[])
                self.assertEqual(len(value['input_refs']),2)
        self.assertGreater(available,0)
        expanded=expand_odds(deepcopy(board))
        for price in expanded['prices']:
            for field in ('gross_comparison','current_comparison'):
                for item in price[field].get('inputs',[]):
                    expected=comparison_input(next(q for q in expanded['prices'] if q['quote_id']==item['quote_id']))
                    self.assertEqual(item,expected)
        self.assertEqual(compact_odds(deepcopy(expanded)),captured)
        self.assertEqual(byid.keys(),{p['quote_id'] for p in expanded['prices']})
        comparison=next(q['gross_comparison'] for q in expanded['prices'] if q['gross_comparison']['available'])
        comparison['inputs'][1]['observation_display']['publication_reason_codes']=['current_dependencies_changed']
        compact_odds(expanded)
        self.assertNotIn('input_refs',comparison)
        self.assertEqual(comparison['inputs'][1]['observation_display']['publication_reason_codes'],['current_dependencies_changed'])

    def test_malformed_and_conflicting_wording_or_price_references_refuse(self):
        from app.dashboard.comparison_board import expand_odds,compact_odds,expand_price_fields
        board=expand_price_fields(self.authored())
        for index in (-1,True,0.5,'0',len(board['native_wordings'])):
            bad=deepcopy(board);bad['prices'][0]['native_contract_summary']['wording_refs']=[['rules',index]]
            with self.subTest(index=index),self.assertRaisesRegex(ValueError,'comparison_wording_reference_conflict'):
                expand_odds(bad)
        bad=deepcopy(board);bad['prices'].append(deepcopy(bad['prices'][0]))
        with self.assertRaisesRegex(ValueError,'comparison_captured_reference_conflict'):expand_odds(bad)
        for reference in ({'quote_id':'absent','quote_revision':1},{'quote_id':board['prices'][0]['quote_id'],'quote_revision':'crossed'},None):
            bad=deepcopy(board)
            comparison=next(q['gross_comparison'] for q in bad['prices'] if q['gross_comparison']['available'])
            comparison['input_refs'][1]=reference
            with self.subTest(reference=reference),self.assertRaisesRegex(ValueError,'comparison_captured_reference_conflict'):expand_odds(bad)
        expanded=expand_odds(deepcopy(board))
        comparison=next(q['gross_comparison'] for q in expanded['prices'] if q['gross_comparison']['available'])
        comparison['inputs'][1]['source']['native_market_id']='different-frozen-source'
        compact_odds(expanded)
        self.assertNotIn('input_refs',comparison)
        self.assertEqual(comparison['inputs'][1]['source']['native_market_id'],'different-frozen-source')
