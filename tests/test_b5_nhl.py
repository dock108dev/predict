"""B5 synthetic NHL bindings around retained price shapes; not live qualification."""
from copy import deepcopy
from hashlib import sha256
import json
import tempfile
from pathlib import Path
import unittest
from app.normalization.nhl import RULES,FIELDS,event_key
from app.normalization.registry import Registry
from app.dashboard.session_projection import SessionProjection
from app.dashboard import product_view,session_history
from app.reference.product import receipt,published_value,at_cutoff,validate
from tests.test_session_projection import fixture as football_fixture
from tests.test_b4_reference import add

AT='2026-09-16T12:00:00+00:00'
TERMS=dict(overtime='included',shootout='included',outcomes='two_way',tie='fraction-0.50',cancellation='venue_fair_value',postponement='48_hours_then_venue_fair_value',abandonment='official_result_else_venue_fair_value',forfeit='official_result')

def fixture():
    rows=football_fixture();cats=rows[1]['inventory']
    for source,cat in cats.items():
        cat['events']=cat['events'][:1];cat['markets']=cat['markets'][:1];cat['selection']['ids']=cat['selection']['ids'][:1]
        e=cat['events'][0];m=cat['markets'][0]
        translation={'Buffalo Bills':'Boston Bruins','Detroit Lions':'New York Rangers'}
        e.update(title='SYNTHETIC NHL · Boston Bruins vs New York Rangers',sport='hockey',competition='NHL',season='2026-2027',stage='regular_season',scheduled_start='2026-10-10T23:00:00+00:00',participants={'BOS':'NHL:BOS','NYR':'NHL:NYR'},home='NHL:BOS',away='NHL:NYR')
        e['canonical_key']=event_key(e)
        for side in m['product_outcomes']:side['participant']=translation[side['participant']]
        meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source and r['market']['raw']['ref']['market_id']==m['id'])
        native=json.loads(meta['raw']['json_text'])
        native_markets=native.get('markets',[])+[v for ev in native.get('events',[]) for v in ev.get('markets',[])]
        for nm in native_markets:
            if source=='kalshi' and nm.get('ticker')==m['id']:nm['yes_sub_title']='Boston Bruins'
            if source in ('polymarket_us','novig') and str(nm.get('id'))==m['id']:
                for side in nm.get('marketSides',[]):side['team']['name']=translation[side['team']['name']]
        literal='SYNTHETIC NHL review '+json.dumps(TERMS,sort_keys=True)
        orientation=json.dumps(m['product_outcomes'],sort_keys=True)
        fee='SYNTHETIC fee basis KXNHLGAME quadratic_with_maker_fees multiplier 1' if source=='kalshi' else 'SYNTHETIC PMUS feeCoefficient 0.06'
        native['b5_synthetic_terms']=literal;native['b5_synthetic_outcomes']=orientation;native['b5_synthetic_fee']=fee
        meta['raw']['json_text']=json.dumps(native)
        body=meta['raw']['json_text']
        # JSON string escapes are retained, so exact spans refer to serialized body.
        r=dict(source=source,event_id=e['id'],market_id=m['id'],evidence_mode='synthetic',raw_sha256=sha256(body.encode()).hexdigest(),terms=deepcopy(TERMS),literals={k:v for k,v in TERMS.items()},outcomes=deepcopy(m['product_outcomes']),outcome_literal='b5_synthetic_outcomes')
        if source=='kalshi':r['fee_basis']=dict(series_id='KXNHLGAME',fee_type='quadratic_with_maker_fees',multiplier='1',evidence_literal=fee)
        if source=='polymarket_us':r['fee_basis']=dict(coefficient='0.06',evidence_literal=fee)
        m.update(period='full_game',outcome_set='two_way',rules_revision=RULES,nhl_review=r)
    rows=[r for r in rows if not (r.get('market',r.get('book',{})).get('raw',{}).get('ref',{}).get('market_id','').endswith('m1'))]
    return rows

