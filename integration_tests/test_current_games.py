"""Isolated database durability, exact binding and snapshot publication checks."""
import base64
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch
from psycopg import sql
from app.storage.store import connect,Store,hashed
from app.storage.current_games import GameStore,calculate,age_result
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.estimated_ev import _ordinary_reference,_grid
from app.comparison.current_dependencies import references
from app.comparison.domain import CanonicalSelection
from app.comparison.costs import UnitSpec

ROOT=Path(__file__).resolve().parents[1]
KEY='the_odds_api:855f58fad5f0f14b239f4f63df27998b'


def actual():
    v=json.loads((ROOT/'tests/fixtures/stored-game.json').read_text());body=json.dumps(v['replay']).encode()
    return dict(source='the_odds_api',kind='aggregate_batch',retained_at=v['received_at'],
        value=dict(sport='NFL',received_at=v['received_at'],body_sha256=__import__('hashlib').sha256(body).hexdigest(),body_b64=base64.b64encode(body).decode()))


class DurableGames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_test_ev09_'+uuid4().hex[:12]
        with connect('prediction_arb') as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db=connect(cls.name);Store(cls.db).migrate();cls.store=GameStore(cls.db)
        cls.record=actual();cls.store.import_record(cls.record);cls.store.project(KEY)
        cls.snapshot=cls.store.snapshot(KEY,DEFAULT_POLICY,at=cls.record['value']['received_at'])
        cls.result=calculate(cls.snapshot);cls.store.publish(cls.snapshot,cls.result)
    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect('prediction_arb') as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
    def test_additive_migrations_keep_legacy_row(self):
        before=self.db.execute('SELECT count(*) AS n FROM schema_migration').fetchone()['n'];Store(self.db).migrate()
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM schema_migration').fetchone()['n'],before)
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM information_schema.columns WHERE table_name='quote_observation' AND column_name='ask'").fetchone()['n'],1)
    def test_duplicate_and_conflicting_envelope(self):
        eid=self.store.envelope(self.record);self.assertEqual(eid,self.store.envelope(self.record))
        crossed=deepcopy(self.record);crossed['value']['sport']='NHL'
        with self.db.transaction(),self.assertRaisesRegex(ValueError,'conflicting immutable'):self.store.envelope(crossed,eid)
    def test_exact_out_of_order_source_clock(self):
        eid=self.store.envelope(self.record);k=uuid4().hex
        self.store.source('test','quote',k,'2026-10-13T20:00:00.000000002+00:00',eid,{'price':'2.30'},received_at='2026-10-13T20:00:00.000000002+00:00')
        self.store.source('test','quote',k,'2026-10-13T20:00:00.000000001+00:00',eid,{'price':'9.99'},received_at='2026-10-13T20:00:00.000000001+00:00')
        r=self.db.execute('SELECT payload FROM current_source_projection WHERE native_id=%s',(k,)).fetchone()
        self.assertEqual(json.loads(r['payload'])['price'],'2.30')
    def test_journal_restart_duplicate_and_incomplete_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'observations.jsonl';p.write_text(json.dumps(self.record)+'\n'+json.dumps(self.record))
            _,n=self.store.catch_up(p);self.assertEqual(n,1)
            with connect(self.name) as db:self.assertEqual(GameStore(db).catch_up(p)[1],0)
            with p.open('a') as stream:stream.write('\n')
            self.assertEqual(self.store.catch_up(p)[1],1)
            self.assertEqual(self.store.catch_up(p)[1],0)
    def test_snapshot_replay_and_no_clock_renewal(self):
        replay=calculate(self.snapshot)
        for value in (replay,self.result):value.pop('calculated_at',None)
        self.assertEqual(replay,self.result)
        later=age_result(dict(self.result,superseded=False),at='2026-10-14T23:00:00+00:00')
        self.assertEqual(later['status'],'historical');self.assertEqual(later['as_of'],self.snapshot['as_of'])
        self.assertFalse(later['state']['events'][0]['funded_pairs'][0]['ranking_eligible'])
    def test_atomic_publication_refuses_changed_game_keeps_result(self):
        key='test:'+uuid4().hex;payload=deepcopy(self.snapshot['projection']);payload['game_key']=key
        self.db.execute('INSERT INTO current_game_projection VALUES (%s,%s,%s,now())',(key,'v1',json.dumps(payload)))
        snap=self.store.snapshot(key,DEFAULT_POLICY,at=self.snapshot['as_of']);result=dict(self.result,calculated_at=self.snapshot['as_of'])
        self.db.execute('UPDATE current_game_projection SET input_version=%s WHERE game_key=%s',('v2',key))
        rid,published=self.store.publish(snap,result);self.assertFalse(published)
        self.assertTrue(self.db.execute('SELECT 1 FROM current_game_result WHERE id=%s',(rid,)).fetchone())
        self.assertIsNone(self.store.result(key,DEFAULT_POLICY))
    def test_unrelated_arrival_does_not_revoke_publication(self):
        snap=self.store.snapshot(KEY,DEFAULT_POLICY,at=self.snapshot['as_of']);result=dict(self.result,calculated_at=self.snapshot['as_of'])
        self.db.execute('INSERT INTO current_game_projection VALUES (%s,%s,%s,now())',('unrelated:'+uuid4().hex,'v1','{}'))
        self.assertTrue(self.store.publish(snap,result)[1])
    def test_sql_reads_are_small_acquisition_free_and_fail_visible(self):
        import asyncio
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from types import SimpleNamespace
        from app.dashboard.stored_games import mount
        async def check():
            provider=SimpleNamespace(database=SimpleNamespace(selected=[KEY],error=None,failures=0,status=lambda:dict(state='available'),request=lambda *a:None),dispatch=True,closed=False,closing=False)
            app=web.Application();mount(app,provider)
            async with TestClient(TestServer(app)) as client:
                with patch('app.dashboard.comparison_board_api.connect',side_effect=AssertionError('retired reads cannot use SQL')),patch('app.collection.current_account_recovery.observe_and_activate',side_effect=AssertionError('reads cannot acquire')):
                    for path in ('/api/stored/result','/api/stored/games'):
                        response=await client.get(path,params={'game':KEY})
                        captured=await response.read();self.assertEqual(response.status,410);self.assertLess(len(captured),1000)
                        result=json.loads(captured);self.assertEqual(result['error'],'sports_history_unavailable')
                        self.assertEqual(result['provider_requests'],0)
        asyncio.run(check())

    def quote(self):
        state=self.result['state'];e=state['events'][0]
        q=next(q for g in e['groups'] if g['market']=='winner' for o in g['outcomes'] for q in o['quotes'].values() if q['venue']=='novig')
        vals=references(q,state['comparison_profiles']);return deepcopy(q),deepcopy(vals)
    def test_same_provider_reference_despite_native_ambiguity(self):
        q,values=self.quote();selected=CanonicalSelection.from_dict(values['identity']['payload']['selection'])
        q['occurrence_match'].update(status='unresolved',method='unresolved',conflicts=['ambiguous_native_candidates'])
        # Reference originals remain the exact source-local market, independent
        # of the unrelated Kalshi GAME/SPREAD/TOTAL association failure.
        from app.collection.current_comparison_inputs import reference_payload
        payload=reference_payload(q,self.snapshot['projection']['inputs']['references'])
        self.assertEqual(len(payload['outcomes']),2)
        for row in payload['outcomes']:row['market_identity']=deepcopy(q['occurrence_match']['original_market_identity'])
        self.assertEqual(len(_ordinary_reference(q,payload,selected)['outcomes']),2)
        for field in ('event','period','roles','receipt','opposition','odds','clock'):
            wrong=deepcopy(payload)
            if field=='event':wrong['outcomes'][0]['source']['native_event_id']='wrong'
            if field=='period':wrong['outcomes'][0]['market_identity']['period']='first_half'
            if field=='roles':q2=deepcopy(q);q2['occurrence_match']['original_event']['home']='wrong'
            if field=='receipt':wrong['outcomes'][0]['receipt_sha256']='0'*64
            if field=='opposition':wrong['outcomes'][0]['selection']['predicate']='not_win'
            if field=='odds':wrong['outcomes'][0]['decimal_odds']='9.99'
            if field=='clock':wrong['outcomes'][0]['source_at']='2026-01-01T00:00:00+00:00'
            with self.subTest(field=field),self.assertRaises(ValueError):_ordinary_reference(q2 if field=='roles' else q,wrong,selected)
    def test_modeled_grid_actual_status_retained_and_qualified_precedence(self):
        q,values=self.quote();at=__import__('app.storage.store',fromlist=['stamp']).stamp(self.snapshot['as_of'])
        q['comparison_input_status']['quantity']['status']='applicability_unresolved'
        v={'quantity':dict(expires_at=None,payload=dict(grid=dict(minimum_native='1',increment_native='1'),unit=None))}
        grid=_grid(q,v,UnitSpec('stake_usd'),{'fee':{}},at)
        self.assertIn('hypothetical',grid['qualification']);self.assertEqual(q['comparison_input_status']['quantity']['status'],'applicability_unresolved')
        q['comparison_input_status']['quantity']['status']='available_and_bound'
        self.assertEqual(_grid(q,v,UnitSpec('stake_usd'),{'fee':{}},at)['minimum_native'],'1')
        v['quantity']['payload']['unit']={'unit':'dollar_face_contracts','face_usd_per_native':'1','quantity_scale':'1','price_scale':'1'}
        with self.assertRaises(ValueError):_grid(q,v,UnitSpec('stake_usd'),{'fee':{}},at)
        v['quantity']['expires_at']='2000-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):_grid(q,v,UnitSpec('stake_usd'),{'fee':{}},at)


