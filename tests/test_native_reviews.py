"""Isolated synthetic review controls; retained regression remains a separate test."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from app.dashboard.native_reviews import DIRECTORY,validate
from app.dashboard.session_projection import stable,SessionProjection
from app.dashboard.session_history import load,project_rows
from app.dashboard.price_comparison import comparisons
from app.dashboard.decision_support import size_report
from tests.test_native_book_comparison import project,FOLDER,rows


def seal(b):
 b.pop('sha256',None);b['sha256']=stable(b);return b


def control():
 p=project();p.spec['mode']='mock';p.spec['native_discovery']={'slice':'ordinary-fixture'}
 b=json.loads((DIRECTORY/'retained-wku-nmsu-v1.json').read_text());b['evidence_mode']='synthetic';b['review_id']='ISOLATED-SYNTHETIC-A'
 for key,meta in p.metadata.items():meta['market']['raw']['kind']='synthetic'
 p.native_reviews={('A',1):seal(b)}
 return p,b


def add_event(p,b,tag='B',state='UNKNOWN'):
 b=deepcopy(b);b['review_id']='ISOLATED-SYNTHETIC-'+tag;b.pop('retained_research',None);b.pop('version',None);b['scope']='ISOLATED synthetic normal-winner correspondence; exceptional terms unknown'
 names={name:'SYNTHETIC '+tag+' '+name for name in b['participants'].values()}
 ids={i:'SYNTHETIC:'+tag+':'+i for i in b['participants']}
 b['participants']={ids[i]:names[n] for i,n in b['participants'].items()};b['event'][1]=sorted(ids.values())
 b['settlement_assessment']=dict(status=state,qualified=False,evidence=['ISOLATED fixture'],unknown=[dict(condition='No real qualification')])
 for venue,s in b['sources'].items():
  old=(venue,s['event_id'],s['market_id']);new=(venue,'SYNTHETIC-'+tag+'-'+s['event_id'],'SYNTHETIC-'+tag+'-'+s['market_id'])
  e=deepcopy(next(x for x in p.inventory[venue]['events'] if x['id']==s['event_id']));m=deepcopy(next(x for x in p.inventory[venue]['markets'] if x['id']==s['market_id']))
  e.update(id=new[1],canonical_key=b['event'],participants={n:i for i,n in b['participants'].items()});e['native_metadata']['ISOLATED_SYNTHETIC_EVENT']=tag
  m.update(id=new[2],event_id=new[1]);m['native_metadata']['ISOLATED_SYNTHETIC_MARKET']=tag
  for field in ('rules_primary','rules_secondary','description'):
   if field in m['native_metadata']:m['native_metadata'][field]='ISOLATED SYNTHETIC '+tag+' winner; exceptional terms unknown'
  p.inventory[venue]['events'].append(e);p.inventory[venue]['markets'].append(m);p.inventory[venue]['selection']['ids'].append(new[2])
  s.update(event_id=new[1],market_id=new[2],event_metadata_sha256=stable(e['native_metadata']),native_metadata_sha256=stable(m['native_metadata']),metadata=deepcopy(m['native_metadata']),orientation_evidence={'basis':'ISOLATED synthetic orientation'})
  meta=deepcopy(p.metadata[old]);meta['market']['raw']['ref']=dict(venue=venue,event_id=new[1],market_id=new[2]);meta['market']['raw']['json_text']=json.dumps({'ISOLATED_SYNTHETIC':tag,'event':e['native_metadata'],'market':m['native_metadata']});s['provenance']=[dict(body_sha256=sha256(meta['market']['raw']['json_text'].encode()).hexdigest(),basis='Isolated synthetic fixture')]
  p.metadata[new]=meta;p.books[new]=deepcopy(p.books[old]);p.books[new]['book']['raw']['ref']=deepcopy(meta['market']['raw']['ref']);p.health[new]=deepcopy(p.health.get(old,{}))
  for o in s['outcomes'].values():
   o['participant']=names[o['participant']]
   if o.get('normal_winner'):o['normal_winner']=names[o['normal_winner']]
  s['fee_review']=dict(status='UNKNOWN',model='none',evidence=['ISOLATED fixture'],reason='No fixture fee evidence')
 seal(b);p.native_reviews[(tag,1)]=b
 return b


class Reviews(unittest.TestCase):
 def setUp(self):
  for name in ('socket.socket.connect','app.collection.venue_access.load_credentials'):
   x=patch(name,side_effect=AssertionError('offline only'));x.start();self.addCleanup(x.stop)
 def test_multiple_concurrent_events_isolate_fees_and_settlement(self):
  p,b=control();other=add_event(p,b);v=p.snapshot(mode='saved');rs=comparisons(v,{'quantity':'100'})
  self.assertEqual(len(v['games']),2);self.assertEqual(len(rs),4)
  for r in rs:
   if r['game_title'].startswith('SYNTHETIC'):
    self.assertEqual(r['settlement_status'],'UNKNOWN');self.assertTrue(all(l['entry']['upper'] is None and 'conditional_fee_scenario' not in l['entry'] for l in r['legs']))
   else:self.assertEqual(r['settlement_status'],'INCOMPATIBLE');self.assertTrue(any(l['entry']['upper'] for l in r['legs']))
 def test_all_settlement_states_keep_raw_available(self):
  for state in ('UNKNOWN','CONDITIONAL','INCOMPATIBLE','SUPPORTED'):
   p,b=control();b['settlement_assessment']['status']=state;seal(b)
   rs=comparisons(p.snapshot(mode='saved'),{});self.assertEqual(len(rs),2);self.assertTrue(all(r['settlement_status']==state and r['net'] is None for r in rs))
 def test_missing_tampered_and_duplicate_reviews(self):
  p,b=control();p.native_reviews={};p.spec['native_review_records']=[];self.assertFalse(p.snapshot()['games'])
  p,b=control();b['participants']['NCAAF:NCAA472']='tampered';v=p.snapshot();self.assertFalse(v['games']);self.assertTrue(v['native_comparison_review']['errors'])
  p,b=control();p.native_reviews['duplicate']=deepcopy(b);self.assertFalse(p.snapshot()['games'])
  p,b=control();p.native_reviews['revision']=seal(dict(deepcopy(b),revision=2));self.assertFalse(p.snapshot()['games'])
 def test_changed_metadata_and_conflicting_ids_isolate_other_event(self):
  for field in ('metadata','duplicate','scope','participants','outcomes','provenance'):
   p,b=control();add_event(p,b);s=b['sources']['kalshi'];m=next(x for x in p.inventory['kalshi']['markets'] if x['id']==s['market_id'])
   if field=='metadata':m['native_metadata']['title']='later knowledge'
   elif field=='duplicate':p.inventory['kalshi']['markets'].append(deepcopy(m))
   elif field=='scope':m['period']='first_half'
   elif field=='participants':next(x for x in p.inventory['kalshi']['events'] if x['id']==s['event_id'])['participants']={}
   elif field=='outcomes':m['sides'][0]['id']='conflict'
   else:p.metadata[('kalshi',s['event_id'],s['market_id'])]['market']['raw']['json_text']='{}'
   v=p.snapshot();self.assertEqual(len(v['games']),1,field);self.assertTrue(v['games'][0]['title'].startswith('SYNTHETIC'))
 def test_fee_interval_coefficient_minimum_and_fractional(self):
  p,b=control();f=b['sources']['polymarket_us']['fee_review'];f.update(coefficient='0.02',minimum_quantity='2');seal(b)
  rs=comparisons(p.snapshot(),{'quantity':'100'});u=next(x for x in rs[0]['legs'] if x['venue']=='polymarket_us');self.assertEqual(u['entry']['audit']['coefficient'],'0.02')
  self.assertIsNone(next(x for x in comparisons(p.snapshot(),{'quantity':'1'})[0]['legs'] if x['venue']=='polymarket_us')['entry']['upper'])
  f['applicability']=dict(b['applicability'],end='2026-09-30T14:51:51+00:00');seal(b)
  u=next(x for x in comparisons(p.snapshot(),{})[0]['legs'] if x['venue']=='polymarket_us');self.assertIsNone(u['entry']['upper']);self.assertIn('effective interval',u['entry']['reason'])
  f.pop('applicability')
  for state in ('UNKNOWN','CONDITIONAL','INCOMPATIBLE','SUPPORTED'):
   f['status']=state;seal(b);u=next(x for x in comparisons(p.snapshot(),{})[0]['legs'] if x['venue']=='polymarket_us')
   self.assertEqual(u['entry']['fee_status'],state);self.assertEqual(u['entry']['upper'] is not None,state=='SUPPORTED')
 def test_outcome_orientation_is_review_owned(self):
  p,b=control();source=b['sources']['kalshi'];s=source['outcomes'];s['yes']['participant']='Western Kentucky';s['yes']['normal_winner']='Western Kentucky';s['no']['participant']='Western Kentucky';s['no']['normal_winner']='New Mexico State'
  m=next(m for m in p.inventory['kalshi']['markets'] if m['id']==source['market_id']);m['native_metadata']['rules_primary']='ISOLATED reversed fixture: YES is Western Kentucky winner'
  source['orientation_evidence']={'basis':'ISOLATED reversed fixture contract'};source['native_metadata_sha256']=stable(m['native_metadata']);source['metadata']=deepcopy(m['native_metadata'])
  meta=p.metadata[('kalshi',source['event_id'],source['market_id'])];meta['market']['raw']['json_text']=json.dumps({'ISOLATED_REVERSED':m['native_metadata']});source['provenance']=[dict(body_sha256=sha256(meta['market']['raw']['json_text'].encode()).hexdigest(),basis='ISOLATED reversed fixture')];b['revision']=2;seal(b)
  r=next(x for x in comparisons(p.snapshot(),{}) if x['outcome']=='Western Kentucky');self.assertEqual(next(x for x in r['legs'] if x['venue']=='kalshi')['side'],'yes')
 def test_synthetic_records_cannot_connect_real_sessions(self):
  p,b=control();p.spec['mode']='real';self.assertFalse(p.snapshot()['games'])
 def test_frozen_calculation_does_not_reread_review(self):
  p,b=control();v=p.snapshot();before=comparisons(v,{});b['sources']['polymarket_us']['fee_review']['coefficient']='0.99';seal(b)
  with patch('app.dashboard.native_reviews.DIRECTORY',Path('/missing')):self.assertEqual(before,comparisons(v,{}))
 def test_ordinary_preflight_accepts_review_records_and_rejects_tampering(self):
  from app.collection.run_spec import preflight
  from app.dashboard.coverage_owner import spec
  p,b=control();s=spec();s.update(mode='mock',native_review_records=[b]);self.assertTrue(preflight(s)['valid'],preflight(s))
  s['native_review_records'][0]['revision']=99;self.assertFalse(preflight(s)['valid'])
 def test_immutable_journal_reviews_and_selected_spec(self):
  p,b=control();rr=rows();rr=deepcopy(rr);rr[0]['spec'].update(mode='mock',native_review_records=[b])
  for row in rr:
   if row['type']=='market_selected':row['market']['raw']['kind']='synthetic'
  v=project_rows(rr);self.assertEqual(len(v['games']),1)
  r=SessionProjection();r.apply(rr[0]);record=dict(type='native_review',session_id=r.sid,observed_at=rr[0]['observed_at'],review=b)
  with self.assertRaisesRegex(ValueError,'rewritten'):r.apply(record)
 def test_versioned_original_and_sealed_reopening(self):
  self.assertFalse(load(FOLDER,native_interpretation='original')['games'])
  self.assertEqual(stable(load(FOLDER,native_interpretation='original')),'ec133aca72d787fd9d9d0d124370e964385e6ac3083f5cd5215b9b26e4075db4')
  self.assertEqual(stable(load(FOLDER,native_interpretation='native-book-comparison-2')),'fce68c3545983d2a87381eadef9ceca39f2ced83017f7dffd23750901d88343c')
  old=load(FOLDER,native_interpretation='native-book-comparison-2');self.assertEqual(old['games'][0]['native_review']['version'],'native-book-comparison-2')
  self.assertEqual(stable(load(FOLDER,native_interpretation='native-book-comparison-3')),'a6b63fe28c401db2607770c5ea32afd908971fa5ad555bba3fe8011d90c76e78')
  new=load(FOLDER);self.assertEqual(new['games'][0]['native_review']['version'],'native-book-comparison-4')
 def test_unsupported_structure_has_precise_exclusion(self):
  p,b=control();b['identity']['family']='player_prop';seal(b);v=p.snapshot();self.assertFalse(v['games']);self.assertIn('Unsupported native market family',str(v['native_comparison_review']['errors']))
 def test_missing_economic_judgment_keeps_raw_correspondence(self):
  p,b=control();b['sources']['polymarket_us'].pop('fee_review');b['settlement_assessment']=dict(status='UNKNOWN',qualified=False,evidence=[],unknown=[]);seal(b)
  r=comparisons(p.snapshot(),{})[0];self.assertEqual(r['settlement_status'],'UNKNOWN');self.assertTrue(r['raw_difference'] is not None)
  self.assertIsNone(next(x for x in r['legs'] if x['venue']=='polymarket_us')['entry']['upper'])
 def test_two_markets_in_one_event_keep_distinct_reviews(self):
  p,b=control();other=add_event(p,b)
  other['event']=deepcopy(b['event']);other['participants']=deepcopy(b['participants'])
  for venue,source in other['sources'].items():
   old=b['sources'][venue];new_event=source['event_id'];source['event_id']=old['event_id'];source['event_metadata_sha256']=old['event_metadata_sha256'];source['outcomes']=deepcopy(old['outcomes'])
   p.inventory[venue]['events']=[e for e in p.inventory[venue]['events'] if e['id']!=new_event]
   m=next(m for m in p.inventory[venue]['markets'] if m['id']==source['market_id']);m['event_id']=old['event_id']
   key=(venue,new_event,source['market_id']);new=(venue,old['event_id'],source['market_id'])
   p.metadata[new]=p.metadata.pop(key);p.books[new]=p.books.pop(key);p.metadata[new]['market']['raw']['ref']['event_id']=old['event_id'];p.books[new]['book']['raw']['ref']['event_id']=old['event_id']
  seal(other);v=p.snapshot();self.assertEqual(len(v['games']),2)
  rs=comparisons(v,{});self.assertEqual(len(rs),2);self.assertTrue(all(len(r['alternatives'])==1 for r in rs));self.assertEqual(len({r['native_review']['binding_sha256'] for r in rs for r in [r,*r['alternatives']]}),2)
 def test_concurrent_reviews_use_shared_sizes(self):
  p,b=control();add_event(p,b);v=p.snapshot()
  for g in v['games']:
   r=size_report(v,g,{'sizes':['1','100']});self.assertIsNone(r['best']);self.assertEqual(len(r['sizes']),2)



def concurrent_rows():
 p,b=control();add_event(p,b)
 original=rows();start=deepcopy(original[0]);start['spec'].update(mode='mock',native_review_records=list(p.native_reviews.values()))
 inventory=deepcopy(next(x for x in original if x['type']=='coverage_inventory'));inventory['inventory']=p.inventory
 result=[start,inventory]
 for meta in p.metadata.values():result.append(deepcopy(meta))
 for book in p.books.values():result.append(deepcopy(book))
 result.append(deepcopy(original[-1]))
 return result


class ConcurrentRoutes(unittest.IsolatedAsyncioTestCase):
 async def test_feed_details_sizes_watch_history_and_download(self):
  import socket,tempfile
  from aiohttp.test_utils import TestClient,TestServer
  from app.dashboard.coverage_owner import CoverageOwner
  from app.dashboard.multi_game_server import create_app
  from app.dashboard.opportunity_history import WatchStore
  from tests.test_native_book_comparison import SID,watch
  rr=concurrent_rows();v=project_rows(rr);self.assertEqual(len(v['games']),2)
  original=socket.socket.connect
  def local(sock,address):
   if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):raise AssertionError('external network prohibited')
   return original(sock,address)
  with tempfile.TemporaryDirectory() as d,patch('socket.socket.connect',local),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no credentials')),patch('app.dashboard.session_history.verified',side_effect=lambda folder:dict(rows=deepcopy(rr),state='complete')):
   p=Path(d);owner=CoverageOwner(p/'saved',pilot_output=p/'unused',product_mode=True);owner.history_paths=lambda:{SID:p/SID}
   w=p/'watch.json';WatchStore(w).save([{k:v for k,v in watch().items() if k!='id'}])
   async with TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=w))) as client:
    response=await client.get('/api/dashboard',params={'view':'feed','capture':SID});self.assertEqual(response.status,200);data=await response.json();self.assertEqual(len(data['comparisons']),4)
    for r in data['comparisons']:
     q={k:r[k] for k in ('session','hash','cutoff')}
     response=await client.get('/api/calculate',params=q);self.assertEqual(response.status,200);detail=await response.json();self.assertTrue(detail['native_raw'])
     response=await client.get('/api/calculate',params=dict(q,download='true'));self.assertEqual(response.status,200);self.assertEqual(await response.json(),detail)
     response=await client.post('/api/decision-sizes',headers={'Origin':str(client.make_url('')).rstrip('/')},json=dict(q,sizes=['1','100']));self.assertEqual(response.status,200);self.assertIsNone((await response.json())['best'])
    response=await client.get('/api/opportunity-history',params={'capture':SID,'download':'true'});self.assertEqual(response.status,200);history=await response.json();self.assertFalse(history['events']);self.assertEqual(len(history['items']),4)


def reviewed_scope_fixture(rr):
 """Explicit test-only annotation of existing 63-cell fixtures; never provider evidence."""
 from app.normalization.score_lines import descriptor
 p=SessionProjection()
 for row in rr:p.apply(row)
 v=p.snapshot();g=next(g for g in v['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
 ident=deepcopy(g['product_identity']);ident.pop('rules',None)
 sources={};event=None;normalized=None;participants=None
 for venue in ('kalshi','polymarket_us'):
  ids=g['sources'][venue];e=next(e for e in p.inventory[venue]['events'] if e['id']==ids['event_id']);m=next(m for m in p.inventory[venue]['markets'] if m['id']==ids['market_id'])
  key=(venue,e['id'],m['id']);meta=p.metadata[key];raw=meta['market']['raw']
  e['native_metadata']=dict(ISOLATED_SYNTHETIC_EVENT=deepcopy(e));m['native_metadata']=dict(ISOLATED_SYNTHETIC_MARKET=deepcopy(m))
  p.inventory[venue]['selection']={'ids':[m['id']]}
  event=e['canonical_key'];normalized=deepcopy(e)
  participants=dict(zip(sorted(e.get('participants',{}).values() or e['field']),sorted(g['teams'])))
  outcomes={x['native_id']:deepcopy(x) for k,x in g['sides'].items() if k.startswith(venue+':')}
  source=dict(event_id=e['id'],market_id=m['id'],event_metadata_sha256=stable(e['native_metadata']),native_metadata_sha256=stable(m['native_metadata']),outcomes=outcomes,metadata=m['native_metadata'],provenance=[dict(body_sha256=sha256(raw['json_text'].encode()).hexdigest(),basis='ISOLATED 63-cell synthetic control')],orientation_evidence={'basis':'Existing synthetic normalized descriptor'},fee_review=dict(status='UNKNOWN',evidence=[],model='none'))
  if g.get('score_reviews'):
   d=deepcopy(m['score_review']['descriptor']);canonical=descriptor(e,d);source['descriptor']=d
   for side in d['outcomes']:
    outcomes[side['native_id']]['comparison_outcome']=stable(dict(canonical,operator=outcomes[side['native_id']].get('operator'),role=side.get('role'),participant=d.get('participant') if d['family']=='futures' else None))
  sources[venue]=source
 b=dict(schema='native-review-1',review_id='ISOLATED-63-'+stable(ident),revision=1,evidence_mode='synthetic',identity=ident,event=event,participants=participants,normalized_event=normalized,sources=sources,applicability=dict(status='SUPPORTED',start='2020-01-01T00:00:00+00:00',end='2030-01-01T00:00:00+00:00',basis='Isolated synthetic test interval'),settlement_assessment=dict(status='UNKNOWN',qualified=False,evidence=[],unknown=[]))
 seal(b);p.native_reviews={'fixture':b};return p


class ScopeRecords(unittest.TestCase):
 def test_all_63_cells_use_existing_descriptors_and_math(self):
  from tests.test_full_scope_engineering import cases
  seen=[]
  with patch('socket.socket.connect',side_effect=AssertionError('offline')),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no credentials')):
   for cell,rr in cases():
    p=reviewed_scope_fixture(rr);v=p.snapshot();raw=[g for g in v['games'] if g.get('native_raw')]
    self.assertEqual(len(raw),1,(cell,v['native_comparison_review']))
    rs=[r for r in comparisons(v,{}) if r.get('native_raw')];self.assertTrue(rs,cell);self.assertTrue(all(r['net'] is None for r in rs))
    seen.append(cell)
  self.assertEqual(len(seen),63)

if __name__=='__main__':unittest.main()
