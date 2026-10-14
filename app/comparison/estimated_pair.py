"""Opposing allocations, joint settlement and bounded exact search.

Allocation cashflows come from the fixed-allocation consumer. No source mutation
or browser finance occurs here. Retained shells contain only chosen allocations."""
from dataclasses import asdict, replace
from fractions import Fraction as F
from itertools import product

from app.fees.engine import generic_fee
from .current_dependencies import digest, instant, references, link_reasons
from .domain import CanonicalSelection
from .estimated_content import describe, STATES as CELLS
from .estimated_consumer import consume, _unit
from .estimated_ev import _scope, _reference, _grid, _path, _fills, cell, eligibility, MAX_NATIVE
from .estimated_policy import DEFAULT_POLICY
from .net_costs import wire

VERSION='predict-funded-pair-1'
CONSTRAINT_VERSION='ev06-meaningful-exposure-1'
OBJECTIVES=('decisive_max_min','all_modeled_states_max_min')
EXPOSURE_FLOOR=F(25)
MIN_SHARE=F(1,5)
MAX_POINTS=16
MAX_EVALUATIONS=MAX_POINTS**2
MAX_PAIRS=256
MAX_CANDIDATE_LEGS=128
STATE_MAP=dict(a_wins='home_win',b_wins='away_win',tie='tie',terminal_noncompletion='terminal_noncompletion')