class PipelineBounds(unittest.IsolatedAsyncioTestCase):
    def service(self):
        from types import SimpleNamespace
        from app.collection.current_database import DatabasePipeline
        svc=SimpleNamespace(config={'cleanup_seconds':1,'sports':['NFL'],'families':['moneyline']},sink=SimpleNamespace(error=None))
        return DatabasePipeline(svc)
    async def test_failure_is_visible_and_finite(self):
        pipe=self.service()
        async def timeout(awaitable,timeout):
            awaitable.close();raise TimeoutError
        with patch.object(pipe,'tick',side_effect=OSError('database unavailable')),patch('app.collection.current_database.asyncio.wait_for',side_effect=timeout) as wait:
            await pipe.run_maintenance()
        self.assertEqual(wait.call_count,3)
        self.assertIn('database unavailable',pipe.error)
    async def test_archive_calculation_queue_is_absent(self):
        pipe=self.service()
        self.assertFalse(hasattr(pipe,'request'));self.assertFalse(hasattr(pipe,'pending'))
    async def test_stop_revokes_and_finishes_owned_worker(self):
        import asyncio
        pipe=self.service()
        pipe.task=asyncio.create_task(pipe.run_maintenance())
        await asyncio.sleep(0)
        self.assertTrue(await pipe.close());self.assertTrue(pipe.closed);self.assertTrue(pipe.task.done())


