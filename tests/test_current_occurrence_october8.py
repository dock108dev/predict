"""Current retained native identity; simulated books and clocks, no source I/O."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from app.collection.current_occurrence import annotate,load
from tests import test_current_occurrence as fixtures
from app.collection.current_service import CurrentService
from app.collection.current_policy import DEFAULT
from app.collection.current_sink import LatestStateSink,utc
from app.dashboard.current_state import CurrentStore
P=Path(__file__).parent/'fixtures/current-buccaneers-cowboys-retained.json'
def catalogs():return json.loads(P.read_text())['catalogs']
class CurrentOccurrence(unittest.TestCase):
 def setUp(self):
  clock=patch('app.collection.current_occurrence.datetime');mock=clock.start();mock.now.return_value=datetime(2026,10,7,1,tzinfo=timezone.utc);self.addCleanup(clock.stop);self.clock=mock
 def test_exact_shared_identifier_and_original_schedule(self):
  b=load();self.assertEqual(b['event']['game_id'],'aa6b58bf-4feb-11f1-abca-2c54536568a9')
  self.assertEqual(b['sources']['kalshi']['milestone']['source_id'],b['sources']['polymarket_us']['shared_game_id'])
  for v,c in catalogs().items():
   annotate(c,v);self.assertEqual(c['events'][0]['current_occurrence_binding'],b['sha256'])
   self.assertTrue(all(m.get('direct_win_binding') for m in c['markets']))
 def test_invalidation_preserves_local_catalog_without_current_binding(self):
  for kind in ('shared_us','shared_kalshi','schedule','home_away','season','postponed','closed_event','closed_market','side','rules','expired'):
   with self.subTest(kind=kind):
    v='kalshi' if kind=='shared_kalshi' else 'polymarket_us';c=catalogs()[v];e=c['events'][0];m=c['markets'][0]
    if kind=='shared_us':e['_native']['sportradarGameId']='another-occurrence'
    if kind=='shared_kalshi':e['observed_identity_facts'][0]['source_id']='another-occurrence'
    if kind=='schedule':e['scheduled_start']='2026-10-10T00:15:00Z'
    if kind=='home_away':e['home']='NFL:TB'
    if kind=='season':e['season']='2027'
    if kind=='postponed':e['_native']['rescheduledFromGameId']='19519'
    if kind=='closed_event':e['_native']['closed']=True
    if kind=='closed_market':m['_native']['closed']=True
    if kind=='side':m['_native']['marketSides'][0]['long']=False
    if kind=='rules':m['_native']['description']='changed settlement material'
    if kind=='expired':self.clock.now.return_value=datetime(2026,10,9,0,16,tzinfo=timezone.utc)
    annotate(c,v);self.assertFalse(m.get('direct_win_binding'));self.assertEqual(len(c['markets']),2 if v=='kalshi' else 1)
class CurrentSelections(unittest.IsolatedAsyncioTestCase):
 setUp=CurrentOccurrence.setUp
 async def test_direct_wins_join_no_stays_local_and_economics_remain_withheld(self):
  s=CurrentService(config=dict(DEFAULT,enabled=False,aggregate_enabled=False));store=CurrentStore(s);s.store=store;s.sink=LatestStateSink(store,s.initial_state());s.dispatch=True
  try:
   for v,c in catalogs().items():
    s.catalog(v,c)
    for m in c['markets']:s.book(v,fixtures.book(v,m,utc()))
   snap=store.snapshot();common=[o for e in snap['events'] for g in e['groups'] for o in g['outcomes'] if len(o['quotes'])==2]
   self.assertEqual({o['participant'] for o in common},{'NFL:TB','NFL:DAL'})
   for o in common:
    self.assertEqual(o['predicate'],'win')
    for q in o['quotes'].values():
     self.assertTrue(q['binding']['verified']);self.assertTrue(q['comparison']['eligible']);self.assertTrue(q['rules_differ'])
     self.assertTrue(q['calculations']['arbitrage']['eligible']);self.assertFalse(q['calculations']['net_arbitrage']['eligible']);self.assertFalse(q['calculations']['ev']['eligible'])
   nos=[q for e in snap['events'] for g in e['groups'] for o in g['outcomes'] for q in o['quotes'].values() if q['source']['native_side']=='no']
   self.assertEqual(len(nos),2);self.assertTrue(all('native_predicate' not in q for q in nos))
  finally:await store.close()