def native_key(q):
    return (q['venue'],*[q['source'][k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')])


def pool_identity(pool):
    return digest({k:pool[k] for k in ('venue','channel','market_id')})


def reference_basis(reference):
    """Exact decisive reference originals, independent of execution annotations.

    Shared profile storage binds a reference into each execution contract's equality/payout context.
    Those execution annotations do not change the two original Pinnacle outcomes.
    Native IDs, evidence, observation revisions, odds, clocks, event, score scope
    and predicates all remain part of this one coherent pair basis.
    """
    if getattr(reference,'source_revision',None) is not None:
        return digest(dict(version='ev09-two-way-reference-basis-1',originals=reference.to_dict()))
    return digest(dict(version='ev06-pair-reference-basis-1',receipt=reference.receipt_sha256,
        conditioning=reference.conditioning,partition=reference.partition_evidence_sha256,
        outcomes=sorted([dict(native_key=list(row.selection.native.key),
            evidence=[e.to_dict() for e in row.selection.native.evidence],revision=row.revision,
            event=list(row.selection.event.key),scope=list(row.selection.scope.key),
            predicate=row.selection.predicate.to_dict(),participant=row.selection.participant_id,
            odds=row.decimal_odds.original,book_at=row.book_at,market_at=row.market_at,received_at=row.received_at)
            for row in reference.outcomes],key=lambda r:r['participant'])))


class Leg:
    """Occurrence-local preparation and bounded scalar allocation cache."""
    def __init__(self,q,group,profiles,event,at,*,funding=None,policy=DEFAULT_POLICY,benchmark=None):
        self.q=q;self.group=group;self.profiles=profiles;self.at=at;self.event=event
        self.policy=policy;self.benchmark=benchmark
        self.funding=funding or {};self.cache={};self.probes=0
        from .estimated_consumer import AllocationInputs
        self.inputs=AllocationInputs(q,profiles,at)
        self.content=self.inputs.content
        if any(not x['available'] for x in self.content.values()):
            raise ValueError('; '.join(r for x in self.content.values() for r in x['reasons']) or 'pair_content_unavailable')
        self.roles,self.assumptions=_scope(q,event,group,self.content,at)
        values=references(q,profiles)
        identity=values.get('identity')
        if identity is None or identity['payload'].get('current_selection_binding')!=q['binding']['selection']:
            raise ValueError('pair_exact_identity_unbound')
        selection=CanonicalSelection.from_dict(identity['payload']['selection'])
        if (list(selection.native.key)!=list(native_key(q)) or selection.event.home_id!=self.roles['home'] or
                selection.event.away_id!=self.roles['away'] or selection.scope.period!='full_game' or
                selection.predicate.domain!='home_margin' or selection.predicate.threshold.value!=0):
            raise ValueError('pair_identity_orientation_conflict')
        native=q['binding']['selection']
        home=native['participant']==self.roles['home']
        operator=('gt' if home else 'lt') if native['predicate']=='win' else ('le' if home else 'ge')
        if selection.participant_id!=native['participant'] or selection.predicate.operator!=operator or selection.family not in ('moneyline','team_binary'):
            raise ValueError('pair_identity_predicate_conflict')
        for kind in ('identity','quantity'):
            p=values.get(kind)
            if p and p['expires_at'] and at>=instant(p['expires_at']):raise ValueError('pair_'+kind+'_expired')
        if link_reasons(q,at):raise ValueError('; '.join(link_reasons(q,at)))
        self.unit=_unit(q,self.content['fee']);self.grid=_grid(q,values,self.unit,self.content,at)
        self.minimum=F(self.grid['minimum_native']);self.increment=F(self.grid['increment_native'])
        if self.minimum<=0 or self.increment<0 or (self.increment==0 and self.grid.get('qualification')!='diagnostic_continuous'):raise ValueError('pair_grid_invalid')
        if self.unit.unit in ('fixed_point_contracts','novig_v3_cent_contracts') and any(x.denominator!=1 for x in (self.minimum,self.increment)):
            raise ValueError('pair_native_integer_grid_required')
        self.path=_path(q,self.unit,self.grid)
        ids=[row['liquidity_id'] for row in q.get('depth',[]) if row.get('liquidity_id')]
        if len(ids)!=len(set(ids)):raise ValueError('pair_duplicate_observed_liquidity')
        self.liquidity_ids=set(ids)
        self.weight=None;self.reference=None;self.reference_reason=None
        try:
            self.weight,self.reference=_reference(q,values,self.roles,policy=policy,benchmark=benchmark,at=at)
            ref=values.get('reference')
            if ref and ref['expires_at'] and at>=instant(ref['expires_at']):raise ValueError('pair_reference_expired')
        except (ValueError,KeyError,TypeError) as error:self.reference_reason=str(error);self.weight=None;self.reference=None
        self.rank_reasons=eligibility(q,self.reference,at,event) if self.reference else self._source_reasons()
        if any('reference_clock_future' in r or (getattr(policy,'sizing_mode',None) is not None and r.startswith('reference_')) for r in self.rank_reasons):
            self.reference=None;self.weight=None;self.reference_reason='pair_reference_invalid_or_expired';self.rank_reasons=self._source_reasons()
        self.shared_depth=(values.get('quantity') or {}).get('payload',{}).get('shared_depth_id')
        if any('future' in r for r in self.rank_reasons):raise ValueError('; '.join(self.rank_reasons))
        self.reference_basis=None if self.reference is None else reference_basis(self.reference)
        self.conditions=(values.get('payout') or {}).get('payload',{}).get('normal_condition')
        # Decisive opposition is determined from cashflows, never side labels.
        seed=self.get(self.minimum)
        a=cell(seed,'payout','receipt_usd:home_win');b=cell(seed,'payout','receipt_usd:away_win')
        if a is None or b is None or a==b:raise ValueError('pair_decisive_exposure_unknown')
        self.sign=1 if a>b else -1
        self.exposure_per_native=abs(a-b)/self.minimum
        self.lower=self.ceil(max(self.minimum,EXPOSURE_FLOOR/self.exposure_per_native))

    def _source_reasons(self):
        from .estimated_ev import temporal
        status=temporal(self.q,self.profiles,self.at,self.event)[0]
        return ([{'unknown':'source_clock_unknown','expired':'source_price_expired','future':'source_clock_future',
                  'future_at_receipt':'source_clock_future'}[status]] if status!='current' else [])+(
                      ['execution_source_unavailable'] if self.q['state'] not in ('available','budget_delayed') else [])

    def floor(self,n):
        if not self.increment:return n
        return self.minimum+max(0,int((n-self.minimum)//self.increment))*self.increment
    def ceil(self,n):
        if not self.increment:return n
        steps=(n-self.minimum)/self.increment
        return self.minimum+max(0,-(-steps.numerator//steps.denominator))*self.increment

    def get(self,n,*,rich=False,impact=F(0),cashflows=None):
        key=wire(n)
        if not rich and not impact and cashflows is None and key in self.cache:return self.cache[key]
        fills,support=_fills(self.path,n,self.q['venue'],residual_impact=impact)
        options=dict(self.funding)
        if cashflows is not None:options['state_cashflows']=cashflows
        value=consume(self.q,self.profiles,at=self.at,native_quantity=key,**fills,**options,
            retain_profiles=rich,settlement_metadata=True,_inputs=self.inputs)
        self.probes+=1
        if value['deployed_capital_usd'] is None:raise ValueError('; '.join(value['reasons']['fee']) or 'pair_funding_unknown')
        value['pair_support']=wire(support)
        scalar={}
        for state in CELLS:
            parts=[cell(value,'payout','receipt_usd:'+state),cell(value,'payout','hold_return_usd:'+state),
                cell(value,'fee','fee_refund_usd:'+state),cell(value,'fee','settlement_fee_usd:'+state)]
            scalar[state]=None if any(v is None for v in parts) else sum(parts[:3],F(0))-F(value['deployed_capital_usd'])-parts[3]
        value['_pair_profits']=scalar
        value['_pair_capital']=F(value['deployed_capital_usd'])
        a=cell(value,'payout','receipt_usd:home_win');b=cell(value,'payout','receipt_usd:away_win')
        value['_pair_exposure']=None if a is None or b is None else abs(a-b)
        value['_pair_pools']={pool_identity(t['pool']) for t in value['settlement_terms'] if t['pool']}
        if not rich and not impact and cashflows is None:
            # Bound caches and retain scalar cells, no consumer dependency graphs.
            value={k:value[k] for k in ('components','deployed_capital_usd','acquisition_usd','settlement_terms',
                'settlement_already_withheld','payout_details','pair_support','reasons','_pair_profits','_pair_capital','_pair_exposure','_pair_pools')}
            if len(self.cache)<64:self.cache[key]=value
        return value


def joint_basis(legs,terminal_weights=None):
    """Disjoint terminal pattern/grade partition; one terminal probability mass.

    Equal exact completion conditions exclude split grading. Otherwise both
    asymmetric patterns are feasible. No weights are invented for those splits.
    Normal grading wins before terminal assignment for each contract.
    """
    rows={s:dict(cells=[c,c],terminal=False,weight=None) for s,c in STATE_MAP.items() if s!='terminal_noncompletion'}
    rows['terminal_noncompletion']=dict(cells=['terminal_noncompletion']*2,terminal=True,weight='1')
    conditions=[x.conditions for x in legs]
    if conditions[0] is None or conditions[1] is None or conditions[0]!=conditions[1]:
        # Unknown completion compatibility is an explicit feasible-state model.
        rows['terminal_noncompletion']['weight']=None
        grading_legs=[0,1]
        a,b=conditions
        if a and b and a.get('kind')==b.get('kind') and a.get('kind') in ('starts_within_hours','rescheduled_within_days') and all(a.get(k)==b.get(k) for k in ('original_start','original_scheduled_date','date_timezone')):
            if F(a['maximum'])<F(b['maximum']):grading_legs=[1]
            elif F(a['maximum'])>F(b['maximum']):grading_legs=[0]
        for grading in grading_legs:
            for s,c in list(STATE_MAP.items())[:3]:
                cells=['terminal_noncompletion']*2;cells[grading]=c
                rows['terminal_grade_'+str(grading)+'_'+s]=dict(cells=cells,terminal=True,weight=None)
    if terminal_weights is not None:
        terminal={s for s,r in rows.items() if r['terminal']}
        if set(terminal_weights)!=terminal:raise ValueError('pair_terminal_partition_weights_incomplete')
        weights=[F(v) for v in terminal_weights.values()]
        if any(v<0 for v in weights) or sum(weights)!=1:raise ValueError('pair_terminal_weights_must_partition_one_mass')
        for s in terminal:rows[s]['weight']=wire(F(terminal_weights[s]))
    return rows


def pool_charge(gains,policy,pool=None):
    """The shared engine floors and rounds the complete pool gain once."""
    amount=F(generic_fee([],policy,positions=dict(account='model:pair',market=(pool or {}).get('market_id','model:independent'),
        complete=True,net_before={'state':'0'}),outcomes={'state':wire(sum(gains,F(0)))})['state_fees']['state'])
    return min(amount,F(pool['cap_usd'])) if pool and pool.get('cap_usd') is not None else amount


def economics(components,basis):
    capital=sum(F(c['deployed_capital_usd']) for c in components);states={}
    for state,row in basis.items():
        gains=[];pools={};separate=F(0);unknown=False;parts=[]
        for index,(component,c) in enumerate(zip(components,row['cells'])):
            receipt=cell(component,'payout','receipt_usd:'+c);held=cell(component,'payout','hold_return_usd:'+c)
            refund=cell(component,'fee','fee_refund_usd:'+c);old_fee=cell(component,'fee','settlement_fee_usd:'+c)
            gain=None if any(v is None for v in (receipt,held,refund,old_fee)) else receipt+held+refund-F(component['deployed_capital_usd'])
            gains.append(gain);parts.append(dict(receipt_usd=ws(receipt),returned_hold_usd=ws(held),fee_refund_usd=ws(refund),
                receipt_charge_treatment='attached_net_receipt' if component['settlement_already_withheld'] else 'gross_receipt'))
            if gain is None:unknown=True;continue
            for n,term in enumerate(component['settlement_terms']):
                if term['policy']['basis']!='net_gain':
                    # Keep independent non-net-gain settlement charges from owner.
                    separate+=F(term['state_fees'][c]);continue
                pool=term['pool'];key=digest([pool_identity(pool),term['slot']]) if pool else 'independent:'+str(index)+':'+str(n)
                if key in pools and (pools[key]['policy']!=term['policy'] or pools[key]['pool']!=pool):raise ValueError('pair_pool_terms_conflict')
                target=pools.setdefault(key,dict(policy=term['policy'],pool=pool,gains=[]));target['gains'].append(gain)
        charge=None if unknown else separate+sum((pool_charge(x['gains'],x['policy'],x['pool']) for x in pools.values()),F(0))
        profit=None if unknown else sum(gains,F(0))-charge
        states[state]=dict(profit_usd=ws(profit),settlement_charge_usd=ws(charge),legs=parts,
            cells=row['cells'],terminal=row['terminal'])
    return capital,states


def ws(v):return None if v is None else wire(v)


def minimum(states,names):
    values={s:None if states[s]['profit_usd'] is None else F(states[s]['profit_usd']) for s in names}
    if any(v is None for v in values.values()):return None,[]
    value=min(values.values());return value,[s for s,v in values.items() if v==value]


def expected(states,probabilities):
    if probabilities is None:return None
    if any(p is None or (p>0 and states[s]['profit_usd'] is None) for s,p in probabilities.items()):return None
    return sum((p*F(states[s]['profit_usd']) for s,p in probabilities.items() if p>0),F(0))


def probabilities(legs,basis,policy):
    refs=[x for x in legs if x.reference is not None]
    if not refs:return None,None,'pair_reference_missing'
    # One exact reference revision may be absent on one leg, but conflicting
    # independent reference snapshots may never be averaged or summed.
    first=refs[0]
    if any(x.reference_basis!=first.reference_basis or x.weight!=first.weight for x in refs):
        return None,None,'pair_reference_basis_conflict'
    c=first.weight;t=F(policy.tie);u=F(policy.terminal_noncompletion)
    p=dict(a_wins=(1-t-u)*c,b_wins=(1-t-u)*(1-c),tie=t)
    p.update({s:None if r['weight'] is None and u else u*F(r['weight'] or '0') for s,r in basis.items() if r['terminal']})
    return p,c,None


def evaluate(legs,*,policy=DEFAULT_POLICY,quantities=None,objective=OBJECTIVES[0],terminal_weights=None,details=False):
    """Exact fixed allocation or best evaluated bounded grid, never token legs."""
    if objective == 'requested_funded_net_balance' and getattr(policy,'sizing_mode',None) == 'requested_trade':
        objective=OBJECTIVES[0]
    try:
        if getattr(policy,'sizing_mode',None) is not None:
            rebound=[]
            for x in legs:
                if x.policy.revision != policy.revision:
                    y=Leg(x.q,x.group,x.profiles,x.event,x.at,funding=x.funding,policy=policy,benchmark=x.benchmark)
                    y.conditions=x.conditions
                    rebound.append(y)
                else:rebound.append(x)
            legs=rebound
        return _evaluate(legs,policy,quantities,objective,terminal_weights,details)
    except (ValueError,KeyError,TypeError,ArithmeticError) as error:
        value=dict(version=VERSION,model_available=False,ranking_eligible=False,policy_revision=policy.revision,
            reasons=[str(error)],buffered_profit_usd=None,buffered_return_percent=None)
        if getattr(policy,'sizing_mode',None) is not None:
            from .financial_metrics import unavailable
            unavailable(value,policy,str(error),pair=True)
        return dict(value,revision=digest(value))


def _evaluate(legs,policy,quantities,objective,terminal_weights,details):
    if len(legs)!=2 or objective not in OBJECTIVES:raise ValueError('pair_exact_opposing_legs_and_objective_required')
    if quantities is None and any('state_cashflows' in x.funding for x in legs):
        raise ValueError('pair_absolute_cashflows_require_fixed_allocation')
    if native_key(legs[0].q)==native_key(legs[1].q):raise ValueError('pair_duplicate_instrument')
    if legs[0].event['id']!=legs[1].event['id'] or legs[0].group['period']!=legs[1].group['period']:
        raise ValueError('pair_occurrence_period_conflict')
    if legs[0].sign==legs[1].sign:raise ValueError('pair_same_decisive_exposure')
    # Shared selected native depth is a single resource. Unknown independent
    # native instruments are not silently conflated on venue or display group.
    keys=[(x.q['venue'],x.q['source']['provider'],x.q['source']['native_event_id'],x.q['source']['native_market_id'],x.q['source']['native_outcome_id']) for x in legs]
    if keys[0]==keys[1] or legs[0].liquidity_ids&legs[1].liquidity_ids or (legs[0].shared_depth and legs[0].shared_depth==legs[1].shared_depth):
        raise ValueError('pair_shared_instrument_liquidity_conflict; no duplicated fill allowance')
    basis=joint_basis(legs,terminal_weights);budget=F(policy.capital_ceiling_usd)
    names=('a_wins','b_wins') if objective==OBJECTIVES[0] else tuple(basis)
    def candidate(qs,components):
        if any(n<x.lower or n>MAX_NATIVE or x.floor(n)!=n for x,n in zip(legs,qs)):return None
        exposures=[c['_pair_exposure'] for c in components]
        if min(exposures)<EXPOSURE_FLOOR or min(exposures)<MIN_SHARE*sum(exposures):return None
        capital=sum(component['_pair_capital'] for component in components)
        if capital<=0 or capital>budget:return None
        pool_ids=[component['_pair_pools'] for component in components]
        if pool_ids[0]&pool_ids[1]:
            _,rows=economics(components,basis)
            scalars={s:None if row['profit_usd'] is None else F(row['profit_usd']) for s,row in rows.items()}
        else:
            scalars={}
            for state,row in basis.items():
                a=components[0]['_pair_profits'][row['cells'][0]];b=components[1]['_pair_profits'][row['cells'][1]]
                scalars[state]=None if a is None or b is None else a+b
        score=None if any(scalars[s] is None for s in names) else min(scalars[s] for s in names)
        if score is None:return None
        return score,capital,scalars,components
    requested=getattr(policy,'sizing_mode',None)=='requested_trade'
    requested_search=None
    points=[];global_proof=True
    if quantities is not None:
        if len(quantities)!=2:raise ValueError('pair_two_quantities_required')
        points=[[F(n)] for n in quantities];global_proof=False
    elif requested:
        from .requested_sizing import allocations
        requested_allocations,requested_search=allocations(legs,budget,basis,economics)
        global_proof=False
    else:
        # Exhaustive when the complete acquisition-bounded grid fits. Otherwise
        # sample every range and add balanced-budget/fee/grid neighborhoods.
        balanced=budget/sum(x.path['minimum_cost']/x.exposure_per_native for x in legs)
        centers=[x.floor(max(x.lower,balanced/x.exposure_per_native)) for x in legs]
        funded=sum(F(x.get(n)['deployed_capital_usd']) for x,n in zip(legs,centers))
        adjusted=balanced*min(F(1),budget/funded)
        for x in legs:
            upper=min(MAX_NATIVE,budget/x.path['minimum_cost'])
            count=int((upper-x.lower)//x.increment)+1
            if count<=0:raise ValueError('pair_budget_below_meaningful_minimum')
            if count<=MAX_POINTS:values=[x.lower+i*x.increment for i in range(count)]
            else:
                global_proof=False
                values=[x.lower,x.ceil(x.lower*4)]
                values.extend(x.floor(x.lower+(upper-x.lower)*F(i,8)) for i in range(1,9))
                center=x.floor(max(x.lower,adjusted/x.exposure_per_native))
                values.extend(center+i*x.increment for i in (-2,-1,0,1,2))
            points.append(sorted({n for n in values if x.lower<=n<=upper})[:MAX_POINTS])
    best=None;evaluations=0;objective_bests={name:None for name in OBJECTIVES}
    if requested and quantities is None:
        allocated_pairs=([ (n,x.get(n)) for x,n in zip(legs,qs)] for qs in requested_allocations)
    else:
        allocated_points=[[(n,x.get(n)) for n in values] for x,values in zip(legs,points)]
        allocated_pairs=product(*allocated_points)
    for allocations in allocated_pairs:
        qs,components=zip(*allocations)
        evaluations+=1;value=candidate(qs,components)
        if value is None:continue
        score,capital,states,components=value
        for name,state_names in ((OBJECTIVES[0],('a_wins','b_wins')),(OBJECTIVES[1],tuple(basis))):
            v=None if any(states[s] is None for s in state_names) else min(states[s] for s in state_names)
            prior=objective_bests[name]
            if v is not None and (prior is None or (v,-capital)>(prior[0],-prior[1])):objective_bests[name]=(v,capital,qs)
        if requested and quantities is None:
            key=(-abs(states['a_wins']-states['b_wins']),capital,qs)
            old=None if best is None else (-abs(best[3]['a_wins']-best[3]['b_wins']),best[1],best[2])
        else:
            key=(score,-capital,qs);old=None if best is None else (best[0],-best[1],best[2])
        if old is None or key>old:best=(score,capital,qs,states,components)
    if best is None:raise ValueError('pair_no_feasible_evaluated_allocation')
    score,capital,qs,_,components=best
    _,states=economics(components,basis)
    decisive,decisive_states=minimum(states,('a_wins','b_wins'));all_min,all_states=minimum(states,tuple(basis))
    p,c,reference_reason=probabilities(legs,basis,policy);ev=expected(states,p)
    conditional_p=None if c is None else dict(a_wins=c,b_wins=1-c)
    conditional=expected(states,conditional_p);profit=ev if ev is not None else conditional
    haircut=capital*F(policy.buffer_rate)
    complete=all_min is not None
    category='Positive across modeled outcomes' if complete and all_min-haircut>0 else 'Estimated hedge'
    for row in states.values():row['buffered_profit_usd']=ws(None if row['profit_usd'] is None else F(row['profit_usd'])-haircut)
    reason=[] if reference_reason is None else [reference_reason]
    result=dict(version=VERSION,model_available=True,expected_value_available=ev is not None,
        ranking_eligible=profit is not None and all(not x.rank_reasons for x in legs),reasons=reason,
        conditioning='modeled_complete' if ev is not None else 'modeled_conditional' if conditional is not None else 'reference_free_scenarios',
        condition=None if ev is not None else 'decisive_home_or_away_win' if conditional is not None else None,
        probability_basis=dict(version='ev06-pair-reference-basis-1',revision=next((x.reference_basis for x in legs if x.reference),None)),
        policy_revision=policy.revision,objective=objective,category=category,
        minimum_spend_solution=score<=0 and all(n==x.lower for n,x in zip(qs,legs)),
        target_ceiling_usd=wire(budget),deployed_capital_usd=wire(capital),unused_cash_usd=wire(budget-capital),
        buffer_usd=wire(haircut),fee_adjusted_expected_profit_usd=ws(ev),conditional_decisive_profit_usd=ws(conditional),
        buffered_profit_usd=ws(None if profit is None else profit-haircut),unbuffered_return_percent=ws(None if profit is None else 100*profit/capital),
        buffered_return_percent=ws(None if profit is None else 100*(profit-haircut)/capital),
        decisive_minimum_usd=ws(decisive),all_state_minimum_usd=ws(all_min),
        buffered_decisive_minimum_usd=ws(None if decisive is None else decisive-haircut),
        buffered_all_state_minimum_usd=ws(None if all_min is None else all_min-haircut),
        limiting_states=dict(decisive=decisive_states,all_states=all_states),complete_feasible_state_cashflows=complete,
        percentage_denominator='actual modeled deployed capital including refundable holds; conditional EV is labeled',
        states=states,probabilities=None if p is None else {s:ws(v) for s,v in p.items()},
        conditional_probabilities=None if conditional_p is None else {s:wire(v) for s,v in conditional_p.items()},
        constraints=dict(version=CONSTRAINT_VERSION,minimum_decisive_exposure_usd='25',minimum_exposure_share='0.2',
            rationale='material $25 payout per leg and no leg below 20% of combined decisive payout exposure; unequal native stakes permitted'),
        search=dict(maximum_points_per_leg=MAX_POINTS,maximum_evaluations=MAX_EVALUATIONS,evaluations=evaluations,
            global_optimality_proven=global_proof,limitation='explicit fixed allocation' if quantities is not None else None if global_proof else
            'best evaluated sampled legal grid; nonlinear fees/depth can place a better allocation between points',
            objective_allocations={k:None if v is None else dict(minimum_usd=wire(v[0]),deployed_capital_usd=wire(v[1]),quantities=[wire(n) for n in v[2]]) for k,v in objective_bests.items()}),
        legs=[dict(quote_id=x.q['id'],quote_revision=x.q['revision'],group_id=x.group['id'],native_key=list(native_key(x.q)),
            selection=x.q['binding']['selection'],native_quantity=wire(n),native_unit=asdict(x.unit),
            supported_native_quantity=component['pair_support'],modeled_native_quantity=wire(n-F(component['pair_support'])),
            acquisition_usd=component['acquisition_usd'],net_upfront_fee_usd=ws(cell(component,'fee','net_entry_fee_usd')),
            supported_capital_usd=None if not F(component['pair_support']) else x.get(F(component['pair_support']))['deployed_capital_usd'],
            grid=x.grid,source_times=x.q['times'],eligibility_reasons=x.rank_reasons) for x,n,component in zip(legs,qs,components)],
        cost_breakdown=dict(acquisition_usd=wire(sum(F(x['acquisition_usd']) for x in components)),
            net_upfront_fee_usd=wire(sum(cell(x,'fee','net_entry_fee_usd') for x in components)),
            extra_funding_usd=wire(capital-sum(F(x['acquisition_usd'])+cell(x,'fee','net_entry_fee_usd') for x in components)),
            withholding='inside attached net receipts; never charged twice'),
        assumptions=sorted(set(a for leg in legs for a in leg.assumptions))+['EV01 provisional NFL priors; actual probabilities, charges and execution unknown',
            'unknown commission-market identity modeled as independent standalone pools',
            'unknown/different completion windows retain asymmetric terminal grading states; subcase weights unknown',
            'observed levels consumed before modeled residual at last visible price'],
        size_status='supported_size' if all(F(x['pair_support'])==n for x,n in zip(components,qs)) else
            'modeled_size' if any(F(x['pair_support']) for x in components) else 'size_unverified')
    result['sensitivity']=dict(allocation='fixed_selected_quantities_and_fills',
        buffer=[dict(rate=r,buffered_expected_profit_usd=ws(None if profit is None else profit-capital*F(r)),
            buffered_all_state_minimum_usd=ws(None if all_min is None else all_min-capital*F(r))) for r in ('0','0.0025','0.005','0.01')],prior=[],
        tie_break_even=None,terminal_payout=[],repriced_residual=[],legacy_adverse_price_stress='separate predecessor metric; no deduction')
    for t,u in product(('0','0.01'),('0','0.005')):
        prior,_,_=probabilities(legs,basis,replace(policy,tie=t,terminal_noncompletion=u));v=expected(states,prior)
        result['sensitivity']['prior'].append(dict(tie=t,terminal_noncompletion=u,buffered_expected_profit_usd=ws(None if v is None else v-haircut)))
    if c is not None and all(states[s]['profit_usd'] is not None for s in ('a_wins','b_wins','tie')):
        d=c*F(states['a_wins']['profit_usd'])+(1-c)*F(states['b_wins']['profit_usd']);tie=F(states['tie']['profit_usd'])
        terminal=expected(states,{s:F(r['weight']) for s,r in basis.items() if r['terminal']}) if all(r['weight'] is not None for r in basis.values() if r['terminal']) else None
        if terminal is not None and d!=tie:result['sensitivity']['tie_break_even']=wire(((1-F(policy.terminal_noncompletion))*d+F(policy.terminal_noncompletion)*terminal-haircut)/(d-tie))
    result['dependency_revision']=digest(dict(version=VERSION,quotes=[dict(id=x.q['id'],revision=x.q['revision'],source=x.q['source'],original=x.q['original'],times=x.q['times'],binding=x.q['binding'],occurrence=x.q.get('occurrence_match'),contract=x.q.get('native_contract'),depth=x.q.get('depth',[])) for x in legs],profiles=[x.q['comparison_input_refs'] for x in legs],
        content=[{k:v['recipe']['id'] for k,v in x.content.items()} for x in legs],policy=policy.to_dict(),
        allocation=[wire(n) for n in qs],basis=basis,reference=[None if x.reference is None else x.reference.revision for x in legs],states=states))
    result['id']='pair:'+digest([VERSION,*[x.q['id'] for x in legs]])
    from app.dashboard.current_contract import exact_wire,display_decimal
    result['display']={k:None if result[k] is None else display_decimal(exact_wire(F(result[k]))['decimal_approx'],2,True) for k in ('buffered_profit_usd','buffered_return_percent')}
    if getattr(policy,'sizing_mode',None) is not None:
        from .financial_metrics import pair_metrics
        pair_metrics(result,policy,legs,components,p,requested_search)
    result['revision']=digest(result)
    if details:
        result['components']=[{k:v for k,v in x.get(n,rich=True).items() if not k.startswith('_pair_')} for x,n in zip(legs,qs)]
        # Sensitivity is selected-only; allocation-specific receipts and fees
        # are recomputed, rather than multiplying another result's fees.
        for i,(x,n,component) in enumerate(zip(legs,qs,components)):
            receipts={s:component['components']['payout']['receipt_usd:'+s]['modeled_value'] for s in CELLS}
            endpoints=component['payout_details'].get('terminal_range_usd',[])
            for receipt in endpoints:
                changed=list(components);changed[i]=x.get(n,cashflows=dict(receipts,terminal_noncompletion=receipt))
                cc,ss=economics(changed,basis);v=expected(ss,p)
                result['sensitivity']['terminal_payout'].append(dict(leg=i,receipt_usd=receipt,buffered_expected_profit_usd=ws(None if v is None else v-cc*F(policy.buffer_rate))))
            if F(component['pair_support'])<n:
                try:
                    changed=list(components);changed[i]=x.get(n,impact=F('.01'));cc,ss=economics(changed,basis);v=expected(ss,p)
                    result['sensitivity']['repriced_residual'].append(dict(leg=i,kind='repriced_fixed_quantity; no resizing',
                        deployed_capital_usd=wire(cc),fits_ceiling=cc<=budget,buffered_expected_profit_usd=ws(None if v is None else v-cc*F(policy.buffer_rate))))
                except ValueError as error:result['sensitivity']['repriced_residual'].append(dict(leg=i,reason=str(error)))
    return result


def compact(value):
    """Small chosen result; native instruments reopen through exact quote IDs."""
    fields=('version','id','revision','model_available','ranking_eligible','reasons','conditioning',
        'policy_revision','objective','category','deployed_capital_usd','unused_cash_usd','buffer_usd',
        'minimum_spend_solution','buffered_profit_usd','buffered_return_percent',
        'buffered_decisive_minimum_usd','buffered_all_state_minimum_usd','limiting_states','size_status','display')
    from .financial_metrics import SUCCESSOR_FIELDS
    fields += SUCCESSOR_FIELDS
    result={k:value[k] for k in fields if k in value}
    if 'legs' in value:
        result['legs']=[dict({k:leg[k] for k in ('quote_id','quote_revision','group_id','native_quantity')},venue=leg['native_key'][0]) for leg in value['legs']]
    if 'search' in value:
        result['search']=dict(evaluations=value['search']['evaluations'],global_optimality_proven=value['search']['global_optimality_proven'],
            limitation=None if value['search']['global_optimality_proven'] else 'fixed_allocation' if value['search']['limitation']=='explicit fixed allocation' else 'sampled_legal_grid')
    return result


def assemble(event,profiles,at,*,policy=DEFAULT_POLICY,details=False,selected_quote_id=None,selected_pair_id=None):
    steps=assembly_steps(event,profiles,at,policy=policy,details=details,
        selected_quote_id=selected_quote_id,selected_pair_id=selected_pair_id)
    while True:
        try:next(steps)
        except StopIteration as done:return done.value


def assembly_steps(event,profiles,at,*,policy=DEFAULT_POLICY,details=False,selected_quote_id=None,selected_pair_id=None):
    from app.dashboard.current_contract import quotes_of
    candidates=[];diagnostics=[];results=[];unexamined=0
    for group in event['groups']:
        if group['market']!='winner' or group['period']!='full_game':continue
        for outcome in group['outcomes']:
            for q in quotes_of(outcome):
                if len(candidates)>=MAX_CANDIDATE_LEGS:unexamined+=1;continue
                try:candidates.append(Leg(q,group,profiles,event,at,policy=policy))
                except (ValueError,KeyError,TypeError,ArithmeticError) as error:diagnostics.append(dict(quote_id=q['id'],reason=str(error)))
                yield ('pair_leg', q['id'])
    # No unbounded Cartesian pair list. Round-robin initial leg coverage, then
    # remaining combinations; original quote alternatives are never removed.
    pairs_count=sum(1 for i,a in enumerate(candidates) for b in candidates[i+1:] if a.sign!=b.sign and native_key(a.q)!=native_key(b.q))
    ordered=[];seen=set()
    for i,a in enumerate(candidates):
        for j,b in enumerate(candidates):
            key=tuple(sorted((i,j)))
            if a.sign!=b.sign and native_key(a.q)!=native_key(b.q) and key not in seen:
                ordered.append((a,b) if i<j else (b,a));seen.add(key);break
        if len(ordered)==MAX_PAIRS:break
    for i,a in enumerate(candidates):
        for j in range(i+1,len(candidates)):
            b=candidates[j]
            if len(ordered)>=MAX_PAIRS:break
            if a.sign!=b.sign and native_key(a.q)!=native_key(b.q) and (i,j) not in seen:
                ordered.append((a,b));seen.add((i,j))
    evaluated=0
    for pair in ordered[:MAX_PAIRS]:
        if selected_quote_id is not None and not any(x.q['id']==selected_quote_id for x in pair):continue
        if selected_pair_id is not None and 'pair:'+digest([VERSION,*[x.q['id'] for x in pair]])!=selected_pair_id:continue
        evaluated+=1
        result=evaluate(pair,policy=policy,details=details)
        if result['model_available']:results.append(result if details else compact(result))
        else:diagnostics.append(dict(quote_ids=[x.q['id'] for x in pair],reason='; '.join(result['reasons'])))
        yield ('pair', result.get('id'))
    summary=dict(version=VERSION,candidate_legs=len(candidates),candidate_pairs=pairs_count,evaluated_pairs=evaluated,
        results=len(results),maximum_pairs_per_occurrence=MAX_PAIRS,maximum_evaluations_per_pair=MAX_EVALUATIONS,
        unexamined_legs=unexamined,maximum_candidate_legs=MAX_CANDIDATE_LEGS,truncated=pairs_count>MAX_PAIRS or unexamined>0,limitation='bounded candidate search; round-robin leg coverage before remaining pairs' if pairs_count>MAX_PAIRS or unexamined else None,
        allocation_consumer_probes=sum(x.probes for x in candidates),diagnostics=diagnostics,
        constraints_version=CONSTRAINT_VERSION,minimum_decisive_exposure_usd='25',minimum_exposure_share='0.2',
        sampled_search_limitation='best evaluated legal grid; nonlinear fees/depth may permit a better unsampled allocation',
        percentage_denominator='actual modeled deployed capital including refundable holds')
    return results,summary
