"""Bounded book slice; retained source bytes and explicit protocol mutations only."""
import asyncio, base64, json, unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app.collection import native_books as books, coverage
from app.collection.continuous import Discovery, select_inventory
from app.collection.run_spec import preflight
from app.collection.native_semantics import purchase_book
from app.adapters.kalshi_stream import BookReconstructor, RecoveryRequired
from app.adapters.polymarket_us_stream import MarketStream, StaleSubscriptionFrame
from app.adapters import kalshi, polymarket_us
from app.models.core import BookSync, ReceiptFreshness
from dataclasses import replace
from tests.native_books_rehearsal import PAGES, ROOT

def spec():return json.loads((ROOT/'evidence/native-books-20260930/run-spec.json').read_text())
def at():return datetime.fromisoformat(PAGES[0]['params']['startTimeMin'])-timedelta(minutes=5)
def cats():return {v:coverage.catalog(PAGES,v,at()) for v in books.CAPS}
def markets():
 d=Discovery(SimpleNamespace(spec=spec()));d.pages=PAGES
 c,m=d.project();return m

def kengine():return BookReconstructor([markets()['kalshi']['KXNCAAFGAME-26OCT01WKUNMSU-NMSU']])
def ksnapshot(seq=1,**kw):return json.dumps(dict(type='orderbook_snapshot',sid=1,seq=seq,msg=dict(market_ticker='KXNCAAFGAME-26OCT01WKUNMSU-NMSU',market_id='OFFLINE-id',yes_dollars_fp=[['0.4000','10.00']],no_dollars_fp=[['0.5000','20.00']],**kw)))
def ack(e):e.begin(1);e.feed(json.dumps(dict(id=1,type='subscribed',msg=dict(channel='orderbook_delta',sid=1))),e.generation,at())
def pengine():return MarketStream([markets()['polymarket_us']['932924']],None)
def pmessage(px='0.40',qty='10.00',**kw):return json.dumps(dict(requestId='r',subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(marketSlug='aec-cfb-wkent-nmxst-2026-10-01',bids=[dict(px=dict(value=px,currency='USD'),qty=qty)],offers=[dict(px=dict(value='0.55',currency='USD'),qty='20.00')],transactTime='2026-09-30T10:00:00Z',**kw)))
class Selection(unittest.TestCase):
 def test_exact_spec_and_mutation_refusals(self):
  self.assertTrue(preflight(spec())['valid'])
  for change in (lambda s:s['native_discovery'].update(events_per_venue=2),lambda s:s['native_discovery'].update(acquisition_sports=['NBA']),lambda s:s['prediction'].update(connections=3),lambda s:s['sources']['kalshi'].update(credential_reference='other'),lambda s:s['assessment_revisions'].update(fees='assumed'),lambda s:s.update(reference_enabled=True)):
   s=spec();change(s);self.assertFalse(preflight(s)['valid'])
 def test_common_event_preferred_from_complete_listings(self):
  chosen,basis=books.choices(cats(),at());self.assertEqual(basis,'evidenced_common_event_only');self.assertEqual(chosen['polymarket_us']['id'],'116584')
 def test_independent_operation_when_no_common_event(self):
  c=cats();c['kalshi']['events']=[e for e in c['kalshi']['events'] if 'WKUNMSU' not in e['id']]
  chosen,basis=books.choices(c,at());self.assertEqual(set(chosen),set(books.CAPS));self.assertEqual(basis,'independent_events')
 def test_missing_source_does_not_block_other(self):
  c=cats();c['polymarket_us']['events']=[];chosen,basis=books.choices(c,at());self.assertEqual(set(chosen),{'kalshi'})
 def test_start_time_reresolves_and_excludes_historical_selection(self):
  chosen,basis=books.choices(cats(),datetime(2026,10,3,tzinfo=timezone.utc));self.assertFalse(chosen)
 def test_embedded_identity_is_sufficient_no_detail_gate(self):
  c=coverage.catalog([p for p in PAGES if p['path'].endswith('/events')],'polymarket_us',at());ids,_=select_inventory(c,at());self.assertIn('932924',ids)
  m=next(m for m in c['markets'] if m['id']=='932924');self.assertIsNone(m['subscription_evidence_exclusion'])
 def test_one_market_admission_survives_reconciliation(self):
  d=Discovery(SimpleNamespace(spec=spec()));d.pages=PAGES;d.book_market_ids={'kalshi':['KXNCAAFGAME-26OCT01WKUNMSU-NMSU'],'polymarket_us':['932924']}
  c,_=d.project()
  for v in books.CAPS:self.assertEqual(select_inventory(c[v],at())[0],d.book_market_ids[v])
 def test_malformed_embedded_sides_never_qualify(self):
  p=deepcopy(PAGES[0]);data=json.loads(base64.b64decode(p['body_b64']));data['events'][0]['markets'][0]['marketSides'][0]['long']=False
  raw=json.dumps(data).encode();p['body_b64']=base64.b64encode(raw).decode();p['body_sha256']=__import__('hashlib').sha256(raw).hexdigest()
  self.assertFalse(select_inventory(coverage.catalog([p],'polymarket_us',at()),at())[0])
