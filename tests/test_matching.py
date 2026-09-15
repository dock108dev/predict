import asyncio
from copy import deepcopy
from dataclasses import replace
import itertools
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.matching import Matcher, compare, observation, digest, compact_raw, expand_raw
from app.matching_example import synthetic, report
from app.models.core import Venue


class MatchingTests(unittest.TestCase):
    def run_match(self,*rows,**kwargs):
        m=Matcher(**kwargs); m.ingest(rows); return m

    def statuses(self,m):
        return {x['status'] for x in m.snapshot['mappings'].values()}

    def ids(self,m):
        return {x['canonical_id'] for x in m.snapshot['mappings'].values() if x['canonical_id']}

    def test_aliases_and_reversed_order(self):
        a=synthetic('a',names=('Yankees','Red Sox'))
        b=synthetic('b',Venue.NOVIG,names=('Boston Red Sox','New York Yankees'))
        m=self.run_match(a,b)
        self.assertEqual(self.statuses(m),{'matched'})
        self.assertEqual(len(self.ids(m)),1)
        self.assertEqual(a['roles'],{})

    def test_league_and_participants_required(self):
        a=synthetic('a')
        for b in [synthetic('b',Venue.NOVIG,names=('Yankees','Mets')),
                  synthetic('b',Venue.NOVIG,league='NFL',names=('Dallas Cowboys','New York Giants')),
                  synthetic('b',Venue.NOVIG,names=('Yankees','Unknown')),
                  synthetic('b',Venue.NOVIG,names=()),
                  synthetic('b',Venue.NOVIG,names=('Yankees','Yankees'))]:
            with self.subTest(b=b['participants']):
                self.assertNotIn('matched',self.statuses(self.run_match(a,b)))

    def test_missing_and_conflicting_roles(self):
        a=synthetic('a',roles=('home','away'))
        b=synthetic('b',Venue.NOVIG)
        self.assertEqual(self.statuses(self.run_match(a,b)),{'matched'})
        b=synthetic('b',Venue.NOVIG,roles=('away','home'))
        self.assertEqual(self.statuses(self.run_match(a,b)),{'conflicting'})
        b=synthetic('b',Venue.NOVIG,roles=('home','home'))
        self.assertNotIn('matched',self.statuses(self.run_match(b)))

    def test_partial_and_uninterpreted_roles(self):
        a=synthetic('a',roles=('home',None))
        b=synthetic('b',Venue.NOVIG,roles=(None,'home'))
        self.assertEqual(self.statuses(self.run_match(a,b)),{'conflicting'})
        b=synthetic('b',Venue.NOVIG,roles=('unsupported-label',None))
        self.assertEqual(self.statuses(self.run_match(a,b)),{'candidate'})
        self.assertEqual(b['uninterpreted_roles'],['unsupported-label'])

    def test_timezone_and_midnight(self):
        a=synthetic('a',start='2026-09-13T23:58:00+00:00')
        for start in ('2026-09-13T19:58:00-04:00','2026-09-14T00:02:00+00:00'):
            self.assertEqual(self.statuses(self.run_match(a,synthetic('b',Venue.NOVIG,start=start))),{'matched'})

    def test_equivalent_timestamp_same_reference(self):
        a=synthetic('a',start='2026-09-13T17:00:00+00:00')
        b=synthetic('a',start='2026-09-13T13:00:00-04:00')
        self.assertNotIn('conflicting',self.statuses(self.run_match(a,b)))

    def test_tolerance_inclusive_and_configurable(self):
        a=synthetic('a'); b=synthetic('b',Venue.NOVIG,start='2026-09-13T17:15:00+00:00')
        self.assertEqual(self.statuses(self.run_match(a,b)),{'matched'})
        self.assertNotIn('matched',self.statuses(self.run_match(a,b,tolerance_seconds=899)))
        b=synthetic('b',Venue.NOVIG,start='2026-09-13T17:15:00.001+00:00')
        self.assertNotIn('matched',self.statuses(self.run_match(a,b)))
        for value in (-1,True,float('nan'),float('inf')):
            with self.assertRaises(ValueError): Matcher(tolerance_seconds=value)

    def test_repeat_games_separate_even_same_day(self):
        rows=[synthetic('a'),synthetic('b',Venue.NOVIG),
              synthetic('c',start='2026-09-13T20:00:00+00:00'),
              synthetic('d',Venue.NOVIG,start='2026-09-13T20:00:00+00:00')]
        m=self.run_match(*rows)
        self.assertEqual(self.statuses(m),{'matched'})
        self.assertEqual(len(self.ids(m)),2)

    def test_doubleheaders_and_unknown_game_number(self):
        a,b=synthetic('a',game=1),synthetic('b',game=2)
        rows=[a,b,synthetic('c',Venue.NOVIG,game=1),synthetic('d',Venue.NOVIG,game=2)]
        m=self.run_match(*rows)
        self.assertEqual(self.statuses(m),{'matched'})
        self.assertEqual(len(self.ids(m)),2)
        m=self.run_match(a,b,synthetic('unknown',Venue.NOVIG))
        self.assertEqual(self.statuses(m),{'ambiguous'})
        self.assertEqual(self.ids(m),set())

    def test_missing_uncertain_and_postponed(self):
        a=synthetic('a')
        for b in (synthetic('b',Venue.NOVIG,start=None),
                  synthetic('b',Venue.NOVIG,status='uncertain'),
                  synthetic('b',Venue.NOVIG,status='postponed')):
            self.assertEqual(self.statuses(self.run_match(a,b)),{'candidate'})
            self.assertEqual(self.statuses(self.run_match(b)),{'unmatched'})
        m=self.run_match(a,synthetic('c',start='2026-09-14T17:00:00+00:00'),
                         synthetic('missing',Venue.NOVIG,start=None))
        self.assertEqual(self.statuses(m),{'ambiguous'})

    def test_transitive_chain_no_merge(self):
        m=self.run_match(synthetic('a'),synthetic('b',Venue.NOVIG,start='2026-09-13T17:10:00+00:00'),
                         synthetic('c',Venue.KALSHI,start='2026-09-13T17:20:00+00:00'))
        self.assertEqual(self.statuses(m),{'ambiguous'})
        self.assertFalse(self.ids(m))

    def test_duplicate_observations_and_native_listings(self):
        a=synthetic('a'); b=synthetic('b',Venue.NOVIG)
        m=self.run_match(a,a,b); baseline=m.snapshot
        self.assertEqual(len(baseline['observations']),2)
        m.ingest([b,a]); self.assertEqual(m.snapshot,baseline)
        self.assertEqual(self.statuses(self.run_match(a,synthetic('recreated'))),{'ambiguous'})
        self.assertEqual(self.statuses(self.run_match(synthetic('old',status='canceled'),a)),{'ambiguous'})

    def test_input_order_independence(self):
        rows=[synthetic('a'),synthetic('b',Venue.NOVIG),synthetic('c',start='2026-09-14T17:00:00+00:00')]
        baseline=self.run_match(*rows).snapshot
        for order in itertools.permutations(rows):
            self.assertEqual(self.run_match(*order).snapshot,baseline)

    def test_update_batch_order_independence(self):
        rows=[synthetic('a'),synthetic('a',start='2026-09-15T17:00:00+00:00')]
        self.assertEqual(self.run_match(*rows).snapshot,self.run_match(*reversed(rows)).snapshot)
        self.assertEqual(self.statuses(self.run_match(*rows)),{'conflicting'})

    def test_conflicting_update_retains_identity_and_audit(self):
        a=synthetic('a'); m=self.run_match(a); cid=self.ids(m)
        update=synthetic('a',start='2026-09-15T17:00:00+00:00')
        m.ingest([update])
        self.assertEqual(self.ids(m),cid)
        self.assertEqual(self.statuses(m),{'conflicting'})
        self.assertEqual(len(m.snapshot['observations']),2)
        self.assertEqual(m.snapshot['current'][a['key']],a['hash'])
        before=m.snapshot; m.ingest([update]); self.assertEqual(m.snapshot,before)
        self.assertEqual(m.snapshot['revisions'][-1]['after']['revision'],2)

    def test_reschedule_review_preserves_canonical_and_history(self):
        a=synthetic('a'); m=self.run_match(a); cid=self.ids(m)
        update=synthetic('a',start='2026-09-15T17:00:00+00:00'); m.ingest([update])
        with self.assertRaises(ValueError):
            m.review_schedule(a['key'],update['hash'],reason='',actor='test',source='test')
        m.review_schedule(a['key'],update['hash'],reason='Synthetic postponement',actor='test',source='synthetic')
        self.assertEqual(self.ids(m),cid)
        self.assertEqual(m.snapshot['current'][a['key']],update['hash'])
        self.assertEqual(m.snapshot['observations'][a['hash']],a)
        self.assertEqual(len(m.snapshot['reviews']),1)

    def test_cross_venue_reschedule_requires_group_consistency(self):
        a=synthetic('a'); b=synthetic('b',Venue.NOVIG); m=self.run_match(a,b); cid=self.ids(m)
        updates=[synthetic('a',start='2026-09-15T17:00:00+00:00'),
                 synthetic('b',Venue.NOVIG,start='2026-09-15T17:00:00+00:00')]
        m.ingest(updates)
        self.assertEqual(self.statuses(m),{'conflicting'})
        before=m.snapshot; m.ingest([]); self.assertEqual(m.snapshot,before)
        for i,u in enumerate(updates):
            m.review_schedule(u['key'],u['hash'],reason='Synthetic correction',actor='test',source='synthetic')
            if i==0: self.assertEqual(self.statuses(m),{'conflicting'})
        self.assertEqual(self.statuses(m),{'matched'})
        self.assertEqual(self.ids(m),cid)

    def test_identity_change_cannot_be_schedule_override(self):
        a=synthetic('a'); m=self.run_match(a)
        b=synthetic('a',names=('Yankees','Mets')); m.ingest([b])
        with self.assertRaises(ValueError):
            m.review_schedule(a['key'],b['hash'],reason='test',actor='test',source='synthetic')

    def test_incremental_group_constraint(self):
        a=synthetic('a'); b=synthetic('b',Venue.NOVIG,start='2026-09-13T17:10:00+00:00')
        m=self.run_match(a,b); cid=self.ids(m)
        m.ingest([synthetic('c',Venue.KALSHI,start='2026-09-13T17:20:00+00:00')])
        self.assertNotIn('matched',self.statuses(m))
        self.assertEqual(self.ids(m),cid)

    def test_environment_and_evidence_kind_isolation(self):
        a=synthetic('same',env='production'); b=synthetic('same',env='sandbox')
        m=self.run_match(a,b)
        self.assertEqual(len(self.ids(m)),2)
        self.assertEqual(compare(a,b,900)[1],['environment-or-evidence-kind-isolated'])
        b=deepcopy(a); b['scope'][0]='observation'
        self.assertEqual(compare(a,b,900)[0],'unmatched')

    def test_persistence_equivalence_and_corruption(self):
        m=self.run_match(synthetic('a'),synthetic('b',Venue.NOVIG))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'store.json'; m.save(p); loaded=Matcher.load(p)
            self.assertEqual(m.report(),loaded.report())
            child=subprocess.run([sys.executable,'-c',
                'from app.matching import Matcher,digest; import sys; print(digest(Matcher.load(sys.argv[1]).report()))',
                str(p)],text=True,capture_output=True,check=True)
            self.assertEqual(child.stdout.strip(),digest(m.report()))
            rows=[synthetic('c',start='2026-09-15T17:00:00+00:00')]
            m.ingest(rows);loaded.ingest(rows);self.assertEqual(m.snapshot,loaded.snapshot)
            text=p.read_text();p.write_text(text.replace('event-matcher-1','bad-version'))
            with self.assertRaises(ValueError):Matcher.load(p)
            p.write_text('{"data":{},"data":{}}')
            with self.assertRaises(ValueError):Matcher.load(p)

    def test_store_version_and_audit_validation(self):
        m=self.run_match(synthetic('a'))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'store.json'
            for mutate in ('version','audit','reference'):
                d=m.snapshot
                if mutate=='version': d['schema_version']=999
                elif mutate=='audit': d['revisions'].clear()
                else: d['current'][next(iter(d['current']))]='missing'
                p.write_text(json.dumps({'data':d,'sha256':digest(d)}))
                with self.assertRaises((ValueError,KeyError)): Matcher.load(p)

    def test_failed_atomic_write_keeps_previous_store(self):
        m=self.run_match(synthetic('a'))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'store.json';m.save(p);before=p.read_bytes()
            with patch('app.matching.os.replace',side_effect=OSError('synthetic disk error')):
                with self.assertRaises(OSError):m.save(p)
            self.assertEqual(p.read_bytes(),before)
            self.assertEqual(len(list(Path(td).iterdir())),1)

    def test_raw_provenance_and_defensive_copy(self):
        a=synthetic('a'); before=deepcopy(a); m=self.run_match(a)
        a['roles']['bad']='home'
        snap=m.snapshot;snap['observations'].clear()
        self.assertEqual(m.snapshot['observations'][before['hash']],before)
        self.assertIn('json_text',before['normalized_observation']['observation']['raw'])
        self.assertTrue(before['raw_sha256']);self.assertTrue(before['registry'])
        compact,bodies=compact_raw([before,before])
        self.assertEqual(len(bodies),1)
        self.assertEqual(expand_raw(compact,bodies),[before,before])
        bodies[next(iter(bodies))]='corrupt'
        with self.assertRaises(ValueError):expand_raw(compact,bodies)

    def test_existing_capture_coverage_offline(self):
        with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')):
            r=asyncio.run(report())
        production=next(x for x in r['coverage'] if x['environment']=='production')
        sandbox=next(x for x in r['coverage'] if x['environment']=='sandbox')
        self.assertEqual(production['input_observations'],15)
        self.assertEqual(production['distinct_native_events'],15)
        self.assertEqual(production['canonical_events'],10)
        self.assertEqual(production['outcomes'],{'matched':10,'unmatched':5})
        self.assertEqual(sandbox['input_observations'],32)
        self.assertEqual(sandbox['outcomes'],{'ambiguous':28,'unmatched':4})
        self.assertEqual(sandbox['canonical_events'],4)
        captured=r['captured_results']
        rows=list(captured['observations'].values())
        self.assertEqual(self.run_match(*rows).snapshot,self.run_match(*reversed(rows)).snapshot)
        for pair in captured['comparisons']:
            if pair['status']=='matched':
                self.assertEqual(len(pair['evidence']),2)
                self.assertTrue(all(h in captured['observations'] for h in pair['evidence']))
