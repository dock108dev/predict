"""Exact selected-side original-input reference checks; offline only."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import json
from pathlib import Path
import unittest
from app.comparison.domain import CanonicalSelection, ExactNumber, Price, ScorePredicate, NativeProvenance, UnknownValue
from app.comparison.pinnacle import ReferenceOutcome, ReferenceSet, bind
from app.collection.current_aggregate_admission import admit
from app.collection.current_benchmark import attach
from tests.test_comparison_event_links import body

AT=datetime(2026,10,8,20,tzinfo=timezone.utc)
CLOCK='2026-10-08T20:00:00Z'
P=Path(__file__).resolve().parents[1]/'app/fixtures/comparison-domain-v1.json'


def selection(participant='NFL:DAL',operator='gt',odds='2'):
    s=CanonicalSelection.from_dict(json.loads(P.read_text())['samples'][0]['selection'])
    native=NativeProvenance('pinnacle','authored-event','authored-h2h','authored-'+participant,participant,'Original authored Pinnacle outcome',s.native.evidence)
    return replace(s,family='moneyline',participant_id=participant,predicate=ScorePredicate('home_margin',operator,ExactNumber('0')),native=native,
        payout=None,payout_unknown=UnknownValue('Unbound authored grading',('grading',)),price=Price(ExactNumber(odds),'decimal_odds','usd_per_usd_stake','USD'))


def reference(three=False):
    outcomes=[ReferenceOutcome(selection(),ExactNumber('2'),CLOCK,None,CLOCK,'first'),
              ReferenceOutcome(selection('NFL:TB','lt','4' if three else '3'),ExactNumber('4' if three else '3'),CLOCK,None,CLOCK,'second')]
    if three:outcomes.append(ReferenceOutcome(selection('tie','eq','4'),ExactNumber('4'),CLOCK,None,CLOCK,'draw'))
    return ReferenceSet(tuple(outcomes),'a'*64,'explicit_three_way' if three else 'decisive_win_loss','b'*64 if three else None)


class PinnacleInputs(unittest.TestCase):
    def test_original_selected_odds_both_sides_independent_probability_oracle(self):
        r=reference();a=bind(selection(),r,AT);b=bind(selection('NFL:TB','lt','3'),r,AT)
        self.assertEqual(a['original_odds'],['2','3']);self.assertEqual(a['selected_odds'],'2');self.assertEqual(b['selected_odds'],'3')
        self.assertEqual(a['probabilities'],['3/5','2/5']);self.assertIn('tie',a['unknown_mass'])
        # R07 original values: arithmetic expectation does not call production EV.
        for cost,want in [('1/2','1/5'),('3/5','0'),('2/3','-1/10')]:
            self.assertEqual(Fraction('3/5')/Fraction(cost)-1,Fraction(want))

    def test_source_age_boundary_receipt_cannot_refresh_and_one_side_unknown(self):
        r=reference();self.assertTrue(bind(selection(),r,AT+timedelta(seconds=1800))['available'])
        self.assertEqual(bind(selection(),r,AT+timedelta(seconds=1801))['reason'],'reference_expired')
        newer=replace(r.outcomes[0],received_at='2026-10-08T20:40:00Z',revision='new-receipt')
        self.assertEqual(bind(selection(),replace(r,outcomes=(newer,r.outcomes[1])),AT+timedelta(seconds=2400))['reason'],'reference_expired')
        missing=replace(r.outcomes[1],book_at=None)
        self.assertEqual(bind(selection(),replace(r,outcomes=(r.outcomes[0],missing)),AT)['reason'],'reference_source_clock_unknown')
        self.assertEqual(bind(selection(),r,AT-timedelta(seconds=1))['reason'],'reference_clock_future')

    def test_exact_occurrence_period_line_family_and_opposition(self):
        r=reference();s=selection()
        for changed in [replace(s,event=replace(s.event,occurrence_id='rematch')),replace(s,scope=replace(s.scope,period='first_half',overtime='excluded')),
                        replace(s,family='spread',signed_line=ExactNumber('0'))]:
            self.assertEqual(bind(changed,r,AT)['reason'],'exact_reference_selection_missing')
        with self.assertRaises(ValueError):ReferenceSet((r.outcomes[0],r.outcomes[0]),'a'*64,'decisive_win_loss')
        with self.assertRaises(ValueError):ReferenceSet((r.outcomes[0],replace(r.outcomes[1],selection=selection('NFL:TB','gt','3'))),'a'*64,'decisive_win_loss')
        with self.assertRaises(ValueError):replace(r,receipt_sha256=None)
        with self.assertRaises(ValueError):replace(r.outcomes[0],received_at=None)
        home=replace(selection(),family='team_total',predicate=ScorePredicate('team_score','gt',ExactNumber('8.5'),'NFL:DAL'))
        away=replace(selection('NFL:TB','lt','3'),family='team_total',predicate=ScorePredicate('team_score','lt',ExactNumber('8.5'),'NFL:TB'))
        with self.assertRaises(ValueError):ReferenceSet((replace(r.outcomes[0],selection=home),replace(r.outcomes[1],selection=away)),'a'*64,'decisive_win_loss')

    def test_evidenced_three_way_and_revision(self):
        r=reference(True);out=bind(selection(),r,AT)
        self.assertEqual(out['probabilities'],['1/2','1/4','1/4']);self.assertEqual(out['unknown_mass'],['exceptional'])
        with self.assertRaises(ValueError):replace(r,partition_evidence_sha256=None)
        changed=replace(r,outcomes=(replace(r.outcomes[0],revision='amended'),*r.outcomes[1:]))
        self.assertNotEqual(r.revision,changed.revision)

    def test_current_reference_only_change_missing_opposition_and_time_shift(self):
        payload=json.loads(body());payload[0]['bookmakers'].append(deepcopy(payload[0]['bookmakers'][0]));payload[0]['bookmakers'][1]['key']='pinnacle'
        data=json.dumps(payload).encode();records=admit(data,'NFL',CLOCK,venue='novig');refs=admit(data,'NFL',CLOCK,venue='pinnacle')
        for x in refs:x['market_identity']['scheduled_start']='2026-10-09T00:18:00Z'
        attach(records,refs);original=deepcopy(records[0]['quote']);self.assertIn('sharp_reference',original)
        self.assertEqual(original['sharp_reference']['selected_odds'],original['sharp_reference']['odds'][original['sharp_reference']['selected']])
        refs[0]['quote']['original']['value']='2.2';attach(records,refs)
        self.assertNotEqual(records[0]['quote']['sharp_reference'],original['sharp_reference']);self.assertEqual(records[0]['quote']['original'],original['original'])
        attach(records,refs[:1]);self.assertNotIn('sharp_reference',records[0]['quote']);self.assertEqual(records[0]['quote']['original'],original['original'])

if __name__=='__main__':unittest.main()
