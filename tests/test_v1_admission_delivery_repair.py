"""OFFLINE retained bytes and explicitly synthetic negative controls. No providers."""
import base64,json,tracemalloc,unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from app.collection import native_payload
from app.collection.v1_comparison import bind,admission,REPAIR_POLICY,annotate
from app.collection.admission_enrichment import duplicate_identity_conflicts,share_games
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/v1-admission-delivery-repair-20261001-v1'

class Repair(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.cats={v:json.loads((OUT/(v+'-repaired-catalog.json')).read_text()) for v in ('kalshi','polymarket_us')}
 def market(self,venue,prefix):
  cat=self.cats[venue];m=next(m for m in cat['markets'] if m['id'].startswith(prefix));e=next(e for e in cat['events'] if e['id']==m['event_id']);return deepcopy(e),deepcopy(m)
 def test_awards_have_season_category_entrant_without_game_or_field(self):
  for prefix in ('KXMLB-26-ATL','KXNBA-27-BOS','KXSB-27-BUF','KXNHL-27-ANA','KXMARMAD-27-ALA'):
   e,m=self.market('kalshi',prefix);e['participants']={};e.pop('game_number',None);e.pop('original_start',None)
   b=bind(e,m,'kalshi',policy=REPAIR_POLICY);self.assertEqual(b['status'],'BOUND_RAW_PREDICATE',b['blockers']);self.assertEqual(b['identity']['family'],'futures');self.assertIsNone(b['award_binding']['field'])
  e,m=self.market('kalshi','KXMLB-26-ATL');m['_native']['rules_primary']=m['_native']['rules_primary'].replace('Championship','Championship in a fictional league')
  self.assertEqual(bind(e,m,'kalshi',policy=REPAIR_POLICY)['status'],'IDENTITY_BLOCKED')
 def test_literal_horizon_conflict_and_known_entrant_contradiction(self):
  e,m=self.market('kalshi','KXNBA-27-BOS');m['_native']['rules_primary']=m['_native']['rules_primary'].replace('2027','2028');self.assertEqual(bind(e,m,'kalshi',policy=REPAIR_POLICY)['status'],'IDENTITY_BLOCKED')
  e,m=self.market('kalshi','KXMLB-26-ATL');m['_native']['yes_sub_title']='Philadelphia';m['_native']['rules_primary']=m['_native']['rules_primary'].replace('Atlanta','Philadelphia');self.assertEqual(bind(e,m,'kalshi',policy=REPAIR_POLICY)['status'],'IDENTITY_BLOCKED')
 def test_period_signed_line_long_short_and_literal_scope(self):
  e,m=self.market('polymarket_us','1094940');b=bind(e,m,'polymarket_us',policy=REPAIR_POLICY);self.assertEqual(b['status'],'BOUND_RAW_PREDICATE',b['blockers']);self.assertEqual(b['identity']['period'],'first_half');self.assertEqual(b['source_predicate']['line'],'1.5')
  for mutation in ('side','period','integer'):
   changed=deepcopy(m)
   if mutation=='side':changed['_native']['marketSides'][0]['description']='-1.50'
   elif mutation=='period':changed['_native']['description']=changed['_native']['description'].replace('in the first half of ','in ')
   else:changed['_native']['line']=1
   self.assertEqual(bind(e,changed,'polymarket_us',policy=REPAIR_POLICY)['status'],'IDENTITY_BLOCKED',mutation)
 def test_recovered_combined_total_and_explicit_winner_tie(self):
  for mid in ('1094166','933112','933113','933116'):
   e,m=self.market('polymarket_us',mid);b=bind(e,m,'polymarket_us',policy=REPAIR_POLICY);self.assertEqual(b['status'],'BOUND_RAW_PREDICATE',b['blockers'])
  e,m=self.market('polymarket_us','933113');b=bind(e,m,'polymarket_us',policy=REPAIR_POLICY);self.assertEqual(b['source_predicate']['participant'],'tie');self.assertEqual(b['source_predicate']['outcomes'][0]['operator'],'eq')
 def test_full_metadata_admission_fits_ordinary_operating_bounds(self):
  from app.collection.catalog_metadata import compact
  from app.dashboard.bounds import retained_bytes
  for venue,c in self.cats.items():
   cat=deepcopy(c);compact(cat,venue);self.assertLessEqual(len(cat['markets']),64);self.assertLessEqual(retained_bytes(cat),2*1024*1024,venue)
   self.assertTrue(cat['excluded_catalog']['metadata_admissions']);self.assertTrue(any(r[3]=='admitted_metadata_not_selected' for r in cat['excluded_catalog']['markets']))
   original={m['id']:m['_native'] for m in c['markets']}
   for m in cat['markets']:self.assertEqual(m['_native'],original[m['id']])
 def test_mlb_games_still_require_occurrence_and_reschedule(self):
  e,m=self.market('kalshi','KXMLBGAME-26OCT011400PHIATL');b=bind(e,m,'kalshi',policy=REPAIR_POLICY);self.assertEqual(b['status'],'IDENTITY_BLOCKED');self.assertTrue(any('MLB game/number' in r for r in b['blockers']))
 def test_expanded_metadata_is_not_duplicate_identity_but_side_conflict_is(self):
  e,m=self.market('polymarket_us','1094940');a=deepcopy(m['_native']);b=deepcopy(a);b['volume']='123';b['title']='Display update'
  self.assertEqual(duplicate_identity_conflicts(a,b,event=False),[]);b['marketSides'][0]['long']=False;self.assertIn('marketSides',duplicate_identity_conflicts(a,b,event=False))
 def test_complete_retained_parse_measurement_and_incomplete_never_rebuilt(self):
  from app.dashboard.session_history import verified
  from scripts.repair_v1_retained_admission import SESSION
  pages=[r for r in verified(SESSION)['rows'] if r['type']=='prediction_discovery_http']
  p=next(r for r in pages if r['path']=='/v1/events/116584');raw=base64.b64decode(p['body_b64']);self.assertTrue(p['complete'])
  with self.assertRaisesRegex(ValueError,'native_parse_expansion_cap'):native_payload.parse(raw,limits=native_payload.TRANSPORT_CONTRACT)
  metrics={};tracemalloc.start();data=native_payload.parse(raw,limits=native_payload.TRANSPORT_CONTRACT,metrics=metrics,revised=True);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
  self.assertEqual(len(data['event']['markets']),246);self.assertLess(peak,16*1024*1024);self.assertLess(metrics['parse_object_bytes'],16*1024*1024)
  for bad,reason in [(b'{"event":{},"x":1,"x":2}','duplicate_key'),(b'{"event":{},"x":NaN}','nonfinite'),(raw[:-1],'incomplete'),(b'{"event":{},"x":"'+b'x'*(2*1024*1024)+b'"}','decoded_byte_cap')]:
   with self.assertRaises(ValueError):native_payload.parse(bad,limits=native_payload.TRANSPORT_CONTRACT,revised=True)
  incomplete=next(r for r in pages if r['path']=='/v1/events/115743');self.assertFalse(incomplete['complete']);self.assertFalse(incomplete['usable_metadata'])
 def test_query_parse_caps_are_local_shared_memory_storage_stop_session(self):
  from app.collection.continuous import REST
  from app.collection.prediction_producer import PredictionBudget
  limits=dict(session_bytes=8*1024*1024,discovery_requests=8,dollar_cap_per_source='0',dollars_per_discovery_request='0',dollars_per_connection='0',frame_bytes=262144)
  c=REST('http://127.0.0.1:9',limits,lambda r:None,1,PredictionBudget(limits));c.native_scope_request_context=True;c.transport_policy=native_payload.TRANSPORT_CONTRACT;c.source_venue='polymarket_us'
  c.session=SimpleNamespace(spec=dict(v1_comparison_policy=REPAIR_POLICY),discovery=SimpleNamespace(stop_source=Mock()),request_stop=Mock())
  for reason in ('native_parse_expansion_cap','native_json_depth_cap','native_json_structure_cap'):c.fail_budget(reason)
  c.session.discovery.stop_source.assert_not_called();c.session.request_stop.assert_not_called()
  for reason in ('rss_cap','journal_byte_cap','disk_floor'):c.fail_budget(reason)
  self.assertEqual(c.session.request_stop.call_count,3)
 def test_legacy_score_interpretation_matches_sealed_original_for_all_records(self):
  import zipfile
  from app.collection.native_score_binding import bind as current
  with zipfile.ZipFile(ROOT/'scripts/v1_coverage_package/SOURCE.zip') as z:
   namespace={'__name__':'app.collection.archived_score_control','__package__':'app.collection'};exec(z.read('app/collection/native_score_binding.py'),namespace)
  for m in self.cats['kalshi']['markets']:
   if m.get('native_scope_binding'):self.assertEqual(current(m['_native'],m['native_scope_binding']),namespace['bind'](m['_native'],m['native_scope_binding']),m['id'])
 def test_reference_prices_never_enable_repeat_award_poll(self):
  from app.collection.source_session import AggregateWorker
  w=object.__new__(AggregateWorker);w.session=SimpleNamespace(spec=dict(v1_comparison_policy=REPAIR_POLICY));w.counterpart_empty=set();w.emit=Mock()
  w.counterpart_interest('award','NFL',[dict(role='reference_only',reasons=[],implied='.5')]);self.assertIn(('award','NFL'),w.counterpart_empty)
  w.counterpart_interest('award','NBA',[dict(role='aggregated_venue_observation',reasons=[],implied='.5')]);self.assertNotIn(('award','NBA'),w.counterpart_empty)

class OrdinaryIsolation(unittest.IsolatedAsyncioTestCase):
 async def test_parse_failure_keeps_unrelated_us_and_kalshi_work_running(self):
  import asyncio,tempfile
  from aiohttp import web
  from unittest.mock import patch
  from tests.test_v1_coverage_collector import Fixture,configuration
  from app.collection.transport_session import reopen
  class Local(Fixture):
   async def boot(self,path):
    owner=await super().boot(path);owner.spec_factory=lambda:dict(configuration(),mode='mock',v1_comparison_policy=REPAIR_POLICY);return owner
   async def rest(self,req):
    if req.path=='/v1/events':
     self.native_calls.append((req.path,dict(req.query)))
     if req.query.get('tagSlug')=='nfl' and req.query.get('sportsMarketTypes')=='football_team_full_game_winner':
      # SYNTHETIC complete negative response, below decoded/token/depth caps.
      return web.json_response(dict(events=[],padding='x'*1750000,ballast=[0]*85000))
     return web.json_response(dict(events=[]))
    return await super().rest(req)
  with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('Offline credentials forbidden')):
   f=Local();o=await f.boot(tmp)
   try:
    await f.start(duration=25)
    await f.wait(lambda:any(p['type']=='native_scope_discovery' and p['source']=='polymarket_us' for p in o.session.projection_rows) if hasattr(o.session,'projection_rows') else len([p for p,q in f.native_calls if p=='/v1/events'])>=6)
    await f.stop_route();self.assertTrue(o.session.cleanup_complete);self.assertNotIn('polymarket_us',o.session.discovery.source_stops)
    rows=reopen(o.session.journal.path)['rows'];bad=[r for r in rows if r['type']=='prediction_discovery_http' and r.get('delivery_reason')=='native_parse_expansion_cap'];self.assertEqual(len(bad),1);self.assertTrue(bad[0]['complete']);self.assertFalse(bad[0]['usable_metadata'])
    query=[(p,q) for p,q in f.native_calls if p=='/v1/events' and q.get('tagSlug')=='nfl' and q.get('sportsMarketTypes')=='football_team_full_game_winner'];self.assertEqual(len(query),1)
    self.assertTrue(any(p=='/v1/events' and q.get('tagSlug')=='nba' for p,q in f.native_calls));self.assertTrue(any(p.startswith('/trade-api/v2/') for p,q in f.native_calls));self.assertTrue(o.session.stop_event.is_set())
   finally:await f.close()

