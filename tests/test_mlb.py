"""Synthetic MLB review annotations; copied price shapes are NOT MLB observations."""
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
import json
import tempfile
from pathlib import Path
import unittest
from app.normalization.mlb import RULES,FIELDS,event_key,inventory_gaps
from app.normalization.registry import Registry
from app.dashboard.session_projection import SessionProjection
from app.dashboard import product_view,session_history
from app.reference.product import receipt,published_value,at_cutoff,validate
from tests.test_nhl import fixture as nhl_fixture
from tests.test_reference_integration import add

AT='2026-09-16T12:00:00+00:00'
TERMS=dict(extra_innings='included',outcomes='two_way',tie='fraction-0.50',
    cancellation='venue_fair_value',postponement='48_hours_then_venue_fair_value',
    suspension='resume_within_48_hours_else_venue_fair_value',shortened_game='official_winner',
    listed_pitchers='action',void='venue_fair_value',refund='not_automatic',
    forfeit='pregame_fair_value_after_start_official',venue_change='same_home_away_within_48_hours',
    result_corrections='before_expiration_only')
EVENT_FIELDS=('game_id','game_number','original_start','scheduled_start','home','away','season','stage','schedule_status')


def seal(rows,source):
    cat=rows[1]['inventory'][source];e=cat['events'][0];m=cat['markets'][0]
    meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source)
    native=json.loads(meta['raw']['json_text']);review=m['mlb_review']
    native['synthetic_mlb_event']={k:e[k] for k in EVENT_FIELDS}
    native['synthetic_mlb_terms']=review['terms']
    meta['raw']['json_text']=json.dumps(native)
    review.update(raw_sha256=sha256(meta['raw']['json_text'].encode()).hexdigest(),event_binding=event_key(e),
        event_literals={k:str(e[k]) for k in EVENT_FIELDS},event_paths={k:['synthetic_mlb_event',k] for k in EVENT_FIELDS},
        literals={k:v for k,v in review['terms'].items()})
    e['canonical_key']=event_key(e)


def fixture():
    rows=nhl_fixture()
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0]
        e.update(title='SYNTHETIC MLB · Boston Red Sox vs New York Yankees',sport='baseball',competition='MLB',
            season='2026',stage='regular_season',scheduled_start='2026-10-10T23:00:00+00:00',
            original_start='2026-10-10T23:00:00+00:00',game_id='synthetic-mlb-game-1',game_number=1,
            schedule_status='scheduled',participants={'BOS':'MLB:BOS','NYY':'MLB:NYY'},home='MLB:BOS',away='MLB:NYY')
        names={'Boston Bruins':'Boston Red Sox','New York Rangers':'New York Yankees'}
        for side in m['product_outcomes']:side['participant']=names[side['participant']]
        meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source)
        body=meta['raw']['json_text']
        for old,new in names.items():body=body.replace(old,new)
        body=body.replace('KXNHLGAME','KXMLBGAME').replace('SYNTHETIC NHL','SYNTHETIC MLB')
        native=json.loads(body)
        for nm in native.get('markets',[])+[v for ev in native.get('events',[]) for v in ev.get('markets',[])]:
            if source=='kalshi' and nm.get('ticker')==m['id']:nm.update(event_ticker=e['id'],series_ticker='KXMLBGAME')
            if source=='polymarket_us' and str(nm.get('id'))==m['id']:nm['eventId']=e['id']
        native['synthetic_mlb_scope']='SYNTHETIC single full-game winner including extra innings; action'
        meta['raw']['json_text']=json.dumps(native)
        review=m.pop('nhl_review');review.update(terms=deepcopy(TERMS),outcomes=deepcopy(m['product_outcomes']),scope_literal=native['synthetic_mlb_scope'])
        if source=='kalshi':
            review['fee_basis']['series_id']='KXMLBGAME';review['fee_basis']['evidence_literal']=review['fee_basis']['evidence_literal'].replace('KXNHLGAME','KXMLBGAME')
        m.update(mlb_review=review,rules_revision=RULES)
        seal(rows,source)
    return rows


def projection(rows=None):
    p=SessionProjection();rows=fixture() if rows is None else rows
    for row in rows:p.apply(row)
    return p,rows


