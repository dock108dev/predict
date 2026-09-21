import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from app.reference.retained_sample import prepare,package
from app.reference.mapping import scope_match,sport_key
from app.dashboard import session_history,product_view
from app.reference.product import at_cutoff

ROOT=Path('evidence/b4-pinnacle-sample-20260921')
class Actual(unittest.TestCase):
    def test_original_actual_response_and_saved_cutoff(self):
        refs,audit=prepare(ROOT)
        self.assertEqual(len(refs),16);self.assertEqual(audit['returned_events'],17)
        self.assertEqual(len(audit['missing_pinnacle_event_ids']),2)
        self.assertTrue(all(r['evidence_mode']=='observation' and r['origin_id']=='pinnacle' for r in refs))
        self.assertEqual(at_cutoff(refs,'2026-09-21T15:59:00Z'),[])
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/'actual-replay';report=package(folder,refs)
            a=session_history.load(folder,report['cutoff']);b=session_history.load(folder,report['cutoff'])
            self.assertEqual(a,b);self.assertEqual(a['state'],'saved')
            self.assertEqual(product_view.dashboard(a,dict(view='ev'),{}),[])
            self.assertEqual(product_view.dashboard(a,dict(view='arb'),{}),[])
            self.assertEqual(len(a['references']),16)
            path=folder/(folder.name+'.jsonl');path.write_bytes(path.read_bytes()+b'\n')
            with self.assertRaises(ValueError):session_history.load(folder)

    def test_nhl_scope_isolation_without_enabling_economics(self):
        refs,_=prepare(ROOT);i=deepcopy(refs[0]['market_identity']);i.update(sport='ice_hockey',competition='NHL',rules='incl-ot-shootout')
        j=deepcopy(i);j['sport']='hockey'
        def check(target):return scope_match(i,target,source_teams=['Home','Away'],target_teams=['nhl-home','nhl-away'],team_bindings={'Home':'nhl-home','Away':'nhl-away'},reviewed_rules=(i['rules'],i['rules']))
        self.assertTrue(check(j)['compatible']);self.assertFalse(check(j)['ordinary_ev_supported'])
        for changes in [dict(period='regulation'),dict(rules='regulation-draw'),dict(season='2027'),dict(competition='NFL'),dict(line='0'),dict(scheduled_start='2026-09-23T00:15:00Z')]:
            self.assertFalse(check(dict(j,**changes))['compatible'])
        self.assertEqual(sport_key('hockey','NHL'),'ice_hockey');self.assertEqual(j['sport'],'hockey')
        self.assertFalse(scope_match(i,j,source_teams=['Home','Away'],target_teams=['nhl-home','nhl-away'],team_bindings={})['compatible'])
