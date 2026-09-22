"""SYNTHETIC line reviews and prices, not venue qualification or forecasts."""
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
import json
import unittest
from app.normalization.score_lines import descriptor,partitions,payout,distribution,VERSION
from app.dashboard.session_projection import SessionProjection
from app.dashboard import product_view
from tests.test_b5_nba import fixture as nba_fixture
from tests.test_b5_ncaab import fixture as ncaab_fixture


def fixture(competition='NBA',family='spread',line='-3',equality='predicate'):
    rows=(nba_fixture if competition=='NBA' else ncaab_fixture)()
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];old=m.pop(competition.lower()+'_review');meta=next(r['market'] for r in rows if r['type']=='market_selected' and r['source']==source)
        outcomes=[]
        for idx,s in enumerate(m['product_outcomes']):
            # Native IDs/Long and Short are explicitly retained; never derive the
            # score predicate from the old winner team or visible title.
            outcomes.append(dict(native_id=s['native_id'],native_label=s.get('native_label') or s['native_id'],operator=('gt' if idx==0 else 'le' if equality=='predicate' else 'lt'),equality=equality,refund_fees='retained'))
        d=dict(version=VERSION,family=family,period='full_game',unit='points',line=line,participant=e['home'] if family=='spread' else 'combined',overtime='included',regulation='four_12_minute_quarters' if competition=='NBA' else 'two_20_minute_halves',outcomes=outcomes)
        c=descriptor(e,d);sides=[]
        for s in outcomes:
            label=(d['participant']+' '+d['line'] if family=='spread' else 'Total '+d['line'])+' '+s['native_label']
            sides.append(dict(s,participant=label,predicate='score',threshold=c['threshold'],domain=c['domain'],label=label))
        terms=dict(completion='SYNTHETIC completed full game official points including overtime',cancellation='unknown',suspension='unknown',postponement='unknown',void='unknown',corrections='unknown',settlement_fee='none')
        series=('KXNBA' if competition=='NBA' else 'KXNCAAMB')+('SPREAD' if family=='spread' else 'TOTAL')
        d.update(source=source,event_id=e['id'],market_id=m['id'],series_id=series if source=='kalshi' else None)
        basis=deepcopy(old.get('fee_basis',{}))
        if source=='kalshi':basis['series_id']=series
        raw=json.loads(meta['raw']['json_text']);raw['SYNTHETIC_score_descriptor']=d;raw['SYNTHETIC_score_terms']=terms;raw['SYNTHETIC_score_fees']=basis
        meta['raw']['json_text']=json.dumps(raw)
        r=dict(source=source,event_id=e['id'],market_id=m['id'],evidence_mode='synthetic',raw_sha256=sha256(meta['raw']['json_text'].encode()).hexdigest(),event_binding=old['event_binding'],event_paths=old['event_paths'],descriptor=d,descriptor_path=['SYNTHETIC_score_descriptor'],terms=terms,terms_path=['SYNTHETIC_score_terms'],fee_basis=basis,fee_path=['SYNTHETIC_score_fees'],series_id=series)
        m.update(market_type=family,period='full_game',line=line,subject=d['participant'],rules_revision=VERSION,outcome_set='score_partition',score_review=r,product_outcomes=sides)
        e['title']='SYNTHETIC '+competition+' '+family+' · '+e['title']
    for row in rows:
        if row['type']=='prediction_book':
            row['book']['source_time_progress']='initial'
            row['book']['raw']['exchange_at']=row['observed_at']
    return rows


def projection(rows=None):
    p=SessionProjection()
    for r in fixture() if rows is None else rows:p.apply(r)
    return p


