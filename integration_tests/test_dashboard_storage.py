"""PostgreSQL dashboard boundary; only a dedicated disposable database is changed."""
import asyncio,json,unittest,uuid
from unittest.mock import patch
from psycopg import sql
from app.storage import Store,connect
from app.dashboard.pipeline import Pipeline
from app.dashboard.controller import Controller,DEFAULTS
from app.dashboard import repository

class DashboardStorageTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.name='prediction_arb_dashboard_test_'+uuid.uuid4().hex[:8]
  cls.admin=connect();cls.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
  with connect(cls.name) as db:Store(db).migrate()
 @classmethod
 def tearDownClass(cls):
  cls.admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)));cls.admin.close()
 def setUp(self):
  self.p=Pipeline('synthetic',dict(DEFAULTS),self.name);self.sid=self.p.start()
 def tearDown(self):
  if not self.p.db.closed:
   try:self.p.finish('test complete',0)
   except Exception:self.p.db.close()
 def test_saved_session_prices_candidates_and_replay(self):
  first=self.p.synthetic_bootstrap();self.p.synthetic_tick(2)
  self.p.finish('test stop',0)
  with patch('app.dashboard.repository.connect',lambda:connect(self.name)):
   view=repository.saved_view(self.sid);self.assertEqual(len(view['markets']),2)
   self.assertTrue(view['candidates']);self.assertEqual(view['session']['evidence_class'],'synthetic')
   h=repository.history(self.sid,view['candidates'][0]['id']);self.assertGreaterEqual(len(h['samples']),2)
  with connect(self.name) as db:
   s=Store(db);self.assertGreaterEqual(s.replay_all(),2)
 def test_history_bounds_cover_more_than_display_limit(self):
  # Use the real schema and repeated real detector observations, preserving audit links.
  v=self.p.synthetic_bootstrap();cid=v['candidates'][-1]['id']
  for n in range(1,102):self.p.synthetic_tick(n)
  with patch('app.dashboard.repository.connect',lambda:connect(self.name)):
   h=repository.history(self.sid,cid)
   self.assertEqual(len(h['samples']),100);self.assertEqual(h['total_observations'],102)
   self.assertGreater(h['last_observed'],h['samples'][-1]['observed_at'])
 def test_on_demand_depth_repeat_is_distinct(self):
  v=self.p.synthetic_bootstrap();cid=v['candidates'][0]['id']
  self.p.depth(cid);self.p.depth(cid)
  with patch('app.dashboard.repository.connect',lambda:connect(self.name)):
   d=repository.saved_depth(self.sid,cid);self.assertIn('solutions',d)
  self.assertEqual(self.p.db.execute("select count(*) n from calculation where session_id=%s and engine='depth-1'",(self.sid,)).fetchone()['n'],2)
 def test_disconnected_projection_recomputed(self):
  self.p.synthetic_bootstrap();v=self.p.disconnect('kalshi','test disconnect')
  self.assertTrue(all(not c['current_opportunity'] for c in v['candidates']))
  self.assertTrue(any('reconstruction-unsynchronized' in r for c in v['candidates'] for r in c['technical_reasons']))
 def test_real_database_disconnect_leaves_incomplete(self):
  self.p.synthetic_bootstrap();self.admin.execute('SELECT pg_terminate_backend(%s)',(self.p.db.info.backend_pid,))
  with self.assertRaises(Exception):self.p.synthetic_tick(1)
  with self.assertRaises(Exception):self.p.finish('database failure',0,True)
  with connect(self.name) as db:
   row=db.execute('SELECT state FROM capture_session WHERE id=%s',(self.sid,)).fetchone()
   self.assertEqual(row['state'],'running')
 def test_worker_pipeline_stops_after_receipt_limit(self):
  self.p.limits={**self.p.limits,'receipts':2};self.p.synthetic_bootstrap()
  with self.assertRaises(OverflowError):self.p.synthetic_tick(1)
  self.assertEqual(self.p.db.execute('SELECT count(*) n FROM receipt WHERE session_id=%s',(self.sid,)).fetchone()['n'],2)

 def test_personal_demo_start_updates_stop_and_saved_reopen(self):
  """The actual controller loop, isolated storage and invented inputs only."""
  from app.dashboard.views import age_view
  async def exercise():
   c=Controller(lambda mode,limits:Pipeline(mode,limits,self.name))
   try:
    await c.start('synthetic',dict(seconds=5,markets=2,receipts=100))
    for _ in range(300):
     if c.state=='scanning' and c.view.get('sequence',0)>=2:break
     await asyncio.sleep(.01)
    self.assertEqual(c.state,'scanning');self.assertGreaterEqual(c.view['sequence'],2)
    self.assertTrue(c.view['markets']);self.assertTrue(c.view['candidates'])
    first=c.view['sequence'];sid=c.sid
    c.request_stop('Stopped by you',initiator='owner');await asyncio.wait_for(c.task,3)
    self.assertIsNone(c.error);self.assertEqual(c.state,'stopped')
    self.assertEqual(c.worker.shutdown['unprocessed'],0)
    self.assertTrue(c.worker.shutdown['refresh_work']['settled'])
    with patch('app.dashboard.repository.connect',lambda:connect(self.name)):
     saved=repository.saved_view(sid)
    self.assertGreaterEqual(saved['sequence'],first)
    self.assertEqual(saved['session']['state'],'complete')
    self.assertTrue(saved['markets']);self.assertTrue(saved['candidates'])
    self.assertFalse(any(x['current_opportunity'] for x in age_view(saved,active=False)['candidates']))
    with connect(self.name) as db:
     self.assertGreaterEqual(Store(db).replay_all(),2)
   finally:await c.close()
  asyncio.run(exercise())

 def test_saved_summary_uses_all_events_and_own_counts(self):
  from pathlib import Path
  from psycopg.types.json import Jsonb
  fixtures=json.loads((Path(__file__).parents[1]/'tests/fixtures/saved_session_status.json').read_text())
  self.p.synthetic_bootstrap();self.p.shutdown=dict(messages=7,rejected=0,unprocessed=0)
  self.p.finish('Time limit reached',0)
  with connect(self.name) as db:
   store=Store(db)
   for fixture in fixtures:
    s=fixture['session']
    db.execute("INSERT INTO capture_session(id,environment,evidence_class,started_at,state,config,provenance) VALUES(%s,%s,%s,%s,%s,'{}',%s)",(s['id'],s['environment'],s['evidence_class'],s['started_at'],s['state'],fixture['source']))
    for e in fixture['coverage']:store.event(s['id'],e['kind'],e['detail'],at=e.get('original_time'))
    for _ in range(101):store.event(s['id'],'coverage',dict(note='Later coverage event'))
  with patch('app.dashboard.repository.connect',lambda:connect(self.name)):
   rows={s['id']:s for s in repository.list_sessions()}
   for fixture in fixtures:
    sid=fixture['session']['id'];v=repository.saved_view(sid)
    self.assertEqual(v['session']['saved_status'],rows[sid]['saved_status'])
    self.assertEqual(v['session']['saved_status']['label'],'Saved with capture gaps')
    self.assertEqual(len(v['coverage']),100);self.assertGreater(v['coverage_total'],100)
    self.assertIsNone(v['messages']);self.assertEqual(v['receipts'],0)
   own=repository.saved_view(self.sid)
   self.assertEqual(own['messages'],7);self.assertEqual(own['receipts'],2)
   self.assertEqual(own['session']['saved_status']['label'],'Saved successfully')
