"""Synthetic source transport stress: unchanged 20 markets per venue, 80 observations."""
from copy import deepcopy
from unittest import IsolatedAsyncioTestCase
from datetime import datetime,timezone
from types import SimpleNamespace
from app.comparison.combined_native import normalize
from app.dashboard.comparison_board import response,expand_odds
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.storage.comparison_board import ReadContext,observation_identity
from app.storage.store import encoded
from tests.multisport_fixtures import source_case,fake_discovery,current_book
from tests.test_current_multisport_ingress import worker
class MarketBoardCapacity(IsolatedAsyncioTestCase):
 async def test_eighty_actual_normalized_native_observations_fit_one_frozen_board(self):


  clock=datetime.now(timezone.utc);base=source_case('NBA','spread','busygame',clock=clock);rows=[]
  for i in range(20):
   case=source_case('NBA','spread','busyline'+str(i),clock=clock,line=str(i+0.5))
   case['markets']['kalshi']['event_ticker']=base['events']['kalshi']['event_ticker']
   case['events']['kalshi']['event_ticker']=base['events']['kalshi']['event_ticker']
   case['milestone']['details']['main_game_event_ticker']=base['events']['kalshi']['event_ticker']
   case['milestone']['source_id']=base['milestone']['source_id'];case['milestone']['related_event_tickers']=[base['events']['kalshi']['event_ticker']]
   case['events']['polymarket_us'].update({key:base['events']['polymarket_us'][key] for key in ('id','gameId','sportradarGameId')})
   for venue in ('kalshi','polymarket_us'):
    w,published=worker(venue,['NBA'],['spread']);fake_discovery(w,[case]);await w.discover()
    at=datetime.now(timezone.utc).isoformat();catalog=dict(id='generated-catalog',record=dict(source=venue,value=dict(inventory=published[-1])))
    obs=dict(type='prediction_book',source=venue,observed_at=at,book=current_book(case,venue))
    values,excluded=normalize(catalog,[dict(id='generated-book',record=dict(retained_at=at,value=dict(observations=[obs])))],at=at);assert not excluded,excluded;rows.extend(values)
  at=datetime.now(timezone.utc).isoformat();context=ReadContext(SimpleNamespace(db=None),at=at,frame=dict(epoch='capacity',revision='busygame',records=rows))
  bundles=context.observation_bundles();self.assertEqual(len(bundles),1);self.assertEqual(len(rows),80)
  for b in bundles:
   b['calculation_context']=observation_identity(b,context);r=response(b,None,DEFAULT_POLICY,view='odds',filter='all',at=at)
   self.assertEqual(len(r['prices']),80)
   self.assertLessEqual(len(encoded(r)),512*1024)
   self.assertEqual(sum(q['current_comparison']['available'] for q in r['prices']),80)
   self.assertTrue(all(len(q['current_comparison']['input_refs'])==2 for q in r['prices']))
   self.assertTrue(all(not q['current_comparison']['inputs'] for q in r['prices']),'new wire frames retain references without duplicate full inputs')
   from app.storage.comparison_board import discover,calculate_current,context_identity
   financial_bundle=discover(context.store,context=context,game=b['game_key'])[0]
   financial_bundle['calculation_context']=context_identity(financial_bundle,DEFAULT_POLICY,context)
   calculation=calculate_current(financial_bundle,DEFAULT_POLICY,context=context)
   for view in ('ev','arbs'):
    financial=response(financial_bundle,calculation,DEFAULT_POLICY,view=view,filter='all',at=at)
    self.assertEqual(len(financial['prices']),80)
    self.assertLessEqual(len(encoded(financial)),512*1024)
   expanded=expand_odds(deepcopy(r))
   self.assertTrue(all(len(q['current_comparison']['inputs'])==2 for q in expanded['prices']))
   self.assertTrue(all(q['native_contract_summary']['wording'] for q in expanded['prices']))
   frozen=encoded(expanded['prices'][0]['current_comparison']['inputs'])
   r['prices'][0]['original']['value']='0.99'
   self.assertEqual(encoded(expanded['prices'][0]['current_comparison']['inputs']),frozen)
