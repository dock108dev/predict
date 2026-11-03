"""Synthetic exact witnesses: never presented as retained provider observations."""
from copy import deepcopy
from fractions import Fraction as F
from unittest import TestCase
from tests.test_snapshot_identity import quote
from app.comparison.snapshot_benchmark import bind
from app.comparison.snapshot_math import assumptions
from app.storage.comparison_snapshot import calculate
from app.storage.store import hashed

AT='2026-11-02T22:00:00Z'


def execution(native='yes',family='total',line='135.5',cost='0.4'):
    q=quote(native=native,family=family,line=line);r=q['original_record']
    r['quote']['original']['value']=cost
    q.update(venue='polymarket_us',quote_id=q['id'],market=dict(market=family,period='full_game',line=line),
        game_title='Away at Home',start_at=r['event']['scheduled_start'],selection=r['selection'],
        original=r['quote']['original'],common_odds={'supported':True},binding={'verified':False})
    return q


def references(family='total',line='135.5'):
    out=[]
    for i,side in enumerate(('yes','no')):
        r=quote('the_odds_api','ref',family,line,side)['original_record'];q=r['quote']
        q.update(venue='pinnacle',provenance={'sha256':'a'*64},
            times=dict(source_at='2026-10-31T21:00:00Z',received_at='2026-10-31T21:00:01Z'),
            provider_clocks=dict(book='2026-10-31T21:00:00Z',market=None,selected_basis='book'))
        q['source']['native_market_id']='line:'+family+line
        q['original'].update(units='decimal_odds',value=['2','3'][i])
        r['market_identity']['competition']='NCAAB'
        r['comparison_source_metadata'].pop('source_predicate',None)
        if family=='spread' and i:r['selection'].update(participant='away',signed_line=str(-F(line)))
        if family=='moneyline' and i:r['selection'].update(participant='away')
        out.append(dict(id=hashed(q['source']),venue='pinnacle',original_record=r,
            market=r['market_identity'],game_key='ref',original=q['original']))
    return out


def inputs(qs,refs):
    return dict(id='fixture',quotes=qs,references=refs,captured_at=AT,games=[],sources={},issues=[],capture_seconds=0)


