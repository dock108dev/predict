"""Synthetic NCAAB review annotations; copied price shapes and compatible terms are NOT NCAAB observations."""
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
import json
import tempfile
from pathlib import Path
import unittest
from app.normalization.ncaab import RULES,FIELDS,EVENT_FIELDS,CONTEXT_FIELDS,event_key,inventory_gaps
from app.normalization.registry import Registry
from app.dashboard.session_projection import SessionProjection
from app.dashboard import product_view,session_history
from app.reference.product import receipt,published_value,at_cutoff,validate
from tests.test_b5_nhl import fixture as nhl_fixture
from tests.test_b4_reference import add

AT='2026-09-16T12:00:00+00:00'
TERMS=dict(overtime='included',outcomes='two_way',tie='fraction-0.50',
    cancellation='venue_fair_value',postponement='synthetic_reviewed_deadline_then_fair_value',
    suspension='resume_within_48_hours_else_venue_fair_value',shortened_game='synthetic_official_result_only',
    abandonment='venue_fair_value',void='venue_fair_value',refund='not_automatic',
    forfeit='pregame_fair_value_after_start_official',venue_change='same_home_away_within_48_hours',
    result_corrections='before_expiration_only',regulation_format='two_20_minute_halves',overtime_format='repeated_5_minutes')


def seal(rows,source):
    cat=rows[1]['inventory'][source];e=cat['events'][0];m=cat['markets'][0]
    meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source)
    native=json.loads(meta['raw']['json_text']);review=m['ncaab_review']
    native['synthetic_ncaab_event']={k:e[k] for k in EVENT_FIELDS}
    native['synthetic_ncaab_terms']=review['terms']
    meta['raw']['json_text']=json.dumps(native)
    review.update(raw_sha256=sha256(meta['raw']['json_text'].encode()).hexdigest(),event_binding=event_key(e),
        event_literals={k:json.dumps(e[k]) if isinstance(e[k],dict) else str(e[k]) for k in EVENT_FIELDS},event_paths={k:['synthetic_ncaab_event',k] for k in EVENT_FIELDS},
        literals={k:v for k,v in review['terms'].items()})
    e['canonical_key']=event_key(e)


def fixture():
    rows=nhl_fixture()
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0]
        e.update(title='SYNTHETIC NCAAB · Alabama Crimson Tide vs Alabama A&M Bulldogs',sport='basketball',competition='NCAAB',
            season='2026-2027',stage='regular_season',scheduled_start='2026-11-10T23:00:00+00:00',
            original_start='2026-11-10T23:00:00+00:00',game_id='synthetic-ncaab-game-1',
            schedule_status='scheduled',participants={'ALA':'NCAAB:M:D1:ALA','AAMU':'NCAAB:M:D1:AAMU'},home='NCAAB:M:D1:ALA',away='NCAAB:M:D1:AAMU',schools={'NCAAB:M:D1:ALA':'school:ALA','NCAAB:M:D1:AAMU':'school:AAMU'},neutral_site='neutral',gender='men',division='I',competition_id='NCAA:M:D1',period_structure='two_20_minute_halves',tournament_id='not_applicable',round='not_applicable')
        names={'Boston Bruins':'Alabama Crimson Tide','New York Rangers':'Alabama A&M Bulldogs'}
        for side in m['product_outcomes']:side['participant']=names[side['participant']]
        meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source)
        body=meta['raw']['json_text']
        for old,new in names.items():body=body.replace(old,new)
        body=body.replace('KXNHLGAME','KXNCAAMBGAME').replace('SYNTHETIC NHL','SYNTHETIC NCAAB')
        native=json.loads(body)
        for nm in native.get('markets',[])+[v for ev in native.get('events',[]) for v in ev.get('markets',[])]:
            if source=='kalshi' and nm.get('ticker')==m['id']:nm.update(event_ticker=e['id'],series_ticker='KXNCAAMBGAME')
            if source=='polymarket_us' and str(nm.get('id'))==m['id']:nm['eventId']=e['id']
        native['synthetic_ncaab_scope']='SYNTHETIC single full-game winner including overtime'
        meta['raw']['json_text']=json.dumps(native)
        review=m.pop('nhl_review');review.update(terms=deepcopy(TERMS),outcomes=deepcopy(m['product_outcomes']),scope_literal=native['synthetic_ncaab_scope'])
        if source=='kalshi':
            review['fee_basis']['series_id']='KXNCAAMBGAME';review['fee_basis']['evidence_literal']=review['fee_basis']['evidence_literal'].replace('KXNHLGAME','KXNCAAMBGAME')
        m.update(ncaab_review=review,rules_revision=RULES)
        seal(rows,source)
    return rows


