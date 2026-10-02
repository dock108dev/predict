"""Regression checks for work avoided without altering retained prices or ages."""
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime
from aiohttp.test_utils import TestClient,TestServer
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_projection import SessionProjection
from app.dashboard.session_history import verified

FOLDER=Path(__file__).resolve().parents[1]/'evidence/live-comparison-multi-run-b9b5f3c7-514f-4ef6-b27d-ac77c5138c17/b9b5f3c7-514f-4ef6-b27d-ac77c5138c17'

@unittest.skipUnless(FOLDER.exists(),'retained local run is not distributed in CI')
class RetainedFreshness(unittest.IsolatedAsyncioTestCase):
    async def test_selected_current_avoids_saved_load_and_registry_per_market(self):
        p=SessionProjection()
        for r in list(verified(FOLDER)['rows'])[:1400]:p.apply(r)
        # This retained-current fixture must not age out as the wall calendar moves.
        class FrozenClock(datetime):
            @classmethod
            def now(cls,tz=None):return datetime.fromisoformat(p.last)
        class Owner(CoverageOwner):
            def active(self):return True
            def status(self):return dict(state='running',active=True,start_available=False)
            def saved(self):return []
            def history_paths(self):return {'unselected':Path('/nonexistent-saved-history')}
            async def close(self):pass
        with tempfile.TemporaryDirectory() as t:
            o=Owner(Path(t),product_mode=True);o.session=SimpleNamespace(projection=p,persistence_error=None,projection_error=None,sid=p.spec['two_source_qualification']['attempt_id'],output=FOLDER,journal=None)
            c=TestClient(TestServer(create_app(owner=o,sessions={})));await c.start_server()
            try:
                from app.normalization.registry import Registry
                with patch('app.dashboard.session_projection.datetime',FrozenClock),patch('app.dashboard.session_history.load',side_effect=AssertionError('unselected history replayed')),patch.object(Registry,'load',wraps=Registry.load) as load:
                    first=await (await c.get('/api/dashboard?view=feed')).json();self.assertEqual(len(first['comparisons']),8)
                    self.assertEqual(load.call_count,0) # Explicit review avoids legacy per-market registry work.
                    frozen=o.cutoffs.copy()
                    second=await (await c.get('/api/dashboard?view=feed')).json()
                    self.assertEqual(load.call_count,0) # Unchanged reviewed inputs remain reusable.
                    self.assertIs(next(iter(frozen.values())),next(iter(o.cutoffs.values())))
                    self.assertEqual([l['received_at'] for x in first['comparisons'] for l in x['legs']],[l['received_at'] for x in second['comparisons'] for l in x['legs']])
                    self.assertTrue(all(not x['timing']['synchronized'] and x['net'] is None for x in second['comparisons']))
                    self.assertTrue(all(x['settlement_status']=='INCOMPATIBLE' for x in second['comparisons']))
                    self.assertTrue(all(any(c['condition']=='postponement' for c in x['settlement_audit']['conflicts']) for x in second['comparisons']))
            finally:await c.close()

class RetainedTerms(unittest.TestCase):
    def test_exact_two_week_listing_and_missing_coefficient(self):
        import json
        from app.opportunities.board import assess
        at='2026-09-28T01:00:00+00:00'
        identity={'sources':{'polymarket_us':{'market_id':'m','event_id':'e'}}}
        market={'id':'m','description':'If the game ends in a tie, the market will settle to $0.50. If not rescheduled to a date within two weeks, the market will settle to the last fair market price.'}
        row={'type':'market_selected','source':'polymarket_us','observed_at':at,'market':{'raw':{'json_text':json.dumps({'markets':[market]}),'source':'retained-test','received_at':at,'ref':{'market_id':'m'}}}}
        result=assess([row],at,identity)
        self.assertIsNone(result['pmus_coefficient'])
        self.assertEqual(result['profiles']['polymarket_us']['dimensions']['postponement']['value'],'rescheduled date within two weeks; otherwise last fair market price')
        market['description']=market['description'].replace('two weeks','three weeks');row['market']['raw']['json_text']=json.dumps({'markets':[market]})
        with self.assertRaises(ValueError):assess([row],at,identity)
