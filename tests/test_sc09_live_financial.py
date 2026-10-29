"""Live qualification repairs: authored ordering and local write boundaries."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from psycopg.errors import LockNotAvailable
from app.storage.schedule_metadata import choose, witness
from app.storage.store import hashed
from tests.test_schedule_metadata import evidence


def aggregate_event(at, start='2026-12-25T17:10:00Z'):
    e=evidence(dict(id='provider-event',sport='basketball',competition='NBA',home='NBA:A',away='NBA:B',
        participants={'A':'NBA:A','B':'NBA:B'},scheduled_start=start),at)
    e['schedule_metadata']['authority']=['the_odds_api','event',e['id']]
    v=e['schedule_metadata'];v['revision']=hashed({k:x for k,x in v.items() if k!='revision'})
    return e


def test_legacy_conflict_recovers_only_after_observed_bound_and_same_occurrence():
    new=aggregate_event('2026-10-28T17:00:00Z')
    old=deepcopy(new);old.pop('schedule_metadata');old['scheduled_start']='2026-12-25T17:00:00Z'
    old['schedule_conflict']={'reason':'schedule_metadata_order_unverified','witnesses':[None,witness(new)]}
    marked=choose(old,new,observed_at='2026-10-28T17:01:00Z')
    assert 'schedule_conflict' in marked
    assert 'schedule_conflict' in choose(marked,new)
    later=aggregate_event('2026-10-28T17:15:00Z')
    recovered=choose(marked,later)
    assert 'schedule_conflict' not in recovered
    assert recovered['scheduled_start']==later['scheduled_start']
    assert recovered['schedule_recovery']['prior']==marked['schedule_conflict']
    wrong=deepcopy(later);wrong['game_number']=2
    assert 'schedule_conflict' in choose(marked,wrong)
    assert 'observed_before' not in old['schedule_conflict']


def test_alternate_lock_retry_never_dispatches_or_changes_receipt():
    from app.collection.alternate_acquisition import save_response
    response={'body':b'original','received_at':'2026-10-28T17:00:00Z'}
    before=deepcopy(response)
    with patch('app.collection.alternate_acquisition._save_response',side_effect=[LockNotAvailable(),None]) as save:
        save_response('NBA','event',response,'cycle')
    assert save.call_count==2
    assert save.call_args_list[0]==save.call_args_list[1]
    assert response==before


def test_alternate_stop_is_not_retried():
    from app.collection.alternate_acquisition import save_response
    from app.collection.current_quota import QuotaStop
    with patch('app.collection.alternate_acquisition._save_response',side_effect=QuotaStop('aggregate_owner_stopped')) as save:
        with pytest.raises(QuotaStop):save_response('NBA','event',{},'cycle')
    assert save.call_count==1


def test_reviewed_scoring_rules_are_exact_type_bound():
    from app.comparison.native_scoring_scope import source_rules
    rules=source_rules()
    for name in ('KXNBAGAME','KXNBASPREAD','KXNBATOTAL','KXNCAAMBSPREAD','KXNCAAMBTOTAL'):
        rule=next(r for r in rules if r['native_type']==name)
        assert rule['overtime']=='included' and rule['evidence_available']
    # A different governing document must not inherit basketball winner rules.
    assert next(r for r in rules if r['native_type']=='KXNCAAMBGAME')['overtime']=='unknown'
    assert all(r['overtime']=='included' for r in rules if r['provider']=='polymarket_us' and r['period']=='full_game')


def test_conditional_math_independent_and_not_complete_ev():
    from fractions import Fraction as F
    from datetime import datetime,timezone
    from app.comparison.conditional_benchmark import attach
    evidence=dict(reviewed_at='2026-10-28T00:00:00Z',review_before='2026-10-29T00:00:00Z')
    at=datetime(2026,10,28,18,tzinfo=timezone.utc)
    q=dict(venue='novig',source=dict(provider='the_odds_api',native_side='bookmaker_outcome'),
        original=dict(value='2',units='decimal_odds'),times=dict(source_at='original',received_at='receipt'))
    for odds in ('1.0001','1.5','2','2.0000001','1000'):
        q['original']['value']=odds
        raw=dict(revision='original',gross_decisive_benchmark=dict(available=True,
            selected_decisive_probability='1/2',reference_revision='exact-pair',state='numeric_last_known'))
        for family in ('winner','spread','total'):
            with patch('app.comparison.conditional_benchmark.basis',return_value=evidence):
                result=attach(deepcopy(raw),q,at=at,event={'start_at':'2026-10-30T00:00:00Z'},group={'period':'full_game','market':family})
            m=result['conditional_trade_benchmark']
            # Independent terminal payoff sum: equal chances of d-1 and -1.
            assert F(m['net_per_dollar_risk'])==((F(odds)-1)-1)/2
            assert F(m['return_percent'])==100*((F(odds)-1)-1)/2
            assert not m['execution_qualified'] and not m['calibrated']
            assert m['source_times']==q['times'] and m['state']=='numeric_last_known'
            assert 'financial_metrics' not in result
    with patch('app.comparison.conditional_benchmark.basis',return_value=evidence):
        expired=attach(deepcopy(raw),q,at=datetime(2026,10,29,tzinfo=timezone.utc),event={},group={})
        started=attach(deepcopy(raw),q,at=at,event={'start_at':at.isoformat()},group={})
    assert not expired['conditional_trade_benchmark']['available']
    assert not started['conditional_trade_benchmark']['available']


def test_provider_display_team_labels_are_exact_event_bound():
    from app.collection.admission_enrichment import source_team_label
    event=dict(competition='NBA',participants={'Charlotte Hornets':'NBA:CHA','Detroit Pistons':'NBA:DET'},
        _native=dict(teams=[dict(name='Charlotte Hornets',safeName='Hornets',displayAbbreviation='CHA'),
            dict(name='Detroit Pistons',safeName='Pistons',abbreviation='det')]))
    assert source_team_label('CHA Hornets',event)=='NBA:CHA'
    assert source_team_label('DET Pistons',event)=='NBA:DET'
    assert source_team_label('DET Hornets',event) is None
    assert source_team_label('CHA Hornets',dict(event,_native={})) is None
    assert source_team_label('CHI Bulls',event) is None


def test_occurrence_projection_preserves_global_matching_and_inputs():
    from app.comparison.occurrence_matching import OccurrenceResolver
    from app.comparison.event_links import EventLinks
    from tests.test_ev02_occurrence import AT,rows
    records=rows('kalshi','a')+rows('polymarket_us','b')
    before=deepcopy(records)
    select=lambda r: (r['verified'],r['market_identity'],r['quote']['occurrence_match']['status'],r['quote']['occurrence_match']['occurrence_id'])
    full=OccurrenceResolver(links=EventLinks()).resolve(records,clock=AT)
    compact=OccurrenceResolver(links=EventLinks()).resolve(records,clock=AT,result_projector=select)
    assert compact==list(map(select,full)) and records==before


def test_shared_worker_deferral_preserves_next_unprocessed_component():
    from contextlib import contextmanager,nullcontext
    from app.storage import latest_board as latest
    from app.collection.background_work import Lease
    class DB:
        def transaction(self):return nullcontext()
        def execute(self,*args):return self
        def fetchall(self):return []
    class Work:
        acquisition_pressure=staticmethod(lambda:False)
        count=0
        @contextmanager
        def claim(self,kind,size,**kwargs):
            self.count+=1
            yield Lease(self.count==1,None if self.count==1 else 'background_work_turn',kind,size,0)
        def resize(self,*args):
            if args[1]==3:raise ValueError('background_memory_capacity')
    admission={};work=Work()
    with patch('app.collection.background_work.BACKGROUND',work), \
         patch.object(latest,'capture_batches',return_value=[['a'],['b'],['c']]), \
         patch.object(latest,'capture_reservation',side_effect=[1,2,3]), \
         patch.object(latest,'_reconcile',return_value=dict(published=True,computed=1,reused=0,errors=[])) as run:
        value=latest.reconcile(DB(),admission=admission)
    assert run.call_count==1
    assert admission['estimates_after']=='a'
    assert admission['estimates_cursor']==1
    assert value['yielded'] and value['remaining_batches']==2


def test_hot_source_turn_cannot_reset_quiet_component_rotation():
    from contextlib import contextmanager,nullcontext
    from app.storage import latest_board as latest
    from app.collection.background_work import Lease
    class DB:
        def transaction(self):return nullcontext()
        def execute(self,*args):return self
        def fetchall(self):return []
    class Work:
        acquisition_pressure=staticmethod(lambda:False)
        @contextmanager
        def claim(self,kind,size,**kwargs):yield Lease(True,None,kind,size,0)
        def resize(self,*args):pass
    admission={};clock=iter(range(0,1000,100));visited=[]
    def calculate(db,**kwargs):
        visited.append(kwargs['event_ids'])
        return dict(published=True,computed=1,reused=0,errors=[])
    with patch('app.collection.background_work.BACKGROUND',Work()), \
         patch.object(latest,'capture_batches',return_value=[['a'],['b'],['c']]), \
         patch.object(latest,'capture_reservation',return_value=1), \
         patch.object(latest,'prioritize_sources',side_effect=lambda db,batches,at:[['c'],*[b for b in batches if b!=['c']]]), \
         patch.object(latest,'monotonic',side_effect=lambda:next(clock)), \
         patch.object(latest,'_reconcile',side_effect=calculate):
        for _ in range(4):latest.reconcile(DB(),observations_only=True,admission=admission)
    assert visited==[['c'],['a'],['c'],['b']]
    assert admission['observations_after']=='b'


def test_polymarket_single_fill_conditional_fee_and_payoff_boundaries():
    from datetime import datetime,timezone
    from decimal import Decimal,ROUND_HALF_EVEN
    from fractions import Fraction as F
    from app.comparison.conditional_benchmark import attach,rounded_cents,basis
    evidence=basis('polymarket_us')
    at=datetime(2026,10,28,19,tzinfo=timezone.utc)
    q=dict(venue='polymarket_us',source=dict(provider='polymarket_us',native_side='Long'),
        original=dict(value='.5',units='usd_per_contract',quantity_units='contracts',payout='1',payout_units='USD'),
        times=dict(source_at='source-clock',received_at='receipt-clock'))
    for raw,want in [('.005','0'),('.025','.02'),('.035','.04'),('.0249999','.02'),('.0250001','.03')]:
        assert rounded_cents(F(raw))==F(want)
    for cost in ('.01','.25','.5','.7525','.99'):
        decimal=Decimal(cost);fee=(Decimal('.0695')*decimal*(1-decimal)).quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN)
        risk=F(cost)+F(fee)
        for side in ('Long','Short'):
            q['source']['native_side']=side;q['original']['value']=cost
            for probability in (F(1,2),risk,risk+F(1,10**9),risk-F(1,10**9)):
                raw=dict(revision='old',gross_decisive_benchmark=dict(available=True,
                    selected_decisive_probability=str(probability),reference_revision='pair',state='numeric_current'))
                with patch('app.comparison.conditional_benchmark.basis',return_value=evidence):
                    result=attach(deepcopy(raw),q,at=at,event={'start_at':'2026-10-30T00:00:00Z'},group={'period':'full_game','market':'winner'})
                m=result['conditional_trade_benchmark']
                expected=probability*(1-risk)+(1-probability)*(-risk)
                assert F(m['trade_fee_usd'])==F(fee)
                assert F(m['scenario_net_usd'])==expected
                assert F(m['return_percent'])==100*expected/risk
                assert not m['execution_qualified'] and not m['calibrated']
                assert all(x in m['exclusions'] for x in ('ties','pushes','voids','split-fill fee adjustments'))
    for key,value in [('value','.001'),('payout','2'),('quantity_units','USD')]:
        broken=deepcopy(q);broken['original'][key]=value
        result=attach(deepcopy(raw),broken,at=at,event={'start_at':'2026-10-30T00:00:00Z'},group={'period':'full_game','market':'winner'})
        assert not result['conditional_trade_benchmark']['available']