def coverage_fixture():
    rows=fixture();cat=rows[1]['inventory']['kalshi']
    e=deepcopy(cat['events'][0]);e.update(id='synthetic-unresolved-school',title='SYNTHETIC unresolved schools · Bulldogs vs Miami',game_id='synthetic-unresolved',participants={'Bulldogs':'NCAAB:M:D1:UNKNOWN','Miami':'NCAAB:M:D1:MIAFL'})
    m=deepcopy(cat['markets'][0]);m.update(id='synthetic-unresolved-market',event_id=e['id'])
    cat['events'].append(e);cat['markets'].append(m);cat['selection']['ids'].append(m['id'])
    e=deepcopy(cat['events'][0]);e.update(id='synthetic-women',title='SYNTHETIC women same school names',gender='women',competition_id='NCAA:W:D1',game_id='synthetic-women')
    m=deepcopy(cat['markets'][0]);m.update(id='synthetic-women-market',event_id=e['id'])
    cat['events'].append(e);cat['markets'].append(m);cat['selection']['ids'].append(m['id'])
    return rows


def projection(rows=None):
    p=SessionProjection();rows=fixture() if rows is None else rows
    for row in rows:p.apply(row)
    return p,rows


def reference(game,kind='game_probability',semantics=True,at=AT,mutate=None,source_at='2026-09-15T12:00:00+00:00'):
    i=deepcopy(game['product_identity']);k=i['event']
    e=dict(competition='NCAAB',sport='basketball',season=k[1],stage=k[2],scheduled_start=k[3],home=k[4],away=k[5],
        game_id=k[6],original_start=k[7],schedule_status=k[8],participants={'ALA':'NCAAB:M:D1:ALA','AAMU':'NCAAB:M:D1:AAMU'},
        gender=k[9],division=k[10],competition_id=k[11],neutral_site=k[12],tournament_id=k[13],round=k[14],period_structure=k[15],schools=dict(k[16]))
    body='SYNTHETIC Alabama Crimson Tide home vs Alabama A&M Bulldogs away '+k[3]+' '+k[6]+' NCAAB '+k[1]+' '+k[2]+' '+k[7]+' '+json.dumps({f:e[f] for f in CONTEXT_FIELDS},sort_keys=True)+' home-win including overtime 60%'
    b=dict(market_identity=i,participant='Alabama Crimson Tide',source_event_id='synthetic-ncaab',event_literal='Alabama Crimson Tide home vs Alabama A&M Bulldogs away',outcome_literal='home-win',date_literal=k[3])
    if semantics:
        review=dict(event=e,published_outcome='home_win',home_name='Alabama Crimson Tide',away_name='Alabama A&M Bulldogs',overtime='included',home_literal='Alabama Crimson Tide home',away_literal='Alabama A&M Bulldogs away',semantics_literal='home-win including overtime')
        for f in CONTEXT_FIELDS:review.update({f:e[f],f+'_literal':json.dumps({f:e[f]},sort_keys=True)[1:-1]})
        b['ncaab_model_review']=review
    if mutate:mutate(b)
    r=receipt(body,provider='espn_bpi',url='https://www.espn.com/synthetic-fixture',received_at=at,mode='synthetic')
    return published_value(r,b,start=len(body)-3,end=len(body),kind=kind,convention='percent',source_at=source_at,model_version='SYNTHETIC NCAAB fixture; not a provider forecast')