def projection(rows=None):
    p=SessionProjection();rows=fixture() if rows is None else rows
    for row in rows:p.apply(row)
    return p,rows

def reference(game,kind='game_probability',semantics=True,at=AT):
    i=game['product_identity'];e=dict(competition='NHL',sport='ice_hockey',season=i['season'],stage=i['stage'],scheduled_start=i['scheduled_start'],home='NHL:BOS',away='NHL:NYR',participants={'BOS':'NHL:BOS','NYR':'NHL:NYR'})
    body='SYNTHETIC Boston Bruins home vs New York Rangers away '+i['scheduled_start']+' home-win including overtime and shootout 60%'
    b=dict(market_identity=i,participant='Boston Bruins',source_event_id='synthetic-nhl',event_literal='Boston Bruins home vs New York Rangers away',outcome_literal='home-win',date_literal=i['scheduled_start'])
    if semantics:b['nhl_model_review']=dict(event=e,published_outcome='home_win',home_name='Boston Bruins',away_name='New York Rangers',overtime='included',shootout='included',home_literal='Boston Bruins home',away_literal='New York Rangers away',semantics_literal='home-win including overtime and shootout')
    r=receipt(body,provider='moneypuck',url='https://moneypuck.com/synthetic-fixture',received_at=at,mode='synthetic')
    return published_value(r,b,start=len(body)-3,end=len(body),kind=kind,convention='percent',source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC NHL fixture')

class NHL(unittest.TestCase):
    def test_registry_identity_and_historical_vocabulary(self):
        r=Registry.load()
        for a,c in [('BOS','BOS'),('Montreal Canadiens','MTL'),('Montréal Canadiens','MTL'),('LA Kings','LAK'),('Utah Mammoth','UTA')]:self.assertEqual(r.resolve('team',a,league='NHL').canonical_id,'NHL:'+c)
        self.assertEqual(r.resolve('team','New York',league='NHL').status,'ambiguous')
        e=fixture()[1]['inventory']['kalshi']['events'][0];self.assertEqual(event_key(e),event_key(dict(e,sport='ice_hockey')))
        for changes in [dict(season='2026'),dict(season='2025-2026'),dict(competition='AHL'),dict(scheduled_start='2026-10-10T23:00:00'),dict(home='NHL:NYR'),dict(participants={'New York':'NHL:NYR','BOS':'NHL:BOS'})]:
            with self.assertRaises((ValueError,KeyError)):event_key(dict(e,**changes))

    def test_supported_ev_unknowns_details_and_reopening(self):
        p,rows=projection();s=p.snapshot();self.assertEqual(len(s['games']),3)
        g=next(g for g in s['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
        refs=[reference(g),reference(g,kind='rating'),reference(g,semantics=False)];add(p,rows,refs);s=p.snapshot()
        ev=product_view.dashboard(s,dict(view='ev'),{})
        self.assertTrue(any(x['reference_id']==refs[0]['id'] and x['profit'] is not None for x in ev))
        self.assertTrue(all(x['profit'] is None for x in ev if x.get('reference_id') in [r['id'] for r in refs[1:]]))
        self.assertTrue(all(x['profit'] is None for x in ev if x['venues']==['novig']))
        key=next(k for k,v in g['sides'].items() if v['participant']=='Boston Bruins' and v['predicate']=='win')
        detail=product_view.calculate(s,g,dict(contract=key,reference=refs[0]['id']))
        self.assertIsNone(detail['ev']['unconditional_ev']);self.assertIsNone(detail['ev']['exceptional_probabilities'])
        self.assertEqual(detail['ev']['probability'],'0.6');self.assertEqual(__import__('decimal').Decimal(detail['ev']['expected_profit']),__import__('decimal').Decimal('-9.53'));self.assertIn('OT/shootout',g['title'])
        cutoff=s['durable_cursor'];self.assertEqual(session_history.project_rows(rows,cutoff),s)
        terminal=dict(type='session_finished',source='session',session_id=p.sid,observed_at=p.last,reason='owner_stop');rows.append(terminal);p.apply(terminal)
        self.assertEqual(session_history.project_rows(rows,cutoff),s)
        with self.assertRaises(ValueError):p.apply(terminal)
        from app.collection.transport_session import ObservationJournal
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/p.sid;folder.mkdir();j=ObservationJournal(folder/(p.sid+'.jsonl'))
            for row in rows:j.save(row)
            j.close();self.assertEqual(session_history.load(folder,through_cursor=cutoff),s)
        for r in refs:validate(r)
        self.assertEqual(at_cutoff(refs,'2026-09-14T00:00:00Z'),[])

    def test_semantic_failures_source_isolation_and_duplicates(self):
        variants=[dict(period='regulation'),dict(outcome_set='three_way'),dict(rules_revision=None),dict(nhl_review=None),dict(line='0'),dict(period=None)]
        for changes in variants:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0].update(changes);p,_=projection(rows);s=p.snapshot()
            self.assertTrue(any(x['source_id']=='kalshi' and x['reason'] for x in s['market_catalog']))
            self.assertEqual(len(s['games']),1)
        for field,value in [('shootout','excluded'),('cancellation','unknown')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['nhl_review']['terms'][field]=value
            self.assertEqual(len(projection(rows)[0].snapshot()['games']),1)
        rows=fixture();cat=rows[1]['inventory']['kalshi'];cat['events'].append(deepcopy(cat['events'][0]));self.assertEqual(len(projection(rows)[0].snapshot()['games']),1)
        rows=fixture();rows[1]['inventory']['kalshi']['events'][0]['scheduled_start']='2026-10-10T23:01:00+00:00'
        self.assertEqual(projection(rows)[0].snapshot()['games'],[])
        rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['product_outcomes'][0]['predicate']='unknown';self.assertEqual(len(projection(rows)[0].snapshot()['games']),1)
        rows=fixture();rows[0]['spec']['mode']='real';self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_missing_fees_and_source_times(self):
        rows=fixture();del rows[1]['inventory']['kalshi']['markets'][0]['nhl_review']['fee_basis'];p,rows=projection(rows);g=p.snapshot()['games'][0];add(p,rows,[reference(g)])
        ev=product_view.dashboard(p.snapshot(),dict(view='ev'),{});self.assertTrue(all(x['profit'] is None for x in ev if x['venues']==['kalshi']))
        r=reference(g,at='2026-10-11T00:00:00+00:00');self.assertEqual(at_cutoff([r],r['received_at'])[0]['availability'],'unsupported')

    def test_model_conflicts_immutable_cutoff_and_native_orientation(self):
        p,rows=projection();g=next(g for g in p.snapshot()['games'] if 'kalshi' in g['sources']);r=reference(g)
        add(p,rows,[r]);cutoff=p.snapshot()['durable_cursor'];saved=p.snapshot()
        later=reference(g,at='2026-09-17T12:00:00+00:00');add(p,rows,[later]);self.assertEqual(session_history.project_rows(rows,cutoff),saved)
        b=deepcopy(r['binding']);b['nhl_model_review']['home_name']='New York Rangers'
        def make(binding,body=None,source_at=None):
            rr=r['receipt'] if body is None else receipt(body,provider='moneypuck',url=r['receipt']['url'],received_at=AT,mode='synthetic')
            return published_value(rr,binding,start=r['extraction']['start'],end=r['extraction']['end'],kind='game_probability',convention='percent',source_at=source_at or r['source_at'],model_version=r['model_version'])
        self.assertEqual(at_cutoff([make(b)],AT)[0]['availability'],'unsupported')
        conflict=make(r['binding'],r['receipt']['body'].replace('60%','65%'))
        self.assertTrue(all(x['availability']=='conflicting' for x in at_cutoff([r,conflict],AT)))
        future=make(r['binding'],source_at='2026-09-18T00:00:00+00:00');self.assertEqual(at_cutoff([future],AT),[])
        self.assertEqual(at_cutoff([future],'2026-09-19T00:00:00Z')[0]['availability'],'unsupported')
        for mutate in ('native_team','native_side','review_hash','mode','missing_terms','season','stage','rule_pair'):
            rows=fixture();cat=rows[1]['inventory']['kalshi'];m=cat['markets'][0];e=cat['events'][0]
            if mutate=='native_team':
                meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']=='kalshi');native=json.loads(meta['raw']['json_text'])
                next(n for n in native['markets'] if n.get('ticker')==m['id'])['yes_sub_title']='New York Rangers';meta['raw']['json_text']=json.dumps(native);m['nhl_review']['raw_sha256']=sha256(meta['raw']['json_text'].encode()).hexdigest()
            elif mutate=='native_side':m['product_outcomes'][0]['native_id']='bad';m['nhl_review']['outcomes']=deepcopy(m['product_outcomes'])
            elif mutate=='review_hash':m['nhl_review']['raw_sha256']='0'*64
            elif mutate=='mode':m['nhl_review']['evidence_mode']='observation'
            elif mutate=='missing_terms':del m['nhl_review']['terms']['tie']
            elif mutate=='season':e['season']='2027-2028'
            elif mutate=='stage':e['stage']='preseason'
            else:m['nhl_review']['terms']['tie']='venue_fair_value'
            snap=projection(rows)[0].snapshot();self.assertEqual(len(snap['games']),1,mutate)
            self.assertTrue(next(x for x in snap['market_catalog'] if x['source_id']=='kalshi')['reason'])

    def test_playoff_overtime_scope_and_regular_season_isolation(self):
        rows=fixture()
        for source,cat in rows[1]['inventory'].items():
            e=cat['events'][0];e.update(stage='playoffs',scheduled_start='2027-05-10T23:00:00+00:00');e['canonical_key']=event_key(e)
            m=cat['markets'][0];review=m['nhl_review'];review['terms']['shootout']='not_applicable_playoffs';review['literals']['shootout']='not_applicable_playoffs'
            meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source)
            native=json.loads(meta['raw']['json_text']);native['synthetic_playoff_rule']='not_applicable_playoffs';meta['raw']['json_text']=json.dumps(native)
            review['raw_sha256']=sha256(meta['raw']['json_text'].encode()).hexdigest()
        snap=projection(rows)[0].snapshot();self.assertEqual(len(snap['games']),3)
        self.assertTrue(all('playoff OT' in g['title'] for g in snap['games']))
        rows[1]['inventory']['kalshi']['markets'][0]['nhl_review']['terms']['shootout']='included'
        self.assertEqual(len(projection(rows)[0].snapshot()['games']),1)
        self.assertEqual(Registry.load().resolve('league','NHL',venue='prophetx',environment='sandbox',native_id='234').canonical_id,'NHL')
        self.assertIn('native-id-unmapped; name-only-resolution',Registry.load().resolve('league','NHL',venue='prophetx',environment='production',native_id='234').provenance)

class StopAPI(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_stop_and_exact_saved_calculation(self):
        from tests.b5_nhl_preview import owner
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.multi_game_server import create_app
        with tempfile.TemporaryDirectory() as t:
            o=owner(Path(t));client=TestClient(TestServer(create_app(owner=o,sessions={})));await client.start_server()
            headers={'Origin':str(client.make_url('/')).rstrip('/')}
            try:
                response=await client.post('/api/start',json={'duration':60},headers=headers);self.assertEqual(response.status,200)
                snap=o.current_snapshot();token=snap['durable_cursor'];before=product_view.dashboard(o.cutoffs[token],dict(view='ev'),{})
                response=await client.post('/api/stop',json={},headers=headers);self.assertEqual(response.status,200)
                await o.finalizer;self.assertFalse(o.active());self.assertTrue(o.session.cleanup_complete)
                saved=session_history.load(o.session.output,token);self.assertEqual(product_view.dashboard(saved,dict(view='ev'),{}),before)
                with self.assertRaises(ValueError):o.session.append(fixture()[-1])
                reopened=session_history.load(o.session.output);self.assertEqual(reopened['state'],'saved')
            finally:await client.close()
