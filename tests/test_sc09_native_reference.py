"""Conditional score binding and metric-specific authority boundaries."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction as F
import pytest
from app.comparison.domain import ExactNumber,ScorePredicate,EqualityDescriptor
from app.comparison.benchmark import TwoWayBenchmark
from app.comparison.current_dependencies import instant
from tests.test_ev09_n01 import retained,AT


def reference(family,line):
    old=TwoWayBenchmark.from_dict(retained()[0]['benchmark'])
    rows=[]
    for r in old.outcomes:
        home=r.selection.participant_id==r.selection.event.home_id
        s=replace(r.selection,family=family,participant_id='combined' if family=='total' else r.selection.participant_id,
            signed_line=ExactNumber(str(-F(line) if home else F(line))) if family=='spread' else None,
            predicate=ScorePredicate('combined_score' if family=='total' else 'home_margin','gt' if home else 'lt',ExactNumber(line)),
            equality=EqualityDescriptor('unknown',None,'not_applicable','equality excluded') if F(line).denominator==1 else EqualityDescriptor('not_feasible',None,'not_applicable',None))
        rows.append(replace(r,selection=s))
    return replace(old,outcomes=tuple(rows))


@pytest.mark.parametrize('family',['spread','total'])
@pytest.mark.parametrize('line',['-4','-3.5','0','3.5','4'])
def test_exact_conditional_opposition_all_signs_and_operators(family,line):
    if family=='total':line=str(abs(F(line)))
    ref=reference(family,line);s=ref.outcomes[0].selection
    for op in ('gt','ge','lt','le'):
        selected=replace(s,predicate=replace(s.predicate,operator=op))
        upper=ref.weight(selected,at=instant(AT),venue='pinnacle',method='proportional_no_vig')
        r=next(r for r in ref.outcomes if r.selection.predicate.operator=='gt');other=next(x for x in ref.outcomes if x is not r)
        assert upper==other.decimal_odds.value/(r.decimal_odds.value+other.decimal_odds.value)
        for score in range(-7,8):
            if score==F(line):continue
            assert (score>F(line) if op in ('gt','ge') else score<F(line))=={'gt':score>F(line),'ge':score>=F(line),'lt':score<F(line),'le':score<=F(line)}[op]
    for broken in (reference(family,str(F(line)+1)).outcomes[0].selection,replace(s,scope=replace(s.scope,overtime='excluded')),replace(s,event=replace(s.event,occurrence_id='different'))):
        with pytest.raises(ValueError):ref.weight(broken,at=instant(AT),venue='pinnacle',method='proportional_no_vig')
    with pytest.raises(ValueError):replace(ref,outcomes=ref.outcomes[:1])
    with pytest.raises(ValueError):replace(ref,outcomes=(ref.outcomes[0],replace(ref.outcomes[1],received_at='2026-10-15T01:00:00Z')))


def test_independent_metric_currentness_excludes_optional_models():
    from app.comparison.bound_finance import age_benchmarks
    now=instant(AT);ref=reference('total','40')
    q=dict(venue='polymarket_us',state='available',times=dict(source_at=AT,received_at=AT),source={'provider':'polymarket_us'})
    event=dict(start_at=(now+timedelta(days=1)).isoformat())
    result=dict(freshness=dict(reasons=['payout_source_rules_expired','probability_missing']),
        gross_decisive_benchmark=dict(available=True,reference_originals=[r.to_dict() for r in ref.outcomes]),
        conditional_trade_benchmark=dict(available=True,evidence=dict(reviewed_at=AT,review_before=(now+timedelta(minutes=2)).isoformat())))
    age_benchmarks(result,q,event,now)
    assert result['gross_decisive_benchmark']['state']=='numeric_current'
    age_benchmarks(result,q,event,now+timedelta(minutes=3))
    assert result['gross_decisive_benchmark']['state']=='numeric_current'
    assert result['conditional_trade_benchmark']['currentness_reasons']==['conditional_fee_review_expired_or_not_effective']
    age_benchmarks(result,q,event,now,reasons=['policy_changed'])
    assert result['gross_decisive_benchmark']['state']=='numeric_last_known'
    old=deepcopy(q);old['times']['source_at']=(now-timedelta(hours=1)).isoformat()
    age_benchmarks(result,old,event,now)
    assert 'source_expired' in result['gross_decisive_benchmark']['currentness_reasons']
    age_benchmarks(result,old,event,now,source_assessment=dict(reasons=[],basis='ordered_native_stream_exact_price'))
    assert result['gross_decisive_benchmark']['state']=='numeric_current'


def test_ordered_stream_proof_requires_exact_price_and_receipt_order():
    from app.storage.native_authority import assessment
    from app.storage.store import hashed
    q=dict(venue='polymarket_us',source=dict(native_event_id='e',native_market_id='m',native_outcome_id='o'),
        original=dict(value='0.43',units='usd_per_contract'),times=dict(source_at=AT,received_at=AT))
    key=hashed(['polymarket_us','e','m','o']);now=instant(AT)+timedelta(hours=1)
    proof=dict(value='0.43',source_at=AT,received_at=AT,runtime_id='run',generation=7)
    valid=assessment(q,{key:proof},now)
    assert valid['clock_at']==AT and valid['basis']=='ordered_native_stream_exact_price'
    for changes in (dict(value='0.44'),dict(received_at=(instant(AT)-timedelta(seconds=1)).isoformat()),
                    dict(received_at=(now+timedelta(seconds=1)).isoformat()),dict(source_at=(now+timedelta(seconds=1)).isoformat())):
        assert assessment(q,{key:dict(proof,**changes)},now) is None
    assert assessment(q,{},now) is None
    assert assessment(q,{key:dict(proof,received_at=None)},now) is None
    snapshot=assessment(q,{key:dict(proof,source_at=None)},now)
    assert snapshot['image_source_at'] is None and snapshot['clock_at']==AT


def test_selected_stream_authority_does_not_require_unrelated_initial_images():
    from app.storage.native_authority import stream_ready
    m=dict(stream_connected=True,synchronization=dict(continuity_intact=True,generation=7,
        current=False,state='initializing',missing_images=20,oldest_processing_delay_seconds=.5))
    assert stream_ready(m)
    for changes in (dict(continuity_intact=False),dict(generation=None),
                    dict(oldest_processing_delay_seconds=2.01),dict(oldest_processing_delay_seconds=None)):
        assert not stream_ready(dict(m,synchronization=dict(m['synchronization'],**changes)))
    assert not stream_ready(dict(m,stream_connected=False))


def test_newer_observation_keeps_original_financial_bundle():
    from app.storage.selected_frame import preserve_newer_observation
    from app.storage.payload_codec import encode,decode
    from app.storage.shared_json import dumps,loads
    financial=dict(selected_frame=encode(dumps(dict(observed={'clock':'old'},financial={'price':'0.43','clock':'original'},at=AT))),
        publication_dependencies={'observations':{'original':'proof'}},boards={'odds':{'clock':'old'}},observation_context={'id':'old'})
    newer=dict(selected_frame=encode(dumps(dict(observed={'clock':'new'},financial=None))),
        publication_dependencies={'observations':{'new':'proof'}},boards={'odds':{'clock':'new'}},
        observation_context={'id':'new'},observation_valid_until='new-boundary')
    preserve_newer_observation(financial,newer)
    saved=loads(decode(financial['selected_frame']))
    assert saved['financial']=={'price':'0.43','clock':'original'} and saved['observed']=={'clock':'new'}
    assert financial['financial_dependencies']=={'observations':{'original':'proof'}}
    assert financial['publication_dependencies']==newer['publication_dependencies']


def test_exact_reference_change_does_not_invalidate_unrelated_benchmark(monkeypatch):
    from app.storage import observation_publication as publication
    from app.storage.store import hashed
    frame=dict(epoch='epoch',offers={},candidate_sets={})
    saved=dict(version=publication.VERSION,epoch='epoch',matching=hashed([]),selector={},observations={},candidates={},
        references={'spread-contract':{'spread-ref':'old'},'total-contract':{'total-ref':'same'}})
    monkeypatch.setattr(publication,'neighborhood',lambda *args:[])
    monkeypatch.setattr(publication,'own',lambda frame,cid:{'spread-ref':'new','total-ref':'same'}[cid])
    checks=publication.reasons(frame,saved)
    assert checks['all']==[]
    assert checks['benchmarks']=={'spread-contract':['reference_dependencies_changed'],'total-contract':[]}
    assert checks['comparisons']=={'spread-contract':['reference_dependencies_changed']}


def test_occurrence_dependency_ignores_repeated_schedule_receipt_but_not_facts():
    from app.storage.observation_publication import event_dependency
    from app.storage.store import hashed
    facts=dict(id='event',sport='football',competition='NFL',home='NFL:GB',away='NFL:CAR',
        participants={'Green Bay Packers':'NFL:GB','Carolina Panthers':'NFL:CAR'},
        scheduled_start='2026-10-29T00:00:00Z',season='2026',stage='regular')
    def event(receipt,tag,start=None):
        f=deepcopy(facts)
        if start:f['scheduled_start']=start
        m=dict(version='predict-schedule-metadata-1',native_event_id='event',authority=['the_odds_api','event','event'],
            start=f['scheduled_start'],received_at=receipt,proofs=[dict(body_sha256=tag,path=tag,received_at=receipt)])
        m['revision']=hashed(m);f['schedule_metadata']=m
        return dict(provider='the_odds_api',native_event_id='event',facts=f)
    original=event(AT,'first');repeated=event((instant(AT)+timedelta(minutes=2)).isoformat(),'new-receipt')
    assert event_dependency(original)==event_dependency(repeated)
    assert event_dependency(original)!=event_dependency(event(AT,'first','2026-10-29T01:00:00Z'))
    missing=deepcopy(original);missing['facts'].pop('schedule_metadata')
    assert event_dependency(original)!=event_dependency(missing)
    conflict=deepcopy(original);conflict['facts']['occurrence_conflict']=True
    assert event_dependency(original)!=event_dependency(conflict)


def college_context(frame=None):
    import json
    from pathlib import Path
    from app.storage.comparison_board import ReadContext
    from app.storage.current_games import GameStore
    if frame is None:frame=json.loads((Path(__file__).parent/'fixtures/sc09-college-exact-reference.json').read_text())
    return ReadContext(GameStore(None),frame=frame,at='2026-10-29T01:15:00Z')


def test_reviewed_college_exact_reference_keeps_side_after_id_order_changes():
    from app.dashboard.comparison_board import entries
    from app.comparison.current_dependencies import references
    context=college_context();bundles=context.bundles()
    assert len(bundles)==1
    state=bundles[0]['state_inputs'];bound=[]
    for e,g,q in entries(state):
        status=q['comparison_input_status']['reference']
        if q['venue']=='kalshi' and q['source']['native_market_id'].endswith('ECU7'):
            assert status['reason']=='exact_native_reference_pair_absent'
            continue
        assert status['status']=='available_and_bound',status
        payload=references(q,state['comparison_profiles'])['reference']['payload']
        if q['venue']!='kalshi':
            # Canonical ECU 196 sorts before Temple 690, reversing the old
            # provider-local home/away ordering. Original odds must follow it.
            assert payload['selected_odds']==q['sharp_reference']['selected_odds']
            assert len(payload['outcomes'])==2
            selected=payload['outcomes'][payload['selected']]
            assert selected['selection']['participant']==q['binding']['selection']['participant']
            assert selected['decimal_odds']==payload['selected_odds']
        else:
            ref=TwoWayBenchmark.from_dict(payload)
            assert {r.selection.predicate.threshold.value for r in ref.outcomes}=={F('5.5')}
            assert {r.selection.event.home_id for r in ref.outcomes}=={'NCAAF:NCAA196'}
            assert {r.selection.event.away_id for r in ref.outcomes}=={'NCAAF:NCAA690'}
            bound.append(q)
    assert len(bound)==2


@pytest.mark.parametrize('change',['receipt','received_at','period','line','side','event'])
def test_college_reference_refuses_incompatible_original_halves(change):
    import json
    from pathlib import Path
    from app.dashboard.comparison_board import entries
    frame=json.loads((Path(__file__).parent/'fixtures/sc09-college-exact-reference.json').read_text())
    ref=next(r for r in frame['records'] if r['quote']['venue']=='pinnacle')
    if change=='receipt':ref['quote']['provenance']['sha256']='b'*64
    elif change=='received_at':ref['quote']['times']['received_at']='2026-10-29T01:14:00Z'
    elif change=='period':ref['market_identity']['period']='first_half'
    elif change=='line':ref['market_identity']['line']='-6.5'
    elif change=='side':ref['selection']['participant']='NCAAF:NCAA29'
    else:ref['event']['id']='different-event';ref['quote']['source']['native_event_id']='different-event'
    context=college_context(frame)
    for bundle in context.bundles():
        for _,_,q in entries(bundle['state_inputs']):
            if q['venue']=='kalshi':
                assert q['comparison_input_status']['reference']['status']!='available_and_bound'


def test_college_publication_capture_uses_the_same_identity_neighborhood():
    import json
    from pathlib import Path
    from app.storage.observation_publication import identity_index,neighborhood
    from app.storage.store import hashed
    frame=json.loads((Path(__file__).parent/'fixtures/sc09-college-exact-reference.json').read_text())
    events={}
    for r in frame['records']:
        e=r['event'];p=r['quote']['source']['provider'];key=p+':'+e['id']
        events[key]=dict(id=key,provider=p,native_event_id=e['id'],revision=hashed(e),facts=e,active=True)
    class Result:
        def fetchall(self):return list(events.values())
        def fetchone(self):return {'epoch':'fixture'}
    class DB:
        def execute(self,*args):return Result()
    index=identity_index(DB())
    for seed in events:
        found=neighborhood(index,dict(events=[seed],occurrences=[],shared=[]))
        assert {r[0] for r in found}==set(events)
