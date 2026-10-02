"""Manual comparison controls: missing economics, identity conflicts and stale data."""
from copy import deepcopy
from datetime import timedelta
import json,tempfile,unittest
from pathlib import Path
from app.collection.v1_comparison import bind,annotate,connect,admission,us_selectors,POLICY
from app.dashboard.session_projection import SessionProjection,stamp,stable
from app.normalization.comparison_identity import baseball,award
from tests.test_session_projection import fixture


def prepared():
 p=SessionProjection()
 for row in fixture():p.apply(row)
 p.spec['v1_comparison_policy']=POLICY
 for venue in ('kalshi','polymarket_us'):
  cat=p.inventory[venue];cat['events']=cat['events'][:1];cat['markets']=cat['markets'][:1]
  e=cat['events'][0];e['stage']='regular_season';m=cat['markets'][0]
  if venue=='kalshi':
   m['native_metadata']=dict(yes_sub_title='Buffalo',rules_primary='If Buffalo wins the listed game, then the market resolves to Yes.')
  else:
   # Synthetic explicit side identity, never claimed as provider coverage.
   raw=json.loads(p.metadata[(venue,e['id'],m['id'])]['market']['raw']['json_text'])
   native=deepcopy(raw['events'][0]['markets'][0]);native['sportsMarketType']='football_team_full_game_winner'
   for side in native['marketSides']:side['marketId']=m['id']
   m['native_metadata']=native
  for k,r in p.books.items():
   if k[0]==venue and k[1]==e['id']:
    r['book']['state']='active';r['book']['sync']='synchronized';r['book']['raw']['exchange_at']=r['book']['raw']['received_at']
    p.health[k]=dict(state='connected')
 p.last='2026-09-16T12:00:01+00:00'
 return p

class RawPolicy(unittest.TestCase):
 def test_all_retained_awards_have_raw_bindings_and_scoped_entrant_hashes(self):
  from app.collection.v1_comparison import award_entrant
  root=Path(__file__).resolve().parents[1]
  rows=json.loads((root/'evidence/v1-coverage-comparison-20261001-v1/derived-awards-32.json').read_text())
  self.assertEqual(len(rows),32)
  for row in rows:
   binding=row['raw_binding'];self.assertEqual(binding['status'],'BOUND_RAW_PREDICATE')
   self.assertEqual(binding['sha256'],stable({k:v for k,v in binding.items() if k!='sha256'}))
  entries=json.loads((root/'app/fixtures/manual-award-entrants-v1.json').read_text())['entries']
  for entry in entries:
   # A similar later contract cannot inherit the captured entrant binding.
   changed=dict(ticker=entry['market_id'],yes_sub_title=entry['native_label'],rules_primary=entry['native_rules_primary'],custom_strike=dict(football_team=entry['native_team_id']))
   self.assertIsNone(award_entrant(changed,dict(season=entry['season'],field=[entry['canonical_id']])))
 def test_account_probability_and_payout_table_not_admission_gates(self):
  p=prepared();s=p.snapshot();s['games']=[];s['points']={};s['rows_by_game']={};connect(p,s,p.last);self.assertTrue(s['manual_comparisons'])
  row=s['manual_comparisons'][0];self.assertIsNone(row['net']);self.assertIsNone(row['ev']);self.assertEqual(row['settlement_status'],'UNKNOWN')
  self.assertTrue(row['manual_binding']['sources'][0]['settlement']['terms']=={})
  self.assertTrue(row['raw_difference']);self.assertEqual(len(row['legs']),2)
  from app.dashboard.price_comparison import comparisons
  self.assertTrue(any(r.get('manual_raw') for r in comparisons(s,{})))
  from app.collection.v1_comparison import size_report
  result=size_report(s,next(g for g in s['games'] if g.get('manual_raw')),dict(session=row['session'],hash=p.sid,cutoff=s['durable_cursor'],sizes=['1']))
  self.assertTrue(all(l['notional'] is not None for l in result['sizes'][0]['legs']));self.assertIsNone(result['best'])
 def test_stale_inactive_wrong_game_and_changed_binding_reject(self):
  p=prepared();cat=p.inventory['kalshi'];b=bind(cat['events'][0],cat['markets'][0],'kalshi');book=deepcopy(p.books[('kalshi','kalshi-e0','kalshi-m0')]['book'])
  self.assertTrue(admission(b,book,p.last)[0])
  altered=deepcopy(b);altered['identity']['season']='2025';self.assertFalse(admission(altered,book,p.last)[0])
  book['raw']['ref']['market_id']='other';self.assertFalse(admission(b,book,p.last)[0])
  book=deepcopy(p.books[('kalshi','kalshi-e0','kalshi-m0')]['book']);book['state']='suspended';self.assertFalse(admission(b,book,p.last)[0])
  book['state']='active';self.assertFalse(admission(b,book,(stamp(p.last)+timedelta(seconds=16)).isoformat())[0])
 def test_missing_identity_and_unknown_us_keys_remain_blocked(self):
  p=prepared();e=p.inventory['kalshi']['events'][0];m=p.inventory['kalshi']['markets'][0]
  self.assertEqual(bind(dict(e,stage=None),m,'kalshi')['status'],'IDENTITY_BLOCKED')
  for sport,period in [('MLB','first_3'),('MLB','first_6'),('MLB','regulation_9'),('NHL','period_1')]:
   self.assertEqual(us_selectors(dict(sport=sport,period=period,family='moneyline')),[])
  self.assertTrue(us_selectors(dict(sport='NFL',period='first_half',family='moneyline'),123))
 def test_exact_baseball_and_award_keys_without_payout_history(self):
  game=dict(competition='MLB',season='2026',stage='regular_season',game_id='official-game',game_number=2,original_start='2026-09-30T19:00:00Z',scheduled_start='2026-09-30T19:00:00Z',schedule_status='original',home='MLB:NYY',away='MLB:BOS')
  self.assertNotEqual(baseball(game),baseball(dict(game,game_number=1)))
  with self.assertRaises(ValueError):baseball(dict(game,scheduled_start='2026-10-01T19:00:00Z'))
  self.assertTrue(baseball(dict(game,schedule_status='rescheduled',scheduled_start='2026-10-01T19:00:00Z')))
  a=dict(competition='NFL',season='2026',stage='championship',category='conference_champion',conference_id='AFC',award_id='official-AFC-championship')
  self.assertTrue(award(a,'NFL:BUF'))
  with self.assertRaises(ValueError):award(dict(a,conference_id=None),'NFL:BUF')

