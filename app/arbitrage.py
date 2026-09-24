"""Finite, ask-only, equal-quantity acquisition diagnostics.

The public entry point refreshes decisions from the current event and market
matchers. No saved pair dictionary alone can establish current confirmation.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Context, Decimal, localcontext, ROUND_FLOOR
from hashlib import sha256
from math import lcm

from app.fees import calculate
from app.fees.engine import number, digest
from app.models.core import Quote, QuoteSide, OrderBook, Venue, aware, typed
from app.adapters.kalshi import quotes as kalshi_quotes

VERSION = 'top-of-book-1'
D = number


@dataclass(frozen=True)
class Policy:
    max_receipt_age_seconds: str = '30'
    max_observation_skew_seconds: str = '5'
    max_source_age_seconds: str = '30'  # only snapshot-clock semantics
    min_profit_usd: str = '0'
    min_roi: str = '0'
    execution_reserve_usd: str = '0'  # cash reserved, conservatively consumed

    def __post_init__(self):
        for value in asdict(self).values():
            if D(value) < 0:
                raise ValueError('policy values must be nonnegative')


@dataclass(frozen=True)
class Observation:
    quote: Quote
    environment: str
    evidence_class: str  # current, historical, synthetic; never inferred from time
    sync: str
    depth: str
    source_time_progress: str
    source_time_semantics: str  # snapshot, last_change, unknown
    source_time_problem: str | None = None  # sticky upstream clock/recovery issue
    locks_clear: bool | None = None
    units_verified: bool = False
    minimum: str | None = None  # in the quote's native unit
    increment: str | None = None
    sizing_evidence: str | None = None
    role: str = 'taker'

    def __post_init__(self):
        typed(self.quote, Quote, 'executable quote')


def book_observations(book, **context):
    """Use adapter Kalshi asks; other venues expose only supplied native asks.

    PMUS short acquisition is deliberately unavailable when its adapter supplied
    no ask. This function does not invent long/short conversions from bids.
    """
    typed(book, OrderBook, 'prediction-market book')
    with localcontext(Context(prec=100)):
        if book.raw.ref.venue == Venue.KALSHI:
            quotes = kalshi_quotes(book)
        else:
            quotes = tuple(Quote(raw=book.raw, outcome_id=o.outcome_id, state=book.state,
                ask=QuoteSide(price=o.asks.levels[0].price, quantity=o.asks.levels[0].quantity)
                    if o.asks and o.asks.levels else None,
                bid=QuoteSide(price=o.bids.levels[0].price, quantity=o.bids.levels[0].quantity)
                    if o.bids and o.bids.levels else None) for o in book.outcomes)
    def ask_depth(q):
        side=q.outcome_id
        if book.raw.ref.venue==Venue.KALSHI:
            side='no' if side=='yes' else 'yes'
            ladder=next((o.bids for o in book.outcomes if o.outcome_id==side),None)
        else:
            ladder=next((o.asks for o in book.outcomes if o.outcome_id==side),None)
        return ladder.depth.value if ladder is not None else 'unknown'
    return tuple(Observation(quote=q, sync=book.sync.value, depth=ask_depth(q),
        source_time_progress=book.source_time_progress.value, **context) for q in quotes)



def seconds(delta):
    return Decimal(delta.days*86400 + delta.seconds) + Decimal(delta.microseconds)/1000000


def wire(obs):
    q=obs.quote; r=q.raw
    return {**{k:v for k,v in asdict(obs).items() if k!='quote'},
        'venue':r.ref.venue.value, 'event_id':r.ref.event_id, 'market_id':r.ref.market_id,
        'side':q.outcome_id, 'state':q.state.value, 'raw_kind':r.kind.value,
        'source':r.source, 'source_sha256':sha256(r.json_text.encode()).hexdigest(),
        'received_at':r.received_at.isoformat(),
        'exchange_at':r.exchange_at.isoformat() if r.exchange_at else None,
        'ask':None if q.ask is None else str(q.ask.price.value),
        'available':None if q.ask is None or q.ask.quantity is None else str(q.ask.quantity.value),
        'unit':None if q.ask is None or q.ask.quantity is None else q.ask.quantity.unit}


def eligibility(obs, now, policy):
    r=obs.quote.raw; issues=[]
    age=seconds(now-r.received_at)
    if age<0: issues.append('receipt-in-future')
    if age>D(policy.max_receipt_age_seconds): issues.append('stale-receipt')
    if obs.quote.state.value!='active': issues.append('market-'+obs.quote.state.value)
    if obs.sync!='synchronized': issues.append('reconstruction-'+obs.sync)
    if obs.locks_clear is not True: issues.append('locked-or-lock-status-unknown')
    if obs.depth not in ('partial','full'): issues.append('depth-unknown')
    if obs.source_time_problem: issues.append('source-time-problem:'+obs.source_time_problem)
    if obs.source_time_progress=='regressed': issues.append('source-time-regressed')
    if r.exchange_at is None: issues.append('source-time-missing')
    else:
        if r.exchange_at>r.received_at: issues.append('source-time-ahead-of-receipt')
        if obs.source_time_semantics=='snapshot':
            if seconds(now-r.exchange_at)>D(policy.max_source_age_seconds): issues.append('stale-source-snapshot')
        elif obs.source_time_semantics!='last_change': issues.append('source-time-semantics-unknown')
    if obs.evidence_class not in ('current','historical','synthetic'): issues.append('evidence-class-unknown')
    expected='synthetic' if obs.evidence_class=='synthetic' else 'observation'
    if r.kind.value!=expected: issues.append('evidence-class-mismatch')
    if obs.environment!='production': issues.append('non-production-environment')
    return issues


def sizing(obs):
    """Return visible size/minimum/increment in $1 payout contracts, or unknown."""
    a=obs.quote.ask
    if not a or not a.quantity or not obs.units_verified or not obs.sizing_evidence:
        return None
    unit=a.quantity.unit
    if unit=='contracts': factor=Decimal(1)
    elif unit=='payout_cents' and obs.quote.raw.ref.venue==Venue.NOVIG: factor=Decimal('0.01')
    else: return None
    if obs.minimum is None or obs.increment is None: return None
    size=D(str(a.quantity.value))*factor; minimum=D(obs.minimum)*factor; step=D(obs.increment)*factor
    if minimum<=0 or step<=0: raise ValueError('positive minimum/increment required')
    return size,minimum,step


def common_quantity(sizes):
    # Decimal rational grid LCM; origin is zero, minimum is a lower bound.
    steps=[s[2] for s in sizes]
    scale=10**max(0,*(-s.as_tuple().exponent for s in steps))
    grid=Decimal(lcm(*(int(s*scale) for s in steps)))/scale
    q=(min(s[0] for s in sizes)/grid).to_integral_value(rounding=ROUND_FLOOR)*grid
    return q if all(q>=s[1] for s in sizes) else Decimal(0)


def total(values):
    return None if any(v is None for v in values) else sum((Decimal(v) for v in values),Decimal(0))


def out(value):
    return None if value is None else str(value)


def detect(parents, matcher, observations, fee_contexts, *, evaluation_time,
           quantity=None, fill_grouping=None, policy=None, registry=None):
    """Refresh current decisions; fee contexts keyed by (market key, native side).

    quantity is an explicit hypothetical $1 payout-contract count, or None for
    the largest common grid quantity within both visible tops. fill_grouping must
    explicitly be 'single_fill_per_leg' to calculate: this is a hypothetical new
    order on each venue, never a claimed observed fill or fragmentation pattern.
    """
    aware(evaluation_time,'evaluation_time')
    policy=policy or Policy()
    with localcontext(Context(prec=100)):
        current=matcher.report(parents)
        snapshot=matcher.snapshot
        markets={k:snapshot['observations'][hs[0]] for k,hs in snapshot['current'].items()}
        index={}
        for obs in observations:
            if not isinstance(obs,Observation): raise ValueError('Observation required')
            w=wire(obs)
            key=(w['venue'],w['environment'],w['event_id'],w['market_id'],w['side'])
            index.setdefault(key,{})[digest(w)]=obs
        candidates=[]; excluded=[]
        for pair in current['pairs'].values():
            if pair.get('withdrawn'):
                excluded.append(pair); continue
            for rel in pair['relationships']:
                if not (rel['opposing_sporting_outcomes'] or rel['opposite_predicates'] or rel['complementary_payoffs']=='YES'):
                    continue
                rows=[markets[pair[k]] for k in ('left','right')]
                sides=[rel['left_side'],rel['right_side']]
                legs=[]; conflicts=[]
                for row,side in zip(rows,sides):
                    key=(row['venue'],row['scope'][1],row['native_event_id'],row['native_market_id'],side)
                    variants=index.get(key,{})
                    # Never select arbitrarily among different representations of one observation.
                    legs.append(next(iter(variants.values())) if len(variants)==1 else None)
                    conflicts.append('conflicting-observations' if len(variants)>1 else 'ask-observation-unavailable')
                result=_evaluate(pair,rel,rows,legs,conflicts,fee_contexts,evaluation_time,
                                 quantity,fill_grouping,policy,registry)
                candidates.append(result)
        return {'engine':VERSION,'evaluation_time':evaluation_time.isoformat(),'policy':asdict(policy),
            'matching':current,'candidates':candidates,'withdrawn':excluded,
            'summary':{'candidates':len(candidates),
                'qualified_modeled':sum(c['qualified_modeled_arbitrage'] for c in candidates),
                'current_production':sum(c['current_production_opportunity'] for c in candidates)},
            'limit':'Equal quantity only; related liquidity families must not be summed. Both legs must fill at stated asks; no actual profit or fill guarantee.'}


def _evaluate(pair, rel, rows, legs, conflicts, contexts, now, supplied_q, grouping, policy, registry):
    sides=[rel['left_side'],rel['right_side']]
    identity=sorted((r['key'],side) for r,side in zip(rows,sides))
    reasons=list(pair['qualification']['reasons']); notes=[]
    if not pair['structural_match']: reasons.extend(pair['structural_reasons'])
    if not pair['settlement']['qualified']: reasons.append('settlement-not-qualified')
    if rel['complementary_payoffs']!='YES': reasons.append('complementary-payouts-'+rel['complementary_payoffs'])
    if len({r['venue'] for r in rows})!=2: reasons.append('same-venue-excluded')
    if rows[0]['scope']!=rows[1]['scope']: reasons.append('environment-or-evidence-isolation')
    detail=[]
    for i,(row,side,obs) in enumerate(zip(rows,sides,legs)):
        detail.append({'native_market_key':row['key'],'side':side,
            'liquidity_family':row['venue_event_liquidity_family'],
            'instrument_liquidity':next(s.get('liquidity_key') for s in row['sides'] if s['native_id']==side),
            'observation':None if obs is None else wire(obs)})
        if (row['key'],side) not in contexts: reasons.append(f'leg-{i}:fee-context-unavailable')
        if obs is None: reasons.append(f'leg-{i}:'+conflicts[i]); continue
        reasons.extend(f'leg-{i}:'+x for x in eligibility(obs,now,policy))
        if obs.quote.raw.kind.value!=row['scope'][0]: reasons.append(f'leg-{i}:matching-evidence-mismatch')
        if obs.role!='taker': reasons.append(f'leg-{i}:maker-dependent-deferred')
        if obs.quote.ask is None: reasons.append(f'leg-{i}:ask-unavailable')
    scope='unobserved'
    if all(legs):
        classes={o.evidence_class for o in legs}
        scope=next(iter(classes)) if len(classes)==1 else 'mixed-evidence'
        if scope=='mixed-evidence': reasons.append('mixed-evidence')
        skew=abs(seconds(legs[0].quote.raw.received_at-legs[1].quote.raw.received_at))
        if skew>D(policy.max_observation_skew_seconds): reasons.append('cross-leg-observation-skew')
    else: skew=None
    prices=[o.quote.ask.price.value if o and o.quote.ask else None for o in legs]
    price_sum=total(prices)
    result={'id':'top-'+digest(identity)[:24], 'pair_id':pair['id'], 'pair_revision':pair['revision'],
        'market_hashes':pair['market_hashes'],'parent_snapshot_hash':pair['parent_snapshot_hash'],
        'scope':scope,'legs':detail,'relationship':deepcopy(rel),'settlement':deepcopy(pair['settlement']),
        'pricing_diagnostic':{'ask_sum':out(price_sum),'unit_payout_reference_gap':out(None if price_sum is None else 1-price_sum),
            'classification':'unavailable' if price_sum is None else 'raw-gap' if price_sum<1 else 'no-pricing-edge',
            'observation_skew_seconds':out(skew),'claim':'Observed ask relationship only; $1 is a reference, not a guaranteed payout.'},
        'conditional_calculation':None,'qualified_modeled_arbitrage':False,'current_production_opportunity':False}
    sizes=[sizing(o) if o else None for o in legs]
    q=D(supplied_q) if supplied_q is not None else common_quantity(sizes) if all(sizes) else None
    if q is not None and q<=0:
        if supplied_q is not None: raise ValueError('hypothetical quantity must be positive')
        reasons.append('no-common-visible-quantity'); q=None
    for i,s in enumerate(sizes):
        if s is None: reasons.append(f'leg-{i}:size-or-economic-rules-unknown')
        elif q is not None and (q>s[0] or q<s[1] or q%s[2]): reasons.append(f'leg-{i}:quantity-outside-visible-size-or-grid')
    if grouping!='single_fill_per_leg': reasons.append('explicit-fill-grouping-required')
    if q is not None and all(p is not None for p in prices) and all(o.role=='taker' for o in legs) and grouping=='single_fill_per_leg':
        fees=[]
        for i,(row,side,obs,price) in enumerate(zip(rows,sides,legs,prices)):
            c=deepcopy(contexts.get((row['key'],side)))
            if c is None:
                reasons.append(f'leg-{i}:fee-context-unavailable'); fees.append(None); continue
            # Context is complete and explicit; stale/mis-scoped inputs cannot be rebound silently.
            expected={'venue':row['venue'],'environment':row['scope'][1],'market_id':row['native_market_id']}
            if any(c.get(k)!=v for k,v in expected.items()):
                reasons.append(f'leg-{i}:fee-context-identity-mismatch'); fees.append(None); continue
            if 'fills' in c or 'market_cashflows' in c:
                raise ValueError('fee template must omit fills/cashflows; detector supplies explicit modeled acquisitions')
            payouts={}
            for name,case in rel['scenarios'].items():
                p=case['left' if i==0 else 'right']
                if p['kind']=='fraction': payouts[name]=p['value']
                elif p['kind']=='refund': payouts[name]=str(price)
            c.update(trade_time=now.isoformat(),calculation_time=now.isoformat(),
                settlement_status=pair['settlement']['status'],outcomes=payouts,
                complete_order_history=True, fills=[dict(fill_id='modeled-fill',order_id='modeled-new-order',
                    role='taker',price=str(price),quantity=str(q),unit='contracts')])
            # Unknown ProphetX native economics remain unsupported by its fee engine.
            try: f=calculate(c,registry)
            except (ValueError,KeyError) as e:
                reasons.append(f'leg-{i}:fee-context-invalid:{e}'); fees.append(None); continue
            fees.append(f)
            if f['qualification']!='documented_scenario':
                reasons.extend(f'leg-{i}:fee:'+s for s in f['unsupported']+f['assumptions'])
                if not f['unsupported']+f['assumptions']: reasons.append(f'leg-{i}:fee-not-qualified')
        cash=total([f['entry_cash_requirement'] if f else None for f in fees])
        reserve=D(policy.execution_reserve_usd)
        denominator=None if cash is None else cash+reserve
        if denominator is not None and denominator<=0: reasons.append('nonpositive-cash-required-denominator')
        outcomes={}
        for name,case in rel['scenarios'].items():
            fs=[f['outcomes'].get(name,{}) if f else {} for f in fees]
            net=total([x.get('net_payout') for x in fs])
            profit=total([x.get('net_cashflow') for x in fs])
            if profit is not None: profit-=reserve
            outcomes[name]={'payout_evidence':case,'net_payout':out(net),
                'settlement_fees':out(total([x.get('settlement_fee') for x in fs])),
                'profit':out(profit),'roi':out(profit/denominator if profit is not None and denominator is not None and denominator>0 else None)}
        known=[Decimal(x['profit']) for x in outcomes.values() if x['profit'] is not None]
        worst=min(known) if known and len(known)==len(outcomes) else None
        if worst is None: reasons.append('material-outcome-net-guarantee-unknown')
        roi=worst/denominator if worst is not None and denominator is not None and denominator>0 else None
        positive=worst is not None and worst>0 and roi is not None
        result['conditional_calculation']={'quantity':str(q),'quantity_unit':'USD_1_payout_contracts',
            'quantity_mode':'hypothetical' if supplied_q is not None else 'common-visible-top',
            'fill_grouping':grouping,'assumptions':['Both new taker orders fill once at the stated asks; actual-fill reconciliation unverified.'],
            'acquisition_cost':str(q*price_sum),'entry_fees':out(total([f['entry_fees'] if f else None for f in fees])),
            'entry_cash_requirement':out(cash),'execution_reserve':str(reserve),'roi_denominator_cash_required':out(denominator),
            'fee_audits':fees,'outcomes':outcomes,'minimum_known_profit':out(min(known) if known else None),
            'worst_case_profit':out(worst),'worst_case_roi':out(roi),
            'classification':'insufficient-evidence' if worst is None else 'positive-conditional' if positive else 'no-net-edge'}
        result['qualified_modeled_arbitrage']=positive and not reasons
        result['passes_reporting_thresholds']=positive and worst>=D(policy.min_profit_usd) and roi>=D(policy.min_roi)
    else:
        result['passes_reporting_thresholds']=False
    if scope=='historical': notes.append('Historical replay never represents current liquidity.')
    if scope=='synthetic': notes.append('Synthetic model only; no production evidence.')
    result['current_production_opportunity']=result['qualified_modeled_arbitrage'] and scope=='current' and result['passes_reporting_thresholds']
    result['reasons']=list(dict.fromkeys(reasons)); result['notes']=notes
    return result
