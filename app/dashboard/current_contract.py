"""Strict current-1 admission/serialization. No acquisition or retained fallback.

Provider input is an evidenced normalized catalog, not a display payload. IDs and
comparisons are derived here. Source admission owns binding evidence verification upstream;
this boundary checks the complete, exact binding against its catalog context.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import re
from .u0_display import VERSION, quote_display, bounded_decimal

VENUES = ('kalshi', 'polymarket_us', 'novig', 'prophetx')
STATES = ('connecting','available','not_offered','unavailable','budget_delayed','stale','error','stopped','resyncing')
MAX_BYTES = 64 * 1024 * 1024


def _canonical_chunks(node, encoder, depth=0):
    # Module recursion has no self-referencing closure to await collection.
    if depth>=3 or not isinstance(node,(dict,list,tuple)) or not node:
        content=encoder.encode(node)
        if len(content)<=1024*1024 or not isinstance(node,(dict,list,tuple)):
            yield content
            return
        del content
    if isinstance(node,dict) and all(isinstance(k,str) for k in node):
        yield '{'
        for index,key in enumerate(sorted(node)):
            if index:yield ','
            yield encoder.encode(key);yield ':'
            yield from _canonical_chunks(node[key],encoder,depth+1)
        yield '}'
    elif isinstance(node,(list,tuple)):
        yield '['
        for index,item in enumerate(node):
            if index:yield ','
            yield from _canonical_chunks(item,encoder,depth+1)
        yield ']'
    else:yield encoder.encode(node)


def canonical_chunks(value):
    # Exact canonical chunks shared by synchronous and sealed HTTP consumers.
    encoder=json.JSONEncoder(sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False)
    yield from _canonical_chunks(value,encoder)


def _small_graph(value):
    # Cheap conservative bound; large publication bodies retain the streamed
    # staging path. Small identity/seal values avoid two recursive encodings.
    pending=[value];nodes=chars=0
    while pending:
        node=pending.pop();nodes+=1
        if nodes>512:return False
        if isinstance(node,str):
            chars+=len(node)
            if chars>16384:return False
        elif isinstance(node,dict):
            if len(node)>128:return False
            pending.extend(node.keys());pending.extend(node.values())
        elif isinstance(node,(list,tuple)):
            if len(node)>128:return False
            pending.extend(node)
    return True


def packed(value):
    if _small_graph(value):
        return json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()
    size=sum(len(chunk.encode()) for chunk in canonical_chunks(value))
    # Stable staging sizes avoid allocating a new large region for every
    # harmless age-digit change. At most one MiB of staging slack; the returned
    # body and all input/output limits still use the exact counted size.
    allocation=((size+1024*1024-1)//(1024*1024))*(1024*1024) if size>1024*1024 else size
    output=bytearray(allocation);offset=0
    for chunk in canonical_chunks(value):
        encoded=chunk.encode();end=offset+len(encoded)
        if end>size:raise ValueError('Encoding input changed between passes')
        output[offset:end]=encoded;offset=end
    if offset!=size:raise ValueError('Encoding input changed between passes')
    return bytes(memoryview(output)[:size])


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
    return q['comparison']['eligible'] and q['state']=='available' and not q['stale'] and q['display']['supported'] and q.get('comparison_age_seconds',q['age_seconds']) is not None

def age_basis(q,clock):
    source=stamp(q['times']['source_at'],True)
    source_age=None if source is None else (clock-source).total_seconds()
    confirmation=q.get('book_confirmation')
    confirmed=None if confirmation is None else (clock-stamp(confirmation['confirmed_at'])).total_seconds()
    q['age_seconds']=None if source_age is None or source_age<0 else source_age
    q['confirmation_age_seconds']=None if confirmed is None or confirmed<0 else confirmed
    age=confirmed if confirmation is not None else source_age
    q['comparison_age_seconds']=None if age is None or age<0 else age
    policy=q.get('freshness_policy')
    q['stale']=age is not None and (age<0 or policy is None or age>policy['maximum_age_seconds'])
    return age


def comparisons(outcome):
    """All 15 visible-venue subsets; no client economic arithmetic/extra fetch."""
    quotes = quotes_of(outcome)
    for q in quotes:
        contexts = {};equivalent_contexts={}
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
            # Supported arithmetic on source-local aggregate originals remains
            # inspectable when cadence/freshness excludes current-price cues.
            if q['source']['provider']=='the_odds_api' and q['binding']['verified'] and q['display']['supported'] and q['venue'] in vs and not gap['eligible']:
                observed=[x for x in quotes if x['venue'] in vs and x['venue']!=q['venue'] and x['source']['provider']=='the_odds_api' and x['binding']['verified'] and x['display']['supported']]
                if observed:
                    best=min(observed,key=lambda x:(price(x),x['id']))
                    basis=dict(version=VERSION,inputs=[dict(quote_id=x['id'],quote_revision=x['revision']) for x in (q,best)])
                    diff=exact_wire((price(best)-price(q))*100)
                    gap=result(diff['decimal_approx'],'cents',basis=basis)
                    gap.update(exact=diff,display_value=display_decimal(gap['value'],1,True)+'c',
                        interpretation='Observed aggregate gross difference; delayed inputs, no current-price advantage or execution claim.')
            context=dict(cue=cue,raw_difference=gap)
            # Absent venues produce identical filter results; share immutable
            # result graphs while preserving every wire-level filter key.
            contexts[key]=equivalent_contexts.setdefault(packed(context),context)
        q['comparison']['contexts'] = contexts
        q['calculations']['raw_difference'] = deepcopy(contexts['+'.join(VENUES)]['raw_difference'])


def percentage_pair(q,other,group):
    from app.opportunities.percentages import normalized_pair
    outcomes=group['outcomes']
    math=normalized_pair(price(q),price(other))
    basis=dict(version='normalized-gross-percent-1',inputs=[dict(quote_id=x['id'],quote_revision=x['revision'],venue=x['venue'],original=deepcopy(x['original']),source_at=x['times']['source_at'],received_at=x['times']['received_at']) for x in (q,other)],
        denominator=math['acquisition_cost'],denominator_basis=math['denominator_basis'],normal_payout=math['normal_payout'],formula=math['formula'],
        outcome_coverage=[dict(label=x['label'],participant=x['participant'],predicate=x['predicate'],line=x['signed_line']) for x in outcomes],
        settlement_basis=group['period_boundary'],exceptions='Completed decisive outcome only; ties, cancellations, refunds, postponement differences and exceptional settlement excluded. Both quoted acquisitions assumed; fees excluded.')
    output=result(math['value'],'percent',basis=basis)
    output.update(display_value=display_decimal(math['value'],2,True)+' %',exact=dict(numerator=math['numerator'],denominator=math['denominator']),
        engine_version=math['engine_version'],scope='Observed gross conditional Arb %; original inputs, before costs; source ages shown separately')
    return output


def percentage_comparisons(group):
    """Only the exact admitted group/outcome domain supplies opposing outcomes."""
    outcomes=group['outcomes']
    for o in outcomes:
        for q in quotes_of(o):
            fallback=result(reason='No other venue with the exact opposing outcome and normal payout basis',unit='percent')
            valid=group['outcome_cardinality']==2 and len(outcomes)==2
            if group['market'] in ('spread','total'):
                valid=valid and group['line'] is not None and abs(Fraction(group['line'])%1)==Fraction(1,2)
            predicates={x['predicate'] for x in outcomes}
            if group['market']=='winner':
                valid=valid and (predicates=={'win'} and len({x['participant'] for x in outcomes})==2 or predicates=={'win','not_win'} and len({x['participant'] for x in outcomes})==1)
            elif group['market']=='total':valid=valid and predicates=={'over','under'}
            elif group['market']=='spread':valid=valid and predicates=={'cover'} and len({x['participant'] for x in outcomes})==2
            def usable(x):
                return x['binding']['verified'] and x['display']['supported'] and x['state'] not in ('unavailable','error','stopped','connecting','resyncing') and x['original']['payout'] is not None and Fraction(x['original']['payout'])==1 and x['original']['payout_units']=='USD'
            opponents=[x for other in outcomes if other['id']!=o['id'] for x in quotes_of(other) if x['venue']!=q['venue'] and usable(x)]
            if valid and usable(q) and opponents:
                other=min(opponents,key=lambda x:(price(x),x['id']))
                try:
                    fallback=percentage_pair(q,other,group)
                except ValueError: fallback=result(reason='Normalized positive prices and payout basis required',unit='percent')
            elif not valid:fallback['reason']='Complete opposing normal-outcome coverage is unverified for this market'
            # Supported net arithmetic, if present, stays separately inspectable.
            if not q['calculations']['arbitrage'].get('scope','').startswith('Observed gross'):
                q['calculations']['net_arbitrage']=deepcopy(q['calculations']['arbitrage'])
            q['calculations']['arbitrage']=fallback


def arbitrage_pairs(snapshot,market=None,search=None):
    """Explicit opposing-leg rows, never same-selection price gaps."""
    pairs=[]
    for event in snapshot['events']:
        if search and search.lower() not in ' '.join([event['title'],*[o['label'] for g in event['groups'] for o in g['outcomes']]]).lower():continue
        for group in event['groups']:
            if market and group['market']!=market:continue
            if len(group['outcomes'])!=2:continue
            left,right=group['outcomes']
            for q in quotes_of(left):
                for other in quotes_of(right):
                    if q['venue']==other['venue'] or not all(x['calculations']['arbitrage']['eligible'] for x in (q,other)):continue
                    math=percentage_pair(q,other,group)
                    pair=dict(id=identity('arb-pair',[q['id'],other['id']]),event_id=event['id'],title=event['title'],league=event['league'],start_at=event['start_at'],market=group['market'],period=group['period'],line=group['line'],
                              legs=[dict(selection=outcome['label'],quote={k:deepcopy(quote[k]) for k in ('id','revision','venue','original','times','state','stale','age_seconds','rule_note','display','source')}) for outcome,quote in ((left,q),(right,other))],arbitrage=math,
                              net=result(reason='Applicable venue costs and exceptional settlement facts are missing'),
                              ev=[deepcopy(x['calculations']['ev']) for x in (q,other)])
                    pairs.append(pair)
    return dict(schema='predict-arbs-1',runtime_id=snapshot['runtime_id'],state_revision=snapshot['state_revision'],mode=snapshot['mode'],source_status=deepcopy(snapshot['source_status']),pairs=pairs)


def binding_context(e,g,o):
    return dict(event_id=e['id'], group_id=g['id'], outcome_id=o['id'], participant=o['participant'],
                predicate=o['predicate'], signed_line=line(o['signed_line']), period_boundary=g['period_boundary'],
                outcome_cardinality=g['outcome_cardinality'],result_interpretation=o.get('result_interpretation','normal_win'))


def event_identity(e):
    """Versioned current occurrence IDs omit scheduled-time metadata."""
    current=e['event_discriminator'].startswith(('predict-occurrence-1:','comparison-provider-occurrence-1:'))
    values=[e[k] for k in (('sport','league','event_discriminator') if current else ('sport','league','season','stage','event_discriminator'))]
    if not current and not e['event_discriminator'].startswith('comparison-occurrence-1:'):
        values.append(stamp(e['start_at']).isoformat())
    values.append(sorted((p['role'],p['id']) for p in e['participants']))
    return identity('event',values)


def serialize(raw, *, allow_synthetic=False, estimate_policy=None, legacy=False, details=False, funded=True, paired=True, supported=True):
    """Reject malformed/conflicting catalogs atomically. Financial floats forbidden."""
    try:
        from app.comparison.estimated_policy import load, DEFAULT_POLICY
        return _serialize(raw, allow_synthetic=allow_synthetic, estimate_policy=estimate_policy or (DEFAULT_POLICY if legacy else load()), legacy=legacy, details=details, funded=funded, paired=paired, supported=supported)
    except (KeyError, TypeError, ArithmeticError, OverflowError, RecursionError):
        raise ValueError('Invalid normalized current catalog') from None


def _serialize(raw, **kwargs):
    return drain(serialize_steps(raw, **kwargs))


def drain(steps):
    """Synchronous financial consumers drain the identical owned iterator."""
    try:
        while True:next(steps)
    except StopIteration as done:return done.value
    finally:steps.close()


def byte_count_steps(value):
    total=0;unit=0
    for block in canonical_chunks(value):
        count=len(block.encode('utf-8'));total+=count;unit+=count
        if total>MAX_BYTES:raise ValueError('Serialized current state byte capacity exceeded')
        if unit>=65536:
            yield ('byte_bound',unit);unit=0
    return total


def serialize_steps(raw, *, allow_synthetic=False, estimate_policy=None, legacy=False, details=False, funded=True, paired=True, supported=True, prices_only=False, prices_progress=None):
    from app.comparison.estimated_policy import load, DEFAULT_POLICY
    estimate_policy=estimate_policy or (DEFAULT_POLICY if legacy else load())
    # Price bootstrap validates original catalog identity independently of the
    # financial registry. Complete admission below still validates and owns it.
    view={k:v for k,v in raw.items() if k!='comparison_profiles'} if prices_only else raw
    yield from byte_count_steps(view)
    r=deepcopy(view)
    from app.comparison.current_dependencies import validate_profiles, references, eligibility
    profiles=validate_profiles(r.get('comparison_profiles', {}))
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
        for k in ('id','sport','league','event_discriminator','title'):text(e[k])
        source_local=e['event_discriminator'].startswith('comparison-provider-occurrence-1:')
        missing_context=any(e[k] is None for k in ('season','stage'))
        for k in ('season','stage'):
            if e[k] is not None:text(e[k])
            elif not source_local:
                raise ValueError('Missing comparison context requires a source-local observation')
        stamp(e['start_at'])
        ps=e['participants']
        if not isinstance(ps,list) or not 2<=len(ps)<=16 or len({p['id'] for p in ps})!=len(ps):raise ValueError('Distinct participants required')
        for p in ps:
            fields(p,{'id','name','role'})
            for k in ('id','name','role'):text(p[k])
        if len({p['role'] for p in ps})!=len(ps):raise ValueError('Distinct participant roles required')
        if source_local and (len(ps)!=2 or {p['role'] for p in ps}!={'home','away'}):
            raise ValueError('Exact source-local home and away roles required')
        eid=event_identity(e)
        e['id']=eid; groups={}
        for g in e['groups']:
            fields(g,{'id','market','period','period_boundary','outcome_cardinality','line','anchor_participant','outcomes'},{'result_policy','display_group'})
            if g['market'] not in ('winner','spread','total'):raise ValueError('Unsupported market')
            text(g['period']);text(g['period_boundary']);integer(g['outcome_cardinality'],2)
            g['line']=line(g['line']); anchor=g['anchor_participant']
            if g['market']=='winner' and (g['line'] is not None or anchor is not None):raise ValueError('Winner has no line/anchor')
            if g['market']!='winner' and g['line'] is None:raise ValueError('Lined market requires exact line')
            if g['market']=='spread' and anchor not in {p['id'] for p in ps}:raise ValueError('Spread anchor required')
            if g['market']=='total' and anchor is not None:raise ValueError('Total has no anchor')
            if g.get('result_policy') is not None:text(g['result_policy'])
            g['id']=identity('group',[eid,*[g[k] for k in ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],g.get('result_policy','unspecified')])
            if 'display_group' in g:
                from app.comparison.domain import display_group_key
                d=g['display_group']
                fields(d,{'version','id','occurrence_id','market','period','overtime','line'})
                if (d['version'],d['occurrence_id'],d['market'],d['period'],d['line'])!=('predict-display-group-1',eid,g['market'],g['period'],g['line']):
                    raise ValueError('Display group context conflict')
                family={'winner':'moneyline','spread':'spread','total':'total'}[g['market']]
                if d['id']!=identity('display-group',display_group_key(eid,family,g['period'],d['overtime'],g['line'])):
                    raise ValueError('Display group identity conflict')
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
                    fields(q,{'id','revision','venue','source','original','times','state','rule_note','provenance','binding'},{'freshness_policy','rules_differ','cost_note','engine_inputs','depth','observation_time_evidence','native_predicate','book_confirmation','sharp_reference','provider_clocks','comparison_input_refs','comparison_input_status','occurrence_link','occurrence_match','native_contract'})
                    if 'native_contract' in q:
                        from app.comparison.event_links import digest
                        c=q['native_contract']
                        fields(c,{'version','id','source','predicate','wording','result_policy','scope','material_sha256'},{'scope_evidence','same_outcome'})
                        if c['version']!='predict-native-contract-1' or c['source']!=q['source'] or c['id']!='native-contract:'+digest({k:v for k,v in c.items() if k!='id'}) or len(packed(c))>65536:
                            raise ValueError('Native contract provenance conflict')
                        if 'same_outcome' in c and (not isinstance(c['same_outcome'],dict) or len(packed(c['same_outcome']))>16384):
                            raise ValueError('Bounded canonical contract facts required')
                        fields(c['scope'],{'period','overtime'})
                        if c['scope']['period']!=g['period'] or c['scope']['overtime'] not in ('included','excluded','unknown'):
                            raise ValueError('Native contract scoring scope conflict')
                        if 'display_group' in g and c['scope']['overtime']!=g['display_group']['overtime']:
                            raise ValueError('Native contract display scope conflict')
                        if 'scope_evidence' in c:
                            from app.comparison.native_scoring_scope import VERSION as SCOPE_VERSION
                            audit=c['scope_evidence']
                            fields(audit,{'version','status','overtime','reason','missing_fields','observed_overtime','conflicts','evidence'},{'scoring','rule_id'})
                            if (audit['version']!=SCOPE_VERSION or audit['overtime']!=c['scope']['overtime']
                                    or audit['status'] not in ('supported','unknown','contradictory')
                                    or (audit['status']=='supported')!=(audit['overtime']!='unknown')):
                                raise ValueError('Native contract scoring evidence conflict')
                        if c['predicate']!=q.get('occurrence_match',{}).get('original_selection'):
                            raise ValueError('Native contract original predicate conflict')
                    if 'occurrence_match' in q:
                        from app.comparison.occurrence_matching import validate_match
                        validate_match(q['occurrence_match'],q['source'])
                    if not prices_only:references(q, profiles)
                    from app.comparison.current_dependencies import input_status
                    if not prices_only:input_status(q)
                    if 'provider_clocks' in q:
                        clocks=q['provider_clocks'];fields(clocks,{'book','market','selected_basis'})
                        if clocks['selected_basis'] not in ('book','market','unknown'):raise ValueError('Explicit original provider clock basis required')
                        for kind in ('book','market'):stamp(clocks[kind],True)
                        expected=None if clocks['selected_basis']=='unknown' else clocks[clocks['selected_basis']]
                        if q['times']['source_at']!=expected:raise ValueError('Original provider clock selection conflict')
                    native=q.get('native_predicate')
                    if native is not None:
                        fields(native,{'version','participant','predicate','native_outcome_id','domain','binding_sha256','original_result_policy'})
                        if native['version']!='predict-direct-win-1' or native['predicate']!='win' or native['participant']!=o['participant'] or native['native_outcome_id']!=q['source']['native_outcome_id']:
                            raise ValueError('Native direct-win correspondence conflict')
                        if not isinstance(native['domain'],list) or len(native['domain'])!=2:raise ValueError('Complete native domain required')
                        for item in native['domain']:
                            fields(item,{'participant','predicate','signed_line','label','native_outcome_id'})
                            if item['participant'] not in {p['id'] for p in ps} or item['predicate'] not in ('win','not_win') or item['signed_line'] is not None:raise ValueError('Invalid native winner domain')
                            text(item['label'])
                            text(item['native_outcome_id'])
                        text(native['binding_sha256']);text(native['original_result_policy'])
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
                    if missing_context and b['verified']:
                        raise ValueError('Missing comparison context cannot have a verified selection binding')
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
                    if q.get('book_confirmation') is not None:
                        from app.collection.current_confirmation import validate
                        validate(q['book_confirmation'],dict(venue=q['venue'],event_id=q['source']['native_event_id'],market_id=q['source']['native_market_id']))
                    policy=q.get('freshness_policy')
                    if policy is not None:
                        fields(policy,{'version','maximum_age_seconds'})
                        text(policy['version']);integer(policy['maximum_age_seconds'])
                    age=age_basis(q,clock)
                    reasons=[]
                    from app.comparison.current_dependencies import link_reasons
                    reasons.extend(link_reasons(q, clock))
                    if not b['verified']:reasons.append('Selection binding unverified')
                    if age is None:reasons.append('Source time unknown')
                    if age is not None and age<0 or at is not None and at>clock:reasons.append('Source clock is ahead of evaluation clock')
                    if q.get('book_confirmation') and stamp(q['book_confirmation']['received_at'])>clock:reasons.append('Confirmation receipt is ahead of evaluation clock')
                    if q['stale']:reasons.append('Stale or unqualified source age policy')
                    if q['state']!='available':reasons.append('Source '+q['state'].replace('_',' '))
                    if not q['display']['supported']:reasons.append(q['display']['reason'])
                    q['comparison']=dict(eligible=not reasons,reasons=reasons)
                    if q.get('observation_time_evidence') is not None:text(q['observation_time_evidence'])
                    if 'rules_differ' in q and type(q['rules_differ']) is not bool:raise ValueError('Explicit rule difference flag required')
                    if q.get('cost_note') is not None:text(q['cost_note'])
                    text(q['rule_note'])
                    if q.get('sharp_reference') is not None:
                        from app.collection.current_benchmark import validate_reference
                        validate_reference(q['sharp_reference'],context)
                    q['calculations']=calculation_outputs(q, evaluate=False)
                    if q.get('engine_inputs') is not None:q['calculation_inputs']=deepcopy(q['engine_inputs'])
                    if q['id'] in unique and packed(unique[q['id']])!=packed(q):raise ValueError('Conflicting duplicate instrument')
                    unique[q['id']]=q
                    if prices_only:yield ('validated_original',q['id'])
                o['quotes']={};o['alternatives']={}
                for v in VENUES:
                    qs=sorted((q for q in unique.values() if q['venue']==v),key=lambda q:(q['source']['native_side'] not in ('yes','long'),q['id']))
                    if qs:o['quotes'][v]=qs[0]
                    if len(qs)>1:o['alternatives'][v]=qs[1:]
                count_quotes+=len(unique)
                if o['id'] in outcomes:raise ValueError('Duplicate outcome identity')
                outcomes[o['id']]=o
                if not prices_only:comparisons(o)
            if len(outcomes)!=g['outcome_cardinality']:raise ValueError('Outcome cardinality conflict')
            g['outcomes']=list(outcomes.values())
            if g['id'] in groups:raise ValueError('Duplicate exact group; merge normalized inputs before commit')
            groups[g['id']]=g;count_groups+=1
            if prices_only and prices_progress is not None:
                prices_progress(dict(r,events=[dict(e,groups=[g])]))
                yield ('validated_price_group',g['id'])
        e['groups']=list(groups.values())
        if eid in events:raise ValueError('Duplicate exact event')
        events[eid]=e
    if count_groups>2000 or count_quotes>16000:raise ValueError('Catalog capacity exceeded')
    r['events']=sorted(events.values(),key=lambda e:(e['start_at'],e['id']))
    r['selection_policy']=dict(ttl_seconds=300,maximum_per_client=1,restart_expires=True)
    r['admin_href']='/admin'
    # Reject arbitrary top-level transport/provider material.
    if set(r)-{'schema','mode','runtime_id','state_revision','projected_at','clock_at','state','source_status','events','selection_policy','admin_href','comparison_profiles','estimate_policy'}:raise ValueError('Unexpected current fields')
    if not legacy:r['estimate_policy'] = estimate_policy.to_dict()
    else:r.pop('estimate_policy',None)
    if prices_only:
        # Same strict native/price/clock admission, without financial discovery.
        # This graph is private bootstrap input, never complete Current.
        yield from byte_count_steps(r)
        return r
    all_quotes=[q for e in r['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
    for q in all_quotes:
        from app.comparison.current_dependencies import refresh_metadata_status
        refresh_metadata_status(q,clock)
        q['comparison_dependency_reasons']=list(eligibility(q, profiles, clock))
        from app.comparison.current_dependencies import temporal_revision
        q['comparison_temporal_revision']=temporal_revision(q,profiles,clock)
        if q.get('engine_inputs'):
            validate_engine_inputs(q['engine_inputs'],all_quotes)
            q['calculations'].update(calculation_outputs(q,clock=clock))
        if q.get('sharp_reference') is not None:
            from app.collection.current_benchmark import calculate
            q['calculations']['ev']=calculate(q,clock)
        q.pop('engine_inputs',None)
        yield ('normalized_quote',q['id'])
    from app.comparison.projection_batches import groups as fair_groups
    for batch in fair_groups(r['events']):
        for e,g in batch:
            for o in g['outcomes']:comparisons(o)
            percentage_comparisons(g)
            from app.comparison.current_metrics import group_metric_steps
            yield from group_metric_steps(g,profiles,clock,event=e,estimate_policy=estimate_policy,legacy=legacy,details=details,funded=funded,supported=supported)
            from app.comparison.shared_templates import shared
            if shared(profiles) and not details:
                from app.comparison.current_details import compact_group
                compact_group(g)
    if not legacy and paired:
        from app.comparison.estimated_pair import assembly_steps
        for event in r['events']:
            event['funded_pairs'],event['funded_pair_search']=yield from assembly_steps(event,profiles,clock,policy=estimate_policy)
    yield from byte_count_steps(r)
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


def calculation_outputs(q, evaluate=True, clock=None):
    basis=dict(version=VERSION,inputs=[dict(quote_id=q['id'],quote_revision=q['revision'])])
    out={k:result(reason=why,basis=basis) for k,why in [('arbitrage','Settlement, costs and depth are not established'),('ev','No matched current Pinnacle baseline'),('sizing','Executable depth and quantity rules unknown'),('manual','Enter explicit probability, costs and settlement assumptions')]}
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
    out['ev']=result(calc['ev_pct'],'percent',None if calc['ev_pct'] is not None else 'Independent probability or applicable state cashflows unavailable',basis)
    for k in ('arbitrage','ev'):
        if out[k]['value'] is not None:out[k]['display_value']=display_decimal(out[k]['value'],2,True)+' %'
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


def snapshot_inputs(payload, *, copy_graph=True):
    """Recover exact normalized inputs without retaining derived calculation results."""
    # Strip derived graphs before copying; they can be much larger than inputs.
    derived={'display','age_seconds','confirmation_age_seconds','comparison_age_seconds','stale','comparison','calculations','calculation_inputs','comparison_dependency_reasons','comparison_temporal_revision','comparison_details'}
    # Only an internal synchronous projection may borrow immutable nested input
    # graphs. Public readers and historical validation retain defensive copying.
    owned=deepcopy if copy_graph else lambda value: value
    def original(q):
        value=owned({k:v for k,v in q.items() if k not in derived})
        if q.get('calculation_inputs') is not None:value['engine_inputs']=owned(q['calculation_inputs'])
        return value
    raw=owned({k:v for k,v in payload.items() if k not in ('events','estimate_policy')})
    raw['events']=[]
    for event in payload['events']:
        e=owned({k:v for k,v in event.items() if k not in ('groups','funded_pairs','funded_pair_search')});e['groups']=[];raw['events'].append(e)
        for group in event['groups']:
            g=owned({k:v for k,v in group.items() if k not in ('outcomes','comparison_pairs','comparison_search')});g['outcomes']=[];e['groups'].append(g)
            for outcome in group['outcomes']:
                o=owned({k:v for k,v in outcome.items() if k not in ('quotes','alternatives')})
                o['quotes']={v:original(q) for v,q in outcome['quotes'].items()}
                if 'alternatives' in outcome:o['alternatives']={v:[original(q) for q in qs] for v,qs in outcome['alternatives'].items()}
                g['outcomes'].append(o)
    return raw


def validate_snapshot(payload, *, allow_synthetic=False):
    """Reproduce every derived value, ID, eligibility and cue from exact inputs."""
    from app.comparison.estimated_policy import EstimatePolicy
    policy = EstimatePolicy.from_dict(payload['estimate_policy']) if 'estimate_policy' in payload else None
    funded=any('funded_estimate' in q.get('calculations',{}) for e in payload['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))
    paired=any('funded_pairs' in e for e in payload['events'])
    supported=any('supported_size_evaluation' in q.get('calculations',{}).get('funded_estimate',{}) for e in payload['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))
    expected=serialize(snapshot_inputs(payload),allow_synthetic=allow_synthetic,estimate_policy=policy,legacy=policy is None,funded=funded,paired=paired,supported=supported)
    if packed(expected)!=packed(payload):raise ValueError('Current snapshot does not reproduce from exact normalized inputs')
    return payload