class RequestedGames(DurableGames):
    """Successor identity/compaction checks on a disposable PostgreSQL database."""
    def test_distinct_saved_policy_variants_and_old_reader(self):
        from app.comparison.estimated_policy import LEGACY_POLICY,EstimatePolicy
        policies=[DEFAULT_POLICY,LEGACY_POLICY,replace(DEFAULT_POLICY,capital_ceiling_usd='900'),
            replace(DEFAULT_POLICY,buffer_rate='0.01'),replace(DEFAULT_POLICY,sizing_mode='ceiling'),
            replace(DEFAULT_POLICY,benchmark_venue='novig')]
        ids=[]
        for policy in policies:
            snap=self.store.snapshot(KEY,policy,at=self.snapshot['as_of'])
            result=calculate(snap);rid,published=self.store.publish(snap,result)
            self.assertTrue(published);ids.append((snap['id'],rid))
            self.assertEqual(EstimatePolicy.from_dict(result['policy']),policy)
            self.assertEqual(self.store.result(KEY,policy)['result_id'],rid)
            pairs=result['state']['events'][0]['funded_pairs']
            if policy is DEFAULT_POLICY:
                self.assertGreater(F(pairs[0]['deployed_capital_usd']),999)
                self.assertIn('financial_metrics',pairs[0])
            if policy is LEGACY_POLICY:
                self.assertEqual(pairs[0]['version'],'predict-funded-pair-1')
                self.assertLess(F(pairs[0]['deployed_capital_usd']),30)
        self.assertEqual(len(set(ids)),6)

    def test_successor_aging_withdraws_positive_filter_authority(self):
        later=age_result(dict(self.result,superseded=False),at='2026-10-14T23:00:00+00:00')
        for e in later['state']['events']:
            for p in e['funded_pairs']:
                self.assertFalse(p['classification']['main_positive_eligible'])
                self.assertFalse(p['classification']['positive_rule_sensitive_eligible'])
