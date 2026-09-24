"""Finite acquisition-depth scenarios. No network, account or execution access.

A proof is only over the supplied discrete domain and explicit fill partition.
Decision qualification is refreshed by size_depth; replay is an audit only.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
from decimal import Context, Decimal, localcontext, ROUND_CEILING, ROUND_FLOOR
from itertools import product
from math import lcm

from app.arbitrage import Policy, book_observations, detect, wire, sizing
from app.fees import calculate, load_registry, Registry
from app.fees.engine import number as D, digest
from app.models.core import Venue

VERSION = 'depth-1'
ZERO = Decimal(0)


@dataclass(frozen=True)
class AcquisitionLadder:
    observation: object
    # Native quantity units; immutable rows (price, quantity, provenance).
    levels: tuple[tuple[str, str, str], ...] | None
    transformation: str
    partial_final: bool | None = None
    # Existing adapter Ladder contract already aggregates identical prices.
    # This layer rejects duplicates, including identical repeats within a ladder.


def book_ladders(book, *, partial_final=None, **context):
    """Only Kalshi's documented 1-opposite-bid transformation; native asks elsewhere."""
    with localcontext(Context(prec=100)):
        result=[]
        for obs in book_observations(book, **context):
            side=obs.quote.outcome_id
            derived=book.raw.ref.venue == Venue.KALSHI
            native_side=('no' if side=='yes' else 'yes') if derived else side
            native=next((o for o in book.outcomes if o.outcome_id==native_side),None)
            ladder=(native.bids if derived else native.asks) if native else None
            transform=f'kalshi:1-{native_side}-bid;quantity=opposite-bid-contracts' if derived else 'native-ask'
            levels=None if ladder is None else tuple((str(1-x.price.value if derived else x.price.value),
                str(x.quantity.value),f'{transform};native-index={i};source={digest(book.raw.json_text)}')
                for i,x in enumerate(ladder.levels))
            result.append(AcquisitionLadder(obs,levels,transform,partial_final))
        return tuple(result)


def ladder_wire(ladder):
    o=ladder.observation
    return dict(observation=wire(o),raw_json=o.quote.raw.json_text,
        levels=None if ladder.levels is None else [dict(price=p,quantity=q,provenance=src) for p,q,src in ladder.levels],
        transformation=ladder.transformation,partial_final=ladder.partial_final,
        sizing=None if sizing(o) is None else [str(x) for x in sizing(o)])


@dataclass(frozen=True)
class Search:
    max_evaluations: int = 4096
    min_profit: str = '0'
    min_roi: str = '0'
    total_cash_limit: str | None = None
    # Left/right venue entry cash limits; reserve belongs only to total.
    venue_cash_limits: tuple[str | None, str | None] = (None, None)
    curve_limit: int = 64

    def __post_init__(self):
        if type(self.max_evaluations) is not int or not 1 <= self.max_evaluations <= 100000:
            raise ValueError('max_evaluations must be 1..100000')
        if type(self.curve_limit) is not int or not 2 <= self.curve_limit <= 256:
            raise ValueError('curve_limit must be 2..256')
        if len(self.venue_cash_limits)!=2: raise ValueError('two venue cash limits required')
        for x in (self.min_profit,self.min_roi,self.total_cash_limit,*self.venue_cash_limits):
            if x is not None and D(x)<0: raise ValueError('nonnegative scenario inputs required')


def consume(levels, quantity, *, partial_final=True):
    """Exact cheapest-first walk; input rows are normalized payout-contract units."""
    with localcontext(Context(prec=100)):
        q=D(quantity); left=q; fills=[]
        if q<0: raise ValueError('negative quantity')
        prices=[D(x['price']) for x in levels]
        if prices!=sorted(set(prices)): raise ValueError('duplicate or unordered acquisition prices')
        for row in levels:
            available=D(row['quantity'])
            if available<=0 or not 0<D(row['price'])<1: raise ValueError('invalid acquisition level')
            take=min(left,available)
            if take:
                if take<available and partial_final is not True: raise ValueError('partial final level unsupported')
                fills.append({**row,'quantity':str(take),'available':str(available)})
                left-=take
        if left: raise ValueError('quantity exceeds supplied depth')
        return fills


