"""Finite controlled native pagination, verification, fairness and bounds."""
import base64
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import tracemalloc
import unittest
from app.comparison.coverage import CoverageLedger, SPORTS
from app.comparison.discovery import DiscoveryCycle, budget, fair_markets, current_catalog
from app.collection.current_policy import DEFAULT
from app.collection.native_selectors import LEAGUES

FIXTURE=Path(__file__).resolve().parents[1]/'app/fixtures/comparison-discovery-v1.json'
AUTHORED=json.loads(FIXTURE.read_text())
AT=datetime.fromisoformat(AUTHORED['at'].replace('Z','+00:00'))


class Catalog:
    def __init__(self,venue,failure=None,wrong_sport=None,metadata_conflict=False):
        self.venue=venue;self.calls=[];self.failure=failure;self.wrong_sport=wrong_sport
        self.metadata_conflict=metadata_conflict

    async def fetch(self,request):
        self.calls.append(deepcopy(request))
        q=request['params'];path=request['path']
        listing=path.endswith('/events')
        if self.venue=='kalshi':
            sport=request['binding']['sport'];family=request['binding']['family']
            position=0 if not q.get('cursor') else 1
        elif listing:
            sport=next(s for s,slug in LEAGUES.items() if slug==q['tagSlug']);family='moneyline'
            position=q['offset']//5
        else:
            sport=SPORTS[int(q['gameId'])-1];family='moneyline';position=0
        data={}
        counts=AUTHORED['kalshi_listing_counts' if self.venue=='kalshi' else 'us_listing_counts']
        if listing:
            n=counts[sport][position]
            rows=[]
            for i in range(n):
                eid=sport+'-'+str(position*5+i)
                if self.venue=='kalshi':
                    rows.append(dict(event_ticker=eid,series_ticker='WRONG' if sport==self.wrong_sport else q['series_ticker'],title='Authored game'))
                else:
                    league=LEAGUES[sport]
                    rows.append(dict(id=eid,title='Authored game',gameId=SPORTS.index(sport)+1,startTime=AUTHORED['start'],
                        teams=[dict(name=sport+' home',league=league),dict(name=sport+' away',league='wrong' if sport==self.wrong_sport else league)],
                        active=True,closed=False,ended=False,period='NS',markets=[]))
            data['events']=rows
            if self.venue=='kalshi':
                data['cursor']='next'+str(position) if sport=='NFL' else ''
                data['milestones']=[dict(category='Sports',type=request['binding']['milestone_type'],start_date=AUTHORED['start'],
                    related_event_tickers=[e['event_ticker']]) for e in rows]
        else:
            rows=[]
            for i in range(2):
                mid=sport+'-'+family+'-'+str(i)
                if self.venue=='kalshi':
                    rows.append(dict(ticker=mid,event_ticker='WRONG' if self.metadata_conflict else q['event_ticker']))
                else:
                    typed={'NFL':'football','NCAAF':'football','NBA':'basketball','NCAAB':'basketball','MLB':'baseball','NHL':'hockey'}[sport]+'_team_full_game_winner'
                    rows.append(dict(id=mid,gameId=999 if self.metadata_conflict else int(q['gameId']),sportsMarketType=typed))
            data['markets']=rows
            if self.venue=='kalshi':data['cursor']=''
        raw=json.dumps(data).encode()
        return dict(source=self.venue,path=path,params=deepcopy(q),received_at=AUTHORED['at'],
            status=403 if sport==self.failure else 200,complete=True,
            body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),
            resource_usage={'wire_bytes':len(raw)})


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_six_sport_first_opportunities_and_crowded_pages_stay_partial(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                callback=Catalog(venue)
                ledger=CoverageLedger({venue:SPORTS})
                cycle=DiscoveryCycle(venue)
                result=await cycle.run(callback.fetch,AT,ledger=ledger)
                first=callback.calls[:6]
                self.assertTrue(all(r['path'].endswith('/events') for r in first))
                self.assertEqual(result['usage']['requests'],12)
                self.assertLessEqual(result['usage']['requests'],18)
                self.assertLessEqual(result['usage']['wire_bytes'],6*1024*1024)
                self.assertLessEqual(result['usage']['retained_bytes'],8*1024*1024)
                cells={c['sport']:c for c in result['cells']}
                self.assertEqual(cells['NFL']['pages'],2)
                self.assertEqual(cells['NFL']['completeness'],'partial')
                self.assertEqual(cells['NCAAB']['state'],'no_offerings_returned')
                self.assertEqual(set(result['selected_events']),{'NFL','NCAAF','NBA','MLB','NHL'})
                self.assertFalse(result['expansion_active'])
                catalog=current_catalog(result,venue,AT)
                self.assertLessEqual(len(catalog['events']),6)
                self.assertLessEqual(len(catalog['markets']),20)
                self.assertTrue(set(m['id'] for m in catalog['markets'])<=set(m['id'] for m in result['selected_markets']))
                self.assertEqual(ledger.observations['NCAAB',venue]['latest']['offered']['games'],0)
                with self.assertRaises(ValueError):await cycle.run(callback.fetch,AT)

    async def test_exact_returned_metadata_conflict_and_access_failure_are_local(self):
        for venue in ('kalshi','polymarket_us'):
            callback=Catalog(venue,failure='NFL',wrong_sport='NBA',metadata_conflict=True)
            result=await DiscoveryCycle(venue).run(callback.fetch,AT)
            cells={c['sport']:c for c in result['cells']}
            self.assertEqual(cells['NFL']['state'],'failed_source')
            self.assertIsNone(cells['NBA']['selected'])
            self.assertEqual(cells['NHL']['state'],'offerings_returned')
            self.assertTrue(cells['NBA']['exclusions'])
            self.assertEqual(result['selected_markets'],[])
            self.assertTrue(cells['NHL']['exclusions'])

    async def test_family_and_sport_rotation_without_cap_increase(self):
        before=deepcopy(DEFAULT)
        for rotation,family in enumerate(('moneyline','spread','total')):
            result=await DiscoveryCycle('kalshi',rotation=rotation).run(Catalog('kalshi').fetch,AT)
            self.assertEqual({c['family'] for c in result['cells']},{family})
            self.assertEqual(result['selected_markets'][0]['sport'],SPORTS[rotation])
            self.assertLessEqual(len(result['selected_markets']),20)
        self.assertEqual(DEFAULT,before)
        self.assertEqual(budget()['requests'],18)

    async def test_consumed_global_request_bound_and_stop_before_or_after_callback(self):
        config=deepcopy(DEFAULT);config['requests_per_source']=6
        callback=Catalog('kalshi')
        result=await DiscoveryCycle('kalshi',config=config).run(callback.fetch,AT)
        self.assertEqual(len(callback.calls),6)
        self.assertTrue(any(c['metadata']=='global_budget_excluded' for c in result['cells']))
        from app.collection.odds_http import BudgetStop
        with self.assertRaisesRegex(BudgetStop,'dispatch_revoked'):
            await DiscoveryCycle('kalshi').run(callback.fetch,AT,dispatch=lambda:False)
        revoked=False
        async def revoke(request):
            nonlocal revoked
            page=await callback.fetch(request);revoked=True;return page
        with self.assertRaisesRegex(BudgetStop,'dispatch_revoked'):
            await DiscoveryCycle('kalshi').run(revoke,AT,dispatch=lambda:not revoked)

    async def test_duplicate_cursor_rejected_and_fixed_workload_memory_bounded(self):
        catalog=Catalog('kalshi')
        async def duplicate(request):
            page=await catalog.fetch(request)
            if request['params'].get('cursor'):
                raw=json.dumps({'events':[],'cursor':request['params']['cursor']}).encode()
                page.update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
            return page
        result=await DiscoveryCycle('kalshi').run(duplicate,AT)
        self.assertEqual(next(c for c in result['cells'] if c['sport']=='NFL')['state'],'rejected_payload')
        tracemalloc.start()
        try:
            for rotation in range(3):
                value=await DiscoveryCycle('kalshi',rotation=rotation).run(Catalog('kalshi').fetch,AT)
                self.assertLessEqual(len(value['pages']),18)
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,32*1024*1024)

    def test_subscription_round_robin_cannot_starve_sports_or_families(self):
        markets=[dict(id=s+'-'+f+'-'+str(i),sport=s,family=f) for s in SPORTS for f in ('moneyline','spread','total') for i in range(100)]
        selected=fair_markets(markets,20)
        self.assertEqual(len(selected),20)
        self.assertEqual({m['sport'] for m in selected[:18]},set(SPORTS))
        for sport in SPORTS:
            self.assertEqual({m['family'] for m in selected[:18] if m['sport']==sport},{'moneyline','spread','total'})

    async def test_failed_and_rejected_receipt_bytes_consume_global_cap(self):
        for mode in ('failed','incomplete','invalid_json','oversize'):
            catalog=Catalog('kalshi')
            async def invalid(request):
                page=await catalog.fetch(request)
                raw=(b'not-json' if mode=='invalid_json' else b'x'*(2*1024*1024+1) if mode=='oversize' else b'{}')
                page.update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),
                    resource_usage={'wire_bytes':2*1024*1024},status=503 if mode=='failed' else 200,
                    complete=mode!='incomplete')
                return page
            result=await DiscoveryCycle('kalshi').run(invalid,AT)
            self.assertEqual(result['usage']['wire_bytes'],6*1024*1024)
            self.assertEqual(len(catalog.calls),3)
            self.assertEqual(result['pages'],[])
            self.assertTrue(any(c['state']=='global_budget_excluded' for c in result['cells']))

    async def test_retained_bound_counts_full_receipt_metadata(self):
        catalog=Catalog('kalshi')
        async def overhead(request):
            page=await catalog.fetch(request)
            page['local_metadata_padding']='x'*(2*1024*1024)
            return page
        result=await DiscoveryCycle('kalshi').run(overhead,AT)
        self.assertEqual(len(catalog.calls),4)
        self.assertLessEqual(result['usage']['retained_bytes'],8*1024*1024)
        self.assertGreater(result['usage']['retained_bytes'],6*1024*1024)
        self.assertEqual(len(result['pages']),3)


if __name__=='__main__':unittest.main()
