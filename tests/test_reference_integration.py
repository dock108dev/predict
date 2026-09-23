"""offline contracts and shared ordinary product; all new source values synthetic."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from app.reference.product import receipt,published_value,pinnacle,probability,kenpom_fanmatch,emit_references,at_cutoff,validate
from app.reference.refresh import Refresh
from app.dashboard.session_projection import SessionProjection
from app.dashboard import product_view,session_history
from app.collection.transport_session import ObservationJournal
from tests.test_session_projection import fixture

AT='2026-09-16T12:00:00+00:00'
ASOF='2026-09-15T12:00:00+00:00'

def references(game,at=AT):
    i=game['product_identity'];team=next(s['participant'] for s in game['sides'].values() if s['predicate']=='win')
    binding=dict(market_identity=i,participant=team,source_event_id='synthetic-event',source_participants=game['teams'],event_literal='Synthetic game',outcome_literal=team,date_literal=i['scheduled_start'])
    body='Synthetic game '+team+' '+i['scheduled_start']+' predictor 60.0% rating 12'
    r=receipt(body,provider='espn_fpi',url='https://www.espn.com/synthetic-fixture',received_at=at,mode='synthetic')
    start=body.index('60.0%');model=published_value(r,binding,start=start,end=start+5,kind='game_probability',convention='percent',source_at=ASOF,model_version='synthetic-fpi-shape')
    rating=published_value(r,binding,start=len(body)-2,end=len(body),kind='rating',convention='rating',source_at=ASOF)
    event=dict(id='synthetic-event',sport_key='americanfootball_nfl',commence_time=i['scheduled_start'],home_team=game['teams'][0],away_team=game['teams'][1],bookmakers=[dict(key='pinnacle',last_update=ASOF,markets=[dict(key='h2h',outcomes=[dict(name=t,price=p) for t,p in zip(game['teams'],['2.0','2.0'])])])])
    r=receipt(json.dumps([event]),provider='the_odds_api',url='https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds',received_at=at,mode='synthetic')
    pin=pinnacle(r,binding)
    return [model,pin,rating]

def projection():
    p=SessionProjection();rows=fixture()
    for r in rows:p.apply(r)
    return p,rows

def add(p,rows,refs):
    for ref in refs:
        r=dict(type='product_reference',session_id=p.sid,source='reference',observed_at=ref['received_at'],reference=ref)
        rows.append(r);p.apply(r)

class Contract(unittest.TestCase):
    def test_exact_conversions(self):
        for v,c,w in [('60','percent','0.6'),('2','decimal_odds','0.5'),('-150','american_odds','0.6'),('150','american_odds','0.4')]:self.assertEqual(probability(v,c),w)
        for v,c in [('NaN','probability'),('1','decimal_odds'),('50','american_odds'),('101','percent')]:
            with self.assertRaises(ValueError):probability(v,c)

    def test_originals_scopes_distinct_roles_and_arb(self):
        p,rows=projection();s=p.snapshot();g=s['games'][0];refs=references(g);before=product_view.dashboard(s,{},{});add(p,rows,refs);s=p.snapshot()
        self.assertEqual(product_view.dashboard(s,{}, {})[0]['legs'],before[0]['legs'])
        from app.reference.product import prepare
        r=refs[0];receipt_input={k:v for k,v in r['receipt'].items() if k not in ('id','provider_id','evidence_mode')};receipt_input.update(provider=r['provider_id'],mode=r['evidence_mode'])
        prepared=prepare([dict(parser='published_value',receipt=receipt_input,binding=r['binding'],options=dict(start=r['extraction']['start'],end=r['extraction']['end'],kind='game_probability',convention='percent',source_at=r['source_at'],model_version=r['model_version']))])
        self.assertEqual(prepared,[r])
        self.assertEqual(refs[0]['original_value'],'60.0%');self.assertEqual(refs[1]['original_value'][0]['price'],'2.0')
        ev=product_view.dashboard(s,{'view':'ev'},{});chosen=[x for x in ev if x.get('reference_id')]
        self.assertTrue(any(x['reference_id']==refs[0]['id'] and x['profit'] is not None for x in chosen))
        self.assertTrue(any(x['reference_id']==refs[1]['id'] and x['profit'] is not None for x in chosen))
        self.assertTrue(all(x['profit'] is None for x in chosen if x['reference_id']==refs[2]['id']))
        key=next(k for k,v in g['sides'].items() if v['participant']==refs[0]['participant'] and v['predicate']=='win')
        self.assertIsNone(product_view.calculate(s,g,dict(contract=key))['reference_id'])
        self.assertEqual(len(product_view.references_for(s,g,key)),3)
        for change in [dict(period='H1'),dict(line='3.5'),dict(competition='NCAAF'),dict(event=['elsewhere'])]:
            other=deepcopy(g);other['product_identity'].update(change)
            self.assertEqual(product_view.references_for(s,other,key),[])
        wrong=deepcopy(g);wrong['sides'][key]['participant']='Other'
        self.assertEqual(product_view.references_for(s,wrong,key),[])
        self.assertIn('Market-informed',refs[0]['dependency']);self.assertEqual(refs[1]['delay_seconds'],None)
        result=product_view.calculate(s,g,dict(contract=key,reference=refs[1]['id']))
        self.assertEqual(product_view.calculate(s,g,dict(contract=key,reference=refs[1]['id'])),result)
        self.assertIsNone(result['ev']['unconditional_ev']);self.assertIsNone(result['ev']['exceptional_probabilities'])

    def test_stale_delayed_missing_conflict_future_and_immutable(self):
        p,rows=projection();g=p.snapshot()['games'][0];refs=references(g);add(p,rows,refs)
        cutoff=p.snapshot()['durable_cursor'];saved=session_history.project_rows(rows,cutoff)
        aged=at_cutoff(refs,'2026-09-16T13:00:00+00:00');self.assertEqual(aged[1]['freshness'],'refresh_due');self.assertEqual(aged[1]['availability'],'available')
        altered=deepcopy(refs[0]);altered['value']='0.9'
        with self.assertRaises(ValueError):validate(altered)
        newer=references(g,'2026-09-17T12:00:00+00:00');add(p,rows,newer)
        self.assertEqual(session_history.project_rows(rows,cutoff),saved)
        self.assertEqual(at_cutoff(newer,AT),[])
        r=refs[0]['receipt'];body=r['body'].replace('60.0','65.0');rr=receipt(body,provider='espn_fpi',url=r['url'],received_at=AT,mode='synthetic');span=refs[0]['extraction'];conf=published_value(rr,refs[0]['binding'],start=span['start'],end=span['end'],kind='game_probability',convention='percent',source_at=ASOF,model_version='synthetic-fpi-shape')
        self.assertTrue(all(x['availability']=='conflicting' for x in at_cutoff([refs[0],conf],AT)))
        pin=refs[1];raw=json.loads(pin['receipt']['body']);raw[0]['bookmakers'][0]['key']='other'
        rr=receipt(json.dumps(raw),provider='the_odds_api',url=pin['receipt']['url'],received_at=AT,mode='synthetic')
        with self.assertRaisesRegex(ValueError,'Pinnacle missing'):pinnacle(rr,pin['binding'])
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/p.sid;folder.mkdir();j=ObservationJournal(folder/(p.sid+'.jsonl'))
            for row in rows:j.save(row)
            j.close();reopen=session_history.load(folder,through_cursor=cutoff)
            self.assertEqual(reopen['references'],saved['references'])

    def test_kenpom_ratings_and_other_sports(self):
        p,_=projection();g=p.snapshot()['games'][0];b=deepcopy(references(g)[0]['binding']);b['market_identity'].update(sport='basketball',competition='NCAAB',season='2027');b.update(source_event_id='123',source_date='2026-11-15')
        body=json.dumps([dict(GameID=123,DateOfGame='2026-11-15',Season=2027,Home=b['participant'],Visitor='Other',HomeWP='0.6',HomeRank=1,HomePred=75,VisitorPred=70)])
        r=receipt(body,provider='kenpom',url='https://kenpom.com/api.php',received_at=AT,mode='synthetic')
        k=kenpom_fanmatch(r,b,game_id=123,convention='probability');self.assertEqual(k['value'],'0.6');self.assertEqual(k['native_record']['HomeRank'],1)
        for provider,sport,comp in [('moneypuck','ice_hockey','NHL'),('fangraphs','baseball','MLB'),('espn_bpi','basketball','NBA')]:
            b['market_identity'].update(sport=sport,competition=comp);body='Synthetic game '+b['participant']+' '+b['date_literal']+' 60%'
            r=receipt(body,provider=provider,url='https://example.com/synthetic',received_at=AT,mode='synthetic')
            v=published_value(r,b,start=len(body)-3,end=len(body),kind='game_probability',convention='percent');self.assertEqual(v['value'],'0.6')
            season=published_value(r,b,start=len(body)-3,end=len(body),kind='season_probability',convention='percent');self.assertEqual(season['state'],'unsupported')

class Budget(unittest.IsolatedAsyncioTestCase):
    async def test_cache_failure_bounds_and_stop(self):
        plan=dict(provider='the_odds_api',bookmakers='pinnacle',markets=['h2h'],max_credits=1,oddsFormat='decimal',sport='americanfootball_nfl')
        log=[];calls=[]
        async def transport(p):calls.append(p);return dict(status=200,body='[]',headers={'x-requests-last':'0'})
        budget=Refresh()
        with self.assertRaises(ValueError):await budget.acquire(plan,at=AT,transport=transport,retain=log.append)
        self.assertEqual(calls,[])
        first=await budget.acquire(plan,at=AT,transport=transport,retain=log.append,approved=True)
        again=await budget.acquire(plan,at=AT,transport=transport,retain=log.append,approved=True)
        self.assertEqual(first,again);self.assertEqual(len(calls),1);self.assertEqual(budget.credits,1)
        with self.assertRaises(ValueError):await budget.acquire(plan,at='2026-09-17T12:00:00+00:00',transport=transport,retain=log.append,approved=True)
        budget.stop()
        with self.assertRaises(ValueError):await budget.acquire(plan,at=AT,transport=transport,retain=log.append,approved=True)
        async def fail(p):raise OSError('synthetic timeout')
        budget=Refresh()
        with self.assertRaises(OSError):await budget.acquire(plan,at=AT,transport=fail,retain=log.append,approved=True)
        self.assertEqual(budget.credits,1);self.assertEqual(budget.requests,1);self.assertEqual(log[-1]['state'],'failed')

    async def test_collector_stop_saved_reopening(self):
        from tests.segmented_collector_fixture import Fixture
        with tempfile.TemporaryDirectory() as t:
            f=Fixture()
            try:
                owner=await f.start(t,product_mode=True);s=owner.session;snap=s.projection.snapshot();g=snap['games'][0]
                refs=references(g,s.projection.last)
                from aiohttp.test_utils import TestClient,TestServer
                from app.dashboard.multi_game_server import create_app
                client=TestClient(TestServer(create_app(owner=owner,sessions={})));await client.start_server()
                try:
                    bad=deepcopy(refs);bad[0]['value']='0.9'
                    response=await client.post('/api/references',json=bad,headers={'Origin':str(client.make_url('/')).rstrip('/')})
                    self.assertEqual(response.status,422);self.assertEqual(s.projection.references,{})
                    response=await client.post('/api/references',json=refs,headers={'Origin':str(client.make_url('/')).rstrip('/')})
                    self.assertEqual(response.status,200)
                finally:await client.close()
                await s.queue.join()
                current=s.projection.snapshot();token=current['durable_cursor']
                original=product_view.dashboard(current,dict(view='ev'),{})
                await owner.stop()
                if owner.finalizer:await owner.finalizer
                folder=s.output;saved=session_history.load(folder,through_cursor=token)
                self.assertEqual(product_view.dashboard(saved,dict(view='ev'),{}),original)
                with self.assertRaises(ValueError):emit_references(s,refs)
            finally:await f.close()

class AdditionalBoundaries(unittest.IsolatedAsyncioTestCase):
    async def test_quota_overrun_http_failure_cache_limit_and_persistence_failure(self):
        plan=dict(provider='the_odds_api',bookmakers='pinnacle',markets=['h2h'],max_credits=1,oddsFormat='decimal',sport='americanfootball_nfl')
        for status,last in [(429,None),(200,'2')]:
            r=Refresh(max_requests=2,max_credits=2);log=[]
            async def transport(p):return dict(body='[]',status=status,headers={} if last is None else {'x-requests-last':last})
            with self.assertRaises(ValueError):await r.acquire(plan,at=AT,transport=transport,retain=log.append,approved=True)
            self.assertTrue(r.stopped);self.assertEqual(r.requests,1);self.assertGreaterEqual(r.credits,1)
        r=Refresh(max_requests=2,max_credits=2,max_entries=1)
        async def ok(p):return dict(body='[]',status=200)
        await r.acquire(plan,at=AT,transport=ok,retain=lambda r:None,approved=True)
        with self.assertRaisesRegex(ValueError,'Cache bound'):await r.acquire(dict(plan,sport='baseball_mlb'),at=AT,transport=ok,retain=lambda r:None,approved=True)
        called=[];r=Refresh()
        async def forbidden(p):called.append(p)
        def failed_save(row):raise OSError('synthetic disk failure')
        with self.assertRaises(OSError):await r.acquire(plan,at=AT,transport=forbidden,retain=failed_save,approved=True)
        self.assertEqual(called,[]);self.assertTrue(r.stopped)

    async def test_recomputed_receipt_and_future_model_line_period_isolation(self):
        from app.reference.product import finish
        p,rows=projection();g=p.snapshot()['games'][0];r=references(g)[0]
        forged=deepcopy(r);forged['value']='0.9';forged=finish({k:v for k,v in forged.items() if k!='id'})
        with self.assertRaisesRegex(ValueError,'reproduce'):validate(forged)
        for changes in [dict(period='H1'),dict(line='0'),dict(family='spread'),dict(horizon='2027')]:
            b=deepcopy(r['binding']);b['market_identity'].update(changes);span=r['extraction']
            v=published_value(r['receipt'],b,start=span['start'],end=span['end'],kind='game_probability',convention='percent',source_at=ASOF)
            self.assertEqual(at_cutoff([v],AT)[0]['availability'],'unsupported')
        span=r['extraction'];future=published_value(r['receipt'],r['binding'],start=span['start'],end=span['end'],kind='game_probability',convention='percent',source_at='2027-01-01T00:00:00Z')
        self.assertEqual(at_cutoff([future],AT),[])
        add(p,rows,[r]);key=next(k for k,v in g['sides'].items() if v['participant']==r['participant'] and v['predicate']=='win');snap=p.snapshot()
        manual={g['id']+'~'+key:dict(probability='0.7',basis='Owner what-if')}
        ev=product_view.dashboard(snap,dict(view='ev'),manual)
        self.assertTrue(any(x['probability']=='0.7' and not x['reference_id'] for x in ev));self.assertTrue(any(x['probability']=='0.6' and x['reference_id']==r['id'] for x in ev))
