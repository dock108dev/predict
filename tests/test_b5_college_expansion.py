"""Authoritative current sponsorship identities, independent of venue qualification."""
import unittest,json,tempfile
from pathlib import Path
from copy import deepcopy
from app.normalization.college_registry import expanded,for_event
from app.normalization.registry import Registry
from app.normalization import ncaaf,ncaab
from tests.test_b5_ncaaf import fixture as football
from tests.test_b5_ncaab import fixture as basketball
from app.dashboard.session_history import verified

class CollegeCoverage(unittest.TestCase):
    def test_every_sponsored_school_current_season_and_legacy_identity(self):
        r=expanded();base=Registry.load()
        for league,expected,make,module in [('NCAAF',266,football,ncaaf),('NCAAB',365,basketball,ncaab)]:
            teams=[v for v in r.entities.values() if v.get('league')==league];self.assertEqual(len(teams),expected)
            e0=make()[1]['inventory']['kalshi']['events'][0];original=module.event_key(e0)
            for team in teams:
                e=deepcopy(e0);cid=team['id'];other=next(v for v in teams if v['id']!=cid);e.update(home=cid,away=other['id'],participants={team['name']:cid,other['name']:other['id']})
                if league=='NCAAF':e['subdivisions']={v['id']:v['football_subdivisions']['2026']['value'] for v in (team,other)}
                else:e['schools']={v['id']:v['school_id'] for v in (team,other)}
                self.assertTrue(module.event_key(e));self.assertEqual(for_event(e).resolve('team',team['name'],league=league).canonical_id,cid)
            self.assertEqual(module.event_key(e0),original);self.assertEqual(for_event(e0).fingerprint,base.fingerprint)
        for alias in ['USC','SDSU','State','Miami']:
            for league in ['NCAAF','NCAAB']:self.assertNotEqual(r.resolve('team',alias,league=league).status,'resolved')
    def test_unknown_season_gender_campus_and_division(self):
        r=expanded();e=basketball()[1]['inventory']['kalshi']['events'][0]
        for change in [dict(gender='women'),dict(division='II'),dict(season='2027-2028'),dict(schools={})]:
            with self.assertRaises(ValueError):ncaab.event_key(dict(e,**change))
    def test_flat_storage_limit_is_nondestructive(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/'large';folder.mkdir();p=folder/'large.jsonl'
            with p.open('wb') as f:f.truncate(64*1024*1024+1)
            with self.assertRaisesRegex(ValueError,'64 MiB'):verified(folder)
            self.assertEqual(p.stat().st_size,64*1024*1024+1)
