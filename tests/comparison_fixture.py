"""Portable authored software preview inputs, never an owner launcher switch."""
from copy import deepcopy
import json
from dataclasses import replace, asdict
from app.comparison.current_dependencies import profile, VERSION
from app.comparison.costs import DEFAULT_POLICY
from app.dashboard.current_contract import binding_context, event_identity, identity
from tests.current_fixture import fixture
from tests.test_comparison_net_arbs import NetArbTests, TIME
from tests.test_comparison_net_ev import NetEVTests


def software_fixture():
    NetArbTests.setUpClass();NetEVTests.setUpClass()
    builder=NetArbTests();ev=NetEVTests()
    pair=builder.pair(available='100',minimum='1',increment='99',row={'complete':False})
    raw=fixture();raw['clock_at']=raw['projected_at']=TIME
    raw['runtime_id']='syn:comparison-software-authored-1'
    event=deepcopy(raw['events'][0]);raw['events']=[event]
    event.update(event_discriminator='comparison-occurrence-1:authored-software-cowboys',
        title='Tampa Bay Buccaneers at Dallas Cowboys',start_at='2026-10-09T00:15:00+00:00',
        participants=[dict(id='NFL:TB',name='Tampa Bay Buccaneers',role='away'),
                      dict(id='NFL:DAL',name='Dallas Cowboys',role='home')])
    event['id']=event_identity(event)
    group=deepcopy(event['groups'][0]);event['groups']=[group]
    group['id']=identity('group',[event['id'],*[group[k] for k in
        ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],
        group.get('result_policy','unspecified')])
    group['outcomes']=[];raw['comparison_profiles']={}
    for index,leg in enumerate(pair):
        selected=leg.bound_leg.selection;venue=selected.native.venue
        template=deepcopy(fixture()['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi'])
        template.update(venue=venue,revision=1,id='syn:authored-'+venue)
        template['source'].update(provider=venue,native_event_id=selected.native.event_id,
            native_market_id=selected.native.market_id,native_outcome_id=selected.native.instrument_id,
            native_side=selected.native.side_id,quote_side='buy')
        template['original'].update(value=selected.price.amount.original,units=selected.price.unit,
            payout='1',payout_units='USD',quantity_units='contracts')
        template['times'].update(source_at=TIME,received_at=TIME,projected_at=TIME)
        template['rule_note']='Authored standalone fee scenario; exceptional payouts unknown'
        outcome=dict(id='',participant=selected.participant_id,predicate='win',signed_line=None,
            label=('Dallas Cowboys' if index==0 else 'Tampa Bay Buccaneers')+' to win',quotes={venue:template})
        outcome['id']=identity('outcome',[group['id'],outcome['participant'],'win',None,'normal_win'])
        template['binding']['selection']=binding_context(event,group,outcome)
        group['outcomes'].append(outcome)
        scenario=__import__('app.comparison.cashflows',fromlist=['cashflow_inputs']).cashflow_inputs(
            (leg.bound_leg,),('1',),at=builder.at)
        reference=ev.reference(scenario)
        reference=replace(reference,outcomes=tuple(replace(o,book_at=TIME,received_at=TIME) for o in reference.outcomes))
        rule=leg.cost_kwargs['registry'].rules[0]
        quantity=dict(grid=asdict(leg.depth_leg.grid),fill_inputs=dict(basis='authored_fills',
            complete_order_history=True,fill_count=1,fragment_upper_bound=1,order_ids=['authored-arb-order']),
            fills=[dict(fill_id='authored-fill',order_id='authored-arb-order',role='taker',unit='contracts',
                        quantity='1',price=leg.depth_leg.levels[0].native_price)],
            native_price=leg.depth_leg.levels[0].native_price,
            fill_partition_basis='authored_complete_depth_fills',
            depth=dict(inputs=asdict(leg.depth_leg.depth),levels=[dict(native_price=level.native_price,
                available_native=level.available_native,liquidity_id=level.liquidity_id,evidence=level.evidence.to_dict())
                for level in leg.depth_leg.levels],partial_final=True))
        fee=dict(rule=rule.to_dict())
        if 'engine_context' in leg.cost_kwargs:fee['engine_context']=deepcopy(leg.cost_kwargs['engine_context'])
        if 'engine_registry' in leg.cost_kwargs:fee['engine_registry']=deepcopy(leg.cost_kwargs['engine_registry'].data)
        payloads=dict(identity=dict(selection=selected.to_dict(),completion_context=leg.bound_leg.context.to_dict(),
            rule_revision=leg.bound_leg.profile.rule_revision,current_selection_binding=deepcopy(template['binding']['selection']),
            current_scope_binding=dict(current_event_id=event['id'],occurrence_id=selected.event.occurrence_id,
                period_boundary=group['period_boundary'],result_policy=group.get('result_policy','unspecified'),
                scope=selected.scope.to_dict(),evidence=[dict(ref='authored:software-scope-association',
                    sha256='d'*64,evidence_class='authored')])),
            payout=leg.bound_leg.profile.to_dict(),fee=fee,quantity=quantity,
            reference=dict(outcomes=[o.to_dict() for o in reference.outcomes],receipt_sha256=reference.receipt_sha256,
                conditioning=reference.conditioning,partition_evidence_sha256=reference.partition_evidence_sha256,
                source_at=[o.source_at for o in reference.outcomes]),buffer=asdict(DEFAULT_POLICY),
            probability=dict(version='comparison-benchmark-basis-1',method='pinnacle_proportional_no_vig'))
        refs={}
        for kind,payload in payloads.items():
            key,value=profile(kind,json.loads(json.dumps(payload)));raw['comparison_profiles'][key]=value;refs[kind]=key
        template['comparison_input_refs']=dict(version=VERSION,phase='pregame',refs=refs)
    return raw
