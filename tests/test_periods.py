"""Owner-selected segments using explicit synthetic native review annotations."""
import unittest
from decimal import Decimal
from app.normalization import score_periods
from app.dashboard.session_projection import SessionProjection
from app.dashboard import product_view
from tests.test_diamond_ice_resolution import baseball,hockey,rec,view
from tests.test_score_lines import reseal


def fixture(sport='MLB',period='first_5',family='spread',line='-3',equality='predicate'):
    rows=(baseball if sport=='MLB' else hockey)(family='spread' if family=='moneyline' else family,line='0' if family=='moneyline' else line,equality=equality)
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor'];start,end=score_periods.PERIODS[sport][period]
        d.update(period=period,family=family,line=None if family=='moneyline' else line,regulation=period,offered='pregame',overtime='excluded',overtime_format='not_applicable',segment_start=start,segment_end=end,normal_completion=period+'_definitively_completed',settlement_score=period+'_only',tied_score='evaluate_actual_score_predicate',contract_document='https://kalshi-public-docs.s3.amazonaws.com/contract_terms/BASEBALLGAMEWIN.pdf' if sport=='MLB' else 'https://www.cftc.gov/filings/orgrules/rules0623267130.docx')
        if sport=='MLB':d.update(extra_innings='excluded',pitcher_conditions='action',completion_scope='specified_segment_only')
        if family=='moneyline':d['winner_structure']='binary_team_win_not_win'
        r['terms']={k:'unknown' for k in score_periods.TERM_FIELDS};r['terms'].update(completion=period+'_definitively_completed',settlement_fee='none')
        # Deliberately not an assertion that a production native series exists.
        series='SYNTHETIC-'+sport+'-'+period+'-'+family;r['series_id']=series;d['series_id']=series if source=='kalshi' else None
        if source=='kalshi':r['fee_basis']['series_id']=series
        m.update(period=period,market_type=family,line=d['line'])
        for side in m['product_outcomes']:
            label=(d['participant']+' '+line if family=='spread' else d['participant']+' '+period+' winner' if family=='moneyline' else 'Total '+line)+' '+side['native_label']
            side.update(label=label,participant=label)
        reseal(rows,source)
    return rows


def snapshot(rows):
    p=SessionProjection()
    for r in rows:p.apply(r)
    return p.snapshot()

class Periods(unittest.TestCase):
    def test_all_selected_segments_families_and_results(self):
        for sport,periods in score_periods.PERIODS.items():
            for period,(start,end) in periods.items():
                for family in ['moneyline','spread','total']:
                    rows=fixture(sport,period,family,line='-3' if family=='spread' else '7');s=snapshot(rows)
                    self.assertEqual(len(s['games']),1,[(m['source_id'],m['reason']) for m in s['market_catalog']]);g=s['games'][0];e=rows[1]['inventory']['kalshi']['events'][0]
                    calc=product_view.calculate(s,g,{});self.assertTrue(calc['score_partitions']);self.assertTrue(any(c['profit'] is not None for c in calc['candidates']))
                    r=rec(s,g,e,period=period,score_scope=period+'_only',score_representation='official_segment_score',completion=period+'_definitively_completed',segment_start=start,segment_end=end,pitcher_conditions='action')
                    self.assertEqual(view(s,g,[r])['sporting']['state'],'final')
    def test_unknown_segment_and_cross_period_do_not_match(self):
        for sport,period in [('MLB','first_5'),('NHL','period_2')]:
            rows=fixture(sport,period);rows[1]['inventory']['kalshi']['markets'][0]['period']='full_game';self.assertEqual(snapshot(rows)['games'],[])
    def test_scalar_probabilities_cannot_hide_tie(self):
        s=snapshot(fixture(family='moneyline'));g=s['games'][0];r=product_view.calculate(s,g,dict(probability='.6'));self.assertIsNone(r['ev']['expected_profit'])