class ScoreLines(unittest.TestCase):
    def test_partition_truth_table(self):
        for line,ids in [('3',['below','equal','above']),('3.5',['below','above']),('-3.5',['below','above'])]:
            ps=partitions('home_margin',line);self.assertEqual([p['id'] for p in ps],ids)
        ps=partitions('home_margin','3')
        expected={'gt':['0','0','1'],'ge':['0','1','1'],'lt':['1','0','0'],'le':['1','1','0']}
        for op,want in expected.items():
            s=dict(threshold='3',operator=op,equality='predicate',refund_fees='retained')
            self.assertEqual([payout(s,p) for p in ps],want)
            s['equality']='stake_refund';self.assertEqual(payout(s,ps[1]),'refund')
            s['refund_fees']='unknown';self.assertIsNone(payout(s,ps[1]))
        self.assertEqual([p['id'] for p in partitions('combined_score','0')],['equal','above'])
        with self.assertRaises(ValueError):partitions('home_margin','3.25')

    def test_projection_and_calculation(self):
        for comp,family,line in [('NBA','spread','-3'),('NCAAB','total','150.5'),('NBA','total','220'),('NCAAB','spread','-2.5')]:
            s=projection(fixture(comp,family,line)).snapshot();self.assertEqual(len(s['games']),1,s['market_catalog'])
            g=s['games'][0];r=product_view.calculate(s,g,{})
            self.assertEqual(len(r['candidates']),4)
            self.assertEqual(sum(c['profit'] is not None for c in r['candidates']),2)
            for c in r['candidates']:
                if c['profit'] is None:continue
                for part,v in c['normal_cashflows'].items():
                    gross=sum(Decimal(l['cashflows'][part]['gross_payout']) for l in c['legs']);cost=sum(Decimal(l['cash']) for l in c['legs'])
                    self.assertEqual(Decimal(v),gross-cost)
            self.assertIsNone(r['ev']['expected_profit'])

    def test_distribution_validation(self):
        ps=partitions('home_margin','3')
        for value in ['.6',{'below':'.4','above':'.6'},{'below':'.4','equal':'.1','above':'.6'},{'below':'-.1','equal':'.5','above':'.6'}]:
            with self.assertRaises(ValueError):distribution(value,ps)
        self.assertEqual(distribution({'below':'.3','equal':'.1','above':'.6'},ps)['equal'],'0.1')

    def test_unknown_equality_visible(self):
        s=projection(fixture(equality='unknown')).snapshot();g=s['games'][0];r=product_view.calculate(s,g,{})
        self.assertTrue(all(c['profit'] is None for c in r['candidates']))
        self.assertTrue(any('Equality' in reason for c in r['candidates'] for reason in c['reasons']))

    def test_refund_arithmetic_and_ev(self):
        s=projection(fixture(equality='stake_refund')).snapshot();g=s['games'][0]
        key=next(k for k,v in g['sides'].items() if k.startswith('kalshi:yes:'))
        r=product_view.calculate(s,g,dict(contract=key,quantity='10',probability={'below':'.3','equal':'.1','above':'.6'}))
        leg=r['ev']['leg'];equal=leg['cashflows']['equal']
        self.assertEqual(Decimal(equal['gross_payout']),Decimal(leg['notional']))
        self.assertNotEqual(Decimal(equal['gross_payout']),Decimal('10'))
        self.assertEqual(Decimal(equal['net_cashflow']),-Decimal(leg['fee']))
        # Direct expectation, independent of partition distribution implementation.
        want=Decimal('.3')*10+Decimal('.1')*Decimal(leg['notional'])-Decimal(leg['cash'])
        self.assertEqual(Decimal(r['ev']['expected_profit']),want)
        self.assertTrue(all(c['profit'] is None or Decimal(c['profit'])<0 for c in r['candidates']))
        missing=product_view.calculate(s,g,dict(contract=key,probability='.6'))
        self.assertIsNone(missing['ev']['expected_profit']);self.assertIn('equality',str(missing['ev']['reasons']))

    def test_exact_identity_evidence_and_scope(self):
        for field,value in [('line','-4'),('period','half_1'),('market_type','futures'),('subject','NBA:NYK')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0][field]=value
            self.assertEqual(projection(rows).snapshot()['games'],[])
        for field in ('raw_sha256','descriptor_path','event_paths','terms_path'):
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review'].pop(field)
            self.assertEqual(projection(rows).snapshot()['games'],[])
        rows=fixture();rows[0]['spec']['mode']='real';self.assertEqual(projection(rows).snapshot()['games'],[])
        rows=fixture();rows[1]['inventory']['kalshi']['events'][0]['game_id']='other';self.assertEqual(projection(rows).snapshot()['games'],[])
        self.assertNotEqual(projection(fixture(line='-3')).snapshot()['games'][0]['id'],projection(fixture(line='-3.5')).snapshot()['games'][0]['id'])

    def test_away_spread_sign_and_inverted_outcomes(self):
        from app.normalization.score_lines import review
        rows=fixture();cat=rows[1]['inventory']['kalshi'];e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor']
        self.assertEqual(descriptor(e,d)['threshold'],'3')
        d.update(participant=e['away'],line='3');m.update(subject=e['away'],line='3')
        self.assertEqual(descriptor(e,d)['threshold'],'3')
        # Exact native inversion; away +3 > 0 means home margin <3.
        for s in m['product_outcomes']:
            s['operator']={'gt':'lt','le':'ge'}[s['operator']]
            label=e['away']+' 3 '+s['native_label'];s.update(label=label,participant=label)
        reseal(rows,'kalshi')
        meta=next(r for r in rows if r['type']=='market_selected' and r['source']=='kalshi')
        self.assertEqual(review(e,m,meta,'kalshi','mock')['canonical']['threshold'],'3')
        s=projection(rows).snapshot();self.assertEqual(len(s['games']),1)
        self.assertEqual({v['operator'] for k,v in s['games'][0]['sides'].items() if k.startswith('kalshi:')},{'lt','ge'})

    def test_source_fees_future_and_stop(self):
        from app.dashboard.session_history import project_rows
        rows=fixture();p=projection(rows);s=p.snapshot();cut=s['durable_cursor']
        terminal=dict(type='session_finished',source='session',session_id=p.sid,observed_at=p.last,reason='owner_stop');p.apply(terminal)
        self.assertEqual(project_rows(rows+[terminal],cut),s)
        with self.assertRaises(ValueError):p.apply(terminal)
        for change in ('fees','settlement','future','failure','completion'):
            rows=fixture();m=rows[1]['inventory']['kalshi']['markets'][0]
            if change=='fees':m['score_review'].pop('fee_basis');reseal(rows,'kalshi')
            if change=='settlement':m['score_review']['terms']['settlement_fee']='unknown';reseal(rows,'kalshi')
            if change=='completion':m['score_review']['terms']['completion']='different complete-score rule';reseal(rows,'kalshi')
            if change=='future':next(r for r in rows if r['type']=='market_selected' and r['source']=='kalshi')['market']['raw']['received_at']='2027-01-01T00:00:00Z'
            if change=='failure':
                p=projection(rows);p.apply(dict(type='source_health',source='kalshi',session_id=p.sid,observed_at=p.last,state='disconnected'));s=p.snapshot()
            else:s=projection(rows).snapshot()
            if change in ('future','completion'):self.assertEqual(s['games'],[]);continue
            result=product_view.calculate(s,s['games'][0],{})
            self.assertTrue(all(c['profit'] is None for c in result['candidates']),change)
            self.assertEqual(next(c for c in s['points'][s['games'][0]['id']]['cards'] if c['venue']=='polymarket_us')['connection'],'connected')

    def test_explicit_reference_and_wrong_kind(self):
        from app.reference.product import validate,at_cutoff
        from app.reference.score_lines import score_distribution
        rows=fixture();s=projection(rows).snapshot();g=s['games'][0];ref=reference(g,rows)
        validate(ref);self.assertEqual(at_cutoff([ref],s['last_update'])[0]['availability'],'available')
        s['references']=[ref];key=next(k for k,v in g['sides'].items() if v['participant']==ref['participant'])
        r=product_view.calculate(s,g,dict(reference=ref['id'],contract=key));self.assertIsNotNone(r['ev']['expected_profit'])
        self.assertEqual(at_cutoff([ref],'2020-01-01T00:00:00Z'),[])
        for changes in [dict(value_kind='projected_margin'),dict(value_kind='rating'),dict(value_kind='season_probability'),dict(probabilities={'above':'.6','below':'.4'}),dict(source_event_id='wrong')]:
            from app.reference.product import receipt
            body=json.loads(ref['receipt']['body']);body.update(changes)
            rr=receipt(json.dumps(body),provider='espn_bpi',url='https://www.espn.com/synthetic',received_at=ref['received_at'],mode='synthetic')
            with self.assertRaises(ValueError):score_distribution(rr,ref['binding'])


    def test_independent_positive_zero_negative_dollars(self):
        from unittest.mock import patch
        from app.opportunities.score_lines import evaluate
        from app.opportunities.board import contracts
        rows=fixture(line='-3.5');s=projection(rows).snapshot();g=s['games'][0];point=s['points'][g['id']]
        keys=[next(k for k,v in g['sides'].items() if k.startswith(venue+':') and v['operator']==op) for venue,op in [('kalshi','gt'),('polymarket_us','le')]]
        game=dict(g,candidates=[('arithmetic','Independent arithmetic fixture',keys)])
        for price,want in [('0.47','0.01'),('0.48','0.00'),('0.49','-0.01')]:
            cs=contracts(point,g)
            for k,c in cs.items():
                p=price if c['venue']=='kalshi' else '0.49'
                c.update(ask=p,top_size='1',visible_size='1',levels=[dict(price=p,quantity='1',provenance='SYNTHETIC independent arithmetic table')],warnings=[])
            # One contract: Kalshi cent-rounded fee .02, US fee .01.
            # Opposite half-point predicates always pay exactly $1 together.
            with patch('app.opportunities.score_lines.contracts',return_value=cs):
                r=evaluate(point,s['rows_by_game'][g['id']],'1','cent',None,keys[0],game)
            self.assertEqual(Decimal(r['candidates'][0]['profit']),Decimal(want))
            self.assertEqual(Decimal(r['candidates'][0]['fees']),Decimal('.03'))

    def test_unknown_refund_fee_and_half_point_proof(self):
        rows=fixture(equality='stake_refund');m=rows[1]['inventory']['kalshi']['markets'][0]
        for side in m['score_review']['descriptor']['outcomes']:side['refund_fees']='returned'
        for side in m['product_outcomes']:side['refund_fees']='returned'
        reseal(rows,'kalshi');s=projection(rows).snapshot();r=product_view.calculate(s,s['games'][0],{})
        self.assertTrue(all(c['profit'] is None for c in r['candidates']))
        s=projection(fixture(line='-3.5',equality='unknown')).snapshot();r=product_view.calculate(s,s['games'][0],{})
        self.assertEqual(sum(c['profit'] is not None for c in r['candidates']),2)
        self.assertNotIn('equal',[p['id'] for p in r['score_partitions']])

    def test_revision_rejects_stale_books_and_assumptions(self):
        rows=fixture();p=projection(rows);before=p.snapshot();revision=deepcopy(rows[1]);revision['previous_generation']=p.generation;revision['generation']='score-revision-2'
        revision['inventory']['kalshi']['markets'][0]['line']='-4'
        p.apply(revision);self.assertEqual(p.snapshot()['games'],[])
        # A changed equality mapping receives a new game/assumption identity.
        a=projection(fixture()).snapshot()['games'][0]
        b=projection(fixture(equality='stake_refund')).snapshot()['games'][0]
        self.assertNotEqual(a['id'],b['id']);self.assertNotEqual(a['product_identity'],b['product_identity'])


