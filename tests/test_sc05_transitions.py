"""Publication evidence, not page diffs. No provider or finance on reads."""
from copy import deepcopy
from unittest import TestCase
from app.comparison.scanner_projection import Projection, Filters
from app.comparison.scanner_transitions import MAX_BATCHES
from tests.test_sc02_projection import frame, fake
from tests.test_ev09_n01 import AT


class Transitions(TestCase):
    def setUp(self):
        self.p=Projection(clock=lambda:AT,evaluator=fake)
        f,x=frame(1);self.p.ingest(f,x);self.p.drain()
        self.filters=Filters(category='covered_outcome_arb')
        self.base=self.p.transitions.read(self.p,self.filters)

    def read(self,prior=None,filters=None):
        prior=prior or self.base
        return self.p.transitions.read(self.p,filters or self.filters,**{k:prior[k] for k in ('cursor','server_id','epoch','scope')})

    def publish(self,rows):
        self.p._publish(rows,'evaluated')

    def test_baseline_rank_receipt_and_read_counters(self):
        self.assertEqual(self.base['continuity'],'censored');self.assertEqual(self.base['events'],[])
        rows=deepcopy(self.p.rows)
        for row in rows.values():row['evaluated_at']='receipt-only'
        count=self.p.evaluations
        self.publish(rows)
        for _ in range(100):self.assertEqual(self.read()['events'],[])
        self.assertEqual(self.p.evaluations,count)
        self.assertEqual(self.read()['financial_evaluations'],0)
        self.assertEqual(self.read()['provider_requests'],0)

    def test_beyond_page_100_improved_and_threshold_crossings(self):
        original=next(iter(self.p.rows.values()));rows={}
        for i in range(130):
            r=deepcopy(original);r.update(id=f'row:{i}',opportunity_id=f'opp:{i}',pair_id=f'pair:{i}')
            r['metric']['value']=str(1000-i);r['supported_capital_usd']='50';rows[r['id']]=r
        self.p.receipts={f'pair:{i}':{} for i in range(130)}
        self.publish(rows);base=self.p.transitions.read(self.p,self.filters)
        # New scope baseline deliberately silent, established before the change.
        high=Filters(minimum_edge='900',category='covered_outcome_arb')
        highbase=self.p.transitions.read(self.p,high)
        low=Filters(minimum_size='100',category='covered_outcome_arb')
        lowbase=self.p.transitions.read(self.p,low)
        changed=deepcopy(rows);r=changed['row:129'];r['metric']['value']='950';r['supported_capital_usd']='150';r['economic_revision']='new';r['dependency_revision']='new'
        self.publish(changed)
        events=self.read(base)['events'];self.assertEqual(len(events),1);self.assertEqual(events[0]['kind'],'improved');self.assertEqual(events[0]['after']['id'],'row:129')
        self.assertEqual(self.read(highbase,high)['events'][0]['kind'],'matching')
        self.assertEqual(self.read(lowbase,low)['events'][0]['kind'],'matching')
        # User scope change with an old cursor cannot manufacture arrival.
        self.assertEqual(self.read(base,low)['continuity'],'censored')

    def test_new_episode_requires_observed_previous_evaluation_and_withdrawal(self):
        rows=deepcopy(self.p.rows);key=next(iter(rows));self.publish({})
        e=self.read()['events'][0];self.assertEqual(e['kind'],'withdrawn')
        previous=self.p.transitions.read(self.p,self.filters)
        self.publish(rows);e=self.read(previous)['events'][0];self.assertEqual(e['kind'],'new')
        self.assertNotEqual(e['episode_id'],self.base.get('episode_id'))
        previous=self.p.transitions.read(self.p,self.filters)
        self.p.receipts={};self.publish({});self.assertEqual(self.read(previous)['events'][0]['kind'],'unavailable')

    def test_gap_overflow_epoch_and_stop_silent(self):
        for _ in range(MAX_BATCHES+2):self.publish(deepcopy(self.p.rows))
        self.assertEqual(self.read()['continuity'],'censored')
        base=self.p.transitions.read(self.p,self.filters)
        self.p.errors=['unknown'];self.publish({})
        self.assertEqual(self.read(base)['events'],[]);self.assertFalse(self.read(base)['coverage_complete'])
        self.p.errors=[];self.p.epoch='new';self.publish({})
        self.assertEqual(self.read(base)['continuity'],'censored')
        self.p.stop();self.assertEqual(self.read(base)['events'],[])

    def test_pending_not_withdrawal_small_churn_and_cooldown(self):
        rows=deepcopy(self.p.rows);self.p.pending['pending']={};self.publish({})
        self.assertEqual(self.read()['events'],[])
        self.p.pending.clear();self.publish(rows)
        base=self.p.transitions.read(self.p,self.filters)
        for i in range(3):
            rows=deepcopy(rows);r=next(iter(rows.values()));r['economic_revision']=str(i);r['dependency_revision']=str(i);r['metric']['value']=str(__import__('fractions').Fraction(r['metric']['value'])+1)
            self.publish(rows)
        e=self.read(base)['events'];self.assertEqual(sum(x['kind']=='improved' for x in e),1)