def reference(game,kind='game_probability',semantics=True,at=AT,mutate=None,source_at='2026-09-15T12:00:00+00:00'):
    i=deepcopy(game['product_identity']);k=i['event']
    e=dict(competition='MLB',sport='baseball',season=k[1],stage=k[2],scheduled_start=k[3],home=k[4],away=k[5],
        game_id=k[6],game_number=k[7],original_start=k[8],schedule_status=k[9],participants={'BOS':'MLB:BOS','NYY':'MLB:NYY'})
    body='SYNTHETIC Boston Red Sox home vs New York Yankees away '+k[3]+' '+k[6]+' game '+str(k[7])+' home-win including extra innings action 60%'
    b=dict(market_identity=i,participant='Boston Red Sox',source_event_id='synthetic-mlb',event_literal='Boston Red Sox home vs New York Yankees away',outcome_literal='home-win',date_literal=k[3])
    if semantics:b['mlb_model_review']=dict(event=e,published_outcome='home_win',home_name='Boston Red Sox',away_name='New York Yankees',extra_innings='included',listed_pitchers='action',home_literal='Boston Red Sox home',away_literal='New York Yankees away',semantics_literal='home-win including extra innings action')
    if mutate:mutate(b)
    r=receipt(body,provider='fangraphs',url='https://fangraphs.com/synthetic-fixture',received_at=at,mode='synthetic')
    return published_value(r,b,start=len(body)-3,end=len(body),kind=kind,convention='percent',source_at=source_at,model_version='SYNTHETIC MLB fixture; not a provider forecast')


