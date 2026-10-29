"""Latest-board capacity and refusal isolation on disposable SQL; zero providers.

Original retained quote/contract facts exercise the real financial owners. Price
and status mutations below are authored fixture evidence, never live authority.
"""
from copy import deepcopy
from datetime import timedelta
import os
from unittest import skipUnless
from unittest.mock import patch, MagicMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.runtime_client import RuntimeClient
from app.storage import latest_board as latest
from app.dashboard.comparison_board import entries
from app.comparison.estimated_policy import DEFAULT_POLICY

from tests.latest_board_fixture import LatestBoardFixture, SOCKET


@skipUnless(SOCKET,'Explicit maintained disposable DA PostgreSQL lane required')
class LatestBoardCapacitySQL(LatestBoardFixture):
    async def test_c1_shaped_capacity_and_game_isolation(self):
        """Authored distinct native wording on real retained lines in disposable SQL."""
        from pathlib import Path
        import json
        from app.dashboard import comparison_board as projection
        from app.storage.store import encoded
        from app.storage.comparison_board import observation_identity
        # Exercise refusal/isolation below the independent 64 KiB native
        # wording guard; live alternate-width publications are measured separately.
        self.enterContext(patch.object(projection,'MAX_RESPONSE',1536*1024))
        root=Path(os.environ['PREDICT_CI_REPORT_ROOT'])
        first_members={tuple(m) for m in self.first['members']}
        real_encoded=projection.encoded
        measurements={}
        for shape,width in (('repeated',4352),('distinct',4352),('irreducible',49152)):
            records=deepcopy(self.records)
            for record in records:
                q=record['quote']
                if (q['source']['provider'],q['source']['native_event_id']) in first_members:
                    token='shared' if shape=='repeated' else q['source']['native_market_id']+q['source']['native_outcome_id']+q['source']['native_side']
                    record.setdefault('comparison_source_metadata',{})['original_wording']={'rules':('Authored '+token+' ').ljust(width,'x')}
            self.admit(records)
            with self.connect() as db:
                db.execute('TRUNCATE latest_board,latest_board_status')
                ctx=latest.read_context(db,at=self.at.isoformat())
                observed=ctx.observation_bundles(game=self.first['game_key'])[0]
                observed['calculation_context']=observation_identity(observed,ctx)
            captured=[]
            def measure(value):
                if isinstance(value,dict) and value.get('version')==projection.VERSION:captured.append(deepcopy(value))
                return real_encoded(value)
            refusal=None
            try:
                with patch.object(projection,'encoded',side_effect=measure):
                    projection.response(observed,None,DEFAULT_POLICY,view='odds',filter='all',at=self.at.isoformat())
            except ValueError as exc:refusal=str(exc)
            value=captured[0]
            components={k:len(encoded(v)) for k,v in value.items()}
            fields={k:sum(len(encoded(p[k])) for p in value['prices'] if k in p)
                for k in {k for p in value['prices'] for k in p}}
            measurements[shape]=dict(bytes=len(encoded(value)),prices=len(value['prices']),components=components,
                price_fields=fields,refusal=refusal)
            (root/'c1-components.json').write_text(json.dumps(measurements,indent=2)+'\n')
            error=None
            try:
                with self.connect() as db:result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
            except ValueError as exc:error=str(exc)
            measurements[shape]['reconcile_error']=error
            measurements[shape]['published_games']=len(self.rows())
            (root/'c1-components.json').write_text(json.dumps(measurements,indent=2)+'\n')
            if shape=='irreducible':
                self.assertEqual(refusal,'board_compact_response_capacity')
                self.assertIsNone(error)
                self.assertTrue(result['published'])
                self.assertIn(self.second['game_key'],self.rows())
                frame=self.snapshot();self.assertFalse(frame['status']['scope_complete'])
                self.assertIn(dict(game_key=self.first['game_key'],reason='board_compact_response_capacity'),frame['status']['observation_errors'])
                with self.assertRaisesRegex(ValueError,'board_compact_response_capacity'):
                    latest.board(frame,self.first['game_key'],view='odds',filter='all')
            elif refusal is None:
                from app.dashboard.comparison_board import expand_odds
                stored=self.rows()[self.first['game_key']]['facts']['boards']['odds']
                expanded=expand_odds(deepcopy(stored))
                expected={projection.quote_key(q):q for _,_,q in entries(observed['state_inputs'])}
                for price in expanded['prices']:
                    quote=expected[price['quote_id']]
                    for field in ('source','original','times'):
                        self.assertEqual(price[field],quote[field])
                    self.assertEqual(price['native_side'],quote['source']['native_side'])
                    self.assertEqual(price['native_contract_summary']['wording'],quote['native_contract']['wording'])
                    for field in ('gross_comparison','current_comparison'):
                        for item in price[field].get('inputs',[]):
                            frozen=expected[item['quote_id']]
                            for key in ('source','original','times'):
                                self.assertEqual(item[key],frozen[key])
                            self.assertEqual(item['quote_revision'],frozen['revision'])
                board=latest.board(self.snapshot(),self.first['game_key'],view='odds',filter='all')
                measurements[shape]['read_board_bytes']=len(encoded(board))
                self.assertLessEqual(len(encoded(board)),projection.MAX_RESPONSE)
                (root/('c1-'+shape+'-board.json')).write_bytes(encoded(board))
                if shape=='distinct':
                    from app.dashboard.comparison_board_api import mount
                    from app.collection.current_storage_policy import sql_usage
                    from app.collection.background_work import resident_bytes
                    import shutil
                    provider=RuntimeClient(connector=self.connect)
                    provider.acquire=MagicMock(side_effect=AssertionError('provider forbidden'))
                    app=web.Application();mount(app,provider)
                    with patch('app.dashboard.comparison_board_api.connect',side_effect=self.connect):
                        async with TestClient(TestServer(app)) as client:
                            reply=await client.get('/api/boards/odds',params=dict(game=self.first['game_key'],filter='all'))
                            self.assertEqual(reply.status,200,await reply.text())
                            http=await reply.json();self.assertEqual(http['provider_requests'],0)
                            measurements[shape]['http_board_bytes']=len(encoded(http))
                            self.assertLessEqual(len(encoded(http)),projection.MAX_RESPONSE)
                            (root/'c1-distinct-http-board.json').write_bytes(encoded(http))
                            # Wire clocks and originals may be exact field references.
                            expand_odds(http)
                            quote=http['prices'][0]
                            reply=await client.get('/api/boards/inputs',params=dict(game=self.first['game_key'],
                                context_id=quote['inputs_identity']['context_id'],quote=quote['quote_id']))
                            self.assertEqual(reply.status,200,await reply.text())
                            selected=await reply.json();self.assertEqual(selected['provider_requests'],0)
                            self.assertEqual(selected['evidence']['original'],quote['original'])
                            self.assertEqual(selected['evidence']['times'],quote['times'])
                    provider.acquire.assert_not_called()
                    with self.connect() as db:
                        resources=dict(sql_bytes=sql_usage(db),
                            maximum_facts_row_bytes=db.execute('SELECT max(octet_length(facts::text)) n FROM latest_board').fetchone()['n'],
                            publication_bytes=db.execute('SELECT sum(octet_length(facts::text)) n FROM latest_board').fetchone()['n'])
                    resources.update(process_rss_bytes=resident_bytes(),free_disk_bytes=shutil.disk_usage(root).free)
                    self.assertLess(resources['sql_bytes'],2*1024**3)
                    self.assertLessEqual(resources['maximum_facts_row_bytes'],2*1024**2)
                    self.assertLessEqual(resources['publication_bytes'],64*1024**2)
                    self.assertLess(resources['process_rss_bytes'],768*1024**2)
                    self.assertGreater(resources['free_disk_bytes'],1024**3)
                    measurements[shape]['resources']=resources
                (root/'c1-components.json').write_text(json.dumps(measurements,indent=2)+'\n')
        self.assertIsNone(measurements['distinct']['refusal'],measurements['distinct'])
        self.assertEqual(measurements['distinct']['published_games'],2)

    async def test_c1_optional_render_and_guard_boundaries(self):
        from app.comparison.calculation_control import CalculationStopped
        self.fresh_sources()
        original=latest.response
        finance_observed=[]
        def fail_finance(bundle,value,*args,**kwargs):
            if value is not None:
                finance_observed.append(bundle['game_key'] in self.rows())
                raise ValueError('authored_financial_render_failure')
            return original(bundle,value,*args,**kwargs)
        with patch.object(latest,'response',side_effect=fail_finance):
            self.assertTrue(self.reconcile()['published'])
        self.assertTrue(finance_observed)
        self.assertTrue(all(finance_observed))
        self.assertEqual(len(self.rows()),2)
        for game,row in self.rows().items():
            self.assertIsNone(row['calculated_at'])
            self.assertIsNone(row['facts']['boards']['odds']['calculated_at'])
            self.assert_source_frame(latest.board(self.snapshot(),game,view='odds',filter='all'))
        with self.connect() as db:db.execute('TRUNCATE latest_board,latest_board_status')
        with patch('app.comparison.combined_inputs._benchmark',side_effect=ValueError('authored_benchmark_failure')):
            self.assertTrue(self.reconcile()['published'])
        for game in self.rows():self.assert_source_frame(latest.board(self.snapshot(),game,view='odds',filter='all'))
        for error in (CalculationStopped('stop'),MemoryError('process_guard'),TimeoutError('deadline'),
                      OSError('storage_failure'),ValueError('current_read_memory_capacity')):
            with self.subTest(error=type(error).__name__):
                with self.connect() as db:db.execute('TRUNCATE latest_board,latest_board_status')
                with patch.object(latest,'_selection_payload',side_effect=error),self.assertRaises(type(error)):
                    with self.connect() as db:latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
                self.assertFalse(self.rows())
        for stage in ('discover','calculate_current'):
            for error in (CalculationStopped('stop'),MemoryError('process_guard'),TimeoutError('deadline'),OSError('storage_failure')):
                with self.subTest(stage=stage,error=type(error).__name__):
                    with self.connect() as db:db.execute('TRUNCATE latest_board,latest_board_status')
                    with patch.object(latest,stage,side_effect=error),self.assertRaises(type(error)):
                        self.reconcile()
                    # The current complete component's source pass committed
                    # first; a fatal worker error must not start its sibling.
                    self.assertEqual(len(self.rows()),1)
                    for game in self.rows():
                        self.assert_source_frame(latest.board(self.snapshot(),game,view='odds',filter='all'))
                    self.assertTrue(self.snapshot()['status']['observation_only'])

    async def test_c1_failed_game_withdraws_old_authority_and_status_recovers(self):
        self.fresh_sources();self.assertTrue(self.reconcile()['published'])
        original=latest._selection_payload
        def refuse(observed,*args,**kwargs):
            if observed['game_key']==self.first['game_key']:raise ValueError('board_compact_response_capacity')
            return original(observed,*args,**kwargs)
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        self.changed_first()
        with patch.object(latest,'_selection_payload',side_effect=refuse):
            with self.connect() as db:result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
        self.assertTrue(result['published']);frame=self.snapshot()
        self.assertFalse(frame['status']['scope_complete'])
        self.assertIn(self.first['game_key'],frame['rows'])
        with self.assertRaisesRegex(ValueError,'board_compact_response_capacity'):
            latest.board(frame,self.first['game_key'],view='odds',filter='all')
        self.assertTrue(latest.board(frame,self.second['game_key'],view='odds',filter='all')['prices'])
        self.assertTrue(self.reconcile()['published'])
        self.assertTrue(self.snapshot()['status']['scope_complete'])
        self.assertTrue(latest.board(self.snapshot(),self.first['game_key'],view='odds',filter='all')['prices'])

    async def test_c1_obsolete_failure_cannot_overwrite_newer_success(self):
        self.fresh_sources();self.reconcile()
        with self.connect() as db:
            owner=latest.runtime(db,at=self.at.isoformat());marker=latest.marker(db)
        old=deepcopy(self.snapshot()['status'])
        old['observation_errors']=[dict(game_key=self.first['game_key'],reason='board_compact_response_capacity')]
        old.update(scope_complete=False,observation_only=True)
        self.changed_first();self.assertTrue(self.reconcile()['published'])
        with self.connect() as db:
            self.assertFalse(latest.publish(db,captured_marker=marker,captured_runtime=owner,status=old,rows=[]))
        self.assertTrue(self.snapshot()['status']['scope_complete'])
        self.assertTrue(latest.board(self.snapshot(),self.first['game_key'],view='odds',filter='all')['prices'])
