"""Isolated documented-schema fixtures; never evidence of actual book coverage."""
from copy import deepcopy
import json
from hashlib import sha256
import unittest
from app.reference.odds_bindings import period_binding, normalize_event, select_event, acquisition_plan
from app.reference.aggregate import bind
from tests.test_aggregate_ingestion import fixture
from app.dashboard.price_comparison import comparisons
from app.dashboard.session_projection import SessionProjection

AT='2026-09-29T00:00:00Z'
SPORTS={'NFL':'americanfootball_nfl','NBA':'basketball_nba','NCAAF':'americanfootball_ncaaf','NCAAB':'basketball_ncaab','MLB':'baseball_mlb','NHL':'icehockey_nhl'}


def event(sport='NFL', market='h2h_h1', outcome='Alpha', point=None):
    return dict(id='abc123',sport_key=SPORTS[sport],commence_time='2026-10-01T00:00:00Z',
        home_team='Alpha',away_team='Beta',bookmakers=[dict(key=book,markets=[dict(key=market,last_update=AT,
        outcomes=[dict(name=outcome,price=price,**({'point':point} if point is not None else {}))])])
        for book,price in [('novig',1.9),('prophetx',2.1)]])


def rows(e,sport='NFL'):
    return normalize_event(json.dumps(e).encode(),sport,AT)


class Bindings(unittest.TestCase):
    def test_all_27_documented_period_cells_through_shared_projection(self):
        for sport in SPORTS:
            suffixes=['h1'] if sport in ('NFL','NBA','NCAAF','NCAAB') else ['1st_3_innings','1st_5_innings'] if sport=='MLB' else ['p1','p2','p3']
            for suffix in suffixes:
                for base in ('h2h','spreads','totals'):
                    with self.subTest(sport=sport,key=base+'_'+suffix):
                        e=event(sport,base+'_'+suffix,'Over' if base=='totals' else 'Alpha',None if base=='h2h' else 2)
                        r=rows(e,sport);p=fixture(r);s=p.snapshot();cs=comparisons(s,{})
                        self.assertEqual(len(cs),1);c=cs[0]
                        self.assertEqual(c['identity']['period'],period_binding(sport,base+'_'+suffix)['period'])
                        self.assertIsNone(c['net']);self.assertIsNone(c['ev']);self.assertIsNone(c['identity']['season'])
                        self.assertEqual(len(s['aggregate_coverage']),63)
                        self.assertEqual(sum(x['comparison_count'] for x in s['aggregate_coverage']),1)
                        self.assertEqual(r[0]['receipt_sha256'],sha256(json.dumps(e).encode()).hexdigest())
                        # Durable record JSON roundtrip must retain exact product output.
                        q=SessionProjection()
                        q.apply(dict(type='session_started',session_id='ISOLATED-FIXTURE',observed_at=AT,spec=dict(mode='observation',aggregate_version='odds-aggregate-1')))
                        q.apply(json.loads(json.dumps(dict(type='product_aggregate',session_id='ISOLATED-FIXTURE',observed_at=AT,version='odds-aggregate-1',records=bind(r)))))
                        self.assertEqual(q.snapshot(),s)

    def test_two_three_way_tie_and_periods_do_not_collapse(self):
        a=rows(event());b=rows(event(market='h2h_3_way_h1'))
        # Same response identity isolates only the market-form difference here.
        for r in b:r['receipt_sha256']=a[0]['receipt_sha256']
        self.assertEqual(len(comparisons(fixture(a+b).snapshot(),{})),2)
        draw=rows(event(market='h2h_3_way_h1',outcome='Draw'))
        c=comparisons(fixture(draw).snapshot(),{})[0]
        self.assertEqual(c['legs'][0]['native_outcome']['predicate'],'draw')
        draw=rows(event(outcome='Draw'));self.assertFalse(comparisons(fixture(draw).snapshot(),{}))
        a[0]['period']='full_game';self.assertFalse(comparisons(fixture(a).snapshot(),{}))

    def test_unsupported_scopes_and_late_records(self):
        for sport,key in [('MLB','h2h_1st_6_innings'),('MLB','totals_1st_9_innings'),('NFL','h2h_p1'),('NHL','h2h_h1'),('NFL','outrights'),('NFL','h2h_3_way')]:
            self.assertIsNone(period_binding(sport,key))
            with self.assertRaises(ValueError):rows(event(sport,key),sport)
        r=rows(event());r[0]['received_at']='2026-10-01T00:00:00Z'
        self.assertFalse(comparisons(fixture(r).snapshot(),{}))
        r=rows(event(market='spreads_h1',point=-2));r[0]['point']='2'
        self.assertFalse(comparisons(fixture(r).snapshot(),{}))

    def test_reference_roles_and_no_native_binding(self):
        e=event();e['bookmakers'][0]['key']='pinnacle';s=fixture(rows(e)).snapshot()
        self.assertFalse(comparisons(s,{}));self.assertEqual(s['references'][0]['role'],'bookmaker_reference')
        cell=next(c for c in s['aggregate_coverage'] if c['identity']==dict(competition='NFL',family='moneyline',period='first_half',category=None))
        self.assertIn('Period records retained',cell['reason'])
        self.assertTrue(all('the_odds_api' in str(r['identity']['event']) for r in bind(rows(e))))

    def test_bounded_selection_and_inert_proposal(self):
        a=event();b=deepcopy(a);b['id']='aaa'
        self.assertEqual(select_event([a,b],AT)['id'],'aaa')
        self.assertIsNone(select_event([a],'2026-10-01T00:00:00Z'))
        self.assertIsNone(select_event([a],'2026-09-01T00:00:00Z'))
        with self.assertRaises(ValueError):select_event([a,a],AT)
        p=acquisition_plan('abc123');self.assertEqual(p['maximum_credits'],3)
        self.assertEqual(p['maximum_requests_including_discovery'],2);self.assertFalse(p['authorized'])
        self.assertEqual(len(p['params']['bookmakers'].split(',')),5)
        with self.assertRaises(ValueError):acquisition_plan('../another')

    def test_event_file_import_hash_and_saved_reopening(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from app.reference.aggregate_import import import_event_response
        from app.dashboard.session_history import load, verified
        with TemporaryDirectory() as d:
            p=Path(d);body=json.dumps(event()).encode();(p/'body.json').write_bytes(body)
            meta=dict(raw_sha256=sha256(body).hexdigest(),received_at=AT)
            (p/'receipt.json').write_text(json.dumps(meta))
            folder=import_event_response(p/'body.json',p/'receipt.json','NFL',p/'sessions')
            first=load(folder);self.assertEqual(len(comparisons(first,{})),1)
            self.assertEqual(load(folder),first);self.assertTrue(list(verified(folder)['rows']))
            with self.assertRaises(FileExistsError):import_event_response(p/'body.json',p/'receipt.json','NFL',p/'sessions')
            (p/'body.json').write_bytes(body+b' ')
            with self.assertRaises(ValueError):import_event_response(p/'body.json',p/'receipt.json','NFL',p/'other')
            (p/'body.json').write_bytes(b' '*(2*1024*1024+1))
            with self.assertRaisesRegex(ValueError,'body limit'):import_event_response(p/'body.json',p/'receipt.json','NFL',p/'large')