class NCAAB(unittest.TestCase):
    def test_registry_aliases_and_native_orientation(self):
        r=Registry.load();self.assertEqual(len([e for e in r.entities.values() if e.get('league')=='NCAAB']),4)
        for alias,cid in [('ALA','ALA'),('AAMU','AAMU'),('Miami University','MIAOH'),('University of Miami','MIAFL')]:
            self.assertEqual(r.resolve('team',alias,league='NCAAB').canonical_id,'NCAAB:M:D1:'+cid)
        self.assertEqual(r.resolve('team','Miami',league='NCAAB').status,'ambiguous')
        p,_=projection();s=p.snapshot();self.assertEqual(len(s['games']),1)
        g=s['games'][0];self.assertEqual(set(g['sources']),{'kalshi','polymarket_us'})
        self.assertEqual({(v['participant'],v['predicate']) for v in g['sides'].values()}, {('Alabama Crimson Tide','win'),('Alabama Crimson Tide','not_win'),('Alabama A&M Bulldogs','win')})
        for source in ('kalshi','polymarket_us'):
            rows=fixture();m=rows[1]['inventory'][source]['markets'][0];
            for side in m['product_outcomes']:side['participant']='Alabama A&M Bulldogs' if side['participant']=='Alabama Crimson Tide' else 'Alabama Crimson Tide'
            m['ncaab_review']['outcomes']=deepcopy(m['product_outcomes']);self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_game_identity_and_conflicts(self):
        e=fixture()[1]['inventory']['kalshi']['events'][0]
        self.assertEqual(event_key(e),event_key(dict(e,scheduled_start='2026-11-10T19:00:00-04:00')))
        for changes in [dict(season='2025'),dict(season=None),dict(game_id=None),dict(schedule_status='suspended'),dict(scheduled_start='2026-11-10T23:00:00'),dict(home='NCAAB:M:D1:AAMU'),dict(competition='NFL'),dict(competition='NCAAF'),dict(stage='summer_league'),dict(season='2026-2028')]:
            with self.assertRaises((ValueError,KeyError,TypeError)):event_key(dict(e,**changes))
        for changes in [dict(game_id='other'),dict(stage='conference_tournament'),dict(stage='ncaa_tournament'),dict(scheduled_start='2026-11-11T23:00:00+00:00',schedule_status='rescheduled')]:
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0].update(changes)
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],changes)
        rows=fixture();cat=rows[1]['inventory']['kalshi'];cat['events'].append(deepcopy(cat['events'][0]))
        self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_repeated_games_and_reschedules(self):
        rows=fixture();inv=rows[1]['inventory']
        for source,cat in inv.items():
            e=deepcopy(cat['events'][0]);e.update(id=e['id']+'-second',game_id='synthetic-ncaab-game-2',scheduled_start='2026-11-11T02:00:00+00:00',original_start='2026-11-11T02:00:00+00:00');cat['events'].append(e)
        self.assertEqual(inventory_gaps(inv),{})
        self.assertNotEqual(event_key(inv['kalshi']['events'][0]),event_key(inv['kalshi']['events'][1]))
        for source,cat in inv.items():
            e=cat['events'][1];e.update(scheduled_start='2026-11-12T23:00:00+00:00',original_start='2026-11-12T23:00:00+00:00')
        self.assertEqual(inventory_gaps(inv),{})
        rows=fixture()
        for source,cat in rows[1]['inventory'].items():
            cat['events'][0].update(scheduled_start='2026-11-11T23:00:00+00:00',schedule_status='rescheduled');seal(rows,source)
        self.assertEqual(len(projection(rows)[0].snapshot()['games']),1)
        # A changed projection without fresh retained native identity is unsupported.
        rows[1]['inventory']['kalshi']['events'][0]['stage']='playoffs'
        self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_period_terms_and_native_evidence_fail_closed(self):
        for changes in [dict(period='regulation'),dict(period='half_1'),dict(period='quarter_1'),dict(market_type='series_winner'),dict(market_type='futures'),dict(horizon='2026'),dict(line='0'),dict(outcome_set='three_way'),dict(ncaab_review=None)]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0].update(changes);s=projection(rows)[0].snapshot()
            self.assertEqual(s['games'],[],changes);self.assertTrue(next(c for c in s['market_catalog'] if c['source_id']=='kalshi')['reason'])
        for field in FIELDS:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['ncaab_review']['terms'][field]='unknown'
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],field)
        for field,value in [('overtime','excluded'),('shortened_game','must_complete_48_minutes'),('tie','refund'),('suspension','next_day_only'),('refund','return_stake')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['ncaab_review']['terms'][field]=value;seal(rows,'kalshi')
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],field)
        for field in ('raw_sha256','outcome_literal','event_paths','scope_literal'):
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['ncaab_review'].pop(field)
            self.assertEqual(projection(rows)[0].snapshot()['games'],[],field)
        rows=fixture();rows[0]['spec']['mode']='real';self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_conditional_math_model_and_unknowns(self):
        p,rows=projection();s=p.snapshot();g=s['games'][0]
        arb=product_view.dashboard(s,dict(view='arb'),{});self.assertTrue(any(v['profit'] is not None for v in arb))
        self.assertTrue(all(v['profit'] is None for v in product_view.dashboard(s,dict(view='ev'),{})))
        refs=[reference(g),reference(g,kind='rating'),reference(g,kind='season_probability'),reference(g,kind='projected_margin'),reference(g,kind='rank'),reference(g,semantics=False)]
        add(p,rows,refs);s=p.snapshot();ev=product_view.dashboard(s,dict(view='ev'),{})
        self.assertTrue(any(v['reference_id']==refs[0]['id'] and v['profit'] is not None for v in ev))
        self.assertTrue(all(v['profit'] is None for v in ev if v.get('reference_id') in [r['id'] for r in refs[1:]]))
        key=next(k for k,v in g['sides'].items() if k.startswith('kalshi:') and v['predicate']=='win')
        detail=product_view.calculate(s,g,dict(contract=key,reference=refs[0]['id']))
        self.assertEqual(Decimal(detail['ev']['expected_profit']),Decimal('-9.53'));self.assertEqual(detail['ev']['probability'],'0.6')
        self.assertIsNone(detail['ev']['unconditional_ev']);self.assertIsNone(detail['ev']['exceptional_probabilities'])
        for r in refs:validate(r)
        for source in ('kalshi','polymarket_us'):
            rr=fixture();del rr[1]['inventory'][source]['markets'][0]['ncaab_review']['fee_basis'];ss=projection(rr)[0].snapshot()
            self.assertTrue(all(v['profit'] is None for v in product_view.dashboard(ss,dict(view='arb'),{})))

    def test_two_repeated_comparisons_never_cross_pair(self):
        rows=fixture();second=fixture()
        for source,cat in second[1]['inventory'].items():
            cat['events'][0].update(game_id='synthetic-ncaab-game-2',scheduled_start='2026-11-12T23:00:00+00:00',original_start='2026-11-12T23:00:00+00:00')
            seal(second,source)
        second=json.loads(json.dumps(second).replace('-e0','-e2').replace('-m0','-m2'))
        # Body hashes change when native listing IDs change.
        for source,cat in second[1]['inventory'].items():
            seal(second,source)
            for field in ('events','markets'):rows[1]['inventory'][source][field]+=cat[field]
            rows[1]['inventory'][source]['selection']['ids']+=cat['selection']['ids']
        rows+=second[2:];snap=projection(rows)[0].snapshot()
        self.assertEqual(len(snap['games']),2)
        self.assertEqual({g['product_identity']['event'][6] for g in snap['games']},{'synthetic-ncaab-game-1','synthetic-ncaab-game-2'})
        for g in snap['games']:
            self.assertEqual(len({v['event_id'][-1] for v in g['sources'].values()}),1)

    def test_native_identity_conflict_and_missing_depth_source_isolation(self):
        for field,value in [('season','2027-2028'),('game_id','wrong'),('home','NCAAB:M:D1:AAMU'),('competition','NFL'),('sport','american_football')]:
            rows=fixture();meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']=='kalshi')
            native=json.loads(meta['raw']['json_text']);native['synthetic_ncaab_event'][field]=value
            meta['raw']['json_text']=json.dumps(native)
            rows[1]['inventory']['kalshi']['markets'][0]['ncaab_review']['raw_sha256']=sha256(meta['raw']['json_text'].encode()).hexdigest()
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
        rows=fixture();review=rows[1]['inventory']['kalshi']['markets'][0]['ncaab_review']
        review['fee_basis']['multiplier']='0.5'
        self.assertTrue(all(v['profit'] is None for v in product_view.dashboard(projection(rows)[0].snapshot(),dict(view='arb'),{})))
        for typ in ('market_selected','prediction_book'):
            for field in ('received_at','exchange_at'):
                rows=fixture();row=next(r for r in rows if r['type']==typ and r['source']=='kalshi')
                row.get('market',row.get('book'))['raw'][field]='2026-09-18T00:00:00Z'
                self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_model_binding_and_future_cutoff(self):
        p,rows=projection();g=p.snapshot()['games'][0]
        for mutate in [lambda b:b['ncaab_model_review']['event'].update(game_id='wrong'),lambda b:b['ncaab_model_review']['event'].update(stage='conference_tournament'),lambda b:b['ncaab_model_review'].update(home_name='Alabama A&M Bulldogs'),lambda b:b['ncaab_model_review'].update(overtime='unknown')]:
            r=reference(g,mutate=mutate);self.assertEqual(at_cutoff([r],AT)[0]['availability'],'unsupported')
        legacy=reference(g);legacy.pop('schema_version')
        self.assertFalse(product_view.usable(legacy))
        self.assertEqual(at_cutoff([legacy],AT)[0]['availability'],'unsupported')
        future=reference(g,source_at='2026-09-18T00:00:00Z');self.assertEqual(at_cutoff([future],AT),[])
        self.assertEqual(at_cutoff([future],'2026-09-19T00:00:00Z')[0]['availability'],'unsupported')
        add(p,rows,[reference(g)]);snap=p.snapshot();token=snap['durable_cursor']
        add(p,rows,[reference(g,at='2026-09-17T12:00:00Z')]);self.assertEqual(session_history.project_rows(rows,token),snap)

    def test_explicit_away_probability_and_native_series_isolation(self):
        p,rows=projection();g=p.snapshot()['games'][0]
        r=reference(g);b=deepcopy(r['binding'])
        b['participant']='Alabama A&M Bulldogs';b['outcome_literal']='away-win'
        b['ncaab_model_review'].update(published_outcome='away_win',semantics_literal='away-win including overtime')
        body=r['receipt']['body'].replace('home-win','away-win')
        native=receipt(body,provider='espn_bpi',url='https://www.espn.com/synthetic-fixture',received_at=AT,mode='synthetic')
        away=published_value(native,b,start=len(body)-3,end=len(body),kind='game_probability',convention='percent',source_at='2026-09-15T12:00:00Z',model_version='SYNTHETIC explicitly published away output')
        self.assertEqual(at_cutoff([away],AT)[0]['availability'],'available')
        add(p,rows,[away]);ev=product_view.dashboard(p.snapshot(),dict(view='ev'),{})
        priced=[v for v in ev if v['profit'] is not None]
        self.assertTrue(priced)
        self.assertTrue(all(v['reference_id']==away['id'] for v in priced))
        # The receipt's 60% is used directly, never complemented to 40%.
        side=next(k for k,v in g['sides'].items() if v['participant']=='Alabama A&M Bulldogs' and v['predicate']=='win')
        self.assertEqual(product_view.calculate(p.snapshot(),g,dict(contract=side,reference=away['id']))['ev']['probability'],'0.6')
        for series in ('KXNBAGAME','KXNCAAWBGAME','KXNFLGAME'):
            rr=fixture();meta=next(r['market'] for r in rr if r['type']=='market_selected' and r['source']=='kalshi')
            meta['raw']['json_text']=meta['raw']['json_text'].replace('KXNCAAMBGAME',series);seal(rr,'kalshi')
            self.assertEqual(projection(rr)[0].snapshot()['games'],[])

    def test_kalshi_series_parser_does_not_guess_start_or_expand_defaults(self):
        from app.adapters.kalshi import Response,parse_event,KalshiAdapter
        from datetime import datetime
        event=dict(event_ticker='synthetic-ncaab',series_ticker='KXNCAAMBGAME',title='Alabama Crimson Tide vs Alabama A&M Bulldogs')
        body=json.dumps(dict(events=[event],milestones=[dict(category='Sports',type='basketball_game',related_event_tickers=['synthetic-ncaab'],start_date='2026-11-10T23:00:00Z')]))
        parsed=parse_event(Response(body,'fixture:synthetic',datetime.fromisoformat(AT)),event,'KXNCAAMBGAME')
        self.assertEqual((parsed.sport,parsed.league),('basketball','NCAAB'))
        self.assertIsNone(parsed.scheduled_start)
        import inspect
        self.assertEqual(inspect.signature(KalshiAdapter).parameters['series'].default,('KXNFLGAME','KXMLBGAME'))


    def test_generic_names_only_matcher_cannot_qualify_college(self):
        from app.matching_example import synthetic
        from app.matching import compare
        from app.models.core import Venue
        a=synthetic('men',league='NCAAB',names=('Alabama','Alabama A&M'))
        b=synthetic('women',Venue.KALSHI,league='NCAAB',names=('Alabama','Alabama A&M'))
        self.assertFalse(a['valid_identity']);self.assertFalse(b['valid_identity'])
        self.assertEqual(compare(a,b,900)[0],'unmatched')

    def test_competition_school_season_and_period_isolation(self):
        e=fixture()[1]['inventory']['kalshi']['events'][0]
        for changes in [dict(gender='women'),dict(gender=None),dict(division='II'),dict(division='III'),dict(competition_id='NCAA:W:D1'),dict(competition='NBA'),dict(competition='WNBA'),dict(period_structure='four_10_minute_quarters'),dict(period_structure='four_12_minute_quarters'),dict(schools={}),dict(schools={'NCAAB:M:D1:ALA':'school:AAMU','NCAAB:M:D1:AAMU':'school:ALA'}),dict(season='2027-2028',scheduled_start='2027-11-10T23:00:00Z',original_start='2027-11-10T23:00:00Z')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):event_key(dict(e,**changes))
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0].update(changes)
            self.assertEqual(projection(rows)[0].snapshot()['games'],[])
        r=Registry.load()
        for alias in ('Bulldogs','Tigers','Hurricanes','SDSU','USC','State','Miami Hamilton','Miami Middletown','Alabama Huntsville','Invented University'):
            self.assertEqual(r.resolve('team',alias,league='NCAAB').status,'unknown')
        self.assertNotEqual(r.resolve('team','ALA',league='NCAAB').canonical_id,r.resolve('team','ALA',league='NCAAF').canonical_id)
        for source in ('kalshi','polymarket_us'):
            for field,value in [('gender','women'),('division','II'),('competition_id','NCAA:W:D1'),('neutral_site','home'),('round','final'),('schools',{})]:
                rows=fixture();meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source)
                native=json.loads(meta['raw']['json_text']);native['synthetic_ncaab_event'][field]=value;meta['raw']['json_text']=json.dumps(native)
                rows[1]['inventory'][source]['markets'][0]['ncaab_review']['raw_sha256']=sha256(meta['raw']['json_text'].encode()).hexdigest()
                self.assertEqual(projection(rows)[0].snapshot()['games'],[])

    def test_tournament_round_site_and_model_context(self):
        for stage in ('in_season_tournament','conference_tournament','ncaa_tournament','other_postseason_tournament'):
            rows=fixture()
            for source,cat in rows[1]['inventory'].items():
                cat['events'][0].update(stage=stage,tournament_id='synthetic-tournament-2027',round='semifinal',scheduled_start='2027-03-10T23:00:00Z',original_start='2027-03-10T23:00:00Z');seal(rows,source)
            p,_=projection(rows);g=p.snapshot()['games'][0]
            self.assertEqual(at_cutoff([reference(g)],AT)[0]['availability'],'available')
            other=dict(rows[1]['inventory']['kalshi']['events'][0],round='final')
            self.assertNotEqual(event_key(other),g['product_identity']['event'])
            rows[1]['inventory']['kalshi']['events'][0]['round']='final';seal(rows,'kalshi')
            self.assertEqual(projection(rows)[0].snapshot()['games'],[])
        for site in ('neutral','home','unknown'):
            rows=fixture()
            for source,cat in rows[1]['inventory'].items():cat['events'][0]['neutral_site']=site;seal(rows,source)
            g=projection(rows)[0].snapshot()['games'][0];self.assertIn('site: '+site,g['title'])
            ref=reference(g);self.assertEqual(at_cutoff([ref],AT)[0]['availability'],'available')
            self.assertEqual(ref['independence'],'not_established')
        g=projection()[0].snapshot()['games'][0]
        for field in CONTEXT_FIELDS:
            for value in (None,'wrong'):
                r=reference(g,mutate=lambda b:b['ncaab_model_review'].update({field:value}))
                self.assertEqual(at_cutoff([r],AT)[0]['availability'],'unsupported',field)
                r=reference(g,mutate=lambda b:b['ncaab_model_review'].update({field+'_literal':'absent'}))
                self.assertEqual(at_cutoff([r],AT)[0]['availability'],'unsupported',field)
        for changes in [dict(stage='ncaa_tournament'),dict(round='semifinal'),dict(neutral_site=None)]:
            with self.assertRaises(ValueError):event_key(dict(fixture()[1]['inventory']['kalshi']['events'][0],**changes))

    def test_college_fee_scope_unknown_size_and_filters(self):
        for changes in [dict(series_id='KXNBAGAME'),dict(series_id='KXNCAAWBGAME'),dict(series_id='KXNCAAFGAME'),dict(fee_type='quadratic'),dict(multiplier='0.5')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['ncaab_review']['fee_basis'].update(changes)
            self.assertTrue(all(v['profit'] is None for v in product_view.dashboard(projection(rows)[0].snapshot(),dict(view='arb'),{})))
        s=projection()[0].snapshot()
        self.assertEqual(product_view.dashboard(s,dict(view='arb',search='not a school'),{}),[])
        self.assertEqual(len(product_view.dashboard(s,dict(view='arb',search='Alabama'),{})),2)
        for point in s['points'].values():
            for card in point['cards']:
                if card['venue']=='kalshi':
                    for outcome in card['book']['outcomes']:outcome['depth']['bids']=None
        self.assertTrue(all(v['profit'] is None for v in product_view.dashboard(s,dict(view='arb'),{})))
        # A women's listing remains visible with precise scope failure, never paired.
        rows=coverage_fixture();s=projection(rows)[0].snapshot()
        self.assertTrue(any('women' in (m.get('reason') or '') for m in s['market_catalog']))


class StopAPI(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_stop_and_exact_saved_calculation(self):
        from tests.b5_ncaab_preview import owner
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
