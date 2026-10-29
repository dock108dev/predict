"""Observed first-page discovery selection; fake HTTP only, no providers or storage."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace
import unittest
import time
from unittest.mock import patch

from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT


class FirstPageSelection(unittest.IsolatedAsyncioTestCase):
    async def discover(self,venue,sports,counts,cap=24):
        calls=[];published=[];now=datetime.now(timezone.utc)
        events={sport:[dict(id=f'{sport}-observed-{i}',sport=sport,competition=sport,
            scheduled_start=(now+timedelta(days=1,minutes=i)).isoformat(),exclusion=None,
            native_aliases=dict(series_ticker=f'fixture-{sport}'),
            market_bindings=[dict(id=f'{sport}-market-{i}')],event_ticker=f'{sport}-observed-{i}',markets=[dict(id=f'{sport}-market-{i}',sportsMarketType='football_team_full_game_winner' if sport=='NFL' else 'basketball_team_full_game_winner')]) for i in range(counts[sport])] for sport in sports}
        if venue=='kalshi':
            for group in events.values():
                for event in group:event.pop('markets')  # Exercise absent-embedded metadata fallback.
        config=dict(deepcopy(DEFAULT),sports=sports,families=['moneyline'],events_per_source=cap)
        service=SimpleNamespace(config=config,dispatch=True,deadline=time.monotonic()+60,catalog=lambda v,c:published.append(deepcopy(c)),
            issue=lambda *args:None,source_state=lambda *args:None)
        worker=NativeWorker(service,venue)
        async def get(path,params,kind=None,scope=None):
            sport=scope['sport'] if scope else str(params.get('tagSlug','')).upper()
            call=dict(path=path,params=deepcopy(params),kind=kind,sport=sport)
            calls.append(call)
            page=dict(path=path,body_b64='',body_sha256=sha256(repr(call).encode()).hexdigest(),rows=[])
            if path.startswith('/v1/events/'):
                page['rows']=[deepcopy(e) for group in events.values() for e in group if e['id']==path.rsplit('/',1)[-1]]
                page['event_id']=page['rows'][0]['id'];page['market_id']=page['rows'][0]['market_bindings'][0]['id']
            elif kind=='events':page['rows']=deepcopy(events[sport][params.get('offset',0):params.get('offset',0)+params['limit']])
            elif venue=='kalshi':page['event_id']=params['event_ticker']
            else:
                page['market_id']=path.rsplit('/',1)[-1]
                page['event_id']=next(e['id'] for group in events.values() for e in group if e['market_bindings'][0]['id']==page['market_id'])
            worker.pages.append(page)
            return page['rows']
        worker.get=get
        def catalog(pages,actual_venue,at,**kwargs):
            listing={e['id']:deepcopy(e) for p in pages for e in p['rows']}
            selected=kwargs.get('current_selection')
            if selected is not None:listing={k:v for k,v in listing.items() if k in selected['events']}
            markets=[]
            for p in pages:
                if 'event_id' not in p:continue
                mid=p.get('market_id') or listing[p['event_id']]['market_bindings'][0]['id']
                markets.append(dict(id=mid,event_id=p['event_id'],market_type='moneyline',period='full_game',status='active',
                    exclusion=None,v1_raw_binding=dict(identity=dict(family='moneyline',period='full_game')),
                    provenance=[dict(body_sha256=p['body_sha256'])],_native=dict(id=mid)))
            return dict(events=list(listing.values()),markets=markets)
        def parsed(response,native,event,*args,**kwargs):
            return SimpleNamespace(raw=SimpleNamespace(ref=SimpleNamespace(market_id=native['id'],event_id=event)))
        with patch('app.collection.current_native.coverage.decode_page',side_effect=lambda p:(b'{}',dict(events=p['rows'],markets=[],cursor='',market=dict(id=p.get('market_id',''),sportsMarketType='football_team_full_game_winner')))), \
             patch('app.collection.current_native.coverage.event_record',side_effect=lambda v,p,r,e,i,a:deepcopy(e)), \
             patch('app.collection.current_native.candidates',side_effect=lambda pages,v,s,a,**kwargs:(deepcopy(pages[0]['rows']),[])), \
             patch('app.collection.current_native.coverage.catalog',side_effect=catalog), \
             patch('app.collection.current_native.coverage.response',return_value=None), \
             patch('app.collection.continuous.select_inventory',side_effect=lambda c,a,n:([m['id'] for m in c['markets']],[])), \
             patch('app.adapters.kalshi.parse_market',side_effect=parsed), \
             patch('app.adapters.polymarket_us.parse_market',side_effect=parsed), \
             patch('app.adapters.polymarket_us.next_market_data',side_effect=lambda m:dict(slug=m.raw.ref.market_id)), \
             patch('app.comparison.lifecycle.worker_selections',return_value=[]):
            await worker.discover()
        return worker,calls,published,events

    async def test_all_pages_receive_exact_metadata(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                worker,calls,published,events=await self.discover(venue,['NFL'],{'NFL':6})
                listings=[c for c in calls if c['kind']=='events']
                self.assertEqual(len(listings),1 if venue=='kalshi' else 2)
                expected=[e['id'] for e in events['NFL']]
                self.assertEqual(worker.findings[0]['selected'],expected)
                self.assertEqual(len(worker.markets),6)
                self.assertEqual({m['event_id'] for m in published[0]['markets']},set(expected))
                self.assertEqual(len(calls),6+len(listings))
                if venue=='kalshi':self.assertEqual([c['params']['event_ticker'] for c in [c for c in calls if c['kind']!='events']],expected)
                else:
                    self.assertEqual(listings[0]['params']['sportsMarketTypes'],'football_team_full_game_winner')
                    self.assertEqual([c['path'] for c in [c for c in calls if c['kind']!='events']],['/v1/events/'+e['id'] for e in events['NFL']])

    async def test_legacy_event_cap_does_not_omit_metadata(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                worker,calls,published,events=await self.discover(venue,['NFL','NBA'],{'NFL':2,'NBA':4},cap=3)
                expected=[e['id'] for e in events['NFL']]+[e['id'] for e in events['NBA']]
                self.assertEqual([eid for finding in worker.findings for eid in finding['selected']],expected)
                self.assertEqual({m['event_id'] for m in published[0]['markets']},set(expected))
                self.assertEqual(len(worker.markets),6)
                listings=[c for c in calls if c['kind']=='events'];self.assertEqual(len(listings),2)
                if venue=='polymarket_us':self.assertEqual([c['params']['limit'] for c in listings],[5,5])
                self.assertEqual(len(calls)-len(listings),6)

    async def test_all_scopes_precede_metadata_without_event_cutoff(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                worker,calls,_,_=await self.discover(venue,['NFL','NBA'],{'NFL':5,'NBA':4},cap=2)
                self.assertEqual(len(worker.findings),2)
                self.assertEqual({c['sport'] for c in calls if c['kind']=='events'},{'NFL','NBA'})
                self.assertEqual({m['event_id'].split('-')[0] for m in worker.catalog['markets']},{'NFL','NBA'})
                self.assertEqual(len(worker.markets),9)


if __name__=='__main__':unittest.main()
