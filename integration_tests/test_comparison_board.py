"""B01 qualification confined to disposable SQL and loopback; no source requests."""
import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from psycopg import sql
from app.storage.store import connect,Store,hashed
from app.storage.current_games import GameStore,calculate,engine_binding
from app.storage.comparison_board import capture,saved,discover,choose,catalog,storage_key,source_guard,view_bundle
from app.dashboard.comparison_board import response,entries
from app.comparison.estimated_policy import DEFAULT_POLICY
from tests.test_ev09_n01 import envelopes,AT,SELECTED,retained


class ComparisonBoardSQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authored_evidence=[]
        cls.name='prediction_arb_test_b01_'+uuid4().hex[:12]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db=connect(cls.name);Store(cls.db).migrate();cls.store=GameStore(cls.db)
        for e in sorted(envelopes(),key=lambda e:e['record']['retained_at']):cls.store.import_record(e['record'],e['id'])
        with patch('app.storage.comparison_board.utc',return_value=AT):cls.snap=capture(cls.store,':'.join(SELECTED),DEFAULT_POLICY,at=AT)
        cls.bundle=cls.snap['projection']['inputs'];cls.game=cls.bundle['game_key']
        cls.result=calculate(cls.snap);cls.rid,ok=cls.store.publish(cls.snap,cls.result);assert ok
        cls.responses={view:response(cls.bundle,dict(cls.result,result_id=cls.rid,superseded=False),DEFAULT_POLICY,view=view,filter='all',at=AT) for view in ('odds','ev','arbs')}
    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
    def setUp(self):
        self.transaction=self.db.transaction(force_rollback=True);self.transaction.__enter__()
    def tearDown(self):self.transaction.__exit__(None,None,None)
    def test_sql_read_omits_irrelevant_projection_facts_preserves_whole_originals(self):
        original=self.store.combined_read_capture()
        quote=self.db.execute("SELECT payload,envelope_id FROM current_source_projection WHERE source='the_odds_api' AND kind='quote' LIMIT 1").fetchone()
        # Authored out-of-scope projection facts in this disposable SQL only.
        # Their immutable original receipts remain untouched and retained.
        for field,value in (('competition','NHL'),('family','spread'),('period','first_half')):
            row=json.loads(quote['payload'])
            row['event' if field=='competition' else 'market_identity'][field]=value
            self.store.source('the_odds_api','quote','authored-offscope-'+field,AT,quote['envelope_id'],row)
        book=self.db.execute("SELECT payload,envelope_id FROM current_source_projection WHERE source='kalshi' AND kind='book' LIMIT 1").fetchone()
        row=json.loads(book['payload']);ref=row['book']['raw']['ref'];ref['market_id']='authored-nonwinner'
        self.store.source('kalshi','book',ref['event_id']+':'+ref['market_id'],AT,book['envelope_id'],row)
        self.assertEqual(self.store.combined_read_capture(),original)
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM current_source_projection WHERE native_id LIKE 'authored-offscope-%'").fetchone()['n'],3)
        for item in original[0]:
            stored=self.db.execute('SELECT payload,payload_sha256 FROM current_envelope WHERE id=%s',(item['id'],)).fetchone()
            self.assertEqual(json.loads(stored['payload']),item['record'])
            self.assertEqual(stored['payload_sha256'],item['payload_sha256'])

    def test_sql_native_winner_scope_keeps_outer_or_bound_identity_and_whole_catalog(self):
        catalog_row=self.db.execute("SELECT native_id,payload FROM current_source_projection WHERE source='kalshi' AND kind='catalog'").fetchone()
        original=json.loads(catalog_row['payload'])
        winner=next(m for m in original['markets'] if m['market_type']=='moneyline')
        native=winner['event_id']+':'+winner['id']
        for changed_side in ('outer','binding'):
            inventory=deepcopy(original);market=next(m for m in inventory['markets'] if m['id']==winner['id'])
            if changed_side=='outer':market['market_type']='spread'
            else:market['v1_raw_binding']['identity']['family']='spread'
            self.db.execute("UPDATE current_source_projection SET payload=%s WHERE source='kalshi' AND kind='catalog' AND native_id=%s",(json.dumps(inventory),catalog_row['native_id']))
            _,associations,rows=self.store.combined_read_capture()
            self.assertIn(('kalshi','book',native),associations)
            kept=next(row for row in rows if row['source']=='kalshi' and row['kind']=='catalog')
            self.assertEqual(json.loads(kept['payload']),inventory)
        inventory=deepcopy(original);market=next(m for m in inventory['markets'] if m['id']==winner['id'])
        market['market_type']='spread';market['v1_raw_binding']['identity']['family']='spread'
        self.db.execute("UPDATE current_source_projection SET payload=%s WHERE source='kalshi' AND kind='catalog' AND native_id=%s",(json.dumps(inventory),catalog_row['native_id']))
        _,associations,rows=self.store.combined_read_capture()
        self.assertNotIn(('kalshi','book',native),associations)
        self.assertTrue(any(row['source']=='kalshi' and row['kind']=='catalog' for row in rows))

    def test_project_queries_exact_event_before_decoding_and_keeps_event_families(self):
        key=':'.join(SELECTED)
        quote=self.db.execute("SELECT payload,envelope_id FROM current_source_projection WHERE source='the_odds_api' AND kind='quote' AND payload::jsonb->'quote'->'source'->>'native_event_id'=%s LIMIT 1",(SELECTED[1],)).fetchone()
        unrelated=json.loads(quote['payload']);unrelated['quote']['source']['native_event_id']='authored-other-event'
        self.store.source('the_odds_api','quote','authored-other-event',AT,quote['envelope_id'],unrelated)
        spread=json.loads(quote['payload']);spread['market_identity'].update(family='spread',line='-1.5');spread['quote']['id']='authored-selected-spread'
        self.store.source('the_odds_api','quote','authored-selected-spread',AT,quote['envelope_id'],spread)
        decode=json.loads
        def selected_only(payload):
            value=decode(payload)
            if isinstance(value,dict) and 'quote' in value:self.assertNotEqual(value['quote']['source']['native_event_id'],'authored-other-event')
            return value
        with patch('app.storage.current_games.json.loads',side_effect=selected_only):self.store.project(key)
        projection=json.loads(self.db.execute('SELECT payload FROM current_game_projection WHERE game_key=%s',(key,)).fetchone()['payload'])
        records=projection['inputs']['records']+projection['inputs']['references']
        self.assertTrue(any(row['market_identity']['family']=='spread' for row in records))
        self.assertTrue(all(row['quote']['source']['native_event_id']==SELECTED[1] for row in records))

    def test_authentic_sql_catalog_and_saved_numeric_trace(self):
        b=choose(discover(self.store,at=AT),self.game);self.assertEqual(b['game_key'],retained()[0]['game_key'])
        n01={q['id']:q for _,_,q in entries(retained()[1])}
        for _,_,q in entries(self.result['state']):
            self.assertEqual(q['original'],n01[q['id']]['original'])
            for field in ('financial_metrics','funding','classification'):
                self.assertEqual(q['calculations']['funded_estimate'].get(field),n01[q['id']]['calculations']['funded_estimate'].get(field))
        expected={p['id']:p for p in retained()[1]['events'][0]['funded_pairs']}
        for p in self.result['state']['events'][0]['funded_pairs']:
            for field in ('financial_metrics','classification'):self.assertEqual(p[field],expected[p['id']][field])
            self.assertEqual({k:v for k,v in p['funding'].items() if k!='legs'},{k:v for k,v in expected[p['id']]['funding'].items() if k!='legs'})
            for a,b in zip(p['funding']['legs'],expected[p['id']]['funding']['legs']):
                for key in ('native_quantity','native_unit','acquisition_usd','net_upfront_fee_usd','deployed_capital_usd'):self.assertEqual(a.get(key),b.get(key))
        c=catalog(discover(self.store,at=AT));self.assertEqual(sum(g['game_key']==self.game for g in c['games']),1)
        self.assertTrue(all(g['scope']=='NFL/full_game/winner' for g in c['games']))
        for e in self.bundle['envelopes']:
            row=self.db.execute('SELECT payload,payload_sha256 FROM current_envelope WHERE id=%s',(e['id'],)).fetchone()
            self.assertEqual(row['payload_sha256'],e['payload_sha256']);self.assertEqual(json.loads(row['payload']),e['record'])
    def test_reopening_does_not_renew_time_and_original_bytes(self):
        with patch('app.storage.comparison_board.utc',return_value=AT):later=capture(self.store,self.game,DEFAULT_POLICY,at='2026-10-14T01:16:09.650084+00:00')
        self.assertEqual(later,self.snap)
        row=self.db.execute('SELECT payload FROM current_game_snapshot WHERE id=%s',(self.snap['id'],)).fetchone()
        self.assertEqual(json.loads(row['payload']),{k:v for k,v in self.snap.items() if k!='id'})
        v=saved(self.store,self.game,DEFAULT_POLICY);self.assertEqual(v['as_of'],AT)
    def test_amount_benchmark_buffer_variants_are_separate_and_reopen(self):
        seen=set()
        for p in (replace(DEFAULT_POLICY,capital_ceiling_usd='500'),replace(DEFAULT_POLICY,buffer_rate='0.01'),replace(DEFAULT_POLICY,benchmark_venue='novig'),replace(DEFAULT_POLICY,benchmark_venue='prophetx')):
            with patch('app.storage.comparison_board.utc',return_value=AT):snap=capture(self.store,self.game,p,at=AT)
            result=calculate(snap);rid,ok=self.store.publish(snap,result);self.assertTrue(ok);seen.add(snap['id'])
            v=saved(self.store,self.game,p);self.assertEqual(v['result_id'],rid)
            self.assertEqual(v['policy']['revision'],p.revision)
            self.assertEqual(v['state']['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['funded_estimate']['benchmark']['venue'],p.benchmark_venue)
        self.authored_evidence.append(dict(case='authored_settings',distinct_variants=len(seen),snapshot_ids=sorted(seen),default_result_preserved=True))
        self.assertEqual(len(seen),4);self.assertEqual(saved(self.store,self.game,DEFAULT_POLICY)['result_id'],self.rid)
    def authored_update(self,offset='2026-10-14T01:15:10+00:00'):
        e=next(e for e in envelopes() if e['record']['source']=='kalshi' and e['record']['kind']=='admitted_books')
        r=deepcopy(e['record']);r['retained_at']=offset
        # Authored observation: original packets are untouched; changed modeled
        # reconstructed level and clocks are never claimed as live evidence.
        r['value']['observations']=r['value']['observations'][:1]
        o=r['value']['observations'][0];o['book']['raw']['exchange_at']=offset;o['book']['raw']['received_at']=offset
        o['book']['outcomes'][0]['asks']['levels'][0]['price']['value']='0.44'
        self.store.import_record(r,'authored:'+uuid4().hex)
        return r
    def test_member_arrival_revises_result_and_refuses_previous_publication(self):
        self.authored_update();rid,ok=self.store.publish(self.snap,self.result);self.assertFalse(ok);self.assertEqual(rid,self.rid)
        self.assertTrue(saved(self.store,self.game,DEFAULT_POLICY)['superseded'])
        with patch('app.storage.comparison_board.utc',return_value='2026-10-14T01:15:11+00:00'):snap=capture(self.store,self.game,DEFAULT_POLICY,at='2026-10-14T01:15:11+00:00')
        result=calculate(snap);newid,ok=self.store.publish(snap,result);self.assertTrue(ok)
        self.assertNotEqual(snap['id'],self.snap['id']);self.assertNotEqual(newid,self.rid)
        self.authored_evidence.append(dict(case='authored_member_arrival',old_snapshot=self.snap['id'],new_snapshot=snap['id'],old_result=self.rid,new_result=newid,stale_publication=False,new_publication=ok,old_input=self.snap['input_version'],new_input=snap['input_version'],original_result_preserved=True))
        self.assertEqual(saved(self.store,self.game,DEFAULT_POLICY)['result_id'],newid)
        old=json.loads(self.db.execute('SELECT payload FROM current_game_result WHERE id=%s',(self.rid,)).fetchone()['payload']);self.assertEqual(old,self.result)
    def test_removed_member_and_reference_revoke_guard_immediately(self):
        for kind in ('book','quote'):
            with self.db.transaction(force_rollback=True):
                if kind=='book':self.db.execute("DELETE FROM current_source_projection WHERE source='kalshi' AND kind='book'")
                else:self.db.execute("DELETE FROM current_source_projection WHERE source='the_odds_api' AND kind='quote' AND payload::jsonb->'quote'->>'venue'='pinnacle'")
                self.assertFalse(self.store.publish(self.snap,self.result)[1])
                self.assertTrue(saved(self.store,self.game,DEFAULT_POLICY)['superseded'])
    def test_changed_reference_creates_new_snapshot(self):
        e=next(e for e in envelopes() if e['record']['kind']=='aggregate_batch');r=deepcopy(e['record'])
        body=json.loads(base64.b64decode(r['value']['body_b64']))
        for event in body:
            if event['id']==SELECTED[1]:
                for book in event['bookmakers']:
                    if book['key']=='pinnacle':
                        book['last_update']='2026-10-14T01:15:10Z'
                        for market in book['markets']:
                            market['last_update']='2026-10-14T01:15:10Z';market['outcomes'][0]['price']=2.24
        raw=json.dumps(body).encode();r['retained_at']='2026-10-14T01:15:11Z';r['value'].update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),received_at='2026-10-14T01:15:11Z')
        self.store.import_record(r,'authored-reference:'+uuid4().hex)
        self.assertFalse(self.store.publish(self.snap,self.result)[1])
        with patch('app.storage.comparison_board.utc',return_value='2026-10-14T01:15:12Z'):snap=capture(self.store,self.game,DEFAULT_POLICY,at='2026-10-14T01:15:12Z')
        self.assertNotEqual(snap['projection']['inputs']['benchmark']['revision'],self.bundle['benchmark']['revision'])
    def test_reordered_arrival_uses_sql_original_association(self):
        new=self.authored_update()
        with patch('app.storage.comparison_board.utc',return_value='2026-10-14T01:15:12Z'):
            a=capture(self.store,self.game,DEFAULT_POLICY,at='2026-10-14T01:15:12Z')
            old=deepcopy(new);old['retained_at']='2026-10-14T01:15:11Z';old['value']['observations'][0]['book']['raw']['exchange_at']='2026-10-14T01:15:07Z'
            old['value']['observations'][0]['book']['outcomes'][0]['asks']['levels'][0]['price']['value']='0.99'
            self.store.import_record(old,'authored-reordered:'+uuid4().hex)
            b=capture(self.store,self.game,DEFAULT_POLICY,at='2026-10-14T01:15:13Z')
        self.assertEqual(a['id'],b['id'])
        q=next(q for _,_,q in entries(b['projection']['inputs']['state_inputs']) if q['venue']=='kalshi' and q['source']['native_side']=='yes' and q['original']['value']=='0.44')
        self.assertEqual(q['times']['source_at'],'2026-10-14T01:15:10+00:00')
    def test_unrelated_arrival_does_not_revoke_or_renew_selected_result(self):
        row=self.db.execute("SELECT payload,envelope_id FROM current_source_projection WHERE source='kalshi' AND kind='book' LIMIT 1").fetchone()
        v=json.loads(row['payload']);v['book']['raw']['ref']['event_id']='authored-unrelated'
        self.store.source('kalshi','book','authored-unrelated:market','2026-10-14T01:15:10Z',row['envelope_id'],v)
        self.assertTrue(self.store.publish(self.snap,self.result)[1])
        with patch('app.storage.comparison_board.utc',return_value=AT):self.assertEqual(capture(self.store,self.game,DEFAULT_POLICY,at=AT)['id'],self.snap['id'])
    def test_wrong_binding_stop_or_policy_result_cannot_publish(self):
        for field in ('snapshot_id','game_key','input_version','engine_binding','policy'):
            v=deepcopy(self.result);v[field]='authored-wrong'
            with self.assertRaisesRegex(ValueError,'binding_conflict'):self.store.publish(self.snap,v)
        self.assertFalse(self.store.publish(self.snap,self.result,allow_latest=False)[1])
    def test_immutable_original_history(self):
        for table,key in (('current_envelope',self.bundle['envelope_ids'][0]),('current_game_snapshot',self.snap['id']),('current_game_result',self.rid)):
            with self.assertRaises(Exception),self.db.transaction():self.db.execute(sql.SQL('UPDATE {} SET payload=%s WHERE id=%s').format(sql.Identifier(table)),('{}',key))
    def test_pipeline_coalesces_settings_and_refuses_retired_publication(self):
        from app.collection.current_database import DatabasePipeline
        service=SimpleNamespace(config={'cleanup_seconds':1},journal=SimpleNamespace(paths=lambda:[]))
        pipe=DatabasePipeline(service,[]);pipe.bootstrapped=True
        half=replace(DEFAULT_POLICY,capital_ceiling_usd='500');pipe.request(self.game,half)
        real_calculate=calculate
        def changed(snapshot):
            pipe.request(self.game,replace(half,capital_ceiling_usd='600'))
            return real_calculate(snapshot)
        with patch('app.collection.current_database.connect',return_value=__import__('contextlib').nullcontext(self.db)),patch('app.collection.current_database.require_disk_space'),patch('app.collection.current_database.calculate',side_effect=changed),patch('app.storage.comparison_board.utc',return_value=AT):
            pipe.tick()
        self.assertIsNone(saved(self.store,self.game,half))
        self.assertEqual(len(pipe.pending),1);self.assertEqual(next(iter(pipe.pending.values())).requested_amount_usd,'600')
        self.assertTrue(self.db.execute('SELECT 1 FROM current_game_result r JOIN current_game_snapshot s ON s.id=r.snapshot_id WHERE s.policy_version=%s',(half.revision,)).fetchone())

    def test_z_worker_calculates_outside_capture_and_retains_generation(self):
        from app.collection.current_database import DatabasePipeline
        service=SimpleNamespace(config={'cleanup_seconds':1},journal=SimpleNamespace(paths=lambda:[]))
        pipe=DatabasePipeline(service,[]);pipe.bootstrapped=True
        p=replace(DEFAULT_POLICY,capital_ceiling_usd='700');pipe.request(self.game,p)
        holder={};observed=[]
        def connection():holder['db']=connect(self.name);return holder['db']
        def calculation(snapshot):
            observed.append(holder['db'].info.transaction_status.name)
            return calculate(snapshot)
        with patch('app.collection.current_database.connect',side_effect=connection),patch('app.collection.current_database.require_disk_space'),patch('app.collection.current_database.calculate',side_effect=calculation),patch('app.storage.comparison_board.utc',return_value=AT):pipe.tick()
        self.assertEqual(observed,['IDLE']);self.assertEqual(pipe.pending,{})
        self.authored_evidence.append(dict(case='authored_worker_transaction',calculation_transaction_status=observed,one_calculation=True,queue_drained=True))

    def test_zz_history_inputs_reopen_exact_snapshot_after_arrival(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        # Commit an authored source change only in this disposable DB. Last case
        # leaves the original snapshot/result immutable and the latest guard stale.
        original_store=self.store
        with connect(self.name) as db:
            self.store=GameStore(db)
            try:self.authored_update()
            finally:self.store=original_store
        p=SimpleNamespace(database=SimpleNamespace(request=lambda *a:None),dispatch=True,closed=False,closing=False)
        async def check():
            app=web.Application();mount(app,p)
            async with TestClient(TestServer(app)) as client:
                with patch('app.dashboard.comparison_board_api.connect',side_effect=lambda:connect(self.name)),patch('app.storage.comparison_board.utc',return_value='2026-10-14T01:15:12Z'),patch('app.dashboard.comparison_board.utc',return_value='2026-10-14T01:15:12Z'):
                    current=await (await client.get('/api/boards/inputs',params={'game':self.game})).json()
                    prior=await (await client.get('/api/boards/inputs',params={'game':self.game,'result_id':self.rid})).json()
                    self.assertNotEqual(current['inputs']['input_version'],self.bundle['input_version'])
                    self.assertEqual(prior['inputs'],self.bundle)
        asyncio.run(check())
        self.authored_evidence.append(dict(case='authored_history_inputs',original_snapshot=self.snap['id'],original_input=self.bundle['input_version'],exact_original_bundle_reopened_after_change=True))

    def test_compact_loopback_reads_settings_details_zero_acquisition(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.comparison_board_api import mount
        calls=[];p=SimpleNamespace(database=SimpleNamespace(request=lambda *a:calls.append(a)),dispatch=True,closed=False,closing=False)
        async def check():
            app=web.Application();mount(app,p)
            async with TestClient(TestServer(app)) as client:
                with patch('app.dashboard.comparison_board_api.connect',side_effect=lambda:connect(self.name)),patch('app.storage.comparison_board.utc',return_value=AT),patch('app.dashboard.comparison_board.utc',return_value=AT),patch('httpx.Client.send',side_effect=AssertionError('No provider traffic')),patch('app.collection.current_account_recovery.observe_and_activate',side_effect=AssertionError('No recovery')):
                    c=await client.get('/api/boards/games');self.assertEqual(c.status,200);self.assertEqual(sum(g['game_key']==self.game for g in (await c.json())['games']),1)
                    for view in ('odds','ev','arbs'):
                        req=await client.get('/api/boards/'+view,params={'game':self.game,'filter':'all'})
                        self.assertEqual(req.status,200);out=await req.json();self.assertEqual(out['provider_requests'],0);self.assertEqual(out['as_of'],AT)
                        self.assertLess(len(await req.read()),512*1024)
                    history=await client.get('/api/boards/history',params={'game':self.game});self.assertEqual(history.status,200);self.assertTrue((await history.json())['results'])
                    original=await client.get('/api/boards/inputs',params={'game':self.game});self.assertEqual(original.status,200);self.assertEqual((await original.json())['inputs'],self.bundle)
                    qid=self.responses['ev']['rows'][0]['quote_id']
                    d=await client.get('/api/boards/details',params={'game':self.game,'result_id':self.rid,'quote':qid})
                    self.assertEqual(d.status,200);self.assertEqual((await d.json())['quote']['calculations']['funded_estimate']['freshness']['status'],'current')
                    for args in ({'amount':'500'},{'benchmark_venue':'novig'}):
                        req=await client.get('/api/boards/ev',params=dict(game=self.game,**args));self.assertEqual(req.status,202);self.assertTrue((await req.json())['prices'])
                    p.dispatch=False;p.closed=True
                    out=await (await client.get('/api/boards/arbs',params={'game':self.game,'filter':'all'})).json()
                    self.assertEqual(out['delivery_state'],'stopped');self.assertTrue(all(not r.get('classification',{}).get('main_positive_eligible') for r in out['rows']))
        asyncio.run(check());self.assertEqual(len(calls),2)
