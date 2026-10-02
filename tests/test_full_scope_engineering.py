"""Full required local product scope; synthetic reviews never qualify native coverage."""
import importlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from app.dashboard import product_view, session_history
from app.dashboard.decision_support import size_report
from app.dashboard.opportunity_feed import combine
from app.dashboard.opportunity_history import Signals, observations
from app.collection.transport_session import ObservationJournal
from app.normalization import futures, score_periods
from app.normalization.college_registry import expanded
from tests.test_commercial_engineering import snapshot, watch
from tests.test_periods import snapshot as project
from tests.test_score_lines import reseal

SPORTS = ('NFL','NBA','MLB','NHL','NCAAF','NCAAB')


def championship(sport, category):
    from tests.test_futures import fixture
    rows = fixture(category=category)
    field = sorted(k for k,v in expanded().entities.items() if v.get('league') == sport)[:3]
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor']
        old=list(e['field']);mapping=dict(zip(old,field))
        e.update(competition=sport, season=futures.SEASONS[sport], field=field,
                 sport={'NFL':'american_football','NCAAF':'american_football','MLB':'baseball','NHL':'ice_hockey','NBA':'basketball','NCAAB':'basketball'}[sport],
                 division='I' if sport=='NCAAB' else None,
                 championship_id='SYNTHETIC-'+sport+'-'+category,
                 horizon=futures.SEASONS[sport]+' championship',
                 scheduled_start='2026-12-01T00:00:00Z' if sport=='MLB' else '2027-07-01T00:00:00Z')
        for state in e['states']:state['winners']=[mapping[v] for v in state['winners']]
        d.update(participant=field[0],horizon=e['horizon'])
        m.update(subject=field[0],horizon=e['horizon'])
        m['product_outcomes']=[dict(side,participant=field[0]+' '+side['native_label'],predicate='score',operator='state',threshold=None,domain='championship_states',label=field[0]+' '+side['native_label']) for side in d['outcomes']]
        r['event_binding']=futures.event_key(e)
        meta=next(v['market'] for v in rows if v['type']=='market_selected' and v['source']==source)
        native=json.loads(meta['raw']['json_text']);native['SYNTHETIC_future_event']={k:e[k] for k in futures.EVENT_FIELDS}
        meta['raw']['json_text']=json.dumps(native);reseal(rows,source)
    return rows


def cases():
    for sport in SPORTS:
        module='session_projection' if sport=='NFL' else sport.lower()
        yield (sport,'full_game','moneyline'), importlib.import_module('tests.test_'+module).fixture()
        for family in ('spread','total'):
            module='score_lines' if sport in ('NBA','NCAAB') else sport.lower()+'_lines'
            yield (sport,'full_game',family), importlib.import_module('tests.test_'+module).fixture(competition=sport,family=family,line='-3' if family=='spread' else '7')
        if sport in ('NFL','NBA','NCAAF','NCAAB'):
            for family in ('moneyline','spread','total'):
                yield (sport,'first_half',family), importlib.import_module('tests.test_'+sport.lower()+'_first_half').fixture(family=family,line='-3' if family=='spread' else '7')
        if sport in score_periods.PERIODS:
            from tests.test_periods import fixture
            for period in score_periods.PERIODS[sport]:
                for family in ('moneyline','spread','total'):
                    yield (sport,period,family), fixture(sport,period,family,line='-3' if family=='spread' else '7')
        for category in ('conference_champion','league_champion'):
            yield (sport,'season',category), championship(sport,category)


