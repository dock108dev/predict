"""Material public rules exercised on ordinary Details/calculation/scenario routes."""
import json,tempfile,unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from copy import deepcopy
from aiohttp.test_utils import TestClient,TestServer
from app.collection.transport_session import ObservationJournal
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load
from app.dashboard.math_scenarios import replay
from app.collection import public_contracts as pc
from tests.test_nfl_resolution import fixture
from tests.test_futures import fixture as futures_fixture
from tests.test_public_contracts import binding
from app.fee_example import scenario

class BindingRoutes(unittest.IsolatedAsyncioTestCase):
 async def test_strict_score_identity_shared_award_effective_fractional_fees_and_probability_gates(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);paths={};snapshots=[]
   rows,_,_,event=fixture('total','first_half','20')
   for n,records in enumerate((rows,futures_fixture(overlap=True,unknown=True))):
    sid='SYNTHETIC-public-edge-'+str(n);folder=root/sid;folder.mkdir();j=ObservationJournal(folder/(sid+'.jsonl'))
    for row in deepcopy(records):row['session_id']=sid;j.save(row)
    j.close();paths[sid]=folder;snapshots.append(load(folder))
   async def close():pass
   owner=SimpleNamespace(output=root,session=None,start_controls=frozenset(),close=close,status=lambda:dict(active=False),saved=lambda:[],active=lambda:False,history_paths=lambda:paths)
   c=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=root/'watches.json')));await c.start_server();origin=str(c.make_url('')).rstrip('/')
   async def get(path):
    r=await c.get(path);self.assertEqual(r.status,200,await r.text());return await r.json()
   async def compute(snapshot,game,req,status=200):
    body=dict(session=snapshot['session_id']+'~'+game['id'],hash=snapshot['session_id'],cutoff=snapshot['durable_cursor'],public_contract=req)
    r=await c.post('/api/math-scenario',json=body,headers={'Origin':origin});self.assertEqual(r.status,status,await r.text());value=await r.json()
    if status==200:self.assertEqual(replay(value),value);self.assertEqual(await get('/api/math-scenario-download?sha256='+value['sha256']),value)
    return value
   try:
    registry=await get('/api/public-contracts?download=true')
    self.assertEqual(registry['registry_sha256'],pc.load()['sha256']);self.assertEqual(len(registry['ncaab_membership']['members']),365)
    self.assertEqual(next(e for e in registry['events'] if e['competition']=='NBA')['stage'],'preseason')
    self.assertTrue(any(e['conflicts'] for e in registry['events'] if e['competition']=='NHL'))
    self.assertTrue(any('ENTITYOUTCOME' in e['clause'] for e in registry['sources'].values()))
    s=snapshots[0];g=s['games'][0]
    req=dict(version=pc.VERSION,kind='score',binding=binding('KXNFL1HTOTAL'),event=event,native=dict(rules_primary='If Buffalo and Detroit collectively score more than 20 points in the 1st half of their game, then the market resolves to Yes.',strike_type='greater',floor_strike=20,cap_strike=None),scores=[dict(period='first_half',completed=True,home=10,away=10),dict(period='first_half',completed=True,home=14,away=7)])
    value=await compute(s,g,req);states=value['public_contract_calculation']['states'];self.assertEqual(states[0]['payouts'],{'yes':'0','no':'1'});self.assertEqual(states[1]['payouts'],{'yes':'1','no':'0'})
    bad=deepcopy(req);bad['event']['game_id']='SYNTHETIC-other';await compute(s,g,bad,422)
    bad=deepcopy(req);bad['native']['floor_strike']=21;bad['native']['rules_primary']=bad['native']['rules_primary'].replace('20','21');await compute(s,g,bad,422)
    original=await get('/api/calculate?'+urlencode(dict(session=s['session_id']+'~'+g['id'],hash=s['session_id'],cutoff=s['durable_cursor'])));self.assertIsNone(original['ev']['expected_profit'])
    fs=snapshots[1];fg=fs['games'][0];calc=await get('/api/calculate?'+urlencode(dict(session=fs['session_id']+'~'+fg['id'],hash=fs['session_id'],cutoff=fs['durable_cursor'])));self.assertTrue(any(p['id']=='shared' for p in calc['score_partitions']));self.assertTrue(all(v['profit'] is None for v in calc['candidates']));self.assertIsNone(calc['ev']['expected_profit'])
    for snapshot,game in [(s,g),(fs,fg)]:
     url='/api/public-contracts?'+urlencode(dict(capture=snapshot['session_id'],cutoff=snapshot['durable_cursor'],game=game['id']));self.assertEqual(await get(url),await get(url+'&download=true'))
    # Every number below is an explicit scenario input; unknown branches remain unknown.
    for pay,expected in [('0.5','10'),('0.4','0'),('0.33','-7'),(None,None)]:
     req=dict(version=pc.VERSION,kind='portfolio',states=['tie'],complete=True,legs=[dict(cash='40',receipts={'tie':None if pay is None else str(Decimal(pay)*100)})])
     audit=(await compute(s,g,req))['public_contract_calculation']['calculation']
     if pay is None:self.assertFalse(audit['mathematical_arbitrage'])
     else:self.assertEqual(Decimal(audit['states']['tie']),Decimal(expected))
     self.assertIsNone(audit['expected_net'])
    for at,coefficient in [('2026-10-01T13:59:59Z','0.04'),('2026-10-01T14:00:00Z','0.06')]:
     context=scenario('polymarket_us',quantity='3.12');context['product']='combo_contract';context['market_id']=g['sources']['polymarket_us']['market_id'];context['trade_time']=context['calculation_time']=at
     req=dict(version=pc.VERSION,kind='fees',context=context,market=dict(id=context['market_id'],isCombo=True),instrument=dict(market_id=context['market_id'],fractionalQtyScale='100',source='SYNTHETIC selected combo association'))
     audit=(await compute(s,g,req))['public_contract_calculation']['fee_audit'];self.assertEqual(audit['schedule']['combo_coefficient'],coefficient)
    ev=await compute(s,g,dict(version=pc.VERSION,kind='portfolio',states=['A','B'],complete=True,legs=[dict(cash='.4',receipts={'A':'1','B':'0'})],probabilities={'A':'.6','B':'.4'}))
    self.assertEqual(Decimal(ev['public_contract_calculation']['calculation']['expected_net']),Decimal('.2'))
    unknown=await compute(s,g,dict(version=pc.VERSION,kind='portfolio',states=['A','exception'],complete=True,legs=[dict(cash='.4',receipts={'A':'1','exception':None})],probabilities={'A':'1','exception':'0'}))
    self.assertIsNone(unknown['public_contract_calculation']['calculation']['worst_case_return']);self.assertIsNone(unknown['public_contract_calculation']['calculation']['expected_net'])
   finally:await c.close()