class Protocol(unittest.TestCase):
 def test_kalshi_exact_ticker_and_side_orientation(self):
  e=kengine();self.assertEqual(e.begin(1)['params']['market_tickers'],['KXNCAAFGAME-26OCT01WKUNMSU-NMSU']);ack(e)
  b=e.feed(ksnapshot(),e.generation,at());b=purchase_book(b)
  q=kalshi.quotes(b);self.assertEqual(str(q[0].ask.price.value),'0.5000');self.assertEqual(str(q[1].ask.price.value),'0.6000')
 def test_kalshi_duplicate_gap_wrong_market_and_delta_before_snapshot(self):
  for mode in ('duplicate','gap','wrong_market','early_delta'):
   e=kengine();ack(e)
   if mode!='early_delta':e.feed(ksnapshot(),e.generation,at())
   data=json.loads(ksnapshot(seq=1 if mode=='duplicate' else 3 if mode=='gap' else 2))
   if mode=='wrong_market':data['msg']['market_ticker']='wrong'
   if mode=='early_delta':data.update(type='orderbook_delta',seq=1);data['msg'].update(side='yes',price_dollars='.4',delta_fp='2')
   with self.subTest(mode=mode),self.assertRaises(RecoveryRequired):e.feed(json.dumps(data),e.generation,at())
   self.assertTrue(all(b.sync==BookSync.UNSYNCHRONIZED for b in e.last.values()))
 def test_us_exact_slug_orientation_and_atomic_replacement(self):
  e=pengine();g=e.begin_subscription('r');b=e.parse(pmessage(),'r',generation=g);b=purchase_book(b)
  native=markets()['polymarket_us']['932924'];roles={s['id']:s['long'] for ev in json.loads(native.raw.json_text)['events'] for m in ev['markets'] for s in m['marketSides']}
  for o in b.outcomes:self.assertEqual(o.asks.levels[0].price.value,__import__('decimal').Decimal('.55' if roles[o.outcome_id] else '.60'))
  data=json.loads(pmessage());data['marketData']['bids']=[];b=e.parse(json.dumps(data),'r',generation=g);self.assertFalse(b.outcomes[0].bids.levels)
 def test_us_unknown_slug_and_ambiguous_delta_reject(self):
  for changes in ({'marketSlug':'wrong'},{'delta':True},{'sequence':2}):
   e=pengine();g=e.begin_subscription('r');data=json.loads(pmessage());data['marketData'].update(changes)
   with self.assertRaises(ValueError):e.parse(json.dumps(data),'r',generation=g)
 def test_us_old_request_cannot_update_current(self):
  e=pengine();g=e.begin_subscription('r');e.begin_subscription('r2')
  with self.assertRaises(StaleSubscriptionFrame):e.parse(pmessage(),'r',generation=g)
 def test_observation_changes_repeats_timestamps_recovery_health(self):
  e=pengine();g=e.begin_subscription('r');o=books.Observations()
  def observe(msg,connection=1):return o.classify(e.parse(msg,'r',generation=g),connection)
  self.assertEqual(observe(pmessage())['classification'],'initial_snapshot')
  x=observe(pmessage(px='0.400',qty='10.000'));self.assertEqual(x['classification'],'repeated_identical_observation');self.assertEqual(x['source_time_progress'],'repeated')
  x=observe(pmessage(qty='12'));self.assertTrue(x['quantities_changed']);self.assertFalse(x['price_levels_changed'])
  self.assertTrue(observe(pmessage(px='.42',qty='12'))['price_levels_changed'])
  self.assertEqual(observe(pmessage(),2)['classification'],'recovery_snapshot')
  b=e.last[next(iter(e.last))];self.assertIsNone(o.classify(b,2));self.assertIsNone(o.classify(replace(b,receipt_freshness=ReceiptFreshness.STALE),2));self.assertIsNone(o.classify(replace(b,sync=BookSync.UNSYNCHRONIZED),2))
class Metadata(unittest.IsolatedAsyncioTestCase):
 async def test_embedded_reuse_and_exact_conditional_slug_request(self):
  from unittest.mock import AsyncMock
  from hashlib import sha256
  for missing in (False,True):
   pages=deepcopy([p for p in PAGES if p['path'].endswith('/events')])
   if missing:
    for p in pages:
     if p['source']!='polymarket_us' or p['params'].get('tagSlug')!='cfb':continue
     body=json.loads(base64.b64decode(p['body_b64']))
     for m in body['events'][0]['markets']:
      for key in ('description','rules_primary','rules_secondary'):m.pop(key,None)
     raw=json.dumps(body).encode();p.update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
   session=SimpleNamespace(spec=spec(),emit=lambda *a:None)
   d=Discovery(session);d.pages=pages;d.selection_time=at();d.pages_for=AsyncMock(return_value=[])
   await books.finish(d)
   calls=[c for c in d.pages_for.call_args_list if c.args[0]=='polymarket_us']
   self.assertEqual(len(calls),int(missing))
   if missing:
    self.assertEqual(calls[0].args[1:3],('/v1/markets',dict(slug=['aec-cfb-wkent-nmxst-2026-10-01'],active='true',closed='false')))
    self.assertEqual(d.book_market_ids['polymarket_us'],[])
   else:self.assertEqual(d.book_market_ids['polymarket_us'],['932924'])
 def test_report_separates_wire_from_accepted_recovery_changes(self):
  from app.collection.native_book_report import summarize
  row=dict(source='kalshi',type='prediction_frame',body_b64=base64.b64encode(b'{"type":"orderbook_delta"}').decode())
  o=dict(classification='recovery_snapshot',source_time_progress='repeated',comparison_to_previous='changed',price_levels_changed=True,quantities_changed=True)
  report=summarize([dict(type='session_started',source='session',spec=spec()),row,row,dict(type='prediction_book',source='kalshi',native_observation=o)])
  k=report['sources']['kalshi'];self.assertEqual(k['wire']['orderbook_delta'],2);self.assertEqual(k['accepted']['recovery_snapshot'],1)
  self.assertEqual(k['price_level_changes'],0);self.assertEqual(k['quantity_changes'],0);self.assertEqual(k['recovery_comparisons']['changed'],1)

if __name__=='__main__':unittest.main()