def size_depth(parents, matcher, ladders, fee_contexts, *, evaluation_time,
               search=None, policy=None, registry=None):
    """Refresh matching and top-of-book diagnostics, then size each candidate independently."""
    search=search or Search(); policy=policy or Policy(); registry=registry or load_registry()
    with localcontext(Context(prec=100)):
        ladders=list(ladders)
        baseline=detect(parents,matcher,[x.observation for x in ladders],fee_contexts,
            evaluation_time=evaluation_time,policy=policy,registry=registry)
        index={}
        for x in ladders:
            w=ladder_wire(x); o=w['observation']
            key=(o['venue'],o['environment'],o['event_id'],o['market_id'],o['side'])
            index.setdefault(key,{})[digest(w)]=w
        results=[]
        markets=matcher.snapshot['observations']
        for base in baseline['candidates']:
            ws=[]; contexts=[]; problems=[]
            for i,leg in enumerate(base['legs']):
                # Matching source rows, not a missing quote, determine lookup identity.
                row=next(r for r in markets.values() if r['key']==leg['native_market_key'])
                key=(row['venue'],row['scope'][1],row['native_event_id'],row['native_market_id'],leg['side'])
                variants=index.get(key,{})
                ws.append(next(iter(variants.values())) if len(variants)==1 else None)
                if len(variants)>1: problems.append(f'leg-{i}:conflicting-depth-observations')
                contexts.append(deepcopy(fee_contexts.get((leg['native_market_key'],leg['side']))))
            snapshot=dict(base=base,ladders=ws,fee_contexts=contexts,problems=problems,
                evaluation_time=evaluation_time.isoformat(),policy=asdict(policy),search=asdict(search),registry=registry.data)
            results.append(_audit(snapshot))
        screen=detect(parents,matcher,[x.observation for x in ladders],fee_contexts,
            evaluation_time=evaluation_time,policy=policy,registry=registry,fill_grouping='single_fill_per_leg')
        return dict(engine=VERSION,top_of_book=screen,candidates=results,
            limit='Related candidates share liquidity: capacities cannot be summed. All supplied levels only; both modeled orders must fill.',
            summary=dict(candidates=len(results),qualified_modeled=sum(bool(r['solutions']['max_profit']['allocation']['qualified_modeled_arbitrage']) for r in results),
                current_production=sum(bool(r['solutions']['max_profit']['allocation']['current_production_opportunity']) for r in results)))


def _audit(snapshot):
    result=_solve(snapshot)
    return dict(engine=VERSION,input=deepcopy(snapshot),input_hash=digest(snapshot),result_hash=digest(result),**result)


def replay(audit):
    """Exact historical calculation replay; does not reconfirm current matching."""
    if audit['engine']!=VERSION or digest(audit['input'])!=audit['input_hash']:
        raise ValueError('depth audit input mismatch')
    with localcontext(Context(prec=100)):
        rebuilt=_audit(audit['input'])
    if rebuilt!=audit: raise ValueError('depth audit result mismatch')
    return rebuilt


def _prepare(w):
    if w is None: return None,'acquisition-ladder-unavailable'
    if w['levels'] is None: return None,'acquisition-ladder-unavailable'
    if len(w['levels'])>10000: return None,'supplied-level-limit-exceeded:10000'
    if not w['transformation']: return None,'level-transformation-unavailable'
    if w['sizing'] is None: return None,'size-or-economic-rules-unknown'
    if w['partial_final'] is None: return None,'partial-fill-rule-unknown'
    o=w['observation']; unit=o['unit']
    factor=Decimal('.01') if unit=='payout_cents' and o['venue']=='novig' else Decimal(1)
    levels=[]
    for row in w['levels']:
        if not row['provenance']: return None,'level-provenance-unavailable'
        levels.append({**row,'quantity':str(D(row['quantity'])*factor)})
    try: consume(levels,'0')
    except ValueError as e: return None,str(e)
    if levels and (D(levels[0]['price'])!=D(o['ask']) or D(levels[0]['quantity'])!=D(o['available'])*factor):
        return None,'top-and-depth-conflict'
    if not levels and o['ask'] is not None: return None,'top-and-depth-conflict'
    size=sum((D(r['quantity']) for r in levels),ZERO)
    minimum,step=map(D,w['sizing'][1:])
    first=int((minimum/step).to_integral_value(rounding=ROUND_CEILING))
    last=int((size/step).to_integral_value(rounding=ROUND_FLOOR))
    return dict(levels=levels,size=size,minimum=minimum,step=step,first=first,last=last,partial_final=w['partial_final']),None