class SnapshotBenchmark(TestCase):
    def test_exact_oriented_positive_zero_negative_and_net(self):
        refs=references();before=deepcopy(refs)
        for cost,expected in [('0.4',F(50)),('0.6',F(0)),('0.8',F(-25))]:
            with self.subTest(cost=cost):
                result=calculate(inputs([execution(cost=cost)],refs))['rows'][0]
                self.assertEqual(F(result['probability']),F(3,5))
                self.assertEqual(F(result['gross_return_percent']),expected)
                self.assertIsNone(result['net_return_percent'])
                self.assertFalse(result['binding']['verified'])
        settings=dict(scenario='decisive_only',sizing='hypothetical_fractional',fees={'polymarket_us':'0.02'},amount='1020')
        r=calculate(inputs([execution(cost='0.5')],refs),settings)['rows'][0]
        self.assertEqual(F(r['math']['buffered_profit_usd']),F('174.9'))
        r=calculate(inputs([execution('no')],refs))['rows'][0]
        self.assertEqual(F(r['probability']),F(2,5))
        self.assertEqual(refs,before)
        self.assertGreater(r['snapshot_benchmark']['age_seconds'],1800)

    def test_each_family_requires_own_pair_and_conditional_winner(self):
        for family,line in [('moneyline','0'),('spread','-3.5'),('total','135.5')]:
            with self.subTest(family=family):
                q=execution(family=family,line=line)
                result=calculate(inputs([q],references(family,line)),{'scenario':'decisive_only'})
                self.assertEqual(F(result['rows'][0]['probability']),F(3,5))
                if family!='total':
                    self.assertIsNone(calculate(inputs([q],references()),{'scenario':'decisive_only'})['rows'][0]['probability'])
        self.assertIsNone(calculate(inputs([execution(family='moneyline')],references('moneyline','0')))['rows'][0]['gross_return_percent'])

    def test_incomplete_crossed_frames_and_original_evidence(self):
        refs=references()
        variants=[refs[:1],[refs[0],deepcopy(refs[0])],[{k:v for k,v in r.items() if k!='original_record'} for r in refs]]
        for field,value in [('received_at','2026-10-31T21:00:02Z'),('source_at','2026-10-31T21:00:02Z')]:
            r=deepcopy(refs);r[1]['original_record']['quote']['times'][field]=value;variants.append(r)
        r=deepcopy(refs);r[1]['original_record']['quote']['provenance']['sha256']='b'*64;variants.append(r)
        for r in variants:
            self.assertIsNone(calculate(inputs([execution()],r))['rows'][0]['probability'])

    def test_identity_threshold_period_and_scope_conflicts(self):
        for field,value in [('scheduled_start','2026-11-03T01:00:00Z'),('home','different'),('season','conflict')]:
            refs=references()
            for r in refs:r['original_record']['event'][field]=value
            q=execution()
            if field=='season':q['original_record']['event'][field]='known'
            self.assertIsNone(calculate(inputs([q],refs))['rows'][0]['probability'])
        for kind in ['line','period','scope','contradictory_line']:
            refs=references(line='136.5') if kind=='line' else references()
            for r in refs:
                if kind=='period':r['original_record']['market_identity']['period']='first_half'
                if kind=='contradictory_line':r['original_record']['market_identity']['line']='999.5'
                if kind=='scope':r['original_record']['comparison_source_metadata']['scoring_scope']['evidence']=[{'overtime':'excluded'}]
            self.assertIsNone(calculate(inputs([execution()],refs))['rows'][0]['probability'])

    def test_unknown_future_and_contradictory_provider_clocks(self):
        for kind in ['unknown','future','receipt','provider']:
            refs=references()
            for r in refs:
                q=r['original_record']['quote']
                if kind=='unknown':q['times']['source_at']=None
                if kind=='future':q['times']['source_at']='2026-11-04T00:00:00Z'
                if kind=='receipt':q['times']['received_at']='2026-11-04T00:00:00Z'
                if kind=='provider':q['provider_clocks']['book']='2026-10-30T00:00:00Z'
            self.assertIsNone(calculate(inputs([execution()],refs))['rows'][0]['probability'])

    def test_no_benchmark_substitution_or_preattachment(self):
        q=execution();q['benchmark_quote']={'made_up':True}
        self.assertIsNone(calculate(inputs([q],[]))['rows'][0]['probability'])
        self.assertIsNone(calculate(inputs([q],references()),{'benchmark_venue':'novig'})['rows'][0]['probability'])

    def test_conflicting_same_time_frames_not_arbitrarily_selected(self):
        refs=references();other=deepcopy(refs)
        for r in other:
            q=r['original_record']['quote'];q['source']['native_market_id']='alternate:total'
            q['original']['value']='2';r['id']=hashed(q['source'])
        row=calculate(inputs([execution()],refs+other))['rows'][0]
        self.assertIsNone(row['probability'])
        self.assertEqual(row['probability_missing'],'Conflicting complete Pinnacle frames')

    def test_named_no_and_short_orientation_and_inclusive_integer_domain(self):
        q=execution(family='moneyline',native='no');q['original_record']['selection']['predicate']='not_win'
        r=calculate(inputs([q],references('moneyline','0')),{'scenario':'decisive_only'})['rows'][0]
        self.assertEqual(F(r['probability']),F(2,5))
        q=execution(native='no',line='136')
        r=calculate(inputs([q],references(line='136')))['rows'][0]
        self.assertIsNone(r['probability'])
        r=calculate(inputs([q],references(line='136')),{'scenario':'decisive_only'})['rows'][0]
        self.assertEqual(F(r['probability']),F(2,5))

    def test_original_identifier_and_other_bookmaker_rejected(self):
        for kind in ['id','bookmaker']:
            refs=references()
            if kind=='id':refs[0]['id']='other'
            else:refs[0]['original_record']['quote']['venue']='novig'
            self.assertIsNone(calculate(inputs([execution()],refs))['rows'][0]['probability'])

    def test_aggregate_alternate_signed_side_ids_share_exact_frame(self):
        refs=references('spread','-3.5')
        for i,r in enumerate(refs):
            r['original_record']['quote']['source']['native_market_id']='alternate:side-'+str(i)
            r['id']=hashed(r['original_record']['quote']['source'])
        row=calculate(inputs([execution(family='spread',line='-3.5')],refs))['rows'][0]
        self.assertEqual(F(row['probability']),F(3,5))
        refs[1]['original_record']['quote']['source']['native_market_id']='standard:side'
        refs[1]['id']=hashed(refs[1]['original_record']['quote']['source'])
        self.assertIsNone(calculate(inputs([execution(family='spread',line='-3.5')],refs))['rows'][0]['probability'])
