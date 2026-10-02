"""Retained records through ordinary Predict, with isolated adversarial fixtures."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from aiohttp.test_utils import TestClient, TestServer
from app.reference.aggregate import bind, VERSION
from app.reference.aggregate_import import OUTPUT
from app.dashboard.session_history import load, verified, project_rows
from app.dashboard.price_comparison import comparisons
from app.dashboard import product_view
from app.dashboard.opportunity_history import observations, Signals, build_history
from tests.test_commercial_engineering import watch

FOLDER=OUTPUT/'odds-aggregate-92257c7e512de1189a81'


def sample_records():
    rows=list(verified(FOLDER)['rows'])
    return [r['original'] for row in rows if row['type']=='product_aggregate' for r in row['records']]


def fixture(records):
    from app.dashboard.session_projection import SessionProjection
    p=SessionProjection();at='2026-09-29T00:00:00Z'
    p.apply(dict(type='session_started',session_id='ISOLATED-FIXTURE',observed_at=at,spec=dict(mode='observation',aggregate_version=VERSION)))
    p.apply(dict(type='product_aggregate',session_id='ISOLATED-FIXTURE',observed_at=at,version=VERSION,records=bind(records)))
    return p


class Aggregate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=sample_records(); cls.snapshot=load(FOLDER)

    def pair(self,market='h2h'):
        group=next(c for c in comparisons(self.snapshot,{}) if c['identity']['family']=={'h2h':'moneyline','spreads':'spread','totals':'total'}[market])
        return [deepcopy(l['provenance']['original']) for l in group['legs']]

    def test_real_retained_roles_feed_filters_and_raw_boundaries(self):
        s=self.snapshot; rows=comparisons(s,{})
        self.assertEqual(len(s['aggregate_coverage']),63)
        self.assertEqual(sum(c['identity']['period']!='full_game' for c in s['aggregate_coverage']),45)
        self.assertEqual(len(self.records),3302);self.assertEqual(len(rows),218)
        self.assertEqual(len(s['references']),2300)
        self.assertEqual({l['venue'] for c in rows for l in c['legs']},{'novig','prophetx'})
        self.assertEqual({r['origin_id'] for r in s['references']},{'pinnacle','draftkings','betmgm'})
        self.assertTrue(all(not product_view.usable(r) for r in s['references']))
        self.assertEqual(product_view.dashboard(s,dict(view='arb'),{}),[])
        self.assertEqual(product_view.dashboard(s,dict(view='ev'),{}),[])
        self.assertTrue(comparisons(s,dict(competition='NCAAF')))
        self.assertFalse(comparisons(s,dict(competition='NBA')))
        self.assertFalse(comparisons(s,dict(competition='NCAAB')))
        self.assertFalse(comparisons(s,dict(venue='pinnacle')))
        self.assertFalse(comparisons(s,dict(positive='true')))
        self.assertFalse(comparisons(s,dict(freshness='usable')))
        for c in rows:
            self.assertIsNone(c['net']);self.assertIsNone(c['ev']);self.assertTrue(c['historical'])
            self.assertEqual(len({l['provenance']['response'] for l in c['legs']}),1)
            for l in c['legs']:
                self.assertIsNone(l['top_size']);self.assertFalse(l['levels']);self.assertIsNone(l['entry']['upper'])
        self.assertEqual(sum(r['price_issue'] is not None for r in bind(self.records)),11)

    def test_line_orientation_missing_books_and_outcomes(self):
        pair=self.pair('spreads')
        self.assertEqual(len(comparisons(fixture(pair).snapshot(),{})),1)
        pair[0]['point']=str(-float(pair[0]['point']) if float(pair[0]['point']) else 1)
        self.assertFalse(comparisons(fixture(pair).snapshot(),{}))
        pair=self.pair('totals');pair[0]['outcome']='Under' if pair[0]['outcome']=='Over' else 'Over'
        self.assertFalse(comparisons(fixture(pair).snapshot(),{}))
        self.assertFalse(comparisons(fixture(self.pair()[:1]).snapshot(),{}))
        pair=self.pair();pair[0]['outcome']='Draw'
        self.assertTrue(bind(pair)[0]['reasons']);self.assertFalse(comparisons(fixture(pair).snapshot(),{}))

    def test_invalid_prices_and_timestamps_only_suppress_dependent_results(self):
        for price in ('1','0','-1','NaN','Infinity','bad'):
            pair=self.pair();pair[0]['decimal_odds']=price
            row=comparisons(fixture(pair).snapshot(),{})[0]
            self.assertIsNone(row['raw_difference']);self.assertIsNone(row['legs'][0]['ask'])
        for timestamp in (None,'bad','2026-09-29T12:00:00','2999-01-01T00:00:00Z'):
            pair=self.pair();pair[0]['source_at']=timestamp
            row=comparisons(fixture(pair).snapshot(),{})[0]
            self.assertIsNotNone(row['raw_difference']);self.assertTrue(row['legs'][0]['warnings'])
        pair=self.pair();pair[0]['received_at']='bad'
        self.assertFalse(comparisons(fixture(pair).snapshot(),{}))

    def test_identity_conflicts_cross_response_and_dedup(self):
        pair=self.pair();p=fixture(pair+pair)
        self.assertEqual(len(p.aggregates),2);self.assertEqual(len(comparisons(p.snapshot(),{})),1)
        conflict=deepcopy(pair[0]);conflict['decimal_odds']='9'
        self.assertFalse(comparisons(fixture(pair+[conflict]).snapshot(),{}))
        pair=self.pair();pair[0]['received_at']='2026-09-28T00:00:00Z'
        self.assertFalse(comparisons(fixture(pair).snapshot(),{}))
        pair=self.pair();pair[0]['receipt_sha256']='another-response'
        self.assertFalse(comparisons(fixture(pair).snapshot(),{}))
        pair=self.pair();pair[0]['scheduled_start']='2026-12-01T00:00:00Z'
        self.assertFalse(comparisons(fixture(pair).snapshot(),{}))
        pair=self.pair();pair[0]['role']='bookmaker_reference'
        self.assertFalse(comparisons(fixture(pair).snapshot(),{}))
        from app.normalization.registry import Registry
        from app.normalization.college_registry import expanded
        data=json.loads(expanded().to_json())
        teamids=[k for k,v in expanded().entities.items() if v.get('league')=='NFL'][:2]
        pair=self.pair();pair[0]['sport']='NFL';pair[0]['home_team']='AMBIGUOUS FIXTURE'
        data['aliases'].append(dict(kind='team',league='NFL',text='AMBIGUOUS FIXTURE',targets=teamids,source='isolated test'))
        self.assertTrue(any('ambiguous' in reason for reason in bind(pair,Registry(data))[0]['reasons']))

    def test_provider_participant_scoped_not_guessed_canonical(self):
        row=next(r for r in bind(self.records) if r['mapping_notes'])
        self.assertTrue(any(str(v).startswith('the_odds_api:') for v in row['identity']['event'][-1].values()))
        self.assertTrue(row['mapping_notes']);self.assertIn(row['original']['source_event_id'],str(row['identity']['event']))

    def test_isolated_missing_sports_through_shared_projection(self):
        for sport in ('NBA','NCAAB'):
            pair=self.pair()
            for r in pair:
                r.update(sport=sport,source_event_id='ISOLATED-'+sport,receipt_sha256='ISOLATED-FIXTURE',
                         home_team='ISOLATED HOME',away_team='ISOLATED AWAY',outcome='ISOLATED HOME')
            s=fixture(pair).snapshot()
            self.assertEqual(len(comparisons(s,dict(competition=sport))),1)
            self.assertFalse(product_view.dashboard(s,dict(view='arb'),{}))
            self.assertTrue(all('ISOLATED' in str(l['provenance']['original']) for c in comparisons(s,{}) for l in c['legs']))

    def test_conflicting_periods_and_unbound_championship(self):
        for period in ('first_half','regulation_9','period_1','season'):
            pair=self.pair();pair[0]['period']=period
            self.assertFalse(comparisons(fixture(pair).snapshot(),{}))
        pair=self.pair();pair[0].update(market='outrights',period='season',
            award_association=dict(season=None,award=None,category='league_champion',conference_id=None))
        # Outrights are supported, but a game record supplies no award/season binding.
        self.assertIn('Exact current season/award association unavailable or conflicting',bind(pair)[0]['reasons'])
        with self.assertRaisesRegex(ValueError,'Unsupported aggregate record'):
            fixture(pair)  # Award records require their separate product_award channel.

    def test_watch_history_exact_reopening_and_live_isolation(self):
        s=self.snapshot;w=watch();obs=observations(s,w)
        self.assertEqual(len(obs),218);self.assertTrue(all(not o['qualifies'] for o in obs))
        p=fixture(self.pair());current=p.snapshot(mode='current')
        self.assertFalse(Signals().update(current,[w],running=True)['events'])
        for metric in ('ev','arb_return'):
            values=observations(s,watch(metric));self.assertEqual(len(values),218)
            self.assertTrue(all(v['metric'] is None and not v['qualifies'] for v in values))
        report=build_history(FOLDER,[w]);self.assertFalse(report['events']);self.assertTrue(report['coverage']['complete'])
        signals=Signals();first=signals.update(s,[w]);second=signals.update(s,[w])
        self.assertEqual(first['exclusions'],second['exclusions'])
        for row in verified(FOLDER)['rows']:
            pass
        rows=list(verified(FOLDER)['rows'])
        for end in range(2,len(rows)+1):
            original=project_rows(rows[:end]);reopened=load(FOLDER,original['durable_cursor'])
            self.assertEqual(comparisons(original,{}),comparisons(reopened,{}))
            self.assertEqual(original['references'],reopened['references'])
        with self.assertRaises(ValueError):load(FOLDER,'wrong-cutoff')
        from app.dashboard.session_projection import SessionProjection
        p=fixture(self.pair())
        with self.assertRaises(ValueError):p.apply(dict(type='coverage_inventory',session_id='ISOLATED-FIXTURE',observed_at='2026-09-29T00:00:00Z'))


class Routes(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_feed_details_watch_download_exact(self):
        from app.dashboard.coverage_owner import CoverageOwner
        from app.dashboard.multi_game_server import create_app
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as temp:
            class Owner(CoverageOwner):
                def history_paths(self):return {FOLDER.name:FOLDER}
                async def start(self,**kwargs):raise ValueError('Retained-only test')
            owner=Owner(Path(temp)/'legacy',pilot_output=Path(temp)/'saved',product_mode=True)
            c=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=Path(temp)/'watches.json')))
            await c.start_server()
            try:
                response=await c.get('/api/dashboard?view=feed&capture='+FOLDER.name)
                self.assertEqual(response.status,200);feed=await response.json()
                self.assertEqual(len(feed['comparisons']),218);self.assertFalse(feed['live']);self.assertFalse(feed['rows'])
                row=feed['comparisons'][0];q={k:row[k] for k in ('session','hash','cutoff','contract')}
                url='/api/calculate?'+urlencode(q)
                detail=await c.get(url);self.assertEqual(detail.status,200);saved=await detail.json()
                self.assertTrue(saved['aggregated']);self.assertEqual(saved,await (await c.get(url)).json())
                response=await c.post('/api/watchlists',json=[watch()],headers={'Origin':str(c.make_url('/')).rstrip('/')});self.assertEqual(response.status,200)
                response=await c.get('/api/opportunity-history?capture='+FOLDER.name+'&download=true')
                self.assertEqual(response.status,200);history=await response.json()
                self.assertFalse(history['events']);self.assertIn('attachment',response.headers['Content-Disposition'])
                response=await c.post('/api/decision-sizes',json=dict(q,sizes=['1']),headers={'Origin':str(c.make_url('/')).rstrip('/')})
                self.assertEqual(response.status,422)
            finally:await c.close()