class MLB(unittest.TestCase):
    def test_registry_aliases_and_native_orientation(self):
        r=Registry.load();self.assertEqual(len([e for e in r.entities.values() if e.get('league')=='MLB']),30)
        for alias,cid in [('BOS','BOS'),('NY Yankees','NYY'),('Athletics','ATH'),('LA Dodgers','LAD')]:
            self.assertEqual(r.resolve('team',alias,league='MLB').canonical_id,'MLB:'+cid)
        self.assertEqual(r.resolve('team','New York',league='MLB').status,'ambiguous')
        p,_=projection();s=p.snapshot();self.assertEqual(len(s['games']),1)
        g=s['games'][0];self.assertEqual(set(g['sources']),{'kalshi','polymarket_us'})
        self.assertEqual({(v['participant'],v['predicate']) for v in g['sides'].values()}, {('Boston Red Sox','win'),('Boston Red Sox','not_win'),('New York Yankees','win')})
        for source in ('kalshi','polymarket_us'):
            rows=fixture();m=rows[1]['inventory'][source]['markets'][0];
            for side in m['product_outcomes']:side['participant']='New York Yankees' if side['participant']=='Boston Red Sox' else 'Boston Red Sox'
            m['mlb_review']['outcomes']=deepcopy(m['product_outcomes']);self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_game_identity_and_conflicts(self):
        e=fixture()[1]['inventory']['kalshi']['events'][0]
        self.assertEqual(event_key(e),event_key(dict(e,scheduled_start='2026-10-10T19:00:00-04:00')))
        for changes in [dict(season='2025'),dict(season=None),dict(game_id=None),dict(game_number=None),dict(game_number=True),dict(schedule_status='suspended'),dict(scheduled_start='2026-10-10T23:00:00'),dict(home='MLB:NYY'),dict(competition='NPB')]:
            with self.assertRaises((ValueError,KeyError,TypeError)):event_key(dict(e,**changes))
        for changes in [dict(game_id='other'),dict(game_number=2),dict(stage='playoffs'),dict(scheduled_start='2026-10-11T23:00:00+00:00',schedule_status='rescheduled')]:
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0].update(changes)
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],changes)
        rows=fixture();cat=rows[1]['inventory']['kalshi'];cat['events'].append(deepcopy(cat['events'][0]))
        self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_doubleheaders_repeated_games_and_reschedules(self):
        rows=fixture();inv=rows[1]['inventory']
        for source,cat in inv.items():
            e=deepcopy(cat['events'][0]);e.update(id=e['id']+'-second',game_id='synthetic-mlb-game-2',game_number=2,scheduled_start='2026-10-11T02:00:00+00:00',original_start='2026-10-11T02:00:00+00:00');cat['events'].append(e)
        self.assertEqual(inventory_gaps(inv),{})
        self.assertNotEqual(event_key(inv['kalshi']['events'][0]),event_key(inv['kalshi']['events'][1]))
        for source,cat in inv.items():
            e=cat['events'][1];e.update(game_number=1,scheduled_start='2026-10-12T23:00:00+00:00',original_start='2026-10-12T23:00:00+00:00')
        self.assertEqual(inventory_gaps(inv),{})
        rows=fixture()
        for source,cat in rows[1]['inventory'].items():
            cat['events'][0].update(scheduled_start='2026-10-11T23:00:00+00:00',schedule_status='rescheduled');seal(rows,source)
        self.assertEqual(len(projection(rows)[0].snapshot()['games']),1)
        # A changed projection without fresh retained native identity is unsupported.
        rows[1]['inventory']['kalshi']['events'][0]['game_number']=2
        self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_period_terms_and_native_evidence_fail_closed(self):
        for changes in [dict(period='innings_1_5'),dict(period='inning_1'),dict(period='innings_6_9'),dict(market_type='series_winner'),dict(market_type='futures'),dict(horizon='2026'),dict(line='0'),dict(outcome_set='three_way'),dict(mlb_review=None)]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0].update(changes);s=projection(rows)[0].snapshot()
            self.assertEqual(s['games'],[],changes);self.assertTrue(next(c for c in s['market_catalog'] if c['source_id']=='kalshi')['reason'])
        for field in FIELDS:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['mlb_review']['terms'][field]='unknown'
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],field)
        for field,value in [('listed_pitchers','listed:home:123-away:456'),('extra_innings','excluded'),('shortened_game','must_complete_9'),('tie','refund'),('suspension','next_day_only'),('refund','return_stake')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['mlb_review']['terms'][field]=value;seal(rows,'kalshi')
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],field)
        for field in ('raw_sha256','outcome_literal','event_paths','scope_literal'):
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['mlb_review'].pop(field)
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],field)
        rows=fixture();rows[0]['spec']['mode']='real';self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_conditional_math_model_and_unknowns(self):
        p,rows=projection();s=p.snapshot();g=s['games'][0]
        arb=product_view.dashboard(s,dict(view='arb'),{});self.assertTrue(any(v['profit'] is not None for v in arb))
        self.assertTrue(all(v['profit'] is None for v in product_view.dashboard(s,dict(view='ev'),{})))
        refs=[reference(g),reference(g,kind='rating'),reference(g,kind='season_probability'),reference(g,semantics=False)]
        add(p,rows,refs);s=p.snapshot();ev=product_view.dashboard(s,dict(view='ev'),{})
        self.assertTrue(any(v['reference_id']==refs[0]['id'] and v['profit'] is not None for v in ev))
        self.assertTrue(all(v['profit'] is None for v in ev if v.get('reference_id') in [r['id'] for r in refs[1:]]))
        key=next(k for k,v in g['sides'].items() if k.startswith('kalshi:') and v['predicate']=='win')
        detail=product_view.calculate(s,g,dict(contract=key,reference=refs[0]['id']))
        self.assertEqual(Decimal(detail['ev']['expected_profit']),Decimal('-9.53'));self.assertEqual(detail['ev']['probability'],'0.6')
        self.assertIsNone(detail['ev']['unconditional_ev']);self.assertIsNone(detail['ev']['exceptional_probabilities'])
        for r in refs:validate(r)
        for source in ('kalshi','polymarket_us'):
            rr=fixture();del rr[1]['inventory'][source]['markets'][0]['mlb_review']['fee_basis'];ss=projection(rr)[0].snapshot()
            self.assertTrue(all(v['profit'] is None for v in product_view.dashboard(ss,dict(view='arb'),{})))

    def test_two_doubleheader_comparisons_never_cross_pair(self):
        rows=fixture();second=fixture()
        for source,cat in second[1]['inventory'].items():
            cat['events'][0].update(game_id='synthetic-mlb-game-2',game_number=2,scheduled_start='2026-10-10T20:00:00+00:00',original_start='2026-10-10T20:00:00+00:00')
            seal(second,source)
        second=json.loads(json.dumps(second).replace('-e0','-e2').replace('-m0','-m2'))
        # Body hashes change when native listing IDs change.
        for source,cat in second[1]['inventory'].items():
            seal(second,source)
            for field in ('events','markets'):rows[1]['inventory'][source][field]+=cat[field]
            rows[1]['inventory'][source]['selection']['ids']+=cat['selection']['ids']
        rows+=second[2:];snap=projection(rows)[0].snapshot()
        self.assertEqual(len(snap['games']),2)
        self.assertEqual({g['product_identity']['event'][7] for g in snap['games']},{1,2})
        for g in snap['games']:
            self.assertEqual(len({v['event_id'][-1] for v in g['sources'].values()}),1)

    def test_native_identity_conflict_and_missing_depth_source_isolation(self):
        for field,value in [('season','2027'),('game_id','wrong'),('home','MLB:NYY')]:
            rows=fixture();meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']=='kalshi')
            native=json.loads(meta['raw']['json_text']);native['synthetic_mlb_event'][field]=value
            meta['raw']['json_text']=json.dumps(native)
            rows[1]['inventory']['kalshi']['markets'][0]['mlb_review']['raw_sha256']=sha256(meta['raw']['json_text'].encode()).hexdigest()
            self.assertEqual(projection(rows)[0].snapshot()['games'],[])
        p,rows=projection();s=p.snapshot();g=s['games'][0]
        self.assertTrue(any(v['profit'] is None and v['modeled_quantity']=='0' for v in product_view.dashboard(s,dict(view='arb'),{})))
        p.apply(dict(type='source_health',source='novig',session_id=p.sid,observed_at=p.last,state='disconnected'))
        self.assertEqual([(v['profit'],v['usable'],v['legs']) for v in product_view.dashboard(s,dict(view='arb'),{})],[(v['profit'],v['usable'],v['legs']) for v in product_view.dashboard(p.snapshot(),dict(view='arb'),{})])
        p.apply(dict(type='source_health',source='kalshi',session_id=p.sid,observed_at=p.last,state='disconnected'))
        self.assertTrue(all(not v['usable'] for v in product_view.dashboard(p.snapshot(),dict(view='arb'),{})))
        # Manual probabilities remain labeled what-if inputs, never model receipts.
        key=next(k for k in g['sides'] if k.startswith('kalshi:yes'))
        manual=product_view.dashboard(s,dict(view='ev'),{g['id']+'~'+key:dict(probability='0.6',basis='Manual what-if')})
        self.assertTrue(any(v['assumption']=='Manual what-if' and v['reference_id'] is None for v in manual))

    def test_series_specific_fee_multiplier_and_future_native_input(self):
        rows=fixture();review=rows[1]['inventory']['kalshi']['markets'][0]['mlb_review']
        review['fee_basis']['multiplier']='0.5'
        meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']=='kalshi')
        old=review['fee_basis']['evidence_literal'];new=old.replace('multiplier 1','multiplier 0.5')
        meta['raw']['json_text']=meta['raw']['json_text'].replace(old,new);review['fee_basis']['evidence_literal']=new;seal(rows,'kalshi')
        p,rows=projection(rows);g=p.snapshot()['games'][0];r=reference(g);add(p,rows,[r])
        key=next(k for k in g['sides'] if k.startswith('kalshi:yes'))
        ev=product_view.calculate(p.snapshot(),g,dict(contract=key,reference=r['id']))['ev']
        self.assertEqual(Decimal(ev['expected_profit']),Decimal('-8.77'))
        for typ in ('market_selected','prediction_book'):
            for field in ('received_at','exchange_at'):
                rows=fixture();row=next(r for r in rows if r['type']==typ and r['source']=='kalshi')
                row.get('market',row.get('book'))['raw'][field]='2026-09-18T00:00:00Z'
                self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_model_binding_and_future_cutoff(self):
        p,rows=projection();g=p.snapshot()['games'][0]
        for mutate in [lambda b:b['mlb_model_review']['event'].update(game_id='wrong'),lambda b:b['mlb_model_review']['event'].update(game_number=2),lambda b:b['mlb_model_review'].update(home_name='New York Yankees'),lambda b:b['mlb_model_review'].update(extra_innings='unknown')]:
            r=reference(g,mutate=mutate);self.assertEqual(at_cutoff([r],AT)[0]['availability'],'unsupported')
        legacy=reference(g);legacy.pop('schema_version')
        self.assertFalse(product_view.usable(legacy))
        self.assertEqual(at_cutoff([legacy],AT)[0]['availability'],'unsupported')
        future=reference(g,source_at='2026-09-18T00:00:00Z');self.assertEqual(at_cutoff([future],AT),[])
        self.assertEqual(at_cutoff([future],'2026-09-19T00:00:00Z')[0]['availability'],'unsupported')
        add(p,rows,[reference(g)]);snap=p.snapshot();token=snap['durable_cursor']
        add(p,rows,[reference(g,at='2026-09-17T12:00:00Z')]);self.assertEqual(session_history.project_rows(rows,token),snap)

class StopAPI(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_stop_and_exact_saved_calculation(self):
        from tests.mlb_preview import owner
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