class RepairedRoutes(unittest.IsolatedAsyncioTestCase):
 async def test_raw_pair_details_informational_sizes_watch_download_reopening(self):
  from tests.test_v1_comparison import OrdinaryRoutes,prepared
  from unittest.mock import patch
  def revised():
   p=prepared();p.spec['v1_comparison_policy']=REPAIR_POLICY;return p
  # Explicit SYNTHETIC positive price control; never included in capture coverage.
  with patch('tests.test_v1_comparison.prepared',side_effect=revised):
   await OrdinaryRoutes.test_details_sizes_watch_download_and_fresh_reopening(self)

class EmptyResolutionIndex(unittest.TestCase):
 def test_exact_negative_fact_preserves_output_and_tampering_falls_back(self):
  import tempfile
  from hashlib import sha256
  from unittest.mock import patch
  from app.dashboard import session_history as history
  from app.collection.transport_session import ObservationJournal
  from app.dashboard.session_projection import stable
  from tests.test_session_projection import fixture
  with tempfile.TemporaryDirectory(dir=OUT) as tmp:
   root=Path(tmp);rows=fixture();sid=rows[0]['session_id'];folder=root/sid;(folder/'session').mkdir(parents=True)
   path=folder/'session'/(sid+'.jsonl');j=ObservationJournal(path)
   for row in rows:j.save(row)
   j.save(dict(type='session_finished',source='session',session_id=sid,observed_at=rows[-1]['observed_at'],reason='SYNTHETIC negative-history control'));j.close()
   (folder/'run-spec.json').write_text(json.dumps(rows[0]['spec']))
   expected=history.resolution_history(folder);self.assertEqual(expected,dict(records=[],options=[],state='complete'))
   entry=dict(session_id=sid,resolution_records=0,state='complete',files={str(p.relative_to(folder)):sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()})
   index=dict(version='retained-empty-resolutions-1',collection_authorized=False,entries={str(folder.relative_to(ROOT)):entry});index['sha256']=stable(index);ip=root/'SYNTHETIC-index.json';ip.write_text(json.dumps(index))
   with patch.object(history,'EMPTY_RESOLUTION_INDEX',ip):
    with patch.object(history,'verified',side_effect=AssertionError('No payload expansion needed for exact indexed zero')):self.assertEqual(history.resolution_history(folder),expected)
    with path.open('ab') as stream:stream.write(b'\n')
    self.assertIsNone(history._retained_empty_resolution(folder))
    with self.assertRaises(ValueError):history.resolution_history(folder)
