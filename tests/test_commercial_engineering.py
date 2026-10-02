"""Local E1-E5 acceptance: no credential access or external traffic."""
import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.session_projection import SessionProjection
from app.dashboard.price_comparison import comparisons, entry_cost
from app.dashboard.decision_support import size_report, explanation
from app.dashboard.opportunity_history import Signals, WatchStore, validate_watch, observations, build_history
from app.dashboard.multi_game_server import create_app
from tests.test_session_projection import fixture
from tests.segmented_collector_fixture import Fixture


def qualified_fixture():
    rows=fixture()
    for r in rows:
        if r['type']=='prediction_book':
            r['book']['source_time_progress']='advanced'
            r['book']['raw']['exchange_at']=r['observed_at']
    return rows


def snapshot():
    p=SessionProjection()
    for r in qualified_fixture():p.apply(r)
    return p,p.snapshot()


def watch(metric='raw_gap',threshold='0'):
    return validate_watch(dict(name='Local acceptance',metric=metric,threshold=threshold,quantity='1',filters={}))


class Decision(unittest.TestCase):
    def test_explanation_exact_conflict_missing_costs_and_supported_branch(self):
        _,s=snapshot();r=comparisons(s,{})[0]
        d=r['decision'];self.assertTrue(d['net_reason']);self.assertTrue(d['freshness']);self.assertTrue(d['quantity'])
        r['settlement_audit']={'qualified':False,'conflicts':[{'condition':'postponement','left':{'value':'48 hours'},'right':{'value':'two weeks'}}]}
        self.assertIn('48 hours versus two weeks',explanation(r)['settlement'][0])
        r.update(profit='1',settlement_audit={'qualified':True})
        self.assertIn('match',explanation(r)['settlement'][0]);self.assertEqual(explanation(r)['net_reason'],[])

    def test_connected_sizes_rounding_negative_and_ceiling(self):
        _,s=snapshot();g=next(g for g in s['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
        r=size_report(s,g,dict(sizes=['1','10'],scenario='cent',ceiling='1.03'))
        one=next(c for c in r['sizes'][0]['candidates'] if c['cash'])
        # Hand arithmetic: .44 + ceil(.07*.44*.56*100)/100 + .565 + .01 = 1.035.
        self.assertEqual(Decimal(one['cash']),Decimal('1.035'))
        self.assertEqual(Decimal(one['profit']),Decimal('-.035'))
        self.assertFalse(one['within_ceiling']);self.assertIsNone(r['best'])
        ten=next(c for c in r['sizes'][1]['candidates'] if c['cash'])
        self.assertEqual(Decimal(ten['cash']),Decimal('10.38'))
        self.assertEqual(r,size_report(s,g,dict(sizes=['1','10'],scenario='cent',ceiling='1.03')))
        self.assertEqual(r['cutoff'],s['points'][g['id']]['id'])

    def test_connected_zero_return_hand_calculation(self):
        _,s=snapshot();g=next(g for g in s['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
        point=s['points'][g['id']]
        for card in point['cards']:
            if card['venue']=='kalshi':
                yes=next(o for o in card['book']['outcomes'] if o['side']=='yes')
                no=next(o for o in card['book']['outcomes'] if o['side']=='no')
                yes['quote']['ask']='0.5'
                no['depth']['bids']['levels']=no['depth']['bids']['levels'][:1]
                no['depth']['bids']['levels'][0]['price']['value']='0.5'
            elif card['venue']=='polymarket_us':
                long=next(o for o in card['book']['outcomes'] if o['quote']['ask'] is not None)
                long['quote']['ask']='0.47'
                long['depth']['asks']['levels']=long['depth']['asks']['levels'][:1]
                long['depth']['asks']['levels'][0]['price']['value']='0.47'
        report=size_report(s,g,dict(sizes=['1'],scenario='cent',ceiling='1'))
        row=next(c for c in report['sizes'][0]['candidates'] if c['cash'])
        # .50 + .02 rounded Kalshi fee + .47 + .01 rounded US fee = 1.
        self.assertEqual(Decimal(row['cash']),Decimal('1'))
        self.assertEqual(Decimal(row['profit']),Decimal('0'))
        self.assertEqual(Decimal(row['return_pct']),Decimal('0'))
        self.assertTrue(row['within_ceiling'])
        self.assertEqual(Decimal(report['best']['profit']),Decimal('0'))

    def test_multilevel_depth_partial_quantity_and_native_fractional_limit(self):
        c=dict(venue='polymarket_us',levels=[dict(price='.4',quantity='1.5',provenance='synthetic'),dict(price='.6',quantity='2',provenance='synthetic')],top_size='1.5')
        at='2026-09-27T00:00:00+00:00'
        r=entry_cost(c,Decimal(3),at,{},dict(market_id='fixture'))
        self.assertEqual(Decimal(r['notional']),Decimal('1.5')) # 1.5*.4 + 1.5*.6
        r=entry_cost(c,Decimal(4),at,{},dict(market_id='fixture'))
        self.assertIsNone(r['upper']);self.assertIn('exceeds',r['reason'])
        r=entry_cost(c,Decimal('1.25'),at,{},dict(market_id='fixture'))
        self.assertEqual(Decimal(r['notional']),Decimal('.5'));self.assertIsNone(r['upper']);self.assertIn('fractional',r['reason'])
        _,s=snapshot();g=s['games'][0]
        result=size_report(s,g,dict(sizes=['.5']))
        self.assertIn('whole',result['sizes'][0]['limitation'])
        self.assertIsNone(result['best'])

    def test_connected_multiple_levels_and_insufficient_depth(self):
        _,s=snapshot();g=next(g for g in s['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
        # Retain exact top quotes, shorten native ladders to 1 + 2.
        point=s['points'][g['id']]
        for card in point['cards']:
            if not card['book']:continue
            for o in card['book']['outcomes']:
                for kind in ('asks','bids'):
                    ladder=o['depth'].get(kind)
                    if not ladder or not ladder['levels']:continue
                    ladder['levels']=ladder['levels'][:2]
                    for i,level in enumerate(ladder['levels']):level['quantity']['value']=str(i+1)
                if o['quote']['ask_size'] is not None:o['quote']['ask_size']='1'
                if o['quote']['bid_size'] is not None:o['quote']['bid_size']='1'
        result=size_report(s,g,dict(sizes=['2','4'],scenario='cent'))
        two=next(c for c in result['sizes'][0]['candidates'] if c['cash'])
        four=next(c for c in result['sizes'][1]['candidates'] if c['cash'])
        self.assertEqual(two['legs'][0]['fills'][1]['quantity'],'1')
        self.assertEqual(Decimal(two['legs'][0]['notional']),Decimal('.44')+Decimal('.45'))
        self.assertEqual(four['modeled_quantity'],'3');self.assertTrue(four['depth_limited'])

    def test_sizes_limits_and_locked_fees(self):
        _,s=snapshot();g=s['games'][0];s['qualification_fee_policy']='native-evidence-required'
        r=size_report(s,g,dict(sizes=['1'],scenario='cent'))
        self.assertTrue(all(c['profit'] is None for c in r['sizes'][0]['candidates']))
        for sizes in ([],['1']*9,['NaN'],['0'],['-1']):
            with self.assertRaises(ValueError):size_report(s,g,dict(sizes=sizes))


class Transitions(unittest.TestCase):
    def test_store_restart_and_invalid_authority(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'w.json';store=WatchStore(p);store.save([watch()])
            self.assertEqual(WatchStore(p).read(),[watch()])
            with self.assertRaises(ValueError):store.save([dict(watch(),auto_start=True)])
            with self.assertRaises(ValueError):store.save([watch(),watch()])
            self.assertEqual(store.read(),[watch()])

    def test_crossing_identical_poll_stale_recovery_stop_restart(self):
        p,s=snapshot();engine=Signals();w=watch()
        before=engine.update(s,[w]);active=[i for i in before['items'] if i['active']]
        self.assertTrue(active)
        counts=[i['qualifying_observations'] for i in before['items']]
        self.assertEqual(counts,[i['qualifying_observations'] for i in engine.update(s,[w])['items']])
        aged=p.snapshot(mode='current',now='2026-09-16T12:00:20+00:00')
        self.assertFalse(any(i['active'] for i in engine.update(aged,[w])['items']))
        for r in qualified_fixture():
            if r['type']=='prediction_book':
                r=deepcopy(r);r['observed_at']='2026-09-16T12:00:21+00:00';r['book']['raw']['received_at']=r['observed_at'];r['ingress_id']+='-recovered';p.apply(r)
        recovered=engine.update(p.snapshot(),[w]);self.assertTrue(any(i['episodes']==2 for i in recovered['items']))
        self.assertTrue(any(len(i['observed_spans'])==2 for i in recovered['items']))
        stopped=engine.update(p.snapshot(),[w],running=False)
        self.assertFalse(any(i['active'] for i in stopped['items']))
        self.assertEqual(Signals().report()['items'],[])

    def test_supported_metric_gating_threshold_equality_and_zero_return(self):
        _,s=snapshot()
        leg=dict(id='l',book_id='b',age_seconds='0',received_at='2026-09-16T12:00:00+00:00',fee='0',fee_audit={'qualification':'documented_scenario','unsupported':[]})
        row=dict(id='c',game_title='Synthetic exact economics',return_pct='0',modeled_quantity='1',usable=True,settlement={'qualified':True},legs=[leg],session='b2-fixture~g',hash='b2-fixture',cutoff='1-x',at='2026-09-16T12:00:00+00:00')
        with patch('app.dashboard.product_view.dashboard',return_value=[row]):
            self.assertTrue(observations(s,watch('arb_return','0'))[0]['qualifies'])
            self.assertFalse(observations(s,watch('arb_return','.01'))[0]['qualifies'])
            row.update(probability='.5',reference_id='fresh-model')
            s['references']=[dict(id='fresh-model',freshness='within_refresh_plan',delay_seconds=0)]
            self.assertTrue(observations(s,watch('ev','0'))[0]['qualifies'])
            s['references'][0]['freshness']='refresh_due'
            self.assertFalse(observations(s,watch('ev','0'))[0]['qualifies'])
            row['settlement']['qualified']=False
            self.assertFalse(observations(s,watch('arb_return','0'))[0]['qualifies'])
            row['settlement']['qualified']=True;leg['fee_audit']['qualification']='conditional'
            self.assertFalse(observations(s,watch('ev','0'))[0]['qualifies'])
        self.assertFalse(any(o['qualifies'] for o in observations(s,watch('arb_return','0'))))

    def test_bounded_state_and_no_future_terms_history(self):
        p,s=snapshot();w=watch();e=Signals()
        with patch('app.dashboard.opportunity_history.MAX_ITEMS',1):
            r=e.update(s,[w]);self.assertEqual(len(r['items']),1);self.assertGreater(r['dropped'],0)
        with tempfile.TemporaryDirectory() as t:
            from app.collection.transport_session import ObservationJournal
            folder=Path(t)/p.sid;folder.mkdir();j=ObservationJournal(folder/(p.sid+'.jsonl'))
            for row in qualified_fixture():j.save(row)
            j.close();first=build_history(folder,[w]);second=build_history(folder,[w])
            self.assertEqual(first,second);self.assertTrue(first['historical']);self.assertFalse(any(i['active'] for i in first['items']))
            self.assertFalse(first['coverage']['complete'])
            for item in first['items']:
                for change in item['changes']:
                    from app.dashboard.session_history import load
                    exact=load(folder,change['point']['cutoff'])
                    original=next(o for o in observations(exact,w) if o['id']==item['id'])
                    self.assertEqual(original['metric'],change['value'])


class Integrated(unittest.IsolatedAsyncioTestCase):
    async def test_finalizing_session_cannot_emit_live_signals(self):
        from types import SimpleNamespace
        _,s=snapshot();s.update(view_mode='current',state='current')
        class Owner:
            session=SimpleNamespace(sid=s['session_id'])
            def active(self):return True  # Includes the owner's saving phase.
            def current_snapshot(self):return s
            async def close(self):pass
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'w.json';WatchStore(path).save([watch()])
            c=TestClient(TestServer(create_app(owner=Owner(),sessions={},watch_path=path)));await c.start_server()
            try:
                live=await (await c.get('/api/signals')).json()
                self.assertTrue(any(i['active'] for i in live['items']))
                s.update(view_mode='saved',state='saving')
                saving=await (await c.get('/api/signals')).json()
                self.assertFalse(any(i['active'] for i in saving['items']))
                self.assertTrue(any(e['kind']=='expired' for e in saving['events']))
            finally:await c.close()

    async def test_ordinary_routes_start_details_watch_history_stop_reopen(self):
        with tempfile.TemporaryDirectory() as t,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            f=Fixture();o=await f.start(t,product_mode=True)
            c=TestClient(TestServer(create_app(owner=o,sessions={},watch_path=Path(t)/'watchlists.json')));await c.start_server()
            origin={'Origin':str(c.make_url('/')).rstrip('/')}
            try:
                d=await (await c.get('/api/dashboard?view=feed')).json();self.assertTrue(d['live']);row=d['comparisons'][0]
                self.assertTrue(row['decision']['settlement'])
                body=dict(session=row['session'],hash=row['hash'],cutoff=row['cutoff'],sizes=['1','10','.5'],ceiling='100',scenario='cent',contract=row['contract'])
                resp=await c.post('/api/decision-sizes',json=body,headers=origin);sized=await resp.json();self.assertEqual(resp.status,200,sized)
                self.assertEqual((await c.post('/api/watchlists',json=[watch()],headers=origin)).status,200)
                signals=await (await c.get('/api/signals')).json();self.assertTrue(signals['items'])
                self.assertEqual((await c.get('/api/opportunity-history?capture='+d['capture'])).status,422)
                await f.send(f.active()[0])
                resp=await c.post('/api/stop',json={},headers=origin);self.assertEqual(resp.status,200);await o.finalizer
                self.assertIsNone(o.error)
                stopped=await (await c.get('/api/signals')).json();self.assertFalse(any(i['active'] for i in stopped['items']))
                reopened=await (await c.post('/api/decision-sizes',json=body,headers=origin)).json();self.assertEqual(sized,reopened)
                r=await c.get('/api/opportunity-history?capture='+d['capture']);report=await r.json();self.assertEqual(r.status,200,report);self.assertTrue(report['historical']);self.assertTrue(report['coverage']['complete'])
                again=await (await c.get('/api/opportunity-history?capture='+d['capture']+'&download=true')).json();self.assertEqual(report,again)
                self.assertFalse(any(i['active'] for i in report['items']))
                self.assertFalse(o.active())
                self.assertEqual((await c.post('/api/decision-sizes',json=dict(body,sizes=['NaN']),headers=origin)).status,422)
                self.assertEqual((await c.post('/api/watchlists',json=[dict(watch(),autostart=True)],headers=origin)).status,422)
                self.assertEqual((await c.post('/api/watchlists',json=[])).status,403)
            finally:await c.close();await f.close()

if __name__=='__main__':unittest.main()
