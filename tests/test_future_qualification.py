import hashlib,json,unittest,subprocess,sys,tempfile
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from app.dashboard.future_qualification import evaluate,proof,VERSION
AT='2026-09-23T15:00:10+00:00'
def inputs():
 cards=[];contexts={}
 for i in range(2):
  key=str(i);scope=dict(venue=('kalshi' if i==0 else 'polymarket_us'),event_id='event',market_id=key)
  cards.append(dict(book=dict(id=key,source_at='2026-09-23T15:00:09+00:00',received_at='2026-09-23T15:00:09.2+00:00',native_qualification_scope=scope,connection_epoch='epoch1',sync='synchronized',market_state='active'),age_seconds='0.8',connection='connected'))
  documents={kind:dict(kind=kind,scope=scope,source_kind='native_document',review_status='reviewed',conflict=False,supported=True,url='https://example.test/document',retained_text='offline test claim',sha256=hashlib.sha256(b'offline test claim').hexdigest(),passage='test claim',effective_from='2026-09-23T00:00:00+00:00',effective_to='2026-09-24T00:00:00+00:00',retrieved_at=AT,precedence='explicit test only') for kind in ('state_semantics','timestamp_semantics','fees','settlement')}
  raw=dict(raw_text='offline observation',raw_sha256=hashlib.sha256(b'offline observation').hexdigest())
  contexts[key]=dict(scope=scope,documents=documents,connection_epoch='epoch1',source_timestamp_meaning='book_state_as_of',source_time_progress_verified=True,
   state=dict(**raw,value='active',book_id=key,source_kind='native_observation',connection_epoch='epoch1',continuity_verified=True,observed_at='2026-09-23T15:00:09+00:00',valid_from='2026-09-23T15:00:09+00:00',valid_until=AT),
   clock=dict(**raw,kind='bounded_relative_clock',offset_min_seconds='-0.1',offset_max_seconds='0.1',connection_epoch='epoch1',local_clock_continuity_verified=True,valid_from='2026-09-23T15:00:00+00:00',valid_until=AT))
 return dict(at=AT,cards=cards),contexts
class FutureTests(unittest.TestCase):
 def test_supported_fixture_and_unknown_fields(self):
  p,c=inputs();self.assertTrue(evaluate(p,c)['prerequisites_supported'])
  for field in ('state','clock','documents','scope','source_timestamp_meaning','source_time_progress_verified'):
   x=deepcopy(c);x['0'].pop(field)
   self.assertFalse(evaluate(p,x)['prerequisites_supported'],field)
 def test_state_expiry_reconnect_halt_and_tampering(self):
  p,c=inputs()
  for field,value in [('valid_until','2026-09-23T15:00:09+00:00'),('observed_at','2026-09-23T15:00:11+00:00'),('continuity_verified',False),('connection_epoch','old'),('raw_sha256','wrong'),('value','unknown')]:
   x=deepcopy(c);x['0']['state'][field]=value;self.assertFalse(evaluate(p,x)['prerequisites_supported'])
  for field,value in [('market_state','closed'),('sync','unsynchronized'),('connection_epoch','new')]:
   x=deepcopy(p);x['cards'][0]['book'][field]=value;self.assertFalse(evaluate(x,c)['prerequisites_supported'])
 def test_receipt_and_source_age_thresholds_not_relaxed(self):
  p,c=inputs()
  for age in ('15.000001','-0.1',None,'NaN'):
   x=deepcopy(p);x['cards'][0]['age_seconds']=age;self.assertFalse(evaluate(x,c)['prerequisites_supported'])
  p['cards'][0]['book']['source_at']='2026-09-23T14:59:55+00:00'
  self.assertIn('Source age interval fails 15-second freshness limit',evaluate(p,c)['reasons'])
 def test_worst_case_skew_and_unsupported_timestamp(self):
  p,c=inputs();c['0']['source_timestamp_meaning']='message_sent_at'
  self.assertFalse(evaluate(p,c)['prerequisites_supported'])
  p,c=inputs();p['cards'][0]['book']['source_at']='2026-09-23T15:00:04+00:00'
  self.assertIn('Worst-case source alignment exceeds 5 seconds',evaluate(p,c)['reasons'])
 def test_conflict_fixture_and_current_only_docs_cannot_qualify(self):
  p,c=inputs()
  for field,value in [('conflict',True),('source_kind','fixture'),('sha256','wrong'),('effective_from','2026-09-24T00:00:00+00:00'),('effective_to','2026-09-23T15:00:10+00:00'),('effective_from',None),('scope',{})]:
   x=deepcopy(c);x['0']['documents']['fees'][field]=value;self.assertFalse(evaluate(p,x)['prerequisites_supported'])
 def test_shared_saved_projection_future_veto_and_fresh_process(self):
  from tests.test_session_projection import fixture
  from app.dashboard.session_projection import SessionProjection
  from app.dashboard.product_view import calculate
  rows=fixture();rows[0]['spec']['future_qualification_policy']=VERSION
  def project(rs):
   p=SessionProjection()
   for r in rs:p.apply(r)
   s=p.snapshot();return [calculate(s,g,{}) for g in s['games']]
  result=project(rows)
  self.assertTrue(result)
  for r in result:
   self.assertFalse(r['future_qualification']['prerequisites_supported'])
   self.assertTrue(all(x['profit'] is None and not x['current_executable'] for x in r['candidates']))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'rows.json';path.write_text(json.dumps(rows))
   code='from app.dashboard.session_projection import SessionProjection;from app.dashboard.product_view import calculate;import json,sys;p=SessionProjection();[p.apply(r) for r in json.load(open(sys.argv[1]))];s=p.snapshot();print(json.dumps([calculate(s,g,{}) for g in s["games"]]))'
   got=subprocess.check_output([sys.executable,'-c',code,str(path)],text=True)
   self.assertEqual(json.loads(got),json.loads(json.dumps(result)))
 def test_context_journal_rewrite_and_bound(self):
  from app.dashboard.session_projection import SessionProjection
  p=SessionProjection();p.apply(dict(type='session_started',session_id='t',observed_at=AT,spec={'future_qualification_policy':VERSION}))
  row=dict(type='qualification_context',session_id='t',observed_at=AT,context={'book_id':'b'})
  p.apply(row)
  with self.assertRaisesRegex(ValueError,'rewritten'):p.apply(row)