class OrdinaryRoutes(unittest.IsolatedAsyncioTestCase):
 async def test_details_sizes_watch_download_and_fresh_reopening(self):
  from app.collection.transport_session import ObservationJournal
  from app.dashboard.session_history import load
  from app.dashboard.multi_game_server import create_app
  from app.dashboard.opportunity_history import observations
  from tests.test_commercial_engineering import watch
  from aiohttp.test_utils import TestClient,TestServer
  from types import SimpleNamespace
  from urllib.parse import urlencode
  import subprocess,sys
  p=prepared();rows=fixture();rows[0]['spec']=p.spec
  # The control deliberately lacks optional selected settlement/fee metadata.
  rows=[rows[0],dict(rows[1],inventory=p.inventory)]
  for key,row in p.books.items():
   if key[0] in ('kalshi','polymarket_us') and key[1].endswith('e0'):
    rows.append(dict(type='source_health',source=key[0],session_id=p.sid,observed_at=row['observed_at'],state='connected',market_ids=[key[2]],stream_group=key[0]))
    rows.append(row)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/p.sid;folder.mkdir();journal=ObservationJournal(folder/(p.sid+'.jsonl'))
   for row in rows:journal.save(row)
   journal.close();s=load(folder);self.assertTrue(s['manual_comparisons']);g=next(g for g in s['games'] if g.get('manual_raw'))
   async def close():pass
   owner=SimpleNamespace(output=root,session=None,start_controls=frozenset(),close=close,status=lambda:dict(active=False),saved=lambda:[],active=lambda:False,history_paths=lambda:{p.sid:folder})
   client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=root/'watches.json')));await client.start_server()
   try:
    q=dict(session=p.sid+'~'+g['id'],hash=p.sid,cutoff=s['durable_cursor'],quantity='1')
    response=await client.get('/api/calculate?'+urlencode(q));self.assertEqual(response.status,200,await response.text());details=await response.json()
    self.assertTrue(details['comparisons'][0]['manual_raw']);self.assertIsNone(details['comparisons'][0]['net'])
    response=await client.get('/api/calculate?'+urlencode(dict(q,download='true')));self.assertEqual(await response.json(),details)
    response=await client.post('/api/decision-sizes',json=dict(session=q['session'],hash=q['hash'],cutoff=q['cutoff'],sizes=['1']),headers={'Origin':str(client.make_url('/')).rstrip('/')});self.assertEqual(response.status,200,await response.text());self.assertIsNone((await response.json())['best'])
    w=watch('raw_gap');w['threshold']='0';values=observations(s,w);self.assertTrue(values)
    code='import json,sys;from app.dashboard.session_history import load;from app.dashboard.price_comparison import comparisons;s=load(sys.argv[1]);print(json.dumps(comparisons(s,{}),sort_keys=True))'
    child=await __import__('asyncio').create_subprocess_exec(sys.executable,'-c',code,str(folder),stdout=__import__('asyncio').subprocess.PIPE,stderr=__import__('asyncio').subprocess.PIPE)
    out,err=await __import__('asyncio').wait_for(child.communicate(),20);self.assertEqual(child.returncode,0,err.decode())
    from app.dashboard.price_comparison import comparisons
    self.assertEqual(json.loads(out),comparisons(s,{}));self.assertEqual(observations(load(folder),w),values)
   finally:await client.close()