class RequiredScope(unittest.TestCase):
    def test_all_63_cells_feed_details_sizes_watch_and_exact_cutoff(self):
        count=0
        for cell,rows in cases():
            with self.subTest(cell=cell):
                s=project(rows);self.assertTrue(s['games'],[(m['source_id'],m['reason']) for m in s['market_catalog']])
                g=next(g for g in s['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
                q=dict(competition=cell[0],period=cell[1],family='futures' if cell[1]=='season' else cell[2],quantity='1')
                feed=combine(product_view.dashboard(s,dict(q,view='ev'),{}),product_view.dashboard(s,dict(q,view='arb'),{}))
                self.assertTrue(feed);self.assertTrue(all(r['decision']['quantity'] for r in feed))
                self.assertEqual(len({r['id'] for r in feed}),len(feed))
                report=size_report(s,g,dict(sizes=['1','.5'],scenario='cent',ceiling='10'))
                self.assertTrue(report['sizes'][0]['candidates']);self.assertIn('whole',report['sizes'][1]['limitation'])
                w=watch('arb_return');w['filters']={k:q[k] for k in ('competition','period','family')}
                values=observations(s,w);self.assertTrue(values)
                with tempfile.TemporaryDirectory() as t:
                    folder=Path(t)/s['session_id'];folder.mkdir();j=ObservationJournal(folder/(s['session_id']+'.jsonl'))
                    for row in rows:j.save(row)
                    j.close();saved=session_history.load(folder,s['durable_cursor'])
                    self.assertEqual(product_view.calculate(saved,g,dict(quantity='1')),product_view.calculate(s,g,dict(quantity='1')))
                    self.assertEqual(observations(saved,w),values)
                count+=1
        self.assertEqual(count,63)

    def test_championship_requires_explicit_conference_identity(self):
        rows=championship('NBA','conference_champion');e=rows[1]['inventory']['kalshi']['events'][0]
        for value in (None,'','   ',123):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'conference'):
                futures.event_key(dict(e,conference_id=value))
        e.pop('conference_id')
        with self.assertRaisesRegex(ValueError,'conference'):futures.event_key(e)
        e['category']='league_champion'
        with self.assertRaisesRegex(ValueError,'conference'):futures.event_key(e)


class SignalChanges(unittest.TestCase):
    def test_readmitted_same_book_recovers_after_disconnect(self):
        from tests.test_commercial_engineering import qualified_fixture
        p,s=snapshot();w=watch();engine=Signals()
        engine.update(s,[w])
        keys=[k for k,i in engine.items.items() if i['active']]
        self.assertTrue(keys)
        p.apply(dict(type='source_health',session_id=p.sid,observed_at=p.last,source='kalshi',state='disconnected'))
        engine.update(p.snapshot(),[w])
        self.assertTrue(all(not engine.items[k]['active'] for k in keys))
        p.apply(dict(type='source_health',session_id=p.sid,observed_at=p.last,source='kalshi',state='connected'))
        for row in qualified_fixture():
            if row['type']=='prediction_book' and row['source']=='kalshi':p.apply(row)
        engine.update(p.snapshot(),[w])
        self.assertTrue(all(engine.items[k]['active'] for k in keys))
        self.assertTrue(all(engine.items[k]['episodes']==2 for k in keys))

    def test_reference_metric_and_eligibility_changes_without_new_book(self):
        _,s=snapshot();w=watch('ev');engine=Signals()
        leg=dict(id='l',book_id='same-book',age_seconds='0',received_at='2026-09-16T12:00:00+00:00',fee='0',fee_audit={'qualification':'documented_scenario','unsupported':[]})
        row=dict(id='c',game_title='Synthetic calculation state',return_pct='-1',modeled_quantity='1',usable=True,legs=[leg],session='b2-fixture~g',hash='b2-fixture',cutoff='1-x',at='2026-09-16T12:00:00+00:00',probability='.5',reference_id='model')
        s['references']=[dict(id='model',freshness='within_refresh_plan',delay_seconds=0)]
        with patch('app.dashboard.product_view.dashboard',return_value=[row]):
            self.assertFalse(engine.update(s,[w])['items'][0]['active'])
            row.update(return_pct='2',probability='.6',cutoff='2-x')
            item=engine.update(s,[w])['items'][0]
            self.assertTrue(item['active']);self.assertEqual(item['episodes'],1)
            row.update(at='2026-09-16T12:00:01+00:00',cutoff='clock-only')
            leg['fee_audit']['context_hash']='calculation-clock-changed'
            self.assertEqual(engine.update(s,[w])['items'][0]['qualifying_observations'],1)
            s['references'][0]['freshness']='refresh_due'
            self.assertFalse(engine.update(s,[w])['items'][0]['active'])
            s['references'][0]['freshness']='within_refresh_plan';row['cutoff']='3-x'
            item=engine.update(s,[w])['items'][0]
            self.assertTrue(item['active']);self.assertEqual(item['episodes'],2)
            self.assertEqual(item['last']['cutoff'],'3-x')
            row.update(return_pct='3',probability='.7',cutoff='4-x')
            item=engine.update(s,[w])['items'][0]
            self.assertEqual(item['changes'][-1]['value'],'3');self.assertEqual(item['qualifying_observations'],3)
            self.assertFalse(engine.update(s,[w],running=False)['items'][0]['active'])