def reseal(rows,source):
    m=rows[1]['inventory'][source]['markets'][0];r=m['score_review'];meta=next(v['market'] for v in rows if v['type']=='market_selected' and v['source']==source);raw=json.loads(meta['raw']['json_text'])
    raw['SYNTHETIC_score_descriptor']=r['descriptor'];raw['SYNTHETIC_score_terms']=r['terms'];raw['SYNTHETIC_score_fees']=r.get('fee_basis')
    meta['raw']['json_text']=json.dumps(raw);r['raw_sha256']=sha256(meta['raw']['json_text'].encode()).hexdigest()


def reference(game,rows=None,at='2026-09-16T12:00:00+00:00'):
    from app.reference.product import receipt
    from app.reference.score_lines import score_distribution
    if rows is None:rows=fixture(game['product_identity']['competition'],game['product_identity']['family'],'-3' if game['product_identity']['family']=='spread' else '150.5')
    e=rows[1]['inventory']['kalshi']['events'][0];side=next(v for k,v in game['sides'].items() if k.startswith('kalshi:yes:'))
    binding=dict(market_identity=game['product_identity'],participant=side['participant'],source_event_id='synthetic-score-forecast')
    probs={'below':'.3','equal':'.1','above':'.6'} if 'equal' in {p['id'] for p in partitions(game['product_identity']['rules']['domain'],game['product_identity']['line'])} else {'below':'.4','above':'.6'}
    body=json.dumps(dict(binding,event=e,value_kind='score_partition_probability',conditional_on='completed_full_game_including_overtime',probabilities=probs))
    r=receipt(body,provider='espn_bpi',url='https://www.espn.com/synthetic-fixture',received_at=at,mode='synthetic')
    return score_distribution(r,binding,source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC partition probabilities; not a forecast')


class ScoreStopAPI(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_live_stop_and_disk_math_exact(self):
        import tempfile
        from pathlib import Path
        from tests.b5_score_lines_preview import owner
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.multi_game_server import create_app
        from app.dashboard.session_history import load
        with tempfile.TemporaryDirectory() as t:
            o=owner(Path(t));client=TestClient(TestServer(create_app(owner=o,sessions={})));await client.start_server()
            try:
                headers={'Origin':str(client.make_url('/')).rstrip('/')}
                response=await client.post('/api/start',json={'duration':60},headers=headers);self.assertEqual(response.status,200)
                snap=o.current_snapshot();token=snap['durable_cursor'];before={v:product_view.dashboard(o.cutoffs[token],dict(view=v),{}) for v in ('arb','ev')}
                response=await client.post('/api/stop',json={},headers=headers);self.assertEqual(response.status,200);await o.finalizer
                saved=load(o.session.output,token);after={v:product_view.dashboard(saved,dict(view=v),{}) for v in ('arb','ev')}
                self.assertEqual(before,after);self.assertFalse(o.active());self.assertEqual(load(o.session.output)['stop_reason'],'manual_stop')
                with self.assertRaises(ValueError):o.session.append(fixture()[-1])
            finally:await client.close()
