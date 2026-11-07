"""Independent whole-universe exact order and grouping checks (no production DB)."""
from copy import deepcopy
from fractions import Fraction as F
from random import Random
from time import perf_counter
from unittest import TestCase
from app.dashboard.snapshot_api import page
from app.dashboard.snapshot_display import outcome_key
from app.comparison.snapshot_fee_scope import RANKING_BASIS


def source(outcome, venue, value, *, estimate=None):
    return dict(id=f'{outcome:05}-{venue}', game_key=f'game-{outcome:05}', game_title=f'Game {outcome}',
        venue=venue, start_at='2026-11-06T12:00:00Z', league='NFL',
        market=dict(market='winner',period='full_game',line=None),
        selection=dict(predicate='win',participant='NFL:BAL',result_interpretation='normal_win'),
        original=dict(value='2.00',units='decimal_odds',payout='1'),
        evidence_result_id=f'member-{outcome}', price_revision='price', economic_revision='economics',
        conditional_return_percent=value, conservative_return_percent=estimate,
        gross_return_percent='9999', price_current=True, current_authority={'price':{}},
        conditional_trade_benchmark=dict(available=value is not None,ranking_basis=RANKING_BASIS),
        conservative_trade_benchmark=dict(available=estimate is not None,ranking_basis=RANKING_BASIS,ranking_eligible=False),
        metric_status=dict(after_trade_fee_ev=dict(state='available' if value is not None else 'unavailable'),
                           conservative_trade_fee_ev=dict(state='available' if estimate is not None else 'unavailable')))


def result(rows):
    return dict(rows=rows,pairs=[],references=[],publication={},games=[])


class GroupedLiveRanking(TestCase):
    def test_whole_universe_exact_oracle_and_complete_pages(self):
        rng=Random(304);rows=[];scores={}
        for i in range(701):
            values=[None if rng.randrange(4)==0 else F(rng.randrange(-5,6)*100000+rng.randrange(3),100000) for _ in range(4)]
            scores[i]=max((x for x in values if x is not None),default=None)
            for venue,v in zip(('kalshi','polymarket_us','novig','prophetx'),values):
                rows.append(source(i,venue,None if v is None else str(v),estimate='10000'))
        rng.shuffle(rows);data=result(rows);before=deepcopy(data)
        expected=sorted(scores,key=lambda i:(scores[i] is None,-scores[i] if scores[i] is not None else 0,f'game-{i:05}'))
        got=[];ids=[]
        for offset in range(0,701,37):
            p=page(data,dict(group='outcome',metric='conditional_return_percent',offset=str(offset),limit='37'))
            self.assertEqual(p['outcome_count'],701);self.assertEqual(p['source_price_count'],2804)
            self.assertEqual(p['unranked_count'],sum(v is None for v in scores.values()))
            for g in p['rows']:
                i=int(g['game_key'].split('-')[1]);got.append(i)
                self.assertEqual(len(g['quotes']),4)
                self.assertEqual(None if g['score'] is None else F(g['score']),scores[i])
                if scores[i] is not None:
                    winner=next(q for q in g['quotes'] if q['id']==g['score_source']['id'])
                    self.assertEqual(F(winner['conditional_return_percent']),scores[i])
                ids.extend(q['id'] for q in g['quotes'])
        self.assertEqual(got,expected);self.assertEqual(len(set(ids)),len(rows));self.assertEqual(data,before)
        rng.shuffle(rows)
        self.assertEqual([g['game_key'] for g in page(data,dict(group='outcome',metric='conditional_return_percent',limit='100'))['rows']], [f'game-{i:05}' for i in expected[:100]])

    def test_expired_unsupported_negative_unknown_and_estimate_separation(self):
        rows=[source(0,'kalshi',None,estimate='80'),source(1,'novig','-1'),source(2,'novig','0'),
              source(3,'novig','50'),source(4,'novig','60'),source(5,'novig','70')]
        rows[3]['price_current']=False
        rows[4]['metric_status']['after_trade_fee_ev']['state']='withdrawn'
        rows[5]['conditional_trade_benchmark']['ranking_basis']='different_fill_size'
        p=page(result(rows),dict(group='outcome',metric='conditional_return_percent'))
        self.assertEqual([g['score'] for g in p['rows']],['0','-1',None,None,None,None])
        self.assertEqual(p['unranked_count'],4)
        e=page(result(rows),dict(group='outcome',metric='conservative_return_percent'))
        self.assertEqual(e['rows'][0]['score'],'80');self.assertEqual(e['ranking']['basis'],'conservative_public_schedule_estimate')

    def test_identity_and_native_instruments_preserved(self):
        a=source(0,'novig','1');b=deepcopy(a);b['id']='distinct-native';b['source']={'native_market_id':'other'}
        self.assertEqual(outcome_key(a),outcome_key(b))
        rows=[a,b]
        for field,value in [('predicate','not_win'),('participant','NFL:JAX'),('signed_line','-3')]:
            r=deepcopy(a);r['id']=field;r['selection'][field]=value;rows.append(r)
        for field,value in [('period','first_half'),('line','3')]:
            r=deepcopy(a);r['id']=field;r['market'][field]=value;rows.append(r)
        r=deepcopy(a);r['id']='other-occurrence';r['game_key']='other-game';rows.append(r)
        p=page(result(rows),dict(group='outcome',metric='conditional_return_percent'))
        self.assertEqual(p['total'],7);self.assertEqual(p['source_price_count'],8)
        self.assertEqual(sorted(len(g['quotes']) for g in p['rows']),[1]*6+[2])

    def test_realistic_broad_volume_first_page(self):
        rows=[source(i,v,str(F(i%31-15,7))) for i in range(5000) for v in ('kalshi','polymarket_us','novig','prophetx')]
        start=perf_counter();p=page(result(rows),dict(group='outcome',metric='conditional_return_percent'))
        elapsed=perf_counter()-start
        self.assertEqual(p['total'],5000);self.assertEqual(p['source_price_count'],20000)
        self.assertEqual(sum(len(g['quotes']) for g in p['rows']),100)
        print(f'L03 broad fixture: 20,000 sources / 5,000 outcomes: {elapsed:.3f}s useful page')
