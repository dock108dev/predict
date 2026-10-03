"""Strict current-1 admission/serialization. No acquisition or retained fallback.

Provider input is an evidenced normalized catalog, not a display payload. IDs and
comparisons are derived here. U3 owns binding evidence verification upstream;
this boundary checks the complete, exact binding against its catalog context.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import re
from .u0_display import VERSION, quote_display, bounded_decimal

VENUES = ('kalshi', 'polymarket_us', 'novig', 'prophetx')
STATES = ('connecting','available','not_offered','unavailable','budget_delayed','stale','error','stopped','resyncing')
MAX_BYTES = 64 * 1024 * 1024


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def identity(kind, value):
    return kind + ':' + hashlib.sha256(packed(value)).hexdigest()[:32]


def text(value):
    if not isinstance(value, str) or not 0 < len(value) <= 2048:
        raise ValueError('Bounded nonempty identity/text required')
    return value


def fields(value,required,optional=frozenset()):
    if not isinstance(value,dict) or set(value)-required-optional or required-set(value):
        raise ValueError('Unknown or missing normalized fields')


def stamp(value, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value,str) or len(value)>64 or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)',value):
        raise ValueError('UTC timestamp required')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def integer(value, lower=1):
    if type(value) is not int or not lower<=value<=9007199254740991:
        raise ValueError('Positive integer revision required')
    return value


def line(value):
    if value is None:
        return None
    d = bounded_decimal(value)
    if d==0:return '0'
    rendered=format(d,'f')
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


def result(value=None, unit=None, reason=None, basis=None):
    return dict(eligible=value is not None, value=value, unit=unit, reason=reason,
                basis=basis or dict(version=VERSION, inputs=[]))


def price(quote):
    v = Fraction(quote['original']['value'])
    return 1/v if quote['original']['units']=='decimal_odds' else v/100 if quote['original']['units']=='cents_per_contract' else v


def exact_wire(v):
    with localcontext() as ctx:
        ctx.prec = max(100, len(str(abs(v.numerator)))+len(str(v.denominator))+20)
        approximate = str(Decimal(v.numerator)/Decimal(v.denominator))
    return dict(numerator=str(v.numerator), denominator=str(v.denominator), decimal_approx=approximate)


def display_decimal(value, digits=2, signed=False):
    d=bounded_decimal(value)
    with localcontext() as ctx:
        ctx.prec=max(100,len(d.as_tuple().digits)+abs(d.adjusted())+digits+10)
        from decimal import ROUND_HALF_UP
        rounded=d.quantize(Decimal(1).scaleb(-digits),rounding=ROUND_HALF_UP)
    if rounded==0:rounded=abs(rounded)
    return format(rounded,('+' if signed and rounded!=0 else '')+'.'+str(digits)+'f')


def quotes_of(outcome):
    return [*outcome['quotes'].values(), *(q for qs in outcome.get('alternatives',{}).values() for q in qs)]


def quote_identity(q,outcome_id):
    source=deepcopy(q['source']);source['native_line']=line(source['native_line'])
    original=q['original']
    return identity('quote',[q['venue'],source,original['units'],line(original['payout']),original['payout_units'],original['quantity_units'],outcome_id])


def current_eligible(q):
    return q['comparison']['eligible'] and q['state']=='available' and not q['stale'] and q['display']['supported'] and q['age_seconds'] is not None


def comparisons(outcome):
    """All 15 visible-venue subsets; no client economic arithmetic/extra fetch."""
    quotes = quotes_of(outcome)
    for q in quotes:
        contexts = {}
        for mask in range(1,16):
            vs = [v for n,v in enumerate(VENUES) if mask & (1<<n)]
            key = '+'.join(vs)
            # Alternatives remain independent instruments. Compare best instrument
            # at OTHER venues, never the selected venue against its own liquidity.
            pool = [x for x in quotes if x['venue'] in vs and current_eligible(x)]
            others = [min((x for x in pool if x['venue']==v),key=lambda x:(price(x),x['id']))
                      for v in vs if v!=q['venue'] and any(x['venue']==v for x in pool)]
            basis = dict(version=VERSION, inputs=[dict(quote_id=x['id'],quote_revision=x['revision']) for x in [q,*others]])
            why = ('; '.join(q['comparison']['reasons']) if not current_eligible(q) else
                   'Selected venue is outside this filter' if q['venue'] not in vs else
                   'No other eligible venue for this exact selection')
            cue = ''; gap = result(reason=why,unit='cents',basis=basis)
            if q['venue'] in vs and current_eligible(q) and others:
                p = price(q); best = min(price(x) for x in others)
                cue = 'Better quote' if p < best else 'Tied quote' if p == best else ''
                diff = exact_wire((best-p)*100)
                gap = result(diff['decimal_approx'],'cents',basis=basis)
                gap['exact'] = diff
                gap['display_value']=display_decimal(gap['value'],1,True)+'c'
                gap['interpretation'] = 'Lowest other eligible venue price minus selected price; gross only'
            contexts[key] = dict(cue=cue, raw_difference=gap)
        q['comparison']['contexts'] = contexts
        q['calculations']['raw_difference'] = deepcopy(contexts['+'.join(VENUES)]['raw_difference'])


def binding_context(e,g,o):
    return dict(event_id=e['id'], group_id=g['id'], outcome_id=o['id'], participant=o['participant'],
                predicate=o['predicate'], signed_line=line(o['signed_line']), period_boundary=g['period_boundary'],
                outcome_cardinality=g['outcome_cardinality'],result_interpretation=o.get('result_interpretation','normal_win'))


def serialize(raw, *, allow_synthetic=False):
    """Reject malformed/conflicting catalogs atomically. Financial floats forbidden."""
    try:
        return _serialize(raw, allow_synthetic=allow_synthetic)
    except (KeyError, TypeError, ArithmeticError, OverflowError, RecursionError):
        raise ValueError('Invalid normalized current catalog') from None


def _serialize(raw, *, allow_synthetic):
    if len(packed(raw))>MAX_BYTES:
        raise ValueError('Current state byte capacity exceeded')
    r=deepcopy(raw)
    if r.get('schema')!=VERSION or r.get('mode') not in (('current','synthetic') if allow_synthetic else ('current',)):
        raise ValueError('Current mode/schema required; no historical or synthetic fallback')
    text(r['runtime_id'])
    if len(r['runtime_id'])>160:raise ValueError('Bounded runtime identity required')
    integer(r['state_revision']); clock=stamp(r['clock_at']); stamp(r['projected_at'],True)
    if r['state'] not in ('connecting','available','empty','degraded','stopped','unavailable'):
        raise ValueError('Unknown service state')
    if set(r['source_status'])!=set(VENUES):
        raise ValueError('All four source states required')
    for status in r['source_status'].values():
        if set(status)-{'state','reason','reason_code','source_at','received_at','next_due_at'} or status['state'] not in STATES:
            raise ValueError('Invalid ordinary source status')
        for k in ('source_at','received_at','next_due_at'):
            if k in status:stamp(status[k],True)
        for k in ('reason','reason_code'):
            if status.get(k) is not None:text(status[k])
    if not isinstance(r['events'],list) or len(r['events'])>200:
        raise ValueError('Event capacity exceeded')
    events={}; native_selections={}; count_groups=0; count_quotes=0
    for e in r['events']:
        fields(e,{'id','sport','league','season','stage','event_discriminator','participants','title','start_at','groups'})
        for k in ('id','sport','league','season','stage','event_discriminator','title'):text(e[k])
        stamp(e['start_at'])
        ps=e['participants']
        if not isinstance(ps,list) or not 2<=len(ps)<=16 or len({p['id'] for p in ps})!=len(ps):raise ValueError('Distinct participants required')
        for p in ps:
            fields(p,{'id','name','role'})
            for k in ('id','name','role'):text(p[k])
        if len({p['role'] for p in ps})!=len(ps):raise ValueError('Distinct participant roles required')
        eid=identity('event',[*[e[k] for k in ('sport','league','season','stage','event_discriminator')],stamp(e['start_at']).isoformat(),sorted((p['role'],p['id']) for p in ps)])
        e['id']=eid; groups={}
        for g in e['groups']:
            fields(g,{'id','market','period','period_boundary','outcome_cardinality','line','anchor_participant','outcomes'},{'result_policy'})
            if g['market'] not in ('winner','spread','total'):raise ValueError('Unsupported market')
            text(g['period']);text(g['period_boundary']);integer(g['outcome_cardinality'],2)
            g['line']=line(g['line']); anchor=g['anchor_participant']
            if g['market']=='winner' and (g['line'] is not None or anchor is not None):raise ValueError('Winner has no line/anchor')
            if g['market']!='winner' and g['line'] is None:raise ValueError('Lined market requires exact line')
            if g['market']=='spread' and anchor not in {p['id'] for p in ps}:raise ValueError('Spread anchor required')
            if g['market']=='total' and anchor is not None:raise ValueError('Total has no anchor')
            if g.get('result_policy') is not None:text(g['result_policy'])
            g['id']=identity('group',[eid,*[g[k] for k in ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],g.get('result_policy','unspecified')])
            outcomes={}
            for o in g['outcomes']:
                fields(o,{'id','participant','predicate','signed_line','label','quotes'},{'alternatives','result_interpretation'})
                if set(o['quotes'])-set(VENUES) or set(o.get('alternatives',{}))-set(VENUES):raise ValueError('Unknown comparison venue')
                text(o['id']); text(o['label']);o['signed_line']=line(o['signed_line'])
                if o['predicate'] not in ('win','not_win','draw','cover','over','under'):raise ValueError('Unsupported predicate')
                if o['participant'] is not None and o['participant'] not in {p['id'] for p in ps}:raise ValueError('Participant conflict')
                if g['market']=='total' and (o['participant'] is not None or o['predicate'] not in ('over','under') or o['signed_line']!=g['line']):raise ValueError('Total selection conflict')
                if g['market']=='spread':
                    expected=bounded_decimal(g['line']) if o['participant']==anchor else bounded_decimal(g['line']).copy_negate()
                    if o['predicate']!='cover' or o['signed_line'] is None or bounded_decimal(o['signed_line'])!=expected:raise ValueError('Spread orientation conflict')
                if g['market']=='winner' and (o['signed_line'] is not None or o['predicate'] not in ('win','not_win','draw')):raise ValueError('Winner predicate conflict')
                if o.get('result_interpretation') is not None:text(o['result_interpretation'])
                o['id']=identity('outcome',[g['id'],o['participant'],o['predicate'],o['signed_line'],o.get('result_interpretation','normal_win')])
                context=binding_context(e,g,o)
                candidates=[*o['quotes'].values(),*(q for qs in o.get('alternatives',{}).values() for q in qs)]; unique={}
                if len(candidates)>64:raise ValueError('Exact-selection instrument capacity exceeded')
                for q in candidates:
                    fields(q,{'id','revision','venue','source','original','times','state','rule_note','provenance','binding'},{'freshness_policy','rules_differ','cost_note','engine_inputs','depth','observation_time_evidence'})
                    original=q['original']
                    fields(original,{'value','units','payout','payout_units','quantity_units','role'},{'native_value','native_units','transformation'})
                    if original['role']!='comparison':
                        continue  # References are never board prices or engine legs.
                    if q['venue'] not in VENUES or q['state'] not in STATES:raise ValueError('Invalid venue/state')
                    bounded_decimal(original['value'])
                    if 'depth' in q:
                        if not isinstance(q['depth'],list) or len(q['depth'])>4096:raise ValueError('Bounded original depth required')
                        for level in q['depth']:
                            fields(level,{'price','quantity'},{'liquidity_id'})
                            if bounded_decimal(level['price'])<0 or bounded_decimal(level['quantity'])<=0:raise ValueError('Invalid original depth')
                            if 'liquidity_id' in level:text(level['liquidity_id'])
                    if 'native_value' in original:
                        native=bounded_decimal(original['native_value']);text(original['native_units'])
                        transform=original.get('transformation')
                        if transform=='one_minus_native_bid':
                            with localcontext() as ctx:
                                ctx.prec=600
                                expected=1-native
                            if original['native_units']!='usd_per_contract' or original['units']!='usd_per_contract' or expected!=bounded_decimal(original['value']):raise ValueError('Native Short/NO complement conflicts with original bid')
                        elif transform!='identity' or original['native_value']!=original['value'] or original['native_units']!=original['units']:raise ValueError('Unsupported original transformation')
                    if original['payout'] is not None:bounded_decimal(original['payout'])
                    for k in ('units','quantity_units'):text(original[k])
                    s=q['source']
                    if set(s)-{'provider','native_event_id','native_market_id','native_outcome_id','native_side','binding_id','binding_version','native_line','quote_side'}:raise ValueError('Unexpected source fields')
                    for k in ('provider','native_event_id','native_market_id','native_outcome_id','native_side','binding_id','binding_version'):text(s[k])
                    if s['quote_side']!='buy':raise ValueError('Only acquisition quotes supported')
                    if s['native_line'] is not None:bounded_decimal(s['native_line'])
                    b=q.pop('binding',None)
                    if not isinstance(b,dict) or b.get('selection')!=context or type(b.get('verified')) is not bool or not b.get('evidence'):
                        raise ValueError('Exact evidenced selection binding required')
                    if not isinstance(b['evidence'],list) or not 1<=len(b['evidence'])<=32:raise ValueError('Bounded binding evidence required')
                    for ev in b['evidence']:text(ev)
                    fields(b,{'verified','evidence','selection'})
                    q['binding']=b
                    native_key=identity('instrument',[q['venue'],*[s[k] for k in ('provider','native_event_id','native_market_id','native_outcome_id','native_side','quote_side')]])
                    if native_key in native_selections and native_selections[native_key]!=o['id']:raise ValueError('Native instrument bound to conflicting selections')
                    native_selections[native_key]=o['id']
                    integer(q['revision'])
                    q['id']=quote_identity(q,o['id'])
                    fields(q['times'],{'source_at','received_at','projected_at','source_time_kind'})
                    for k in ('source_at','received_at','projected_at'):stamp(q['times'][k],True)
                    kind=q['times']['source_time_kind']
                    if kind not in ('provider_quote','provider_book','unknown','synthetic') or kind=='synthetic' and r['mode']!='synthetic':raise ValueError('Invalid source time meaning')
                    if (q['times']['source_at'] is None)!=(kind=='unknown'):raise ValueError('Unknown source time must remain unknown')
                    fields(q['provenance'],{'mode','real_source'},{'fixture','evidence','artifact','sha256'})
                    if type(q['provenance']['real_source']) is not bool:raise ValueError('Explicit source evidence class required')
                    if q['provenance']['mode']!=r['mode'] or r['mode']=='current' and q['provenance'].get('real_source') is not True:raise ValueError('Evidence mode conflict')
                    q['display']=quote_display(original['value'],original['units'],original['payout'])
                    q['display'].pop('what_if',None)
                    if original['payout_units']!='USD':q['display']=dict(supported=False,american=None,cents=None,equivalent=None,reason='USD payout basis required')
                    at=stamp(q['times']['source_at'],True)
                    age=None if at is None else (clock-at).total_seconds()
                    q['age_seconds']=None if age is None or age<0 else age
                    policy=q.get('freshness_policy')
                    if policy is not None:
                        fields(policy,{'version','maximum_age_seconds'})
                        text(policy['version']);integer(policy['maximum_age_seconds'])
                    q['stale']=age is not None and (age<0 or policy is None or age>policy['maximum_age_seconds'])
                    reasons=[]
                    if not b['verified']:reasons.append('Selection binding unverified')
                    if age is None:reasons.append('Source time unknown')
                    if age is not None and age<0:reasons.append('Source clock is ahead of evaluation clock')
                    if q['stale']:reasons.append('Stale or unqualified source age policy')
                    if q['state']!='available':reasons.append('Source '+q['state'].replace('_',' '))
                    if not q['display']['supported']:reasons.append(q['display']['reason'])
                    q['comparison']=dict(eligible=not reasons,reasons=reasons)
                    if q.get('observation_time_evidence') is not None:text(q['observation_time_evidence'])
                    if 'rules_differ' in q and type(q['rules_differ']) is not bool:raise ValueError('Explicit rule difference flag required')
                    if q.get('cost_note') is not None:text(q['cost_note'])
                    text(q['rule_note'])
                    q['calculations']=calculation_outputs(q, evaluate=False)
                    if q.get('engine_inputs') is not None:q['calculation_inputs']=deepcopy(q['engine_inputs'])
                    if q['id'] in unique and packed(unique[q['id']])!=packed(q):raise ValueError('Conflicting duplicate instrument')
                    unique[q['id']]=q
                o['quotes']={};o['alternatives']={}
                for v in VENUES:
                    qs=sorted((q for q in unique.values() if q['venue']==v),key=lambda q:(q['source']['native_side'] not in ('yes','long'),q['id']))
                    if qs:o['quotes'][v]=qs[0]
                    if len(qs)>1:o['alternatives'][v]=qs[1:]
                count_quotes+=len(unique)
                if o['id'] in outcomes:raise ValueError('Duplicate outcome identity')
                outcomes[o['id']]=o
                comparisons(o)
            if len(outcomes)!=g['outcome_cardinality']:raise ValueError('Outcome cardinality conflict')
            g['outcomes']=list(outcomes.values())
            if g['id'] in groups:raise ValueError('Duplicate exact group; merge normalized inputs before commit')
            groups[g['id']]=g;count_groups+=1
        e['groups']=list(groups.values())
        if eid in events:raise ValueError('Duplicate exact event')
        events[eid]=e
    if count_groups>2000 or count_quotes>16000:raise ValueError('Catalog capacity exceeded')
    r['events']=sorted(events.values(),key=lambda e:(e['start_at'],e['id']))
    r['selection_policy']=dict(ttl_seconds=300,maximum_per_client=1,restart_expires=True)
    r['admin_href']='/admin'
    # Reject arbitrary top-level transport/provider material.
    if set(r)-{'schema','mode','runtime_id','state_revision','projected_at','clock_at','state','source_status','events','selection_policy','admin_href'}:raise ValueError('Unexpected current fields')
    all_quotes=[q for e in r['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
    for q in all_quotes:
        if q.get('engine_inputs'):
            validate_engine_inputs(q['engine_inputs'],all_quotes)
            q['calculations'].update(calculation_outputs(q))
        q.pop('engine_inputs',None)
    for e in r['events']:
        for g in e['groups']:
            for o in g['outcomes']:comparisons(o)
    if len(packed(r))>MAX_BYTES:raise ValueError('Serialized current state byte capacity exceeded')
    return r


def validate_engine_inputs(bundle,quotes):
    fields(bundle,{'kind','spec','quantities','quote_inputs','facts','fact_evidence'},{'probability'})
    if bundle['kind']!='explicit-depth-1':raise ValueError('Unsupported engine bundle')
    spec=bundle['spec'];legs=spec['legs'];inputs=bundle['quote_inputs']
    def financial_strings(value):
        if isinstance(value,float):raise ValueError('Financial float is not an original input')
        if isinstance(value,list):
            for item in value:financial_strings(item)
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('price','quantity','minimum','increment','rate','grid','value','reserve','ceiling','settlement_fee_per_unit','refund_fraction') and item is not None:bounded_decimal(item)
                elif key=='probabilities':
                    for amount in item.values():bounded_decimal(amount)
                else:financial_strings(item)
    financial_strings(spec)
    if len(legs)!=len(inputs) or not 1<=len(legs)<=16:raise ValueError('Bounded engine legs require exact quote inputs')
    if not isinstance(bundle['quantities'],list) or len(bundle['quantities'])!=len(legs):raise ValueError('Explicit quantities required')
    for amount in bundle['quantities']:bounded_decimal(amount)
    for k in ('costs','settlement','depth'):
        if type(bundle['facts'].get(k)) is not bool:raise ValueError('Explicit fact support required')
        evidence=bundle['fact_evidence'].get(k)
        if bundle['facts'][k] and (not isinstance(evidence,list) or not 1<=len(evidence)<=32):raise ValueError('Supported facts require evidence')
        for item in evidence or []:text(item)
    bound=[];inputs_eligible=True
    for leg,original in zip(legs,inputs):
        matches=[q for q in quotes if original==dict(source=q['source'],original=q['original'],revision=q['revision'],selection=q['binding']['selection'])]
        if len(matches)!=1:raise ValueError('Engine input has no exact admitted comparison quote')
        q=matches[0]
        inputs_eligible=inputs_eligible and q['comparison']['eligible']
        if leg['id']!=q['id'] or leg['levels']!=q.get('depth'):raise ValueError('Engine depth must equal original bound quote depth')
        if not leg['levels'] or q['display']['supported'] and Fraction(leg['levels'][0]['price'])!=price(q):raise ValueError('Engine price differs from original quote')
        for level in leg['levels']:
            for k in ('price','quantity'):bounded_decimal(level[k])
        if q['original']['quantity_units'] not in ('contracts','payout_units'):raise ValueError('Unsupported engine quantity units')
        bound.append(dict(quote_id=q['id'],quote_revision=q['revision']))
    # Manual probabilities can never be supplied as supported EV.
    probability=bundle.get('probability')
    if probability:
        fields(probability,{'kind','independent','evidence','model_version'})
        text(probability['model_version'])
        if type(probability['independent']) is not bool:raise ValueError('Probability independence must be explicit')
        for ev in probability['evidence']:text(ev)
    bundle['bound_revisions']=bound
    bundle['current_inputs_eligible']=inputs_eligible


def calculation_outputs(q, evaluate=True):
    basis=dict(version=VERSION,inputs=[dict(quote_id=q['id'],quote_revision=q['revision'])])
    out={k:result(reason=why,basis=basis) for k,why in [('arbitrage','Settlement, costs and depth are not established'),('ev','No independent supported probability model'),('sizing','Executable depth and quantity rules unknown'),('manual','Enter explicit probability, costs and settlement assumptions')]}
    bundle=q.get('engine_inputs')
    if not bundle or not evaluate:return out
    if not q['comparison']['eligible'] or bundle.get('current_inputs_eligible') is False:
        for k in ('arbitrage','ev','sizing'):out[k]['reason']='Current calculation inputs are stale, delayed, ineligible or unsupported'
        return out
    from app.depth import explicit_allocation
    # The general explicit engine remains mathematical, never execution evidence.
    # Production adapters must carry exact fact bindings for each input leg.
    if bundle.get('kind')!='explicit-depth-1':raise ValueError('Unsupported calculation adapter')
    spec=deepcopy(bundle['spec']); quantities=bundle['quantities']
    if not isinstance(bundle.get('quote_inputs'),list) or not bundle['quote_inputs']:raise ValueError('Calculation quote binding required')
    # Quote bindings use originals plus the exact parent binding, not generated ID.
    if not any(x==dict(source=q['source'],original=q['original'],revision=q['revision'],selection=q['binding']['selection']) for x in bundle['quote_inputs']):raise ValueError('Calculation selected quote inputs changed')
    for k in ('costs','settlement','depth'):
        if bundle.get('facts',{}).get(k) is not True:return out
    if spec.get('probabilities') is not None:
        probability=bundle.get('probability')
        if not probability or probability.get('kind')!='model EV' or probability.get('independent') is not True or not probability.get('evidence'):
            spec.pop('probabilities',None)
        else:spec['probability_kind']='model EV'
    basis['inputs']=deepcopy(bundle['bound_revisions'])
    try:calc=explicit_allocation(spec,quantities)
    except (ValueError,ArithmeticError,KeyError,TypeError):
        for k in ('arbitrage','ev','sizing'):out[k]['reason']='Supplied inputs are unsupported by the existing calculation engine'
        return out
    out['arbitrage']=result(calc['return_pct'],'percent',None if calc['return_pct'] is not None else '; '.join(calc['reasons']),basis)
    out['sizing']=result(str(len(calc['quantities'])),'legs with supplied quantities',basis=basis)
    out['sizing']['quantities']=calc['quantities']
    out['ev']=result(calc['expected_net'],'USD',None if calc['expected_net'] is not None else 'Independent probability or applicable state cashflows unavailable',basis)
    for k in ('arbitrage','ev'):
        if out[k]['value'] is not None:out[k]['display_value']=display_decimal(out[k]['value'],2,True)+(' %' if k=='arbitrage' else ' USD')
    for k in ('arbitrage','ev','sizing'):
        out[k]['engine_version']=calc['version'];out[k]['input_hash']=calc['input_hash'];out[k]['scope']='Supplied applicable mathematical inputs; not execution assurance'
    if out['ev']['eligible']:out['ev']['probability_provenance']=bundle['probability']
    return out


def manual_scenario(review, assumptions):
    """Existing odds cashflow + portfolio engines, from frozen original values."""
    if not isinstance(assumptions,dict) or set(assumptions)!={'probability','entry_cost','win_cost','loss_cost','quantity','acknowledge_conditional'}:
        raise ValueError('Explicit probability, all costs, quantity and conditional acknowledgment required')
    if assumptions['acknowledge_conditional'] is not True:raise ValueError('Acknowledge normal win/loss scenario; exceptions excluded')
    q=review['quote'];basis=dict(version=VERSION,inputs=[dict(quote_id=q['id'],quote_revision=q['revision'])],assumptions=deepcopy(assumptions))
    if not q['display']['supported']:return result(reason='Unsupported quote units or payout basis',basis=basis)
    values={k:bounded_decimal(assumptions[k]) for k in ('probability','entry_cost','win_cost','loss_cost','quantity')}
    if not 0<=values['probability']<=1 or any(values[k]<0 for k in ('entry_cost','win_cost','loss_cost')) or not 0<values['quantity']<=1000000:raise ValueError('Scenario assumptions outside supported bounds')
    from app.reference.product import odds_cashflows
    from app.settlement import portfolio
    from app.fees.engine import number as engine_number
    from math import lcm
    original=q['original'];value=original['value'];convention='decimal_odds' if original['units']=='decimal_odds' else 'price'
    try:
        for k in values:engine_number(assumptions[k])
        if original['units']=='cents_per_contract':
            with localcontext() as ctx:
                ctx.prec=300
                value=str(bounded_decimal(value)/100)
        conversion=odds_cashflows(value,convention,quantity=assumptions['quantity'])
        # Integer-scaled exact ORIGINAL cashflows avoid rounding a repeating
        # reciprocal into a false negative at mathematical break-even.
        cash=price(q)*Fraction(assumptions['quantity'])+Fraction(assumptions['entry_cost'])
        win=Fraction(assumptions['quantity'])-Fraction(assumptions['win_cost'])
        loss=-Fraction(assumptions['loss_cost'])
        scale=lcm(cash.denominator,win.denominator,loss.denominator)
        probability=values['probability']
        with localcontext() as ctx:
            ctx.prec=300
            complement=str(1-probability)
        calculation=portfolio([dict(id=q['id'],cash=str(cash*scale),receipts={'win':str(win*scale),'loss':str(loss*scale)})],['win','loss'],complete=True,
            probabilities={'win':str(probability),'loss':complement},probability_kind='manual What-if',reserve='0')
        expected=(win-cash)*Fraction(assumptions['probability'])+(loss-cash)*(1-Fraction(assumptions['probability']))
        wire=exact_wire(expected)
        # Retain the original engine audit with explicit scale; it is not USD.
        calculation['cashflow_scale']=str(scale)
        calculation['cashflow_unit']='USD multiplied by cashflow_scale'
    except ValueError:
        return result(reason='Original values exceed the supported scenario engine domain',basis=basis)
    out=result(wire['decimal_approx'],'USD',basis=basis)
    out['exact']=wire
    out['display_value']=display_decimal(wire['decimal_approx'],4,True)+' USD'
    out.update(label='Manual What-if; conditional normal win/loss, all costs explicitly assumed',engine_version=calculation['version'],conversion=conversion,calculation=calculation)
    return out


def snapshot_inputs(payload):
    """Recover exact normalized inputs without retaining derived calculation results."""
    raw=deepcopy(payload)
    for e in raw['events']:
        for g in e['groups']:
            for o in g['outcomes']:
                for q in quotes_of(o):
                    for key in ('display','age_seconds','stale','comparison','calculations'):
                        q.pop(key,None)
                    bundle=q.pop('calculation_inputs',None)
                    if bundle is not None:q['engine_inputs']=bundle
    return raw


def validate_snapshot(payload, *, allow_synthetic=False):
    """Reproduce every derived value, ID, eligibility and cue from exact inputs."""
    expected=serialize(snapshot_inputs(payload),allow_synthetic=allow_synthetic)
    if packed(expected)!=packed(payload):raise ValueError('Current snapshot does not reproduce from exact normalized inputs')
    return payload