def _leg(q, i, domain, snapshot, registry):
    if q==0:
        return dict(quantity='0',consumed_levels=[],weighted_average_price=None,entry_cost='0',entry_fees='0',
            required_cash='0',credits=[],fee_audit=None,reasons=[],outcomes={n:dict(net_payout='0',net_cashflow='0',settlement_fee='0') for n in snapshot['base']['relationship']['scenarios']})
    fills=consume(domain['levels'],str(q),partial_final=domain['partial_final'])
    cost=sum((D(f['price'])*D(f['quantity']) for f in fills),ZERO)
    result=dict(quantity=str(q),consumed_levels=fills,weighted_average_price=str(cost/q),entry_cost=str(cost),
        entry_fees=None,required_cash=None,credits=[],fee_audit=None,reasons=[],outcomes={})
    c=deepcopy(snapshot['fee_contexts'][i]); obs=snapshot['ladders'][i]['observation']
    if c is None:
        result['reasons'].append('fee-context-unavailable'); return result
    if any(c.get(k)!=obs[v] for k,v in [('venue','venue'),('environment','environment'),('market_id','market_id')]):
        result['reasons'].append('fee-context-identity-mismatch'); return result
    if any(k in c for k in ('fills','market_cashflows','refund_outcomes')): raise ValueError('fee template must omit modeled fills/cashflows/refunds')
    payouts={}; refunds=[]
    for name,case in snapshot['base']['relationship']['scenarios'].items():
        p=case['left' if i==0 else 'right']
        if p['kind']=='fraction': payouts[name]=p['value']
        elif p['kind']=='refund': refunds.append(name)
    c.update(trade_time=snapshot['evaluation_time'],calculation_time=snapshot['evaluation_time'],
        settlement_status=snapshot['base']['settlement']['status'],outcomes=payouts,complete_order_history=True,
        fills=[dict(fill_id=f'level-{j}',order_id='modeled-new-order',match_id='modeled-match',
            role='taker',price=f['price'],quantity=f['quantity'],unit='contracts') for j,f in enumerate(fills)])
    if refunds: c['refund_outcomes']=refunds
    try: fee=calculate(c,registry)
    except (ValueError,KeyError) as e:
        result['reasons'].append('fee-context-invalid:'+str(e)); return result
    result.update(fee_audit=fee,entry_fees=fee['entry_fees'],required_cash=fee['entry_cash_requirement'],
        credits=fee['credits'],outcomes=fee['outcomes'])
    if fee['qualification']!='documented_scenario':
        result['reasons'].extend(fee['unsupported']+fee['assumptions'] or ['fee-not-qualified'])
    # Actual fragmentation is unknown even at a single displayed price. No bound
    # is asserted for rounded positive coefficients. Novig zero-fee pregame is invariant.
    schedule=fee.get('schedule') or {}
    if schedule.get('coefficient') is None or D(schedule['coefficient'])!=0:
        result['reasons'].append('fill-fragmentation-unbounded: one fill per consumed price level; different subfills can change rounded charges; no conservative fee bound asserted')
    return result