class PrecisionTests(unittest.TestCase):
 def test_two_documented_grids_bound_known_fill_scenarios_only(self):
  from app.fee_example import scenario
  from app.fees.precision_envelope import calculate_envelope
  from app.fees import calculate
  from decimal import Decimal
  c=scenario('kalshi',price='0.055',quantity='1');c.pop('balance_precision',None)
  self.assertFalse(calculate_envelope(c)['available'])
  bound=calculate_envelope(c,execution_split_known=True);self.assertTrue(bound['available'])
  for grid in ('0.0001','0.01'):
   audit=calculate(dict(c,balance_precision=grid));fee=Decimal(audit['entry_balance_debit'])-Decimal(audit['entry_notional'])
   self.assertLessEqual(Decimal(bound['lower']),fee);self.assertGreaterEqual(Decimal(bound['upper']),fee)
  c.pop('kalshi_metadata');self.assertFalse(calculate_envelope(c,execution_split_known=True)['available'])

class EpochTests(unittest.TestCase):
 def test_subscription_epoch_stamped_before_durable_emission(self):
  from app.collection.continuous import Venue
  from types import SimpleNamespace
  emitted=[]
  def record(source,row):emitted.append(row);return False
  venue=Venue.__new__(Venue)
  venue.session=SimpleNamespace(spec={'future_qualification_policy':VERSION},segmented_history=True,counts={'durably_acknowledged':0},emit=record)
  venue.groups={'g':{}}
  for typ in ('prediction_command','prediction_frame','prediction_command','prediction_frame'):
   venue.emit('g','kalshi',{'type':typ})
  self.assertEqual([r['connection_epoch'] for r in emitted],['g:1','g:1','g:2','g:2'])

class ClockBoundaryTests(unittest.TestCase):
 def test_clock_conflict_expiry_and_exact_threshold(self):
  p,c=inputs()
  for key,value in [('offset_min_seconds','NaN'),('offset_min_seconds','1'),('valid_until','2026-09-23T15:00:09+00:00'),('raw_sha256','bad'),('local_clock_continuity_verified',False),('kind','http_date'),('valid_from','2026-09-23T15:00:09+00:00')]:
   x=deepcopy(c);x['0']['clock'][key]=value;self.assertFalse(evaluate(p,x)['prerequisites_supported'],key)
  for card in p['cards']:
   card['book']['source_at']=card['book']['received_at']='2026-09-23T14:59:55+00:00';card['age_seconds']='15'
  for value in c.values():
   value['clock'].update(offset_min_seconds='0',offset_max_seconds='0',valid_from='2026-09-23T14:59:00+00:00')
  self.assertTrue(evaluate(p,c)['prerequisites_supported'])