def _allocation(qs, domains, snapshot, registry, cache):
    legs=[]
    for i,q in enumerate(qs):
        key=(i,q)
        if key not in cache: cache[key]=_leg(q,i,domains[i],snapshot,registry)
        legs.append({**cache[key],'identity':snapshot['base']['legs'][i],
            'depth_scope':None if snapshot['ladders'][i] is None else snapshot['ladders'][i]['observation']['depth']})
    def add(values):
        return None if any(x is None for x in values) else sum((Decimal(x) for x in values),ZERO)
    def out(x): return None if x is None else str(x)
    no_trade=all(q==0 for q in qs)
    reserve=ZERO if no_trade else D(snapshot['policy']['execution_reserve_usd'])
    cash=add([x['required_cash'] for x in legs]); denominator=None if cash is None else cash+reserve
    outcomes={}
    for name,case in snapshot['base']['relationship']['scenarios'].items():
        os=[l['outcomes'].get(name,{}) for l in legs]
        profit=add([o.get('net_cashflow') for o in os])
        if profit is not None: profit-=reserve
        outcomes[name]=dict(payout_evidence=case,net_payout=out(add([o.get('net_payout') for o in os])),
            settlement_fees=out(add([o.get('settlement_fee') for o in os])),profit=out(profit))
    known=[Decimal(o['profit']) for o in outcomes.values() if o['profit'] is not None]
    worst=min(known) if known and len(known)==len(outcomes) else None
    roi=worst/denominator if worst is not None and denominator and denominator>0 else None
    search=snapshot['search']; constraint_reasons=[]
    for i,limit in enumerate(search['venue_cash_limits']):
        if limit is not None and (legs[i]['required_cash'] is None or Decimal(legs[i]['required_cash'])>D(limit)):
            constraint_reasons.append(f'leg-{i}:cash-limit-exceeded-or-unknown')
    if search['total_cash_limit'] is not None and (denominator is None or denominator>D(search['total_cash_limit'])):
        constraint_reasons.append('total-cash-limit-exceeded-or-unknown')
    reasons=list(snapshot['qualification_reasons'])
    for i,l in enumerate(legs): reasons.extend(f'leg-{i}:{x}' for x in l['reasons'])
    if worst is None: reasons.append('material-outcome-net-guarantee-unknown')
    passes=worst is not None and worst>0 and roi is not None and worst>=D(snapshot['policy']['min_profit_usd']) and roi>=D(snapshot['policy']['min_roi'])
    qualified=not no_trade and not reasons and not constraint_reasons and worst is not None and worst>0
    return dict(provenance={k:deepcopy(snapshot['base'][k]) for k in ('id','pair_id','pair_revision','market_hashes','parent_snapshot_hash','relationship','settlement','scope')},
        quantities=[str(q) for q in qs],legs=legs,entry_cost=out(add([l['entry_cost'] for l in legs])),
        entry_fees=out(add([l['entry_fees'] for l in legs])),required_cash_per_venue=[l['required_cash'] for l in legs],
        required_cash=out(cash),execution_reserve=str(reserve),roi_denominator=out(denominator),outcomes=outcomes,
        worst_case_profit=out(worst),worst_case_roi=out(roi),minimum_known_profit=out(min(known) if known else None),
        reasons=list(dict.fromkeys(reasons)),constraint_reasons=constraint_reasons,feasible=not constraint_reasons,
        no_trade=no_trade,qualified_modeled_arbitrage=qualified,
        passes_reporting_thresholds=passes,current_production_opportunity=qualified and passes and snapshot['base']['scope']=='current',
        fill_partition='One new taker order per leg; one fill per consumed level in cheapest-first order; actual fragmentation unknown.')


def _solve(original):
    snapshot=deepcopy(original); base=snapshot['base']; search=Search(**snapshot['search'])
    # Top-of-book diagnostics were called without a fill assumption: retain qualification, remove
    # only the unrequested top-size choice and replace it with depth-domain checks.
    reasons=[x for x in base['reasons'] if x not in ('explicit-fill-grouping-required','no-common-visible-quantity')]
    reasons.extend(snapshot['problems'])
    domains=[]
    for i,w in enumerate(snapshot['ladders']):
        domain,problem=_prepare(w); domains.append(domain)
        if problem: reasons.append(f'leg-{i}:{problem}')
    snapshot['qualification_reasons']=list(dict.fromkeys(reasons))
    registry=Registry(snapshot['registry']); cache={}
    zero=_allocation((ZERO,ZERO),domains,snapshot,registry,cache)
    keys=('equal_max_profit','max_profit','max_roi','max_deployment','minimum_known_diagnostic')
    winners={k:zero for k in keys}
    def count(d): return 1+max(0,d['last']-d['first']+1)
    available=all(d is not None for d in domains) and not snapshot['problems']
    total=count(domains[0])*count(domains[1]) if available else 1
    seen=set(); evaluated=0; invalid=0; curve=[]; unresolved=0; equal_points=0
    # Exact rational common grid; no binary floats or smoothness assumptions.
    common=None
    if available:
        scale=10**max(0,*(-d['step'].as_tuple().exponent for d in domains))
        common=Decimal(lcm(*(int(d['step']*scale) for d in domains)))/scale
    def compact(a):
        return {k:a[k] for k in ('quantities','required_cash','worst_case_profit','worst_case_roi','minimum_known_profit','feasible','constraint_reasons')}
    def value(a,k): return Decimal(a[k]) if a[k] is not None else None
    def consider(a):
        if not a['feasible']: return
        w=value(a,'worst_case_profit'); roi=value(a,'worst_case_roi')
        if w is not None and w>0:
            if w>value(winners['max_profit'],'worst_case_profit'): winners['max_profit']=a
            if Decimal(a['quantities'][0])==Decimal(a['quantities'][1]) and w>value(winners['equal_max_profit'],'worst_case_profit'): winners['equal_max_profit']=a
            old=value(winners['max_roi'],'worst_case_roi')
            if roi is not None and (old is None or roi>old): winners['max_roi']=a
            if roi is not None and w>=D(search.min_profit) and roi>=D(search.min_roi):
                if value(a,'roi_denominator')>value(winners['max_deployment'],'roi_denominator'): winners['max_deployment']=a
        known=value(a,'minimum_known_profit')
        if known is not None and known>value(winners['minimum_known_diagnostic'],'minimum_known_profit'):
            winners['minimum_known_diagnostic']=a
    def axis(d):
        yield ZERO
        for n in range(d['first'],d['last']+1): yield n*d['step']
    def proposals():
        yield (ZERO,ZERO)
        if not available: return
        # Small domains are exhaustive. Large domains prioritize equal-depth
        # boundaries, then extremes, then a deterministic lexicographic prefix.
        if total>search.max_evaluations:
            points=set()
            for d in domains:
                s=ZERO
                for level in d['levels']:
                    s+=D(level['quantity']); points.add((s/common).to_integral_value(rounding=ROUND_FLOOR)*common)
            limit=min(d['last']*d['step'] for d in domains)
            points.add((limit/common).to_integral_value(rounding=ROUND_FLOOR)*common)
            for q in sorted(points):
                if q>0 and q<=limit and all(q>=d['minimum'] for d in domains): yield q,q
            for qs in product(*[([d['first']*d['step'],d['last']*d['step']] if d['first']<=d['last'] else [ZERO]) for d in domains]): yield qs
        # Nested lazy axes avoid materializing a huge quantity grid.
        for a in axis(domains[0]):
            for b in axis(domains[1]): yield a,b
    reached=False
    for qs in proposals():
        if qs in seen: continue
        if evaluated>=search.max_evaluations: reached=True; break
        seen.add(qs); evaluated+=1
        try: a=_allocation(qs,domains,snapshot,registry,cache)
        except ValueError as e:
            if str(e)!='partial final level unsupported': raise
            invalid+=1; continue
        consider(a)
        if a['feasible'] and a['worst_case_profit'] is None: unresolved+=1
        if qs[0]==qs[1]:
            equal_points+=1
            if len(curve)<search.curve_limit: curve.append(compact(a))
    status='proven-optimal-within-supplied-grid-and-fill-model' if evaluated==total and available else 'best-found-search-limit' if reached else 'unsized-inputs'
    solutions={k:dict(objective=k,optimality=('objective-unresolved-material-cashflows-unknown' if unresolved and k!='minimum_known_diagnostic' else status),allocation=deepcopy(a),
        interpretation='Known outcomes only; never a guaranteed optimum or recommendation.' if k=='minimum_known_diagnostic' else 'Conditional on all qualification reasons and the modeled fill partition.') for k,a in winners.items()}
    return dict(id=base['id'],pair_id=base['pair_id'],reasons=snapshot['qualification_reasons'],solutions=solutions,
        search=dict(method='exact discrete enumeration, boundary-first when budget is insufficient',
            domain=[None if d is None else dict(visible_quantity=str(d['size']),minimum=str(d['minimum']),increment=str(d['step']),
                first_positive_index=d['first'],last_index=d['last'],origin='0',partial_final=d['partial_final']) for d in domains],
            common_grid=None if common is None else str(common),total_grid_allocations=total,evaluated=evaluated,
            invalid_partial_allocations=invalid,unresolved_cashflow_allocations=unresolved,max_evaluations=search.max_evaluations,limit_reached=reached,optimality=status,
            constraints=asdict(search),deployment_measure='total required cash including separate reserve',
            tie_break='first in deterministic search order; zero wins nonpositive ties'),
        curve=curve,curve_truncated=equal_points>len(curve),curve_note=f'At most {search.curve_limit} evaluated equal-quantity points, in search order. Not an interpolation or monotonicity claim.',
        liquidity=[None if w is None else dict(depth=w['observation']['depth'],transformation=w['transformation']) for w in snapshot['ladders']])


def evaluate_allocation(audit, quantities):
    """Validate an explicit grid allocation against a saved scenario, not current liquidity."""
    if digest(audit['input'])!=audit['input_hash']: raise ValueError('depth audit input mismatch')
    with localcontext(Context(prec=100)):
        if len(quantities)!=2: raise ValueError('two quantities required')
        qs=tuple(D(q) for q in quantities)
        snapshot=deepcopy(audit['input']); domains=[]
        for q,w in zip(qs,snapshot['ladders']):
            d,problem=_prepare(w)
            if problem: raise ValueError(problem)
            if q<0 or (q and (q<d['minimum'] or q>d['size'] or q%d['step'])):
                raise ValueError('quantity outside supplied depth, minimum or grid')
            domains.append(d)
        snapshot['qualification_reasons']=audit['reasons']
        return _allocation(qs,domains,snapshot,Registry(snapshot['registry']),{})
